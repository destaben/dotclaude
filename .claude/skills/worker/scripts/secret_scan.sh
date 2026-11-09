#!/usr/bin/env bash
# secret_scan.sh: looks for credential-shaped text that must never reach a public repository.
#   secret_scan.sh --text FILE           scan one text file (a commit message, a PR title or body)
#   secret_scan.sh --repo DIR BASE REF   scan every blob that the range BASE..REF adds, and every commit
#                                        commit (headers and message) in that range, and every entry name of
#                                        every tree in that range, read raw from the object database
# Exit: 0 clean; 1 found (the kinds are printed on stdout, never the matched text); 2 could not scan.
# Callers treat anything but 0 as "do not publish": the scan fails closed.
# Raw reads (cat-file, not diff) mean .gitattributes cannot hide content: `* -diff` and textconv do not apply.
set -euo pipefail

# Kind label, then the extended regular expression. Every pattern is passed behind -e, so a pattern that
# starts with dashes (a PEM header) is still a pattern.
KINDS=(
  "GitHub token"
  "GitHub fine-grained token"
  "Anthropic key"
  "OpenAI project key"
  "OpenAI-style key"
  "AWS access key id"
  "Google API key"
  "Slack token"
  "npm token"
  "PyPI token"
  "Stripe live key"
  "Slack webhook URL"
  "Google OAuth access token"
  "JWT"
  "login token field"
  "private key"
)
PATTERNS=(
  'gh[pousr]_[A-Za-z0-9]{20,}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'sk-ant-[A-Za-z0-9_-]{10,}'
  'sk-(proj|svcacct)-[A-Za-z0-9_-]{20,}'
  'sk-[A-Za-z0-9]{32,}'
  'AKIA[0-9A-Z]{16}'
  'AIza[0-9A-Za-z_-]{35}'
  'xox[abprs]-[A-Za-z0-9-]{10,}'
  'npm_[A-Za-z0-9]{36}'
  'pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}'
  '[rs]k_live_[A-Za-z0-9]{20,}'
  'hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]{16,}'
  'ya29\.[A-Za-z0-9_-]{20,}'
  'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
  '"(accessToken|refreshToken)"[[:space:]]*:'
  '-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----'
)

TMP=""
# shellcheck disable=SC2329 # invoked by the EXIT trap
cleanup() { [ -z "$TMP" ] || rm -rf "$TMP"; }
trap cleanup EXIT

# scan_file <file>: prints the kinds found in one file. Returns 0 clean, 1 found, 2 on any grep error.
scan_file() {
  local file=$1 i rc found=""
  for i in "${!PATTERNS[@]}"; do
    # Not grep -q: with pipefail an early exit can hide a match. -a reads binary as text too.
    rc=0
    grep -a -E -e "${PATTERNS[$i]}" -- "$file" >/dev/null || rc=$?
    case $rc in
      0) found="$found${found:+, }${KINDS[$i]}" ;;
      1) ;;
      *) return 2 ;;
    esac
  done
  if [ -n "$found" ]; then
    printf '%s\n' "$found"
    return 1
  fi
  return 0
}

scan_text() {
  local kinds rc=0
  [ -f "$1" ] && [ -r "$1" ] || return 2
  kinds=$(scan_file "$1") || rc=$?
  case $rc in
    0) return 0 ;;
    1) printf '%s\n' "$kinds"; return 1 ;;
    *) return 2 ;;
  esac
}

scan_repo() {
  local dir=$1 base=$2 ref=$3 objects shas types line sha kinds="" rc=0 blob msgs found newline_in_path=0
  [ -d "$dir" ] || return 2
  git -C "$dir" rev-parse --verify --quiet "$base^{commit}" >/dev/null || return 2
  git -C "$dir" rev-parse --verify --quiet "$ref^{commit}" >/dev/null || return 2
  # An explicit template: a bare `mktemp -d` ignores TMPDIR on macOS, and the host points TMPDIR at its own run
  # directory so a scan killed at its time limit (no EXIT trap) leaves nothing behind.
  TMP=$(mktemp -d "${TMPDIR:-/tmp}/secret-scan.XXXXXX") || return 2

  objects=$(git -C "$dir" -c core.attributesFile=/dev/null rev-list --objects "$base..$ref") || return 2
  shas=$(printf '%s\n' "$objects" | awk '{print $1}')
  types=$(printf '%s\n' "$shas" | git -C "$dir" cat-file --batch-check='%(objecttype) %(objectname)') || return 2

  # Path names are text too: a secret can be spelled in a file name. rev-list --objects names each object once,
  # so a file copied or renamed to a new name (same blob) would show no new path. The entry names are therefore
  # read from every tree object the range adds, which lists each name the tree holds.
  printf '%s\n' "$objects" | awk 'NF > 1 { sub(/^[^ ]+ /, ""); print }' > "$TMP/paths" || return 2
  while IFS= read -r line; do
    case $line in
      "tree "*)
        sha=${line#tree }
        git -C "$dir" ls-tree --name-only -z "$sha" > "$TMP/tree-names" || return 2
        # The path scan reads one name per line, so a token split by a newline inside a name would never match.
        # Names end at NUL here, which makes a newline in one detectable: it is a finding of its own.
        if [ "$(tr -cd '\n' < "$TMP/tree-names" | wc -c | tr -d ' ')" != 0 ]; then newline_in_path=1; fi
        tr '\0' '\n' < "$TMP/tree-names" >> "$TMP/paths" || return 2
        ;;
    esac
  done <<< "$types"
  rc=0
  found=$(scan_file "$TMP/paths") || rc=$?
  case $rc in
    0) ;;
    1) kinds="$kinds${kinds:+, }$found (in a path name)" ;;
    *) return 2 ;;
  esac
  if [ "$newline_in_path" = 1 ]; then kinds="$kinds${kinds:+, }a newline in a path name"; fi
  blob="$TMP/blob"
  while IFS= read -r line; do
    case $line in
      "blob "*)
        sha=${line#blob }
        git -C "$dir" cat-file blob "$sha" > "$blob" || return 2
        rc=0
        found=$(scan_file "$blob") || rc=$?
        case $rc in
          0) ;;
          1) kinds="$kinds${kinds:+, }$found" ;;
          *) return 2 ;;
        esac
        ;;
    esac
  done <<< "$types"

  msgs="$TMP/messages"
  # The raw format carries the author and committer lines as well as the message.
  git -C "$dir" log --format=raw "$base..$ref" > "$msgs" || return 2
  rc=0
  found=$(scan_file "$msgs") || rc=$?
  case $rc in
    0) ;;
    1) kinds="$kinds${kinds:+, }$found" ;;
    *) return 2 ;;
  esac

  if [ -n "$kinds" ]; then
    printf '%s\n' "$kinds"
    return 1
  fi
  return 0
}

main() {
  local rc=0
  case ${1:-} in
    --text)
      [ "$#" -eq 2 ] || { echo "usage: secret_scan.sh --text FILE | --repo DIR BASE REF" >&2; exit 2; }
      scan_text "$2" || rc=$?
      ;;
    --repo)
      [ "$#" -eq 4 ] || { echo "usage: secret_scan.sh --text FILE | --repo DIR BASE REF" >&2; exit 2; }
      scan_repo "$2" "$3" "$4" || rc=$?
      ;;
    *)
      echo "usage: secret_scan.sh --text FILE | --repo DIR BASE REF" >&2
      exit 2
      ;;
  esac
  exit "$rc"
}

main "$@"
