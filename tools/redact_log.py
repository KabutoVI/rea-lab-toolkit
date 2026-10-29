#!/usr/bin/env python3
"""Redact SteamID64s and IPs from a game or mod log before posting it publicly.

Usage: python -I redact_log.py <in.log> <out.log>
Maps each distinct SteamID64 to a stable STEAMID_n placeholder and replaces
every IPv4 with [ip]. Player nicknames are left as they are. Deterministic: same id -> same placeholder across files in one run
is NOT guaranteed across separate runs, so redact a host/client pair together
by importing map_steam; here we keep a shared module-level map per process.
"""
import sys, re

STEAM = re.compile(r'7656\d{13}')
IPV4 = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_ids = {}

def sub_steam(m):
    sid = m.group(0)
    if sid not in _ids:
        _ids[sid] = f"STEAMID_{len(_ids)+1}"
    return _ids[sid]

def redact_text(t):
    t = STEAM.sub(sub_steam, t)
    t = IPV4.sub("[ip]", t)
    return t

def main(paths):
    # paths: flat list of in,out,in,out,... processed with ONE shared id map
    for i in range(0, len(paths), 2):
        src, dst = paths[i], paths[i+1]
        with open(src, encoding='utf-8', errors='replace') as f:
            data = f.read()
        out = redact_text(data)
        with open(dst, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
        print(f"redacted {src} -> {dst}")
    print("steamid map:", _ids)

if __name__ == '__main__':
    main(sys.argv[1:])
