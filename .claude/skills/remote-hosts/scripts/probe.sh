#!/bin/sh
# Non-interactive, read-only SSH diagnosis for one or more aliases.
# Usage: probe.sh <alias> [alias...]   (never sends a password)
for h in "$@"; do
  echo "=== $h"
  ssh -G "$h" | awk '$1~/^(hostname|user|port|identityfile)$/{print "  cfg:",$1,$2}'
  host=$(ssh -G "$h" | awk '$1=="hostname"{print $2}')
  port=$(ssh -G "$h" | awk '$1=="port"{print $2}')
  nc -z -G 3 "$host" "$port" >/dev/null 2>&1 && echo "  port $port: open" || echo "  port $port: CLOSED/unreachable"
  echo "  banner: $(printf '' | nc -w 3 "$host" "$port" 2>/dev/null | head -1)"
  out=$(ssh -v -o BatchMode=yes -o ConnectTimeout=5 "$h" true 2>&1)
  echo "$out" | grep -E "Authentications that can continue|Offering public key|Server accepts key|Authenticated to|Permission denied" | sed 's/^/  /'
  echo "$out" | grep -qE "Authenticated to" && echo "  RESULT: key auth OK" || echo "  RESULT: key auth FAILED"
done
