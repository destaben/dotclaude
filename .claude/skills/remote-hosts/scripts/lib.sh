# shellcheck shell=sh
# Shared helpers, sourced by the other scripts (POSIX sh).

# valid_alias <alias>: succeed only for a plain token that is an exact Host
# entry in ~/.ssh/config. Blocks option injection such as "-oProxyCommand=...".
valid_alias() {
  case "$1" in ''|-*|*[!A-Za-z0-9._-]*) return 1 ;; esac
  awk -v a="$1" '$1=="Host"{for(i=2;i<=NF;i++) if($i==a) f=1} END{exit !f}' "$HOME/.ssh/config" 2>/dev/null
}

# redact: strip credentials from text on stdin (URL userinfo, password/token-like pairs).
redact() {
  perl -pe 's{(://)[^/\s\@:]+(:[^/\s\@]*)?\@}{$1}g;
            s{(?i)\b(pass(?:word|wd)?|token|secret|api[_-]?key|authorization|credentials)(["\x27]?\s*[=:]\s*["\x27]?)[^\s,"\x27]+}{$1$2REDACTED}g'
}
