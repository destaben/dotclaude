#!/bin/sh
# shellcheck disable=SC1091
# Read-only Home Assistant REST access: ONE allowlisted GET, nothing else.
# Usage: ha-read.sh states [entity_id]
#        ha-read.sh config | error_log | logbook[/<timestamp>] | history[/<timestamp>]
#        ha-read.sh "history/period/<timestamp>?filter_entity_id=<entity>&minimal_response"
#        (a leading "/api/" is accepted: ha-read.sh /api/states/sensor.x)
# Config (parsed, never sourced; see SKILL.md): ha.conf with "url <http(s)://host[:port]>" and
# optionally "keychain_service <name>" (default: remote-hosts-ha). The long-lived token of a
# NON-ADMIN Home Assistant user lives only in the macOS Keychain and reaches curl on stdin
# (-H @-), never on argv, in a file or in the environment of curl.
# There is no way to choose a method, header, URL or curl flag: any argument that starts with "-"
# or is not on the allowlist is refused. Exit: 0 ok, 1 request failed, 2 usage/refused,
# 4 setup problem (config or token missing).
# shellcheck source=lib.sh
LC_ALL=C; export LC_ALL   # character ranges in the validation patterns below mean ASCII only
. "$(dirname "$0")/lib.sh"
usage() { echo "usage: ha-read.sh states [entity_id] | config | error_log | logbook[/ts] | history[/period/ts][?query]" >&2; exit 2; }
[ "$#" -eq 1 ] || [ "$#" -eq 2 ] || usage

# Build the request path from the arguments; "states <entity>" is the only two-argument form.
p=$1
if [ "$#" -eq 2 ]; then
  [ "$1" = states ] || usage
  p=states/$2
fi
p=${p#/}; p=${p#api/}
case "$p" in -*|*..*|*//*|*[!A-Za-z0-9_./?\&=,:+%@-]*) echo "refused: argument not allowed" >&2; exit 2 ;; esac
path=${p%%\?*}
query=""; [ "$path" = "$p" ] || query=${p#*\?}
case "$path" in
  states|config|error_log|logbook|history|history/period|logbook/*|history/period/*) ;;
  states/*) case "${path#states/}" in
              *[!a-z0-9_.]*|.*|*.|*.*.*) echo "refused: not an entity id" >&2; exit 2 ;;
              *.*) ;;
              *) echo "refused: not an entity id" >&2; exit 2 ;;
            esac ;;
  *) echo "refused: path '/api/$path' is not on the read allowlist" >&2; exit 2 ;;
esac
# history and logbook take a timestamp (and nothing else) after the prefix.
case "$path" in
  logbook/*|history/period/*)
    case "${path#*/}" in period/*) ts=${path#history/period/} ;; *) ts=${path#logbook/} ;; esac
    case "$ts" in ''|*/*|*[!0-9T:+%.Z-]*) echo "refused: bad timestamp" >&2; exit 2 ;; esac ;;
esac
[ "$path" = history ] && path=history/period

conf=$(conf_file ha.conf REMOTE_HOSTS_HA_CONF)
[ -f "$conf" ] && [ -r "$conf" ] || { echo "setup: no readable ha.conf at $conf" >&2; exit 4; }
if bad=$(conf_unknown_key "$conf" url keychain_service printer_power_entity printer_moonraker); then
  echo "setup: unknown key '$(printf '%s' "$bad" | tr -c 'A-Za-z0-9._-' '?')' in ha.conf (a misspelled key must not silently drop a setting)" >&2; exit 4
fi
url=$(conf_get "$conf" url); svc=$(conf_get "$conf" keychain_service); svc=${svc:-remote-hosts-ha}
case "$url" in
  http://*|https://*) ;;
  *) echo "setup: ha.conf needs 'url http(s)://host[:port]'" >&2; exit 4 ;;
esac
case "${url#*://}" in ''|*[!A-Za-z0-9.:_\[\]-]*) echo "setup: ha.conf url must be scheme://host[:port] only" >&2; exit 4 ;; esac
case "$svc" in *[!A-Za-z0-9._-]*|-*) echo "setup: bad keychain_service name" >&2; exit 4 ;; esac
command -v security >/dev/null 2>&1 || { echo "setup: macOS 'security' not found (Keychain required)" >&2; exit 4; }
token=$(security find-generic-password -s "$svc" -a "${USER:-$(id -un)}" -w 2>/dev/null) && [ -n "$token" ] || {
  echo "setup: no Keychain item for service '$svc' (the owner adds it, see SKILL.md)" >&2; exit 4; }
case "$token" in *[!A-Za-z0-9._~+/=-]*) echo "setup: Keychain token has unexpected characters" >&2; exit 4 ;; esac

full="$url/api/$path"; [ -z "$query" ] || full="$full?$query"
# printf is a builtin: the token never appears in a process argument list. -g: no URL globbing;
# --max-redirs 0: a redirect could carry the header elsewhere; --proto restricts to http(s).
out=$(printf 'Authorization: Bearer %s\n' "$token" | curl -g -sS -f -m 20 --max-redirs 0 --proto '=http,https' -X GET -H @- -- "$full")
rc=$?
[ "$rc" -eq 0 ] || { echo "request failed (curl exit $rc)" >&2; exit 1; }
# The error log is free text from the instance: strip control characters and redact best-effort.
if [ "$path" = error_log ]; then
  command -v perl >/dev/null 2>&1 || { echo "setup: perl is needed to redact the error log; not shown" >&2; exit 4; }
  printf '%s\n' "$out" | sanitize_text 4000 | redact
else printf '%s\n' "$out"; fi
