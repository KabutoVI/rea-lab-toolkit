"""
Plain-text fingerprint search over decompiled C# files to rank candidate
classes, without reading any code content.

Usage: python fingerprint_search.py <decompiled-dir> <candidates.json-out> [--config fingerprints.json]

Scans every .cs file for the scored terms in your fingerprint config (see
fingerprints.py for the format; a small default set is used if none is given)
and a separate UI term set used only to flag likely UI files (not counted
toward the score).

Prints a ranked table (by hits-per-1000-lines) and writes candidates.json in
the dashboard's file contract:
[ { "file", "lines", "total_hits", "density_per_1k", "fingerprints",
    "approved", "note" } ]

Approval decisions and notes come from the "decisions" section of the config,
since they come from your review, not from the scan itself.
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import fingerprints


def count_terms(text, terms):
    hits = Counter()
    for term in terms:
        count = len(re.findall(re.escape(term), text))
        if count:
            hits[term] = count
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decompiled_dir")
    ap.add_argument("candidates_out")
    ap.add_argument("--config", default=None, help="fingerprint config JSON (see fingerprints.py)")
    args = ap.parse_args()

    cfg = fingerprints.load_config(args.config)
    scored_terms = fingerprints.terms_for(cfg)
    ui_terms = cfg["ui"]
    decisions = cfg["decisions"]

    root = Path(args.decompiled_dir)
    out_path = Path(args.candidates_out)
    cs_files = list(root.rglob("*.cs"))

    results = []
    candidates = []
    for f in cs_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        line_count = text.count("\n") + 1
        hits = count_terms(text, scored_terms)
        ui_hits = count_terms(text, ui_terms)
        if not hits:
            continue

        total = sum(hits.values())
        density = total / line_count * 1000
        ui_total = sum(ui_hits.values())
        ui_density = ui_total / line_count * 1000
        relpath = f.relative_to(root)
        relpath_str = str(relpath).replace("\\", "/")

        results.append((density, total, line_count, ui_total, ui_density, relpath, hits))

        decision = decisions.get(relpath_str, {})
        candidates.append({
            "file": relpath_str,
            "lines": line_count,
            "total_hits": total,
            "density_per_1k": round(density, 1),
            "fingerprints": dict(hits),
            "approved": bool(decision.get("approved", False)),
            "note": decision.get("note", ""),
        })

    results.sort(key=lambda r: r[0], reverse=True)
    candidates.sort(key=lambda c: c["density_per_1k"], reverse=True)

    print(f"Scanned {len(cs_files)} files. {len(results)} had fingerprint hits.\n")
    print(f"{'Dens/1k':>8}  {'Total':>6}  {'Lines':>6}  {'UI?':>4}  {'File':<30}  Top fingerprints")
    print("-" * 130)
    for density, total, lines, ui_total, ui_density, relpath, hits in results[:40]:
        top = ", ".join(f"{k}:{v}" for k, v in hits.most_common(5))
        ui_flag = "UI" if ui_density > density * 0.5 and ui_total >= 3 else ""
        print(f"{density:>8.1f}  {total:>6}  {lines:>6}  {ui_flag:>4}  {str(relpath):<30}  {top}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    print(f"\nWrote {len(candidates)} candidates to {out_path}")
    print(f"(generated {datetime.now(timezone.utc).isoformat()})")


if __name__ == "__main__":
    main()
