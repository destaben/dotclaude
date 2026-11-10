#!/bin/sh
# shellcheck disable=SC1091
# Call ONE Home Assistant service on ONE entity. Dry run by default; --yes performs the POST.
# Usage: ha-call.sh <domain> <service> <entity_id> [--yes]
# The only request ever sent is POST /api/services/<domain>/<service> with {"entity_id": "<entity>"}.
# Config: ha.conf (see ha-read.sh) plus, to protect a printer:
#   printer_power_entity <entity_id>   the entity that switches the printer's power
#   printer_moonraker    <host[:port]> its Moonraker address (as in printers.conf)
# That entity is refused unless print-state.sh exits 0, in the dry run too. If the entity is set
# but the address is missing, it is refused (fail closed). The token comes from the Keychain and is
# passed to curl on stdin. The guard is a safety net against mistakes, not a barrier against
# someone who can run other commands (a group or scene that includes the printer is not covered).
# Exit: 0 ok (or dry run), 1 request failed, 2 usage/refused, 3 printer guard refused, 4 setup problem.
# shellcheck source=lib.sh
LC_ALL=C; export LC_ALL   # character ranges in the validation patterns below mean ASCII only
. "$(dirname "$0")/lib.sh"
usage() { echo "usage: ha-call.sh <domain> <service> <entity_id> [--yes]" >&2; exit 2; }
yes=0
case "$#" in 3) ;; 4) [ "$4" = --yes ] || usage; yes=1 ;; *) usage ;; esac
dom=$1; svc=$2; ent=$3
case "$dom" in ''|*[!a-z0-9_]*) usage ;; esac
case "$svc" in ''|*[!a-z0-9_]*) usage ;; esac
case "$ent" in *[!a-z0-9_.]*|.*|*.|*.*.*) usage ;; esac   # exactly <domain>.<object>, no list, no "all"
case "$ent" in *.*) ;; *) usage ;; esac

conf=$(conf_file ha.conf REMOTE_HOSTS_HA_CONF)
[ -f "$conf" ] && [ -r "$conf" ] || { echo "setup: no readable ha.conf at $conf" >&2; exit 4; }
url=$(conf_get "$conf" url); kcs=$(conf_get "$conf" keychain_service); kcs=${kcs:-remote-hosts-ha}
pent=$(conf_get "$conf" printer_power_entity); pmr=$(conf_get "$conf" printer_moonraker)
case "$url" in http://*|https://*) ;; *) echo "setup: ha.conf needs 'url http(s)://host[:port]'" >&2; exit 4 ;; esac
case "${url#*://}" in ''|*[!A-Za-z0-9.:_\[\]-]*) echo "setup: ha.conf url must be scheme://host[:port] only" >&2; exit 4 ;; esac
case "$kcs" in *[!A-Za-z0-9._-]*|-*) echo "setup: bad keychain_service name" >&2; exit 4 ;; esac

if [ -n "$pent" ] && [ "$(printf '%s' "$ent" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$pent" | tr '[:upper:]' '[:lower:]')" ]; then
  if [ -z "$pmr" ]; then echo "refused: $ent is the printer power entity but ha.conf has no printer_moonraker address" >&2; exit 3; fi
  "$(dirname "$0")/print-state.sh" "$pmr" >/dev/null; gs=$?
  if [ "$gs" -ne 0 ]; then
    echo "refused: $ent switches the printer and its print state is not idle (print-state exit $gs)" >&2
    exit 3
  fi
fi

body=$(printf '{"entity_id": "%s"}' "$ent")
echo "POST $url/api/services/$dom/$svc $body"
if [ "$yes" -ne 1 ]; then echo "dry run: nothing sent; add --yes to perform it"; exit 0; fi

command -v security >/dev/null 2>&1 || { echo "setup: macOS 'security' not found (Keychain required)" >&2; exit 4; }
token=$(security find-generic-password -s "$kcs" -a "${USER:-$(id -un)}" -w 2>/dev/null) && [ -n "$token" ] || {
  echo "setup: no Keychain item for service '$kcs'" >&2; exit 4; }
case "$token" in *[!A-Za-z0-9._~+/=-]*) echo "setup: Keychain token has unexpected characters" >&2; exit 4 ;; esac
printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$token" |
  curl -g -sS -f -m 20 --max-redirs 0 --proto '=http,https' -X POST -H @- --data "$body" -- "$url/api/services/$dom/$svc" >/dev/null
rc=$?
[ "$rc" -eq 0 ] || { echo "request failed (curl exit $rc)" >&2; exit 1; }
echo "done"
