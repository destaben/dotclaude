#!/bin/sh
# shellcheck disable=SC1091
# Periodic reachability check, meant for launchd on the Mac (see healthcheck.plist.template).
# No ssh login is ever opened: per host alias a ping and a TCP check of its ssh port, plus the
# print-state guard for printers, plus optional Prometheus queries (plain GETs).
# Usage: healthcheck.sh [--quiet]
# Config: healthcheck.conf (parsed, never sourced), lines:
#   host <alias>                      an alias from ~/.ssh/config (validated like probe.sh does)
#   prometheus <http(s)://host:port>  optional: counts firing alerts and targets that are down
# Printers are those recognised by printers.conf (see SKILL.md). A printer that is printing, paused
# or in an unknown state is NOT probed at all ("busy"): it is only reported, never loaded.
# State lives in $REMOTE_HOSTS_VAULT/healthcheck/ (created 0700, git-ignored): last.txt (problems
# of the previous run) and healthcheck.log. A macOS notification is raised ONLY when the set of
# problems changes (new problem, or recovery); an unchanged problem stays quiet.
# Exit: 0 everything ok, 1 at least one problem, 2 usage or setup problem.
# shellcheck source=lib.sh
LC_ALL=C; export LC_ALL   # character ranges in the validation patterns below mean ASCII only
. "$(dirname "$0")/lib.sh"
quiet=0
case "${1:-}" in '') ;; --quiet) quiet=1 ;; *) echo "usage: healthcheck.sh [--quiet]" >&2; exit 2 ;; esac
[ "$#" -le 1 ] || { echo "usage: healthcheck.sh [--quiet]" >&2; exit 2; }
[ -n "${REMOTE_HOSTS_VAULT:-}" ] || { echo "setup: set REMOTE_HOSTS_VAULT (state and log live in its healthcheck/ folder)" >&2; exit 2; }
conf=$(conf_file healthcheck.conf REMOTE_HOSTS_HEALTHCHECK_CONF)
[ -f "$conf" ] && [ -r "$conf" ] || { echo "setup: no readable healthcheck.conf at $conf" >&2; exit 2; }
dir=$REMOTE_HOSTS_VAULT/healthcheck
umask 077
{ mkdir -p "$dir" && chmod 700 "$dir"; } || { echo "setup: cannot create $dir" >&2; exit 2; }
[ -e "$dir/.gitignore" ] || printf '*\n' > "$dir/.gitignore"

results=$(mktemp "$dir/run.XXXXXX") || exit 2
trap 'rm -f "$results"' EXIT INT TERM
# add <ok|PROBLEM> <text>: one line per check; only text built from validated tokens is stored.
add() { printf '%s %s\n' "$1" "$2" >> "$results"; }

is_darwin=0; [ "$(uname -s)" = Darwin ] && is_darwin=1
ping_ok() {
  command -v ping >/dev/null 2>&1 || return 2     # 2: could not be checked
  if [ "$is_darwin" = 1 ]; then ping -c 1 -W 2000 "$1" >/dev/null 2>&1; else ping -c 1 -W 2 "$1" >/dev/null 2>&1; fi
}

while read -r kind val _ || [ -n "$kind" ]; do
  case "$kind" in ''|'#'*) continue ;; esac
  case "$kind" in
    host)
      if ! valid_alias "$val"; then add PROBLEM "config: '$(printf '%s' "$val" | tr -c 'A-Za-z0-9._-' '?')' is not a plain Host alias"; continue; fi
      if ! printer_guard "$val" >/dev/null 2>&1; then add PROBLEM "$val: printer busy or state unknown (not probed)"; continue; fi
      cfg=$(ssh -n -G -- "$val" 2>/dev/null)
      h=$(printf '%s\n' "$cfg" | awk '$1=="hostname"{print $2; exit}'); p=$(printf '%s\n' "$cfg" | awk '$1=="port"{print $2; exit}')
      case "$h" in ''|-*|*[!A-Za-z0-9.:_-]*) add PROBLEM "$val: unusable host name in ssh config"; continue ;; esac
      case "$p" in ''|*[!0-9]*) add PROBLEM "$val: unusable port in ssh config"; continue ;; esac
      ping_ok "$h"; case $? in 0) pr=up ;; 2) pr=unchecked ;; *) pr=down ;; esac
      if command -v nc >/dev/null 2>&1; then
        if nc -z -w 3 "$h" "$p" >/dev/null 2>&1; then pt=open; else pt=closed; fi
      else pt=unchecked; fi
      if [ "$pr" = unchecked ] && [ "$pt" = unchecked ]; then add PROBLEM "$val: not checked (ping and nc are both missing)"
      elif [ "$pt" = closed ] || { [ "$pr" = down ] && [ "$pt" != open ]; }; then add PROBLEM "$val: unreachable (ping $pr, port $pt)"; else add ok "$val: ping $pr, port $pt"; fi ;;
    prometheus)
      case "$val" in http://*|https://*) ;; *) add PROBLEM "config: prometheus needs an http(s) url"; continue ;; esac
      case "${val#*://}" in ''|*[!A-Za-z0-9.:_\[\]-]*) add PROBLEM "config: prometheus url must be scheme://host[:port]"; continue ;; esac
      command -v python3 >/dev/null 2>&1 || { add PROBLEM "prometheus: python3 missing"; continue; }
      for q in 'ALERTS{alertstate="firing"}' 'up==0'; do
        n=$(curl -g -sS -f -m 10 --max-redirs 0 --proto '=http,https' -G --data-urlencode "query=$q" -- "$val/api/v1/query" 2>/dev/null |
            python3 -I -c 'import json,sys
try:
    d=json.load(sys.stdin); assert d["status"]=="success"; print(len(d["data"]["result"]))
except Exception:
    print("x")')
        if [ "$q" = 'up==0' ]; then label="targets down"; else label="alerts firing"; fi
        case "$n" in 0) add ok "prometheus: 0 $label" ;; x|'') add PROBLEM "prometheus: query failed ($label)" ;; *[!0-9]*) add PROBLEM "prometheus: query failed ($label)" ;; *) add PROBLEM "prometheus: $n $label" ;; esac
      done ;;
    *) add PROBLEM "config: unknown line '$(printf '%s' "$kind" | tr -c 'A-Za-z0-9._-' '?')'" ;;
  esac
done < "$conf"

grep '^PROBLEM ' "$results" | LC_ALL=C sort > "$dir/now.txt" || : > "$dir/now.txt"
[ "$quiet" = 1 ] || cat "$results"
stamp=$(date '+%Y-%m-%d %H:%M:%S')
{ echo "== $stamp"; cat "$results"; } >> "$dir/healthcheck.log"
# keep the log bounded: last 2000 lines
if [ "$(wc -l < "$dir/healthcheck.log")" -gt 4000 ]; then tail -n 2000 "$dir/healthcheck.log" > "$dir/log.new" && mv "$dir/log.new" "$dir/healthcheck.log"; fi

[ -f "$dir/last.txt" ] || : > "$dir/last.txt"
if cmp -s "$dir/now.txt" "$dir/last.txt"; then changed=0; else changed=1; fi
nprob=$(wc -l < "$dir/now.txt" | tr -d ' ')
if [ "$changed" = 1 ]; then
  if [ "$nprob" -eq 0 ]; then msg="All checks ok again"; else msg="$nprob problem(s); first: $(head -n 1 "$dir/now.txt" | cut -c9-120)"; fi
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "remote-hosts health check"' -e 'end run' -- "$msg" >/dev/null 2>&1 || :
  else
    echo "notify: $msg"
  fi
fi
mv "$dir/now.txt" "$dir/last.txt"
[ "$nprob" -eq 0 ]
