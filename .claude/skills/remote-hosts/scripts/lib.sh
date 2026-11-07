# shellcheck shell=sh
# Shared helpers, sourced by the other scripts (POSIX sh).

# ssh_config_files: the main ssh config plus files pulled in by Include directives.
ssh_config_files() {
  c=$HOME/.ssh/config
  [ -r "$c" ] || return 0
  printf '%s\n' "$c"
  awk 'tolower($1)=="include"{for(i=2;i<=NF;i++)print $i}' "$c" | while read -r p; do
    case "$p" in /*) ;; "~"/*) p=$HOME/${p#"~"/} ;; *) p=$HOME/.ssh/$p ;; esac
    # shellcheck disable=SC2086  # the glob in an Include pattern must expand
    for f in $p; do [ -f "$f" ] && printf '%s\n' "$f"; done
  done
}

# valid_alias <alias>: succeed only for a plain token that is an exact Host entry
# (case-insensitive keyword, Include files honoured). Blocks option injection such
# as "-oProxyCommand=...".
valid_alias() {
  case "$1" in ''|-*|*[!A-Za-z0-9._-]*) return 1 ;; esac
  ssh_config_files | while read -r f; do
    awk -v a="$1" 'tolower($1)=="host"{for(i=2;i<=NF;i++) if($i==a){print "y"; exit}}' "$f"
  done | grep -q y
}

# redact: strip credentials from text on stdin: URL userinfo, Authorization/Bearer/Basic
# values, and any NAME=value / NAME: value whose name contains password, token, secret,
# api key or credentials (including underscore-prefixed names such as DB_PASSWORD).
redact() {
  perl -pe 's{(://)[^/\s\@:]+(:[^/\s\@]*)?\@}{$1}g;
            s{(?i)(authorization["\x27]?\s*[=:]\s*).*}{$1REDACTED}g;
            s{(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}}{$1 REDACTED}g;
            s{(?i)((?:password|passwd|passphrase|token|secret|api[_-]?key|credentials)[A-Za-z0-9_]*["\x27]?\s*[=:]\s*["\x27]?)[^\s,"\x27]+}{$1REDACTED}g'
}
