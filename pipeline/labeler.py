"""
Local-model labeler: reads exported methods for a target (from
functions\\manifest.json), sends each to a local Ollama model for a
structured JSON label, mechanically checks the result, and appends to
summaries.jsonl. Writes status.json for the dashboard after every method.

See pipeline\\README.md for what "verified / unverified / failed /
skipped" mean. See prompts\\labeler_v1.txt for the model's instructions.

Usage:
  python labeler.py --target <target> --model qwen3:14b
  python labeler.py --target <target> --model gpt-oss:20b --force
  python labeler.py --target <target> --model qwen3:14b --limit 5
"""

import os
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LAB_ROOT = Path(os.environ.get("REA_LAB_ROOT", "."))
PROMPT_PATH = Path(__file__).parent / "prompts" / "labeler_v1.txt"
FAILURE_LOG_PATH = Path(__file__).parent / "labeler_failures.log"

CATEGORIES = [
    "initialization", "state", "math", "input", "networking", "rendering",
    "ui", "io", "utility", "other", "unknown",
]
CONFIDENCES = ["low", "medium", "high", "unknown"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "guessed_name": {"type": "string"},
        "summary": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "calls": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": CONFIDENCES},
        "too_long": {"type": "boolean"},
        "evidence": {"type": "string"},
    },
    "required": ["guessed_name", "summary", "category", "calls", "confidence", "too_long", "evidence"],
    "additionalProperties": False,
}

CHAR_LIMIT_DEFAULT = 6000
NUM_CTX_DEFAULT = 8192
OLLAMA_URL_DEFAULT = "http://localhost:11434"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_ws(text):
    return re.sub(r"\s+", " ", text.strip())


def validate_schema(obj):
    if not isinstance(obj, dict):
        return False
    required = RESPONSE_SCHEMA["required"]
    if any(k not in obj for k in required):
        return False
    if not isinstance(obj["guessed_name"], str):
        return False
    if not isinstance(obj["summary"], str):
        return False
    if obj["category"] not in CATEGORIES:
        return False
    if not isinstance(obj["calls"], list) or not all(isinstance(c, str) for c in obj["calls"]):
        return False
    if obj["confidence"] not in CONFIDENCES:
        return False
    if not isinstance(obj["too_long"], bool):
        return False
    if not isinstance(obj["evidence"], str):
        return False
    return True


def check_evidence(evidence, source):
    if len(evidence) < 20:
        return False
    if not re.search(r"[A-Za-z_][A-Za-z0-9_]*", evidence):
        return False
    return normalize_ws(evidence) in normalize_ws(source)


def filter_calls(calls, source):
    return [c for c in calls if c and c in source]


def call_ollama(ollama_url, model, system_prompt, method_source, num_ctx, keep_alive=None):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": method_source},
        ],
        "think": False,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("message", {}).get("content", "")


def log_failure(exported_file, raw_output):
    with open(FAILURE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"--- {now_iso()} {exported_file} ---\n{raw_output}\n\n")


def write_status(status_path, state, model, total, counts, current, started_at, message=""):
    tmp_path = status_path.with_suffix(".json.tmp")
    data = {
        "state": state,
        "model": model,
        "total": total,
        "done": counts["verified"] + counts["unverified"] + counts["failed"] + counts["skipped"],
        "verified": counts["verified"],
        "unverified": counts["unverified"],
        "failed": counts["failed"],
        "too_long": counts["skipped"],
        "current": current,
        "started_at": started_at,
        "updated_at": now_iso(),
        "message": message,
    }
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(status_path)


def load_already_labeled(summaries_path):
    done = set()
    if not summaries_path.exists():
        return done
    with open(summaries_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "exported_file" in obj:
                done.add(obj["exported_file"])
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--char-limit", type=int, default=CHAR_LIMIT_DEFAULT)
    parser.add_argument("--num-ctx", type=int, default=NUM_CTX_DEFAULT)
    parser.add_argument("--ollama-url", default=OLLAMA_URL_DEFAULT)
    parser.add_argument("--force", action="store_true", help="relabel methods already in summaries.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N unlabeled methods")
    parser.add_argument("--keep-alive", default=None, help="Ollama keep_alive value, e.g. 30m, to keep the model loaded for the whole run")
    parser.add_argument("--prompt", default=None, help="path to a prompt template; defaults to prompts/labeler_v1.txt")
    parser.add_argument("--categories", default=None, help="comma-separated category enum; defaults to the built-in category set")
    args = parser.parse_args()

    # Per-target overrides (backward compatible: unset = original behaviour).
    global CATEGORIES, RESPONSE_SCHEMA, PROMPT_PATH
    if args.categories:
        CATEGORIES = [c.strip() for c in args.categories.split(",") if c.strip()]
        RESPONSE_SCHEMA = dict(RESPONSE_SCHEMA)
        RESPONSE_SCHEMA["properties"] = dict(RESPONSE_SCHEMA["properties"])
        RESPONSE_SCHEMA["properties"]["category"] = {"type": "string", "enum": CATEGORIES}
    if args.prompt:
        PROMPT_PATH = Path(args.prompt)

    target_root = LAB_ROOT / "targets" / args.target
    manifest_path = target_root / "functions" / "manifest.json"
    summaries_path = target_root / "summaries.jsonl"
    status_path = target_root / "status.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    already_labeled = set() if args.force else load_already_labeled(summaries_path)
    pending = [m for m in manifest if m["exported_file"] not in already_labeled]
    if args.limit is not None:
        pending = pending[: args.limit]

    total = len(manifest)
    counts = {"verified": 0, "unverified": 0, "failed": 0, "skipped": 0}
    started_at = now_iso()

    write_status(status_path, "running", args.model, total, counts, None, started_at)

    for i, entry in enumerate(pending, 1):
        exported_file = entry["exported_file"]
        method_path = target_root / "functions" / exported_file
        current = f"{entry['source_file']}::{entry['method']}"
        write_status(status_path, "running", args.model, total, counts, current, started_at)

        source = method_path.read_text(encoding="utf-8", errors="ignore")

        if len(source) > args.char_limit:
            line = {
                "function": entry["method"],
                "exported_file": exported_file,
                "guessed_name": "",
                "summary": "",
                "category": "",
                "calls": [],
                "confidence": "",
                "too_long": True,
                "evidence": "",
                "check": "skipped",
            }
            counts["skipped"] += 1
            with open(summaries_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            print(f"[{i}/{len(pending)}] {current} -> skipped (too_long, {len(source)} chars)")
            continue

        parsed = None
        raw_output = None
        for attempt in range(2):
            try:
                raw_output = call_ollama(args.ollama_url, args.model, system_prompt, source, args.num_ctx, args.keep_alive)
                parsed = json.loads(raw_output)
                if not validate_schema(parsed):
                    parsed = None
            except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
                parsed = None
            if parsed is not None:
                break

        if parsed is None:
            log_failure(exported_file, raw_output if raw_output is not None else "<no response>")
            line = {
                "function": entry["method"],
                "exported_file": exported_file,
                "guessed_name": "",
                "summary": "",
                "category": "",
                "calls": [],
                "confidence": "",
                "too_long": False,
                "evidence": "",
                "check": "failed",
            }
            counts["failed"] += 1
            with open(summaries_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            print(f"[{i}/{len(pending)}] {current} -> failed (schema validation)")
            continue

        verified = check_evidence(parsed["evidence"], source)
        check = "verified" if verified else "unverified"
        calls = filter_calls(parsed["calls"], source)

        line = {
            "function": entry["method"],
            "exported_file": exported_file,
            "guessed_name": parsed["guessed_name"],
            "summary": parsed["summary"],
            "category": parsed["category"],
            "calls": calls,
            "confidence": parsed["confidence"],
            "too_long": False,
            "evidence": parsed["evidence"],
            "check": check,
        }
        counts[check] += 1
        with open(summaries_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        print(f"[{i}/{len(pending)}] {current} -> {parsed['category']} ({check})")

    write_status(status_path, "done", args.model, total, counts, None, started_at,
                 message=f"finished {len(pending)} methods this run")
    print(f"\nDone. verified={counts['verified']} unverified={counts['unverified']} "
          f"failed={counts['failed']} skipped={counts['skipped']}")


if __name__ == "__main__":
    main()
