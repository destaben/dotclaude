# shellcheck shell=sh
# Shared helpers, sourced by the other scripts (POSIX sh).

# ssh_config_files: the main ssh config plus files pulled in by Include directives.
ssh_config_files() {
  c=$HOME/.ssh/config
  [ -r "$c" ] || return 0
  printf '%s\n' "$c"
  awk 'tolower($1)=="include"{for(i=2;i<=NF;i++)print $i}' "$c" | while read -r p; do
    case "$p" in
      /*) pre=""; pat=$p ;;
      "~"/*) pre="$HOME/"; pat=${p#"~"/} ;;
      *) pre="$HOME/.ssh/"; pat=$p ;;
    esac
    # The prefix is quoted (HOME may contain spaces); only the user's glob pattern is expanded.
    # shellcheck disable=SC2086
    for f in "$pre"$pat; do [ -f "$f" ] && printf '%s\n' "$f"; done
  done
}

# valid_alias <alias>: succeed only for a plain token that is an exact Host entry
# (case-insensitive keyword, Include files honoured, trailing comments ignored).
# Blocks option injection such as "-oProxyCommand=...".
valid_alias() {
  case "$1" in ''|-*|*[!A-Za-z0-9._-]*) return 1 ;; esac
  ssh_config_files | while read -r f; do
    awk -v a="$1" 'tolower($1)=="host"{for(i=2;i<=NF;i++){ if($i ~ /^#/) break; if($i==a){print "y"; exit} }}' "$f"
  done | grep -q y
}

# shell_quote <string>: print the string as one single-quoted shell word (safe for any content,
# including apostrophes), for building a remote `sh -c '...'` command.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# redact: BEST-EFFORT removal of credentials from text on stdin. It is a safety net, not a
# guarantee: output must still be treated as private. Covers URL userinfo (up to the last
# "@" of the token), Authorization values, Bearer/Basic tokens, "--password X" style flags,
# "curl -u user:pass", "mysql -pSECRET", and NAME=value / NAME: value for password, passwd,
# passphrase, pass, pwd, token, secret, api/access/private key and credentials (including
# prefixed names such as DB_PASSWORD or suffixed ones such as TOKEN_FILE). Values may be bare,
# or quoted with spaces ("correct horse battery").
# Deliberate non-goal: "mysql -p secret" (with a space) is NOT a password: mysql then prompts
# and treats "secret" as the database name, so redacting it would only hide a diagnostic.
redact() {
  perl -pe '
    my $v = q{(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,"\x27]+)};
    s{(://)\S*@}{$1}g;
    s{(?i)(authorization["\x27]?\s*[=:]\s*).*}{$1REDACTED}g;
    s{(?i)\b(bearer|basic)\s+(?:(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,}|[A-Za-z0-9._~+/=-]{20,})}{$1 REDACTED}g;
    s{(?i)(--?(?:password|passwd|passphrase|pass|pwd|token|secret|api-?key|access-?key)(?:\s+|=))(?!-)(?:"[^"]*"|\x27[^\x27]*\x27|\S+)}{$1REDACTED}g;
    s{(?i)(\s-u\s+)[^\s:]+:\S+}{$1REDACTED}g;
    s{(?i)(\bmysql\w*\b[^\n]*?\s)-p\S+}{$1-pREDACTED}g;
    s{(?i)((?:(?:password|passwd|passphrase|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)(?:[_-][A-Za-z0-9_-]*)?|pass|pwd)["\x27]?\s*[=:]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,"\x27]+)}{$1REDACTED}g'
}
