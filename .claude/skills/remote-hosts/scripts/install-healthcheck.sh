#!/bin/sh
# shellcheck disable=SC1091
# Render the launchd plist for healthcheck.sh and PRINT the launchctl commands. It never runs
# launchctl and never writes into ~/Library: loading a job is the owner's decision.
# Usage: install-healthcheck.sh [--interval <seconds>] [--label <reverse.dns.label>]
# Needs REMOTE_HOSTS_VAULT. Writes <vault>/healthcheck/<label>.plist (mode 0600, git-ignored).
# Default interval 1800 s (30 minutes); minimum 300.
# Exit: 0 ok, 2 usage or setup problem.
# shellcheck source=lib.sh
LC_ALL=C; export LC_ALL   # character ranges in the validation patterns below mean ASCII only
. "$(dirname "$0")/lib.sh"
usage() { echo "usage: install-healthcheck.sh [--interval <seconds>] [--label <label>]" >&2; exit 2; }
interval=1800; label=local.remote-hosts.healthcheck
while [ "$#" -gt 0 ]; do
  case "$1" in
    --interval) [ "$#" -ge 2 ] || usage; interval=$2; shift 2 ;;
    --label) [ "$#" -ge 2 ] || usage; label=$2; shift 2 ;;
    *) usage ;;
  esac
done
case "$interval" in ''|*[!0-9]*) usage ;; esac
[ "$interval" -ge 300 ] && [ "$interval" -le 86400 ] || { echo "interval must be 300..86400 seconds" >&2; exit 2; }
case "$label" in ''|-*|*[!A-Za-z0-9._-]*) usage ;; esac
[ -n "${REMOTE_HOSTS_VAULT:-}" ] && [ -d "$REMOTE_HOSTS_VAULT" ] || { echo "setup: REMOTE_HOSTS_VAULT must name the vault directory" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd -P) || exit 2
script=$here/healthcheck.sh
vault=$(cd "$REMOTE_HOSTS_VAULT" && pwd -P) || exit 2
# XML-escape and sed-escape the substituted values (paths may contain & or <).
esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/[\\|&]/\\&/g'; }
dir=$vault/healthcheck
umask 077
{ mkdir -p "$dir" && chmod 700 "$dir"; } || exit 2
[ -e "$dir/.gitignore" ] || printf '*\n' > "$dir/.gitignore"
out=$dir/$label.plist
sed -e "s|__LABEL__|$(esc "$label")|g" -e "s|__SCRIPT__|$(esc "$script")|g" \
    -e "s|__VAULT__|$(esc "$vault")|g" -e "s|__INTERVAL__|$interval|g" \
    "$here/healthcheck.plist.template" > "$out" || exit 2
chmod 600 "$out"
echo "wrote $out (every $interval s). Nothing was loaded. To start it, run:"
echo "  launchctl bootstrap gui/\$(id -u) $(shell_quote "$out")"
echo "To stop it later:"
echo "  launchctl bootout gui/\$(id -u)/$label"
