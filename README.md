# REA Lab toolkit

My reverse-engineering workflow, pulled out of my private lab so others can reuse it:
Ghidra headless scripts, .NET/PE metadata helpers, a local-model function labeler
with mechanical evidence checks, and a small read-only dashboard.

Nothing here contains game binaries, assets, or decompiled code. Point the scripts
at your own copy of a game.

This is an early prototype. It works for me, but I have only used it on my own setup.

## Layout

| Path | What it is |
| --- | --- |
| `pipeline/` | Function labeler (talks to a local Ollama), benchmark runner, method exporter, fingerprint search (you supply the terms), managed-name lister, prompt template |
| `pipeline/ghidra_scripts/` | Headless Ghidra scripts: dump all functions, decompile at addresses, list instructions, scan immediates and data, string xrefs |
| `dashboard/` | Read-only local web page (127.0.0.1 only) showing labeler progress and per-target notes |
| `tools/` | Log redaction (SteamID64s and IPs) |
| `docs/LAB-CONVENTIONS.md` | The rules I work by (own-words notes, evidence before claims, no redistribution of game files) |

## Setup

Run everything from the repository root. Your targets go in a `targets/<name>/` folder
there (it is ignored by git).

```text
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set REA_LAB_ROOT=.
set REA_TARGET=<target name>
```

`REA_LAB_ROOT` is the folder that contains `targets\` and defaults to the current folder.
The dashboard always uses the folder above `dashboard\`.

For the fingerprint search, write your own `targets/<name>/fingerprints.json` (format in
`pipeline/fingerprints.py`) with the terms you care about. A small default set is used if
you don't.

Ghidra (Apache-2.0) is not included; install it separately and point `analyzeHeadless`
at it. Local models run through Ollama.

## Notes

- Model summaries are an index, not evidence. The labeler only accepts output that
  passes schema validation and a verbatim-evidence check.
- The one Python dependency is `dnfile` (MIT), listed in `requirements.txt`.
- License: [MIT](LICENSE).
