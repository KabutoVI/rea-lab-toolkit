# REA-Lab Conventions

This folder is a reverse-engineering lab for studying, modding, and decompiling software I own, following each community's established norms.

## Session start

First step of any session, before acting: read `LAB.md` (the index of every target and where each effort stands). Then, for the target in play, read its `targets\<name>\notes.md`, starting at the "CURRENT EFFORT SNAPSHOT" section if it has one, and its `CONTEXT-PROMPT.md` if present. This is the lab's persistent cross-session context; load it instead of re-deriving. Keep `LAB.md`'s status lines and each target's snapshot current as work moves.

## Captured logs

Keep every runtime/session log we capture; never let one be the only copy in a chat. Save under `targets\<name>\input\logs\<date>-<case>\` with clear names (`host-*.log`, `client-*.log`), and add a line to that target's `LOGS-INDEX.md` recording: date, case, build and protocol/version identifiers, which plugins were loaded, and one sentence on what happened. This is the metadata a maintainer always asks for, so capturing it up front makes "logs on demand" instant. Before sharing any log publicly, redact personal identifiers (SteamID64s, IPs) with `tools\redact_log.py` and post only the scrubbed copy; raw logs stay local.

## Target modes

Each target declares its mode at the top of its notes.md:

- study: learn approaches for my own projects. notes.md in my own words, never reproducing third-party source (rules 2 and 4 apply).
- mod: build modifications. Distribute only my own code, patches and tooling, never game files or assets. Users must supply their own copy of the game.
- decomp: reconstruct source, ideally contributing to an existing decompilation project and following that project's contribution rules. Never commit or distribute original game binaries or assets. Decomp work happens in a clone of the upstream project's repo under targets\<name>\repo\, following that repo's structure and contribution rules. functions\ and summaries.jsonl may still be used for triage.

Rules 1, 3 and 5 apply to all modes. Ask me which mode when creating any new target.

## Rules

1. Never analyze live installs. Copy only the specific files needed into a target's input folder before analysis. Live installs outside this folder are read-only reference points, never edited or treated as the working copy. Exception for mod mode: a built mod may be installed into a live game install only with my explicit approval each time, after backing up every file it replaces into targets\<name>\backups\.

2. notes.md is in my own words. Findings describe the approach and the evidence for it (for example: uses a semi-implicit Euler integrator, confirmed by the velocity-then-position update order in UpdatePhysics) never verbatim or near-verbatim third-party source. If pseudocode must be quoted to make a point, keep it minimal and put it in functions, not notes.md.

3. Local model summaries are an index, not evidence. Output from the pipeline's local-model labeler (summaries.jsonl) is for navigation only, such as which functions probably relate to X, never cited as proof of how something works. Local models hallucinate; treat their summaries as leads to check, not conclusions. Summaries are only accepted if they pass the pipeline's mechanical checks (schema validation and verbatim evidence check, see pipeline\README.md).

4. Everything in notes.md must be traceable to raw pseudocode. Before writing a claim in notes.md, the underlying exported pseudocode must exist in that target's functions folder and actually support the claim. Mark each claim confirmed, likely, or unknown based on how directly the pseudocode supports it.

5. Each target is self-contained, under targets\<name>\:
   - input: copied files being analyzed (never live installs)
   - functions: exported pseudocode, one file per function, plus a manifest
   - summaries.jsonl: local-model labeler output (index only, see rule 3)
   - notes.md: mode declaration plus my own words findings (see rules 2 and 4)

## Tools

First step for any new target: identify engine and runtime before choosing tools.

- Unity Mono or other .NET assemblies: ilspycmd for readable C# (output into the target's functions\decompiled\), dnfile in pipeline\.venv for cheap metadata and name listings, REA for targeted inspection.
- Obfuscated .NET: search decompiled output for engine API fingerprints (Unity, physics, config classes) before any token-heavy reading.
- Unity IL2CPP: REA's IL2CPP metadata decoding for names; native code needs Ghidra (not set up yet, ask me).
- Native binaries (C/C++ engines): Ghidra via REA (not set up yet, ask me).

Triage order always: plain search, then local model labeler, then Claude reads only what the evidence points to.

## Scope

Only create or modify files inside <lab root>, except for REA's own setup (agent config files), which is called out explicitly when it happens.
