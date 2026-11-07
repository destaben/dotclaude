# shellcheck shell=sh
# Shared helpers, sourced by the other scripts (POSIX sh).

# ssh_config_files: the main ssh config plus files pulled in by Include directives, followed
# recursively up to 3 levels deep (which also bounds include cycles).
ssh_config_files() { _ssh_cfg "$HOME/.ssh/config" 0; }
_ssh_cfg() {
  [ -r "$1" ] || return 0
  printf '%s\n' "$1"
  [ "$2" -lt 3 ] || return 0
  awk 'tolower($1)=="include"{for(i=2;i<=NF;i++)print $i}' "$1" | while read -r p; do
    case "$p" in
      /*) pre=""; pat=$p ;;
      "~"/*) pre="$HOME/"; pat=${p#"~"/} ;;
      *) pre="$HOME/.ssh/"; pat=$p ;;
    esac
    # The prefix is quoted (HOME may contain spaces); only the user's glob pattern is expanded.
    # shellcheck disable=SC2086
    for f in "$pre"$pat; do [ -f "$f" ] && _ssh_cfg "$f" $(($2 + 1)); done
  done
}

# valid_alias <alias>: succeed only for a plain token that is an exact Host entry
# (case-insensitive keyword, Include files honoured, trailing comments ignored).
# Blocks option injection such as "-oProxyCommand=...".
valid_alias() {
  case "$1" in ''|-*|.*|*[!A-Za-z0-9._-]*) return 1 ;; esac   # no leading dot: '.' and '..' must never name the output dir
  ssh_config_files | while read -r f; do
    awk -v a="$1" 'tolower($1)=="host"{for(i=2;i<=NF;i++){ if($i ~ /^#/) break; if($i==a){print "y"; exit} }}' "$f"
  done | grep -q y
}

# shell_quote <string>: print the string as one single-quoted shell word (safe for any content,
# including apostrophes), for building a remote `sh -c '...'` command.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# printer_guard <alias>: if the alias is listed as a printer, require print-state.sh to report it
# idle before any ssh. Returns 3 (and explains) otherwise. The mapping file has lines
# "<alias> <host[:port]>" (Moonraker address) and defaults to
# ${HOMELAB_VAULT:-$HOME/homelab-vault}/config/printers.conf (override: REMOTE_HOSTS_PRINTERS).
# No file or no entry: no guard. REMOTE_HOSTS_FORCE=1 bypasses it after the user agreed.
printer_guard() {
  cfg=${REMOTE_HOSTS_PRINTERS:-${HOMELAB_VAULT:-$HOME/homelab-vault}/config/printers.conf}
  [ -r "$cfg" ] || return 0
  target=$(awk -v a="$1" '$1==a{print $2; exit}' "$cfg")
  [ -n "$target" ] || return 0
  if [ "${REMOTE_HOSTS_FORCE:-}" = 1 ]; then echo "note: print-state guard bypassed for $1 (REMOTE_HOSTS_FORCE=1)" >&2; return 0; fi
  st=$("$(dirname "$0")/print-state.sh" "$target"); gs=$?
  [ "$gs" -eq 0 ] && return 0
  echo "refused: $1 is a printer and its print state is '$st' (print-state exit $gs). Do not load the host;" >&2
  echo "confirm with the user, then rerun with REMOTE_HOSTS_FORCE=1 if they agree." >&2
  return 3
}

# bounded <seconds> <command...>: run a command with a hard wall-clock limit (needs perl; without
# perl the command runs unbounded, which callers must tolerate).
bounded() {
  secs=$1; shift
  if command -v perl >/dev/null 2>&1; then perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; else "$@"; fi
}

# redact: BEST-EFFORT removal of credentials from text on stdin. It is a safety net, not a
# guarantee: output must still be treated as private. Covers URL userinfo (up to the last
# "@" of the token), Authorization values, Bearer/Basic tokens, "--password X" style flags,
# "curl -u/--user user:pass", whole `-H/--header` values naming a credential, "sshpass -p SECRET", "mysql -pSECRET", and NAME=value / NAME: value for password, passwd,
# passphrase, pass, pwd, token, secret, auth, cookie, session, credentials and any NAME_KEY
# (including prefixed names such as DB_PASSWORD or suffixed ones such as TOKEN_FILE). A value is
# either one bare run of non-space characters (commas included) or a quoted string that may
# contain spaces ("correct horse battery"); the same holds for `-u` and mysql `-p` forms.
# Deliberate non-goal: an UNQUOTED value with spaces (PASSWORD=correct horse) is not a single value
# in shell/env semantics, only the first word is the value, so only that word is redacted.
# Deliberate non-goal: "mysql -p secret" (with a space) is NOT a password: mysql then prompts
# and treats "secret" as the database name, so redacting it would only hide a diagnostic.
redact() {
  perl -pe '
    s{(://)\S*@}{$1}g;
    s{(?i)(authorization["\x27]?\s*[=:]\s*).*}{$1REDACTED}g;
    s{(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}}{Bearer REDACTED}g;
    s{(?i)\bbasic\s+(?:(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,}|[A-Za-z0-9._~+/=-]{20,})}{Basic REDACTED}g;
    s{(?i)(--?(?:password|passwd|passphrase|pass|pwd|token|secret|api-?key|access-?key)(?:\s+|=))(?!--[A-Za-z])(?:"[^"]*"|\x27[^\x27]*\x27|\S+)}{$1REDACTED}g;
    s{(?i)(\s(?:-u|--user|--proxy-user)(?:\s+|=))(?:"[^"]*"|\x27[^\x27]*\x27|[^\s:]+:\S+)}{$1REDACTED}g;
    s{(?i)(?:-H|--header)(?:\s+|=)([\"\x27])(?=[^\"\x27]*(?:auth|token|key|secret|cookie|passw))[^\"\x27]*\1}{-H REDACTED}g;
    s{(?i)(\bsshpass\b[^\n]*?\s-p\s*)(?:\"[^\"]*\"|\x27[^\x27]*\x27|\S+)}{$1REDACTED}g;
    s{(?i)(\bmysql\w*\b[^\n]*?\s)-p(?:"[^"]*"|\x27[^\x27]*\x27|\S+)}{$1-pREDACTED}g;
    s{(?i)((?:(?:password|passwd|passphrase|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)(?:[_-][A-Za-z0-9_-]*)?|pass|pwd|auth|cookie|session(?:[_-]?(?:id|token|key))?|[A-Za-z0-9]+[_-]key)["\x27]?\s*[=:]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s"\x27]+)}{$1REDACTED}g'
}
