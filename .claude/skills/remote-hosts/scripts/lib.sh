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

# printer_guard <alias>: if the alias is a printer, require print-state.sh to report it idle before
# any ssh. Returns 3 (and explains) otherwise. The mapping file has lines "<alias> <host[:port]>"
# (Moonraker address). Location, first match wins: $REMOTE_HOSTS_PRINTERS, then
# $REMOTE_HOSTS_VAULT/config/printers.conf, then ${XDG_CONFIG_HOME:-~/.config}/remote-hosts/printers.conf
# (a symlink there to wherever the user keeps the file works). An alias counts as a printer if it is listed, OR if its
# configured HostName (as `ssh -G` reports it, compared literally, no DNS lookup) equals the HostName
# of a listed alias or the host part of a listed Moonraker address. No file: no guard. Everything
# else fails closed: a path that exists but is not a readable regular file, or a listed printer
# without a Moonraker address, is refused. REMOTE_HOSTS_FORCE=1 bypasses it; it is a safety net
# against mistakes and forgetting, not a barrier against a deliberate bypass: SKILL.md says it is
# set only after the user agrees.
printer_guard() {
  if [ -n "${REMOTE_HOSTS_PRINTERS:-}" ]; then cfg=$REMOTE_HOSTS_PRINTERS
  elif [ -n "${REMOTE_HOSTS_VAULT:-}" ]; then cfg=$REMOTE_HOSTS_VAULT/config/printers.conf
  else cfg=${XDG_CONFIG_HOME:-$HOME/.config}/remote-hosts/printers.conf
  fi
  if [ ! -e "$cfg" ]; then
    # Without a list there is no way to know which aliases are printers, so the guard cannot act;
    # say so once instead of staying silent.
    if [ -z "${_PG_NOTED:-}" ]; then echo "note: printer guard inactive (no printers.conf at $cfg)" >&2; _PG_NOTED=1; fi
    return 0
  fi
  if [ ! -f "$cfg" ] || [ ! -r "$cfg" ]; then echo "refused: $cfg exists but is not a readable file, so the printer guard cannot be evaluated" >&2; return 3; fi
  want=$(ssh -n -G -- "$1" 2>/dev/null | awk '$1=="hostname"{print $2; exit}')
  target=""; matched=0
  while read -r a t _ || [ -n "$a" ]; do   # the || keeps an unterminated last line
    case "$a" in ''|'#'*) continue ;; esac
    other=$(ssh -n -G -- "$a" 2>/dev/null | awk '$1=="hostname"{print $2; exit}')
    case "$t" in    # host part of host[:port], [ipv6][:port] or a bare ipv6 address
      \[*\]*) thost=${t#\[}; thost=${thost%%\]*} ;;
      *:*:*) thost=$t ;;
      *:*) thost=${t%:*} ;;
      *) thost=$t ;;
    esac
    if [ "$a" = "$1" ] || { [ -n "$want" ] && { [ "$want" = "$other" ] || { [ -n "$thost" ] && [ "$want" = "$thost" ]; }; }; }; then target=$t; matched=1; break; fi
  done < "$cfg"
  [ "$matched" = 1 ] || return 0
  if [ "${REMOTE_HOSTS_FORCE:-}" = 1 ]; then echo "note: print-state guard bypassed for $1 (REMOTE_HOSTS_FORCE=1)" >&2; return 0; fi
  if [ -z "$target" ]; then echo "refused: $1 is listed as a printer in $cfg without a Moonraker address, so its print state cannot be checked" >&2; return 3; fi
  st=$("$(dirname "$0")/print-state.sh" "$target"); gs=$?
  [ "$gs" -eq 0 ] && return 0
  if [ "$gs" -eq 2 ] || [ -z "$st" ]; then st="not available: print-state.sh rejected the address '$target' from printers.conf (use host[:port] or [ipv6]:port)"; fi
  echo "refused: $1 is a printer and its print state is '$st' (print-state exit $gs). Do not load the host;" >&2
  echo "confirm with the user, then rerun with REMOTE_HOSTS_FORCE=1 if they agree." >&2
  return 3
}

# sanitize_text [max]: strip control characters (keeping tab and newline; carriage return is stripped so
# device text cannot overwrite earlier terminal output) and cap every line at max bytes (default 1000).
# Device output is data, never instructions; this removes terminal escape tricks and giant lines.
sanitize_text() {
  LC_ALL=C tr -d '\000-\010\013-\037\177' | LC_ALL=C cut -c1-"${1:-1000}"
}

# cap_lines <max>: cap every line at max bytes.
cap_lines() {
  LC_ALL=C cut -c1-"$1"
}

# bounded <seconds> <command...>: run a command with a hard wall-clock limit (needs perl; without
# perl the command runs unbounded, which callers must tolerate).
bounded() {
  secs=$1; shift
  if command -v perl >/dev/null 2>&1; then perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; else "$@"; fi
}

# redact: BEST-EFFORT removal of credentials from text on stdin. It is a safety net, not a
# guarantee: output must still be treated as private. Covers URL userinfo (up to the last
# "@" of the token), Authorization and Cookie/Set-Cookie values (whole line), Bearer/Basic tokens, "--password X" style flags,
# "curl -u/--user user:pass" (also the attached form -ubob:pw), whole `-H/--header` values naming a credential, "sshpass -p SECRET", "mysql -pSECRET", and NAME=value / NAME: value for password, passwd,
# passphrase, pass, pwd, token, secret, auth, cookie, session, credentials and any NAME_KEY
# (including prefixed names such as DB_PASSWORD or suffixed ones such as TOKEN_FILE). A value is
# either one bare run of non-space characters (commas included) or a quoted string that may
# contain spaces ("correct horse battery"); the same holds for `-u` and mysql `-p` forms.
# Deliberate non-goal: an UNQUOTED value with spaces (PASSWORD=correct horse) is not a single value
# in shell/env semantics, only the first word is the value, so only that word is redacted.
# A flag value is always redacted, even if it looks like another flag (`--password --Hunter2`): hiding
# a following flag is preferred to leaking.
# Deliberate non-goal: "mysql -p secret" (with a space) is NOT a password: mysql then prompts
# and treats "secret" as the database name, so redacting it would only hide a diagnostic.
redact() {
  perl -pe '
    s{(://)\S*@}{$1}g;
    s{(?i)((?:set-)?cookie["\x27]?\s*[:=]\s*).*}{$1REDACTED}g;
    s{(?i)(authorization["\x27]?\s*[=:]\s*).*}{$1REDACTED}g;
    s{(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}}{Bearer REDACTED}g;
    s{(?i)\bbasic\s+(?:(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,}|(?-i)(?=[A-Za-z0-9+/=]*[a-z][A-Za-z0-9+/=]*[A-Z])[A-Za-z0-9+/=]{12,}|[A-Za-z0-9._~+/=-]{20,})}{Basic REDACTED}g;
    s{(?i)(--?(?:password|passwd|passphrase|pass|pwd|token|secret|api-?key|access-?key)(?:\s+|=))(?:"[^"]*"|\x27[^\x27]*\x27|\S+)}{$1REDACTED}g;
    s{(?i)(\s(?:-u|--user|--proxy-user)(?:\s+|=))(?:"[^"]*"|\x27[^\x27]*\x27|[^\s:]+:\S+)}{$1REDACTED}g;
    s{(\s-u)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s:]+:\S+)}{$1REDACTED}g;
    s{(?i)(?:-H|--header)(?:\s+|=)([\"\x27])(?=[^\"\x27]*(?:auth|token|key|secret|cookie|passw))[^\"\x27]*\1}{-H REDACTED}g;
    s{(?i)(\bsshpass\b[^\n]*?\s-p\s*)(?:\"[^\"]*\"|\x27[^\x27]*\x27|\S+)}{$1REDACTED}g;
    s{(?i)(\bmysql\w*\b[^\n]*?\s)-p(?:"[^"]*"|\x27[^\x27]*\x27|\S+)}{$1-pREDACTED}g;
    s{(?i)([?&](?:key|api_?key|access_?token|token|auth|password|passwd|secret|sig|signature)=)[^&\s"\x27]+}{$1REDACTED}g;
    s{(?i)((?:(?:password|passwd|passphrase|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)(?:[_-][A-Za-z0-9_-]*)?|pass|pwd|auth|cookie|session(?:[_-]?(?:id|token|key))?|(?<![A-Za-z0-9])[A-Za-z0-9]+[_-]key)["\x27]?\s*[=:]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s"\x27]+)}{$1REDACTED}g'
}

# conf_file <name> <override-var-name>: print the path of a vault-side config file. Location, first
# match wins: the file named by the override variable, $REMOTE_HOSTS_VAULT/config/<name>, then
# ${XDG_CONFIG_HOME:-~/.config}/remote-hosts/<name>. The path is printed even if the file is missing.
conf_file() {
  eval "_ov=\${$2:-}"
  if [ -n "$_ov" ]; then printf '%s\n' "$_ov"
  elif [ -n "${REMOTE_HOSTS_VAULT:-}" ]; then printf '%s\n' "$REMOTE_HOSTS_VAULT/config/$1"
  else printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/remote-hosts/$1"
  fi
}

# conf_get <file> <key>: print the value of the first "<key> <value>" line (whitespace separated).
# '#' starts a comment line; a trailing " # comment" after the value is stripped. A line with the key
# and no value gives an empty value (never the key name). Config is parsed, never sourced, so a value
# cannot run code.
conf_get() {
  awk -v k="$2" '$1==k { v=$0; sub(/^[^ \t]+/, "", v); sub(/^[ \t]+/, "", v); if (v ~ /^#/) v=""; sub(/[ \t]+#.*$/, "", v); sub(/[ \t]+$/, "", v); print v; exit }' "$1"
}

# conf_has <file> <key>: succeed if some line starts with the key, whether or not it has a value. Lets a
# caller tell "not configured" from "configured but unusable" and fail closed on the latter.
conf_has() {
  awk -v k="$2" '$1==k { found=1; exit } END { exit !found }' "$1"
}

# conf_unknown_key <file> <allowed-key>...: print the first key in the file that is not in the allowed
# list (blank lines and comment lines ignored) and succeed; fail if every key is known. A misspelled
# key would otherwise silently disable the setting it was meant to carry, such as a safety guard.
conf_unknown_key() {
  _cf=$1; shift
  awk -v list=" $* " '$1 !~ /^#/ && NF && index(list, " " $1 " ") == 0 { print $1; found=1; exit } END { exit !found }' "$_cf"
}
