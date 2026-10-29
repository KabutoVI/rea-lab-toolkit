"""
Benchmark two Ollama models on the same handful of exported methods, for
comparison before picking one to run the full labeler with.

Usage: python benchmark.py --target <target> --models qwen3:14b,gpt-oss:20b --files bbp__llk__L4.cs,bbe__lyg__L22.cs,...
"""

import os
import argparse
import json
import time
from pathlib import Path

import labeler

LAB_ROOT = Path(os.environ.get("REA_LAB_ROOT", "."))


def run_one(ollama_url, model, system_prompt, source, num_ctx):
    start = time.monotonic()
    raw_output = None
    parsed = None
    for attempt in range(2):
        try:
            raw_output = labeler.call_ollama(ollama_url, model, system_prompt, source, num_ctx)
            parsed = json.loads(raw_output)
            if not labeler.validate_schema(parsed):
                parsed = None
        except Exception:
            parsed = None
        if parsed is not None:
            break
    elapsed = time.monotonic() - start

    if parsed is None:
        return {"elapsed_s": round(elapsed, 2), "schema_ok": False, "raw": raw_output}

    verified = labeler.check_evidence(parsed["evidence"], source)
    calls = labeler.filter_calls(parsed["calls"], source)
    return {
        "elapsed_s": round(elapsed, 2),
        "schema_ok": True,
        "check": "verified" if verified else "unverified",
        "guessed_name": parsed["guessed_name"],
        "summary": parsed["summary"],
        "category": parsed["category"],
        "confidence": parsed["confidence"],
        "calls": calls,
        "evidence": parsed["evidence"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--models", required=True, help="comma-separated model names")
    parser.add_argument("--files", required=True, help="comma-separated exported_file names")
    parser.add_argument("--num-ctx", type=int, default=labeler.NUM_CTX_DEFAULT)
    parser.add_argument("--ollama-url", default=labeler.OLLAMA_URL_DEFAULT)
    args = parser.parse_args()

    target_root = LAB_ROOT / "targets" / args.target
    system_prompt = labeler.PROMPT_PATH.read_text(encoding="utf-8")
    models = args.models.split(",")
    files = args.files.split(",")

    results = {}
    for fname in files:
        source = (target_root / "functions" / fname).read_text(encoding="utf-8", errors="ignore")
        results[fname] = {}
        for model in models:
            print(f"Running {model} on {fname}...")
            results[fname][model] = run_one(args.ollama_url, model, system_prompt, source, args.num_ctx)

    out_path = Path(__file__).parent / "benchmark_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    for fname, by_model in results.items():
        print(f"\n{fname}")
        for model, r in by_model.items():
            if r["schema_ok"]:
                print(f"  {model}: {r['elapsed_s']}s  category={r['category']}  confidence={r['confidence']}  check={r['check']}")
            else:
                print(f"  {model}: {r['elapsed_s']}s  SCHEMA INVALID")

    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
