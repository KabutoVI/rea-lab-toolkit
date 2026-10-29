# REA-Lab Dashboard

Read-only local page that shows Ollama status (loaded + installed), labeler progress, exported methods, Claude Code activity, and per-target findings.

## Start

From the repository root, with the virtual environment from the main README active:

```text
python dashboard\server.py
```

Optional port:

```text
python dashboard\server.py --port 8777
```

Open [http://127.0.0.1:8777](http://127.0.0.1:8777). The server binds to `127.0.0.1` only. The page polls `/api/state` every 3 seconds.

## Log activity (Claude Code hooks)

```text
python dashboard\hooks\log_activity.py session_start "Phase 6 labeler"
python dashboard\hooks\log_activity.py --event tool_use --detail "exported methods"
```

Appends one JSON line to `dashboard\activity.jsonl`. The HTTP server never writes this file.

## Files

| File | Role |
|---|---|
| `server.py` | Stdlib HTTP server; `/`, `/api/state`, `/api/source` |
| `index.html` | Dark UI (inline CSS/JS); optional marked.js from cdnjs |
| `hooks\log_activity.py` | CLI to append activity events |
| `activity.jsonl` | Optional; last 50 lines shown in Activity |
| `SPEC.md` | Full product spec |

## What each panel reads

Lab root is the parent of `dashboard\`.

| Panel | Source |
|---|---|
| Ollama status bar | `GET http://127.0.0.1:11434/api/ps` |
| Ollama installed list | `GET http://127.0.0.1:11434/api/tags` |
| Labeler | `targets\<name>\status.json` |
| Claude activity | `dashboard\activity.jsonl` |
| Target tabs | folders under `targets\` |
| Mode badge | `mode: …` line in `targets\<name>\notes.md` |
| Candidates | `targets\<name>\candidates.json` |
| Functions | `targets\<name>\functions\manifest.json` + `summaries.jsonl` |
| Summaries | `targets\<name>\summaries.jsonl` |
| Method source drawer | `GET /api/source?target=…&file=…` → `functions\<exported_file>` |
| Notes | `targets\<name>\notes.md` |
| Setup log | `SETUP_LOG.md` at lab root |

Missing files show **not available yet**. The HTTP server is read-only with one exception: the **Reset `<target>` analysis** button (top-right of the target tabs) calls `POST /api/reset`, which backs up a target's generated labeler outputs (`status.json`, `summaries.jsonl`, `functions/`) into `targets/<name>/backups/reset_<timestamp>/` and then clears them. It never deletes (the move is reversible) and intentionally keeps `candidates.json` and `notes.md`. It binds `127.0.0.1` only. The server still does not start or stop anything, and never writes `activity.jsonl`.
