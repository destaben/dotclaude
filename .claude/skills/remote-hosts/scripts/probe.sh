#!/bin/sh
# shellcheck disable=SC1091,SC2016
# Non-interactive, read-only SSH diagnosis for one or more aliases.
# Usage: probe.sh <alias> [alias...]   (never sends a password)
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
rc=0
for h in "$@"; do
  echo "=== $h"
  if ! valid_alias "$h"; then echo "  RESULT: refused (not a plain Host alias in ~/.ssh/config)"; rc=2; continue; fi
  cfg=$(ssh -G -- "$h")
  host=$(echo "$cfg" | awk '$1=="hostname"{print $2}')
  port=$(echo "$cfg" | awk '$1=="port"{print $2}')
  echo "$cfg" | awk '$1~/^(hostname|user|port|identityfile)$/{print "  cfg:",$1,$2}'
  if nc -z -w 3 -- "$host" "$port" >/dev/null 2>&1; then echo "  port $port: open"; else echo "  port $port: CLOSED/unreachable"; fi
  echo "  banner: $(nc -w 3 -- "$host" "$port" </dev/null 2>/dev/null | head -1)"
  out=$(ssh -n -v -T -o BatchMode=yes -o ConnectTimeout=5 -- "$h" true 2>&1)
  echo "$out" | grep -E "Authentications that can continue|Offering public key|Server accepts key|Authenticated to|Permission denied" | sed 's/^/  /'
  if echo "$out" | grep -q "Authenticated to"; then echo "  RESULT: key auth OK"; else echo "  RESULT: key auth FAILED"; [ "$rc" -lt 2 ] && rc=1; fi
done
exit $rc
