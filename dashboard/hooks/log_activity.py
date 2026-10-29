#!/usr/bin/env python3
"""Append one Claude Code activity event to dashboard/activity.jsonl.

Stdlib only. Safe to call from Claude Code hooks or the shell. Never
makes network calls, never touches any file other than activity.jsonl,
and always exits 0 - a logging failure must never block or fail the
tool call or session event it is attached to.

Manual usage (unchanged):
  python dashboard/hooks/log_activity.py <event> [detail...]
  python dashboard/hooks/log_activity.py --event session_start --detail "Phase 6"
  python dashboard/hooks/log_activity.py --event tool_use --detail "ran labeler" --ts 2026-10-22T12:00:00+00:00

Hook usage: called with NO arguments, Claude Code hook JSON on stdin
(hook_event_name, tool_name, tool_input, tool_response, source, reason,
...). Event and a short detail are derived automatically:
  PreToolUse/PostToolUse/PostToolUseFailure -> event = hook_event_name,
    detail = "<tool_name>: <short input summary>"
  SessionStart -> event = "SessionStart", detail = source (startup/resume/...)
  SessionEnd   -> event = "SessionEnd", detail = reason
  anything else -> event = hook_event_name, detail = ""

Writes one JSON line:
  {"ts": "<ISO-8601>", "event": "<event>", "detail": "<detail>"}

The dashboard shows the last 50 lines of activity.jsonl (newest last in the file).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
ACTIVITY_PATH = DASHBOARD_DIR / "activity.jsonl"

MAX_DETAIL_CHARS = 160


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(event: str, detail: str = "", ts: str | None = None) -> Path:
    if not event or not str(event).strip():
        raise ValueError("event is required")
    record = {
        "ts": ts or utc_now_iso(),
        "event": str(event).strip(),
        "detail": detail if detail is not None else "",
    }
    ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACTIVITY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return ACTIVITY_PATH


def _truncate(text: str, limit: int = MAX_DETAIL_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _summarize_tool_input(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "pattern", "path", "url", "prompt", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _derive_from_hook_payload(payload: dict) -> tuple[str, str]:
    hook_event = payload.get("hook_event_name") or "unknown"

    if hook_event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        tool_name = payload.get("tool_name") or "unknown_tool"
        summary = _summarize_tool_input(payload.get("tool_input"))
        detail = f"{tool_name}: {summary}" if summary else str(tool_name)
        return hook_event, _truncate(detail)

    if hook_event == "SessionStart":
        return hook_event, _truncate(str(payload.get("source") or ""))

    if hook_event == "SessionEnd":
        return hook_event, _truncate(str(payload.get("reason") or ""))

    return hook_event, ""


def _run_hook_mode() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        event, detail = _derive_from_hook_payload(payload)
        append_event(event, detail)
    except Exception as e:
        try:
            print(f"log_activity: hook mode error ignored: {e}", file=sys.stderr)
        except Exception:
            pass
    return 0


def _run_cli_mode(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Append one line to dashboard/activity.jsonl")
    parser.add_argument("event_pos", nargs="?", help="Event name (positional)")
    parser.add_argument("detail_pos", nargs="*", help="Detail words (positional)")
    parser.add_argument("--event", "-e", help="Event name (overrides positional)")
    parser.add_argument("--detail", "-d", default=None, help="Detail string (overrides positional)")
    parser.add_argument("--ts", help="ISO timestamp (default: now UTC)")
    args = parser.parse_args(argv)

    event = args.event or args.event_pos
    if args.detail is not None:
        detail = args.detail
    elif args.detail_pos:
        detail = " ".join(args.detail_pos)
    else:
        detail = ""

    if not event:
        parser.print_help()
        return 0

    path = append_event(event, detail, args.ts)
    print(f"appended to {path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return _run_hook_mode()
    return _run_cli_mode(argv)


def _safe_main() -> int:
    try:
        return main()
    except SystemExit as e:
        code = e.code
        if isinstance(code, int) and code != 0:
            try:
                print(f"log_activity: suppressing non-zero exit ({code})", file=sys.stderr)
            except Exception:
                pass
        return 0
    except Exception as e:
        try:
            print(f"log_activity: error ignored: {e}", file=sys.stderr)
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(_safe_main())
