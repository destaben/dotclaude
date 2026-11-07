#!/bin/sh
# shellcheck disable=SC1091,SC2016
# Non-interactive, read-only SSH diagnosis for one or more aliases.
# Usage: probe.sh <alias> [alias...]   (never sends a password)
# Exit: 0 all ok, 1 key auth failed, 2 usage or refused alias, 3 printer guard refused (most severe wins).
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
[ "$#" -gt 0 ] || { echo "usage: probe.sh <alias> [alias...]" >&2; exit 2; }
rc=0
set_rc() { [ "$1" -gt "$rc" ] && rc=$1; }   # keep the most severe code: 3 guard > 2 refused > 1 failed
for h in "$@"; do
  echo "=== $h"
  if ! valid_alias "$h"; then echo "  RESULT: refused (not a plain Host alias in ~/.ssh/config)"; set_rc 2; continue; fi
  printer_guard "$h" || { echo "  RESULT: refused (printer guard, see stderr)"; set_rc 3; continue; }
  cfg=$(ssh -G -- "$h")
  host=$(echo "$cfg" | awk '$1=="hostname"{print $2}')
  port=$(echo "$cfg" | awk '$1=="port"{print $2}')
  # Print no address, user name or key path: probe output is often pasted into issues and PRs.
  echo "  cfg: port $port, $(echo "$cfg" | awk '$1=="identityfile"{n++} END{print n+0}') identity file(s) configured"
  # No `--` is passed to nc (not every netcat build accepts it); a host name that could be read as an
  # option is refused instead.
  if ! command -v nc >/dev/null 2>&1; then
    echo "  port $port: not checked (nc not installed); the ssh result below is authoritative"
  elif [ -z "$host" ] || [ "${host#-}" != "$host" ]; then
    echo "  port $port: not checked (unusable host name); the ssh result below is authoritative"
  else
    if nc -z -w 3 "$host" "$port" >/dev/null 2>&1; then echo "  port $port: open"; else echo "  port $port: CLOSED/unreachable"; fi
    # The banner comes from the device, so it is untrusted text and is never echoed. It is mapped to
    # a fixed vocabulary: a known server family plus a version made of digits, or a generic label.
    if ! command -v perl >/dev/null 2>&1; then
      echo "  banner: not read (perl is needed for a hard time limit on the read)"
    else
    raw=$(bounded 4 nc -w 3 "$host" "$port" </dev/null 2>/dev/null | head -c 120 | head -1 | tr -cd '[:print:]')
    case "$raw" in
      SSH-2.0-OpenSSH_[0-9]*) banner="OpenSSH $(printf '%s' "$raw" | sed -n 's/^SSH-2\.0-OpenSSH_\([0-9][0-9.]*\(p[0-9][0-9]*\)\{0,1\}\).*/\1/p')" ;;
      SSH-2.0-dropbear_[0-9]*) banner="Dropbear $(printf '%s' "$raw" | sed -n 's/^SSH-2\.0-dropbear_\([0-9][0-9.]*\).*/\1/p')" ;;
      SSH-2.0-*|SSH-1.99-*) banner="SSH server (other)" ;;
      *) banner="(not an SSH identification string)" ;;
    esac
    echo "  banner: $banner"
    fi
  fi
  # The verdict (RESULT) comes from ssh's exit status only; nothing the device sends can change it.
  # The "server offers" line is informational: it is limited to a fixed vocabulary of method names, but
  # a hostile server could still misreport it (the verbose log also contains its pre-auth banner), so
  # do not rely on it for decisions.
  out=$(ssh -n -v -T -o BatchMode=yes -o ConnectTimeout=5 -- "$h" true 2>&1); status=$?
  methods=$(printf '%s\n' "$out" | grep -m1 '^debug1: Authentications that can continue' | grep -oE 'publickey|password|keyboard-interactive|gssapi-with-mic|hostbased' | sort -u | tr '\n' ' ')
  [ -n "$methods" ] && echo "  server offers: $methods"
  if [ "$status" -eq 0 ]; then echo "  RESULT: key auth OK"; else echo "  RESULT: key auth FAILED (ssh exit $status)"; set_rc 1; fi
done
exit "$rc"
