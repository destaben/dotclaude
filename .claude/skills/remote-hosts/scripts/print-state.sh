#!/bin/sh
# Least-invasive check of a Klipper/Moonraker printer: ONE plain HTTP GET, no ssh.
# Usage: print-state.sh <host-or-ip>      (default port 80; use host:port if needed)
# Exit: 0  = idle/standby/complete/cancelled (safe for normal work)
#       10 = printing or paused (do not load the host)
#       20 = unknown: unreachable, malformed answer, python3 missing, or Klipper in "error"
#            (treat like printing and ask the user)
#       2  = bad usage
case "$1" in ''|-*|*[!A-Za-z0-9.:_-]*) echo "usage: print-state.sh <host-or-ip>" >&2; exit 2 ;; esac
command -v python3 >/dev/null 2>&1 || { echo "state=unknown (python3 missing)"; exit 20; }
body=$(curl -s -m 5 "http://$1/printer/objects/query?print_stats&display_status") || { echo "state=unreachable"; exit 20; }
printf '%s' "$body" | python3 -I -c '
import json, sys
try:
    s = json.load(sys.stdin)["result"]["status"]
    p, d = s["print_stats"], s.get("display_status") or {}
    st = str(p.get("state") or "unknown")
    try:
        pct = 100 * float(d.get("progress") or 0)
    except (TypeError, ValueError):
        pct = 0.0
    print("state=%s file=%s progress=%.1f%%" % (st, p.get("filename") or "-", pct))
except Exception:
    print("state=unknown"); sys.exit(20)
sys.exit(10 if st in ("printing", "paused") else 0 if st in ("standby", "complete", "cancelled") else 20)
'
