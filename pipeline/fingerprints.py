"""Fingerprint configuration shared by fingerprint_search.py and export_methods.py.

A fingerprint is a plain-text term (an API name, a keyword, a type name) whose
presence hints that a file or method is relevant to what you are studying.
Terms are grouped, and the config lives next to your target's data, not in
this repo, so what you are looking for stays yours.

Config file (JSON), e.g. targets/<name>/fingerprints.json:

{
  "scored": {
    "networking": ["Socket", "Send", "Receive"],
    "serialization": ["Serialize", "BinaryReader"]
  },
  "ui": ["Canvas", "Button"],
  "decisions": {
    "SomeFile.cs": { "approved": true, "note": "why", "groups": ["networking"] }
  }
}

- "scored": groups of terms that count toward a file's ranking.
- "ui": terms used only to flag likely UI files (not scored).
- "decisions": your review results per file (relative path, forward slashes).
  "approved" feeds export_methods.py; the optional "groups" limits which
  scored groups pick the methods to export for that file.

With no config the small default set below is used, just to show the shape.
"""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "scored": {
        "networking": ["Socket", "NetworkStream", "Send", "Receive", "Packet"],
        "serialization": ["Serialize", "Deserialize", "BinaryReader", "BinaryWriter"],
        "crypto": ["AES", "RSA", "Hash", "Encrypt", "Decrypt"],
    },
    "ui": ["Canvas", "Button", "OnClick", "RectTransform", "TextMeshPro"],
    "decisions": {},
}


def load_config(path=None):
    """Return the config dict, falling back to DEFAULT_CONFIG if path is None or missing."""
    if path and Path(path).is_file():
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            "scored": cfg.get("scored", {}),
            "ui": cfg.get("ui", []),
            "decisions": cfg.get("decisions", {}),
        }
    return DEFAULT_CONFIG


def terms_for(cfg, groups=None):
    """Flatten scored groups (or just the named ones) into a unique term list."""
    names = groups if groups else list(cfg["scored"])
    seen, out = set(), []
    for g in names:
        for t in cfg["scored"].get(g, []):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out
