#!/usr/bin/env python3
"""REA-Lab read-only dashboard server. Binds 127.0.0.1 only."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

DASHBOARD_DIR = Path(__file__).resolve().parent
LAB_ROOT = DASHBOARD_DIR.parent
TARGETS_DIR = LAB_ROOT / "targets"
ACTIVITY_PATH = DASHBOARD_DIR / "activity.jsonl"
SETUP_LOG_PATH = LAB_ROOT / "SETUP_LOG.md"

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ACTIVITY = 50
MAX_SUMMARIES_PER_TARGET = 2000
MAX_FUNCTIONS_PER_TARGET = 5000
MAX_NOTES_CHARS = 400_000
MAX_SETUP_LOG_CHARS = 400_000
MAX_SOURCE_BYTES = 2 * 1024 * 1024

MODE_RE = re.compile(r"(?i)^\s*mode:\s*(\S+)")
OLLAMA_PS_URL = "http://127.0.0.1:11434/api/ps"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _ollama_get(url: str) -> dict | None:
    try:
        with urlopen(url, timeout=1) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except (URLError, HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None


def fetch_ollama() -> dict:
    """Combine /api/ps (loaded) and /api/tags (installed)."""
    ps = _ollama_get(OLLAMA_PS_URL)
    tags = _ollama_get(OLLAMA_TAGS_URL)
    if ps is None and tags is None:
        return {
            "reachable": False,
            "loaded": [],
            "installed": [],
            "models": [],  # back-compat alias of loaded
        }

    loaded = []
    loaded_by_name: dict[str, dict] = {}
    for m in (ps or {}).get("models") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model") or ""
        entry = {
            "name": name,
            "size_vram_bytes": int(m.get("size_vram") or 0),
            "expires_at": m.get("expires_at") or None,
        }
        loaded.append(entry)
        if name:
            loaded_by_name[name] = entry
            # also index bare model field
            model = m.get("model") or ""
            if model and model not in loaded_by_name:
                loaded_by_name[model] = entry

    installed = []
    for m in (tags or {}).get("models") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model") or ""
        loaded_info = loaded_by_name.get(name)
        installed.append(
            {
                "name": name,
                "size_bytes": int(m.get("size") or 0),
                "loaded": loaded_info is not None,
                "size_vram_bytes": (loaded_info or {}).get("size_vram_bytes", 0),
                "expires_at": (loaded_info or {}).get("expires_at"),
            }
        )

    return {
        "reachable": True,
        "loaded": loaded,
        "installed": installed,
        "models": loaded,  # back-compat for status-bar consumers
    }


def read_activity() -> list:
    text = read_text(ACTIVITY_PATH)
    if text is None:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    events = []
    for ln in lines[-MAX_ACTIVITY:]:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        events.append(
            {
                "ts": obj.get("ts", ""),
                "event": obj.get("event", ""),
                "detail": obj.get("detail", ""),
            }
        )
    return events


def parse_mode(notes_text: str | None) -> str:
    if not notes_text:
        return "unknown"
    for line in notes_text.splitlines():
        m = MODE_RE.match(line)
        if m:
            return m.group(1).rstrip(".,;")
    return "unknown"


def read_summaries(path: Path) -> tuple[list, int]:
    """Return (summaries, malformed_count). Caps list length."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return [], 0

    summaries = []
    malformed = 0
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(obj, dict):
            malformed += 1
            continue
        summaries.append(
            {
                "function": obj.get("function"),
                "exported_file": obj.get("exported_file"),
                "guessed_name": obj.get("guessed_name"),
                "summary": obj.get("summary"),
                "category": obj.get("category"),
                "calls": obj.get("calls"),
                "confidence": obj.get("confidence"),
                "too_long": obj.get("too_long"),
                "evidence": obj.get("evidence"),
                "check": obj.get("check"),
            }
        )
        if len(summaries) >= MAX_SUMMARIES_PER_TARGET:
            break
    return summaries, malformed


def read_functions(manifest_path: Path, summaries: list) -> tuple[list, dict, bool]:
    """Join manifest entries with summaries by exported_file."""
    raw = read_json(manifest_path)
    if not isinstance(raw, list):
        return [], {}, False

    by_file: dict[str, dict] = {}
    for s in summaries:
        ef = s.get("exported_file")
        if isinstance(ef, str) and ef and ef not in by_file:
            by_file[ef] = s

    functions = []
    counts = {
        "exported": 0,
        "labeled": 0,
        "verified": 0,
        "unverified": 0,
        "failed": 0,
        "skipped": 0,
        "not_labeled": 0,
    }
    truncated = False

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if len(functions) >= MAX_FUNCTIONS_PER_TARGET:
            truncated = True
            break
        exported_file = entry.get("exported_file") or ""
        label = by_file.get(exported_file)
        if label:
            status = (label.get("check") or "unverified").lower()
            if status not in ("verified", "unverified", "failed", "skipped"):
                status = "unverified"
            category = label.get("category") or ""
            counts["labeled"] += 1
            counts[status] = counts.get(status, 0) + 1
        else:
            status = "not_labeled"
            category = ""
            counts["not_labeled"] += 1

        counts["exported"] += 1
        functions.append(
            {
                "class": entry.get("class"),
                "method": entry.get("method"),
                "source_file": entry.get("source_file"),
                "start_line": entry.get("start_line"),
                "end_line": entry.get("end_line"),
                "exported_file": exported_file,
                "fingerprints": entry.get("fingerprints") or {},
                "label_status": status,
                "category": category,
                "guessed_name": (label or {}).get("guessed_name"),
                "summary": (label or {}).get("summary"),
                "confidence": (label or {}).get("confidence"),
                "calls": (label or {}).get("calls"),
                "evidence": (label or {}).get("evidence"),
                "check": (label or {}).get("check"),
            }
        )

    return functions, counts, truncated


def build_targets() -> tuple[list, bool]:
    truncated = False
    targets = []
    if not TARGETS_DIR.is_dir():
        return targets, truncated

    for entry in sorted(TARGETS_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir():
            continue
        notes_path = entry / "notes.md"
        notes_md = read_text(notes_path)
        if notes_md is not None and len(notes_md) > MAX_NOTES_CHARS:
            notes_md = notes_md[:MAX_NOTES_CHARS] + "\n\n… [truncated]"
            truncated = True

        status_raw = read_json(entry / "status.json")
        status = status_raw if isinstance(status_raw, dict) else {}

        candidates_raw = read_json(entry / "candidates.json")
        candidates = candidates_raw if isinstance(candidates_raw, list) else []

        summaries_path = entry / "summaries.jsonl"
        if summaries_path.is_file():
            summaries, _malformed = read_summaries(summaries_path)
            try:
                with summaries_path.open("r", encoding="utf-8", errors="replace") as f:
                    nonempty = sum(1 for ln in f if ln.strip())
                if nonempty > len(summaries):
                    truncated = True
            except OSError:
                pass
        else:
            summaries = []

        manifest_path = entry / "functions" / "manifest.json"
        functions_available = manifest_path.is_file()
        if functions_available:
            functions, functions_counts, f_trunc = read_functions(manifest_path, summaries)
            truncated = truncated or f_trunc
        else:
            functions, functions_counts = [], {
                "exported": 0,
                "labeled": 0,
                "verified": 0,
                "unverified": 0,
                "failed": 0,
                "skipped": 0,
                "not_labeled": 0,
            }

        targets.append(
            {
                "name": entry.name,
                "mode": parse_mode(notes_md),
                "status": status,
                "candidates": candidates,
                "summaries": summaries,
                "functions": functions,
                "functions_counts": functions_counts,
                "notes_md": notes_md,
                "summaries_available": summaries_path.is_file(),
                "candidates_available": (entry / "candidates.json").is_file(),
                "status_available": (entry / "status.json").is_file(),
                "notes_available": notes_path.is_file(),
                "functions_available": functions_available,
            }
        )
    return targets, truncated


def build_state() -> dict:
    truncated = False
    setup_log_md = read_text(SETUP_LOG_PATH)
    if setup_log_md is not None and len(setup_log_md) > MAX_SETUP_LOG_CHARS:
        setup_log_md = setup_log_md[:MAX_SETUP_LOG_CHARS] + "\n\n… [truncated]"
        truncated = True

    targets, t_trunc = build_targets()
    truncated = truncated or t_trunc

    state = {
        "generated_at": utc_now_iso(),
        "ollama": fetch_ollama(),
        "activity": read_activity(),
        "targets": targets,
        "setup_log_md": setup_log_md,
        "truncated": truncated,
    }

    payload = json.dumps(state, ensure_ascii=False)
    while len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES:
        shrunk = False
        for t in state["targets"]:
            if len(t.get("functions") or []) > 20:
                t["functions"] = t["functions"][: max(20, len(t["functions"]) // 2)]
                shrunk = True
            if len(t.get("summaries") or []) > 10:
                t["summaries"] = t["summaries"][: max(10, len(t["summaries"]) // 2)]
                shrunk = True
        if not shrunk:
            for t in state["targets"]:
                notes = t.get("notes_md")
                if isinstance(notes, str) and len(notes) > 2000:
                    t["notes_md"] = notes[: len(notes) // 2] + "\n\n… [truncated]"
                    shrunk = True
            setup = state.get("setup_log_md")
            if isinstance(setup, str) and len(setup) > 2000:
                state["setup_log_md"] = setup[: len(setup) // 2] + "\n\n… [truncated]"
                shrunk = True
        state["truncated"] = True
        if not shrunk:
            break
        payload = json.dumps(state, ensure_ascii=False)

    return state


def resolve_source(target: str, file: str) -> tuple[Path | None, str | None]:
    """Resolve file under targets/<target>/functions/. Reject traversal.

    Returns (path, error_message).
    """
    if not target or not file:
        return None, "missing target or file"
    if "/" in target or "\\" in target or target in (".", ".."):
        return None, "invalid target"
    # Reject absolute paths and any parent traversal in the file param
    norm = file.replace("\\", "/").strip()
    if not norm or norm.startswith("/") or Path(file).is_absolute():
        return None, "absolute paths rejected"
    # Normalize separators; reject .. / empty / drive-root segments before resolve
    parts = Path(norm).parts
    if any(p in ("..", "", "/", "\\") or (len(p) >= 2 and p[1] == ":") for p in parts):
        return None, "path traversal rejected"

    functions_root = (TARGETS_DIR / target / "functions").resolve()
    if not functions_root.is_dir():
        return None, "functions folder not found"

    candidate = (functions_root / Path(*parts)).resolve()
    try:
        candidate.relative_to(functions_root)
    except ValueError:
        return None, "path outside functions folder"

    if not candidate.is_file():
        return None, "file not found"
    return candidate, None


def read_source_payload(target: str, file: str) -> dict:
    path, err = resolve_source(target, file)
    if err:
        return {"ok": False, "error": err, "target": target, "file": file}
    try:
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            return {
                "ok": False,
                "error": "file too large",
                "target": target,
                "file": file,
                "size_bytes": size,
            }
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc), "target": target, "file": file}
    return {
        "ok": True,
        "target": target,
        "file": file,
        "text": text,
        "line_count": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
    }


# The dashboard is read-only EXCEPT for this one explicit, operator-invoked
# action. It never deletes: it moves the labeler outputs into a timestamped
# backup folder, so a reset is fully reversible. candidates.json and notes.md
# (human-authored) are intentionally kept.
RESET_ARTIFACTS = ["status.json", "summaries.jsonl", "functions"]


def reset_target(name: str) -> dict:
    """Back up then clear a target's generated labeler outputs. 127.0.0.1 only."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return {"ok": False, "error": "invalid target"}
    targets_root = TARGETS_DIR.resolve()
    target_dir = (TARGETS_DIR / name).resolve()
    try:
        target_dir.relative_to(targets_root)
    except ValueError:
        return {"ok": False, "error": "target outside targets dir"}
    if target_dir == targets_root or not target_dir.is_dir():
        return {"ok": False, "error": "target not found"}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = target_dir / "backups" / f"reset_{ts}"
    moved = []
    try:
        for art in RESET_ARTIFACTS:
            src = target_dir / art
            if src.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(backup_dir / art))
                moved.append(art)
    except OSError as exc:
        return {"ok": False, "error": f"reset failed: {exc}", "moved": moved}
    return {
        "ok": True,
        "target": name,
        "moved": moved,
        "backup": str(backup_dir) if moved else None,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "REALabDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            try:
                body = (DASHBOARD_DIR / "index.html").read_bytes()
            except OSError:
                self._send(404, b"index.html not found", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            try:
                state = build_state()
                body = json.dumps(state, ensure_ascii=False).encode("utf-8")
            except Exception as exc:  # noqa: BLE001
                err = {
                    "error": "state_build_failed",
                    "message": str(exc),
                    "generated_at": utc_now_iso(),
                }
                body = json.dumps(err).encode("utf-8")
                self._send(500, body, "application/json; charset=utf-8")
                return
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path == "/api/source":
            qs = parse_qs(parsed.query)
            target = (qs.get("target") or [""])[0]
            file = (qs.get("file") or [""])[0]
            payload = read_source_payload(target, file)
            code = 200 if payload.get("ok") else 400
            if payload.get("error") == "file not found":
                code = 404
            elif payload.get("error") in (
                "path traversal rejected",
                "path outside functions folder",
                "absolute paths rejected",
                "invalid target",
            ):
                code = 403
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/reset":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b""
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, json.JSONDecodeError):
                data = {}
            target = data.get("target") if isinstance(data, dict) else None
            result = reset_target(target or "")
            code = 200 if result.get("ok") else 400
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")
            return
        self._send(405, b"read-only", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:  # noqa: N802
        self._send(405, b"read-only", "text/plain; charset=utf-8")

    def do_DELETE(self) -> None:  # noqa: N802
        self._send(405, b"read-only", "text/plain; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="REA-Lab read-only dashboard")
    parser.add_argument("--port", type=int, default=8777, help="Port (default 8777)")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"REA-Lab dashboard: http://127.0.0.1:{args.port}")
    print(f"Lab root: {LAB_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
