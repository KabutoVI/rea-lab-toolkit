"""
Split approved decompiled C# files into individual methods and export only
the methods that contain fingerprint hits, one file per method, plus a
manifest (class, method, line range, fingerprints).

This is a heuristic brace-depth parser, not a real C# parser. It is tuned
for ILSpy's decompiled output (mechanical, consistently formatted) and
will occasionally mis-detect a method boundary or name; false positives
just export a harmless extra chunk, false negatives just skip a method
that can still be found by re-running against the full decompiled file.

Usage: python export_methods.py
Reads approved=true entries from candidates.json and fingerprint terms from
fingerprints.json (see fingerprints.py), reads source files from
functions\\decompiled\\, writes to functions\\, and writes manifest.json.
"""

import os
import json
import re
from pathlib import Path

import fingerprints

LAB_ROOT = Path(os.environ.get("REA_LAB_ROOT", "."))
TARGET_ROOT = LAB_ROOT / "targets" / os.environ.get("REA_TARGET", "your-target")
DECOMPILED_ROOT = TARGET_ROOT / "functions" / "decompiled"
OUT_ROOT = TARGET_ROOT / "functions"
CANDIDATES_PATH = TARGET_ROOT / "candidates.json"
MANIFEST_PATH = OUT_ROOT / "manifest.json"

CONTROL_KEYWORDS = {
    "if", "else", "for", "foreach", "while", "switch", "case", "default",
    "try", "catch", "finally", "using", "lock", "fixed", "do", "checked",
    "unchecked", "get", "set", "add", "remove", "unsafe",
}
TYPE_KEYWORDS = {"class", "struct", "interface", "enum", "namespace"}


def sanitize(text):
    """Blank out string/char literal and comment contents, preserving
    length and newlines, so brace counting ignores braces inside them."""
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = i
            while j < n and text[j] != "\n":
                out[j] = " "
                j += 1
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = i
            while j < n - 1 and not (text[j] == "*" and text[j + 1] == "/"):
                if text[j] != "\n":
                    out[j] = " "
                j += 1
            if j < n - 1:
                out[j] = out[j + 1] = " "
                j += 2
            i = j
        elif c == "@" and i + 1 < n and text[i + 1] == '"':
            j = i + 2
            out[i] = out[i + 1] = " "
            while j < n:
                if text[j] == '"' and j + 1 < n and text[j + 1] == '"':
                    if text[j] != "\n":
                        out[j] = " "
                    if text[j + 1] != "\n":
                        out[j + 1] = " "
                    j += 2
                    continue
                if text[j] == '"':
                    out[j] = " "
                    j += 1
                    break
                if text[j] != "\n":
                    out[j] = " "
                j += 1
            i = j
        elif c == '"':
            j = i + 1
            out[i] = " "
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    if text[j] != "\n":
                        out[j] = " "
                    j += 1
                if j < n and text[j] != "\n":
                    out[j] = " "
                j += 1
            if j < n:
                out[j] = " "
                j += 1
            i = j
        elif c == "'":
            j = i + 1
            out[i] = " "
            while j < n and text[j] != "'":
                if text[j] == "\\" and j + 1 < n:
                    if text[j] != "\n":
                        out[j] = " "
                    j += 1
                if j < n and text[j] != "\n":
                    out[j] = " "
                j += 1
            if j < n:
                out[j] = " "
                j += 1
            i = j
        else:
            i += 1
    return "".join(out)


def find_brace_pairs(sanitized):
    stack = []
    pairs = []
    for i, c in enumerate(sanitized):
        if c == "{":
            stack.append(i)
        elif c == "}":
            if stack:
                open_idx = stack.pop()
                pairs.append((open_idx, i))
    return pairs


def extract_header(sanitized, open_idx):
    j = open_idx - 1
    depth = 0
    while j >= 0:
        c = sanitized[j]
        if c in ")]":
            depth += 1
        elif c in "([":
            depth -= 1
        elif c in ";{}" and depth <= 0:
            j += 1
            break
        j -= 1
    else:
        j = 0
    return sanitized[max(j, 0):open_idx]


def method_name_from_header(header):
    cut = re.split(r":\s*(?:base|this)\s*\(", header)[0]
    matches = list(re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^<>]*>)?\s*\(", cut))
    if not matches:
        return None
    return matches[-1].group(1)


def is_method_header(header):
    stripped = header.strip()
    if not stripped:
        return False
    collapsed = re.sub(r"\s+", " ", stripped)
    if re.search(r"=>\s*$", collapsed):
        return False
    first_word_match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", collapsed)
    first_word = first_word_match.group(0) if first_word_match else ""
    if first_word in CONTROL_KEYWORDS:
        return False
    for kw in TYPE_KEYWORDS:
        if re.search(rf"\b{kw}\b", collapsed):
            return False
    if "(" not in collapsed:
        return False
    return True


def extract_methods(text):
    sanitized = sanitize(text)
    pairs = find_brace_pairs(sanitized)
    methods = []
    for open_idx, close_idx in pairs:
        header = extract_header(sanitized, open_idx)
        if not is_method_header(header):
            continue
        name = method_name_from_header(header)
        if not name:
            continue
        start_line = text.count("\n", 0, open_idx) + 1
        header_start_offset = open_idx - len(header)
        sig_start_line = text.count("\n", 0, max(header_start_offset, 0)) + 1
        end_line = text.count("\n", 0, close_idx) + 1
        body = text[max(header_start_offset, 0):close_idx + 1]
        methods.append({
            "name": name,
            "start_line": sig_start_line,
            "end_line": end_line,
            "source": body,
        })
    return methods


def count_terms(text, terms):
    hits = {}
    for term in terms:
        count = len(re.findall(re.escape(term), text))
        if count:
            hits[term] = count
    return hits


CONFIG_PATH = TARGET_ROOT / "fingerprints.json"


def main():
    cfg = fingerprints.load_config(CONFIG_PATH)
    decisions = cfg["decisions"]
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    approved = [c for c in candidates if c["approved"]]

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    exported_count = 0

    for cand in approved:
        rel = cand["file"]
        src_path = DECOMPILED_ROOT / rel
        if not src_path.exists():
            print(f"MISSING source file, skipped: {rel}")
            continue

        text = src_path.read_text(encoding="utf-8", errors="ignore")
        class_name = Path(rel).stem
        terms = fingerprints.terms_for(cfg, decisions.get(rel, {}).get("groups"))

        methods = extract_methods(text)
        for m in methods:
            hits = count_terms(m["source"], terms)
            if not hits:
                continue
            safe_method = re.sub(r"[^A-Za-z0-9_]", "_", m["name"])
            out_name = f"{class_name}__{safe_method}__L{m['start_line']}.cs"
            out_path = OUT_ROOT / out_name
            out_path.write_text(m["source"], encoding="utf-8")
            manifest.append({
                "class": class_name,
                "source_file": rel,
                "method": m["name"],
                "start_line": m["start_line"],
                "end_line": m["end_line"],
                "exported_file": out_name,
                "fingerprints": hits,
            })
            exported_count += 1

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exported {exported_count} methods from {len(approved)} approved files.")
    print(f"Manifest written to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
