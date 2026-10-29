# REA-Lab Dashboard Spec

Location: `<lab root>\dashboard\`
Builder: Cursor Composer
Owner of everything outside `dashboard\`: Claude Code. Composer must not create, edit or delete any file outside `<lab root>\dashboard\`.

## Goal

A read-only local web page that shows what the lab is doing: whether the local model is loaded, which models are installed, labeler progress, exported methods and their labels, what Claude Code has been doing, and what has been found per target. Open it in a browser, leave it on a second screen.

## Hard constraints

- Read-only. No buttons, forms or endpoints that change, run, start, stop or delete anything. (Exception: `hooks\log_activity.py` is a separate CLI that appends to `activity.jsonl`; the HTTP server itself never writes.)
- Server binds to `127.0.0.1` only. Never `0.0.0.0`.
- Python standard library only for the server (`http.server`, `json`, `urllib`, `pathlib`). No pip installs. Runs with the existing venv: `python dashboard\server.py`.
- Frontend: one `index.html` with inline CSS and JS. No build step, no npm. One optional CDN script allowed for Markdown rendering (marked.js from cdnjs); if it fails to load, show Markdown as preformatted text.
- Every data source is optional. If a file or service is missing, the panel shows "not available yet" instead of erroring. The lab is under construction and most files won't exist on day one.
- Default port 8777, overridable with `--port`.

## Files

```
dashboard\
  SPEC.md              (this file)
  server.py
  index.html
  README.md            (how to start it, what each panel reads)
  activity.jsonl       (optional; appended by hooks, not by the server)
  hooks\
    log_activity.py    (CLI: append one activity event line)
```

## Server

Serves `index.html` at `/` and JSON endpoints. The page polls `/api/state` every 3 seconds. The server builds state fresh on each request by reading files from disk (lab root = parent folder of `dashboard\`).

### `GET /api/state`

```json
{
  "generated_at": "ISO timestamp",
  "ollama": {
    "reachable": true,
    "loaded": [
      { "name": "...", "size_vram_bytes": 0, "expires_at": "ISO or null" }
    ],
    "installed": [
      { "name": "...", "size_bytes": 0, "loaded": true,
        "size_vram_bytes": 0, "expires_at": "ISO or null" }
    ],
    "models": []
  },
  "activity": [ { "ts": "...", "event": "...", "detail": "..." } ],
  "targets": [
    {
      "name": "example-target",
      "mode": "study",
      "status": { },
      "candidates": [ ],
      "summaries": [ ],
      "functions": [ ],
      "functions_counts": {
        "exported": 230, "labeled": 180, "verified": 150,
        "unverified": 20, "failed": 5, "skipped": 5, "not_labeled": 50
      },
      "notes_md": "...",
      "summaries_available": true,
      "candidates_available": true,
      "status_available": false,
      "notes_available": true,
      "functions_available": true
    }
  ],
  "setup_log_md": "...",
  "truncated": false
}
```

`ollama.models` is a back-compat alias of `ollama.loaded`.

### `GET /api/source?target=<name>&file=<exported_file>`

Read-only. Returns the text of one exported method file under `targets\<name>\functions\`.

```json
{ "ok": true, "target": "...", "file": "...", "text": "...", "line_count": 42 }
```

On failure: `{ "ok": false, "error": "...", "target": "...", "file": "..." }` with HTTP 400/403/404.

Path rules (must all pass):

- `target` must be a single path segment (no `/`, `\`, `.`, `..`).
- `file` must be relative; absolute paths rejected.
- `file` must not contain `..` segments.
- Resolved path must stay inside `targets\<name>\functions\` (`Path.resolve` + `relative_to` check).
- File size capped (~2 MB).

### Data sources

| Field | Source | Notes |
|---|---|---|
| `ollama.loaded` | `GET http://127.0.0.1:11434/api/ps` (1s timeout) | `name`, `size_vram`, `expires_at`. Unreachable = `reachable: false`. |
| `ollama.installed` | `GET http://127.0.0.1:11434/api/tags` (1s timeout) | `name`, `size`; `loaded` / VRAM / expiry joined from `/api/ps`. |
| `activity` | `dashboard\activity.jsonl`, last 50 lines | Written by `hooks\log_activity.py` or Claude Code hooks. Missing = empty list. |
| `targets[]` | one entry per folder in `targets\` | |
| `mode` | first line of `targets\<name>\notes.md` matching `mode: <value>` | `unknown` if absent. |
| `status` | `targets\<name>\status.json` | Labeler progress, contract below. |
| `candidates` | `targets\<name>\candidates.json` | Contract below. |
| `summaries` | `targets\<name>\summaries.jsonl` | Skip and count malformed lines, don't crash. Includes `exported_file`. |
| `functions` | `targets\<name>\functions\manifest.json` joined to summaries by `exported_file` | See Functions contract. |
| `notes_md` | `targets\<name>\notes.md` | Raw text. |
| `setup_log_md` | `SETUP_LOG.md` | Raw text. |
| `/api/source` | `targets\<name>\functions\<exported_file>` | Traversal-safe. |

Cap anything large (summaries, functions, logs) so a single `/api/state` response stays under ~2 MB; include a `truncated` flag if capped.

## File contracts (Claude Code / pipeline write these)

`targets\<name>\status.json`, written by the labeler:

```json
{
  "state": "idle | running | done | error",
  "model": "qwen3:14b",
  "total": 120,
  "done": 45,
  "verified": 38,
  "unverified": 5,
  "failed": 2,
  "skipped": 3,
  "too_long": 3,
  "current": "Example.cs::Update",
  "started_at": "ISO", "updated_at": "ISO",
  "message": "optional free text"
}
```

Notes:

- Today's labeler writes the skipped (too_long methods) count into `too_long` and may omit `skipped`. The UI treats `skipped` as `status.skipped` if present, else `status.too_long`, and still displays the raw `too_long` field.
- If `state` is `running` but `updated_at` is older than 60 seconds, the UI shows "stalled?".
- Elapsed time = now − `started_at`. ETA = `(elapsed / done) * (total − done)` when `done > 0` and `state` is `running`.

`targets\<name>\candidates.json`, written by the fingerprint search:

```json
[ { "file": "bbe.cs", "lines": 197, "total_hits": 73, "density_per_1k": 370.6,
    "fingerprints": { "Socket": 20, "Packet": 12 }, "approved": true, "note": "..." } ]
```

`summaries.jsonl` lines follow the labeler schema: `function, exported_file, guessed_name, summary, category, calls, confidence, too_long, evidence`, plus a `check` field: `verified | unverified | failed | skipped`.

- `skipped` = method never sent to the model (typically `too_long: true`). Grey badge in the UI; included in filters and counts.

`targets\<name>\functions\manifest.json`, written by the method exporter:

```json
[
  {
    "class": "bbp",
    "source_file": "bbp.cs",
    "method": "llk",
    "start_line": 4,
    "end_line": 10,
    "exported_file": "bbp__llk__L4.cs",
    "fingerprints": { "Serialize": 3, "Hash": 2 }
  }
]
```

Joined to summaries by `exported_file`. Label status per method: `verified | unverified | failed | skipped | not_labeled`.

`dashboard\activity.jsonl` lines:

```json
{ "ts": "ISO", "event": "session_start", "detail": "optional text" }
```

Append via:

```text
pipeline\.venv\Scripts\python.exe dashboard\hooks\log_activity.py <event> [detail...]
```

## Page layout

Dark theme, monospace-friendly, readable at a glance from a second monitor.

1. **Status bar** (top, always visible): Ollama dot (green loaded / grey idle / red unreachable) with loaded model name, VRAM in GB, and "unloads in X min" when `expires_at` is present; labeler state per target with a progress bar (`done/total`), verified/unverified/failed/skipped/too_long counts, elapsed and ETA; time of last Claude Code activity event ("Claude: active 12s ago" or "no activity logged").
2. **Ollama panel** (under status bar): list of installed models from `/api/tags` (name, size), marking which are loaded and showing unload countdown when available.
3. **Target tabs**: one tab per target, showing its mode as a badge.
4. **Labeler panel** (inside the active target, when `status.json` exists): state, model, progress bar, verified/unverified/failed/skipped/too_long counts, current method, elapsed, ETA, stalled? warning.
5. **Sub-tabs** per target:
   - **Candidates**: sortable table (file, lines, hits, density, top fingerprints, approved). Approved rows highlighted.
   - **Functions**: every exported method from `manifest.json` (class, method, line range, fingerprints) with label status joined from summaries. Filters by class, category and status. Count summary at top (e.g. 230 exported, 180 labeled, 150 verified).
   - **Summaries**: table with filters by category, confidence and check status. Check badges: verified green, unverified amber, failed red, skipped grey. Clicking a row opens the method detail drawer.
   - **Notes**: rendered `notes.md`. Highlight the words `confirmed`, `likely`, `unknown` in green, amber, grey.
6. **Method detail drawer**: opened by clicking a method in Functions or Summaries. Side panel with source (line numbers) from `/api/source` next to the label (guessed name, summary, category, confidence, calls). Highlights the evidence quote in the source when found; if the label is unverified and the quote is not found verbatim, shows the quote in the label panel with a note that it wasn't found in the source.
7. **Activity**: reverse-chronological list of the last 50 events.
8. **Setup log**: rendered `SETUP_LOG.md`, collapsed by default.

Polling must not reset scroll position, open tabs, sub-tabs, expanded/selected rows, active filters, or an open method detail drawer.

## Done when

- `python dashboard\server.py` starts and the page loads at `http://127.0.0.1:8777`.
- Missing optional files still render "not available yet" with no browser console errors.
- `/api/source` serves files under `functions\` and rejects `../` traversal (HTTP 403).
- `hooks\log_activity.py` appends a valid activity line that appears in the Activity panel within one poll.
- No file outside `dashboard\` was touched by the dashboard builder.
