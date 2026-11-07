#!/bin/sh
# Least-invasive check of a Klipper/Moonraker printer: ONE plain HTTP GET, no ssh.
# Usage: print-state.sh <host-or-ip>      (default port 80; use host:port if needed)
# Exit: 0 = idle (safe for normal work), 10 = printing/paused (do not load the host),
#       20 = unreachable or unexpected answer (treat as unknown; ask before anything heavy).
case "$1" in ''|-*|*[!A-Za-z0-9.:_-]*) echo "usage: print-state.sh <host-or-ip>" >&2; exit 2 ;; esac
body=$(curl -s -m 5 "http://$1/printer/objects/query?print_stats&display_status") || { echo "state=unreachable"; exit 20; }
printf '%s' "$body" | python3 -I -c '
import json, sys
try:
    s = json.load(sys.stdin)["result"]["status"]
    p, d = s["print_stats"], s.get("display_status", {})
except Exception:
    print("state=unknown"); sys.exit(20)
st = p.get("state", "unknown")
print("state=%s file=%s progress=%.1f%%" % (st, p.get("filename") or "-", 100 * (d.get("progress") or 0)))
sys.exit(10 if st in ("printing", "paused") else 20 if st == "unknown" else 0)
'
