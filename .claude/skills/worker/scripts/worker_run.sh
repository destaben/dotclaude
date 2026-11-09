#!/usr/bin/env bash
# worker_run.sh: hands one task to a one-shot Claude worker container on an owner-listed SSH host,
# then publishes the branch it produced. Runs on the owner's machine. Usage, exit codes and the
# remote layout: see ../SKILL.md.
#   worker_run.sh <ssh-alias> <repo> (--issue N | --handoff FILE)
#                 [--max-turns N] [--timeout 90m] [--out DIR] [--config FILE] [--no-publish]
# The container has no GitHub credential. Publishing uses this machine's own git and gh logins.
set -euo pipefail

SKILL_DIR=$(cd "$(dirname "$0")/.." && pwd)
TEMPLATE="$SKILL_DIR/templates/handoff.md"
STATE_DIR=${DOTCLAUDE_WORKER_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude-worker}
GIT_BASE=${WORKER_GIT_URL_BASE:-https://github.com}
MAX_HANDOFF_BYTES=262144
# Seconds a stopped container has to finish its handoff, summary and bundle after TERM, before it is killed.
STOP_GRACE=${WORKER_STOP_GRACE:-60}
ACCEPT_WORKER=0
ORIGINAL_SRC=""
ALIAS_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
REPO_RE='^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9._-]*$'
DIR_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
# Largest files copied back from the host. Anything bigger is not copied.
SUMMARY_MAX=1048576
HANDOFF_OUT_MAX=2097152
BUNDLE_MAX=${WORKER_BUNDLE_MAX:-52428800}

FETCH_TOO_LARGE=""
LOCK_PATH=""
LOCK_HELD=0
TMP_DIR=""
BASE=""
BRANCH=""
RUN_ID=""
ISSUE_TITLE=""
PUBLISH="none"
PUBLISH_MSG=""
PR_URL=""

usage() {
  echo "usage: worker_run.sh <ssh-alias> <repo> (--issue N | --handoff FILE) [--max-turns N] [--timeout 90m] [--out DIR] [--config FILE] [--no-publish]" >&2
  exit 2
}

refuse() { echo "refused: $*" >&2; exit 2; }

# shell_quote <string>: one single-quoted shell word, for the `sh -c` command sent over ssh.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# fm_get <file> <key>: one value from the YAML front matter (the first block only).
fm_get() {
  awk -v key="$2" '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    NR > 1 {
      i = index($0, ":"); if (i == 0) next
      k = substr($0, 1, i - 1); v = substr($0, i + 1)
      gsub(/^[ \t]+|[ \t\r]+$/, "", k); gsub(/^[ \t]+|[ \t\r]+$/, "", v)
      if (k == key) { print v; exit }
    }' "$1"
}

valid_base() { [[ $1 =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$ ]] && [[ $1 != *..* ]]; }

valid_branch() { [[ $1 =~ ^worker/[a-z0-9][a-z0-9-]{0,80}$ ]]; }

# slugify <text>: lower case, runs of other characters become "-", at most 40 characters; "task" if empty.
slugify() {
  local s
  s=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40)
  s=$(printf '%s' "$s" | sed -E 's/-+$//')
  printf '%s\n' "${s:-task}"
}

# timeout_seconds <value>: 90 or 90s, 90m, 2h; prints seconds, fails for anything else or above 24 h.
timeout_seconds() {
  local re='^([1-9][0-9]{0,3})([smh]?)$' n unit
  [[ $1 =~ $re ]] || return 1
  n=${BASH_REMATCH[1]}
  unit=${BASH_REMATCH[2]}
  case $unit in
    h) n=$((n * 3600)) ;;
    m) n=$((n * 60)) ;;
  esac
  [ "$n" -le 86400 ] || return 1
  printf '%s\n' "$n"
}

# config_check <list|argv|str> <key> <value>: reads the JSON config. A list answers yes or no for <value>;
# argv prints each item of a list on its own line (an absent key prints nothing); a string prints its
# value (or <value> when the key is absent). Bad config exits 2 with a message.
config_check() {
  python3 -I -c '
import json, sys
path, mode, key, value = sys.argv[1:5]
try:
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, ValueError) as err:
    sys.exit("config %s is missing or not valid JSON (%s)" % (path, type(err).__name__))
if not isinstance(cfg, dict):
    sys.exit("config must be a JSON object")
item = cfg.get(key)
if mode == "argv" and item is None:
    sys.exit(0)
if mode in ("list", "argv"):
    if not isinstance(item, list) or not all(isinstance(x, str) for x in item):
        sys.exit("config key \"%s\" must be a list of strings" % key)
    if mode == "argv":
        for x in item:
            if "\n" in x:
                sys.exit("config key \"%s\" items must not contain a newline" % key)
            print(x)
    else:
        print("yes" if value in item else "no")
else:
    if item is None:
        print(value)
    elif isinstance(item, str):
        print(item)
    else:
        sys.exit("config key \"%s\" must be a string" % key)
' "$CONFIG" "$1" "$2" "$3"
}

# check_handoff_source: validates a handoff the owner wrote, before anything touches the network.
check_handoff_source() {
  [ -f "$HANDOFF_SRC" ] && [ -r "$HANDOFF_SRC" ] || refuse "--handoff must name a readable file"
  [ "$(wc -c < "$HANDOFF_SRC" | tr -d ' ')" -le "$MAX_HANDOFF_BYTES" ] || refuse "the handoff is larger than 256 KiB"
  [ "$(head -n 1 "$HANDOFF_SRC")" = "---" ] || refuse "the handoff has no front matter"
  [ "$(fm_get "$HANDOFF_SRC" version)" = "1" ] || refuse "the handoff version must be 1"
  [ "$(fm_get "$HANDOFF_SRC" repo)" = "$REPO" ] || refuse "the handoff repo does not match $REPO"
  case $(fm_get "$HANDOFF_SRC" status) in
    new|checkpoint) ;;
    *) refuse "the handoff status must be new or checkpoint to start a run (done and blocked do not run)" ;;
  esac
  BASE=$(fm_get "$HANDOFF_SRC" base)
  valid_base "$BASE" || refuse "the handoff base is not a valid branch name"
  BRANCH=$(fm_get "$HANDOFF_SRC" branch)
  [ -n "$BRANCH" ] || BRANCH="worker/handoff-$RUN_ID"
  valid_branch "$BRANCH" || refuse "the handoff branch must be worker/<name>; main and other names are never used"

  # A worker's own output, passed back as input, would make the worker's words instructions. That needs consent.
  if [ "$(fm_get "$HANDOFF_SRC" origin)" = worker ]; then
    [ "$ACCEPT_WORKER" = 1 ] || refuse "this handoff was written by a worker run (origin: worker), so its Task, Context and Acceptance sections are the worker's own words. Review them, then rerun with --accept-worker-handoff (add --original FILE, the owner's original handoff, to see the differences)"
    echo "worker: WARNING: this handoff was written by a worker run; its instruction sections are the worker's own words" >&2
    show_instruction_diff
  fi
}

# instruction_sections <file>: the Task, Context and Acceptance sections, which are what the worker is told.
instruction_sections() {
  awk '{ sub(/[ \t\r]+$/, "") } /^## / { keep = ($0 == "## Task" || $0 == "## Context" || $0 == "## Acceptance") } keep { print }' "$1"
}

# show_instruction_diff: the differences between the owner's original instruction sections (given with
# --original) and this handoff's. Without --original, the instruction sections themselves are shown.
show_instruction_diff() {
  if [ -n "$ORIGINAL_SRC" ]; then
    [ -f "$ORIGINAL_SRC" ] && [ -r "$ORIGINAL_SRC" ] || refuse "--original must name a readable file"
    echo "worker: differences in the instruction sections (owner's original, then this handoff):" >&2
    diff -u <(instruction_sections "$ORIGINAL_SRC") <(instruction_sections "$HANDOFF_SRC") >&2 || true
  else
    echo "worker: no --original given, so there is no diff; the instruction sections are:" >&2
    instruction_sections "$HANDOFF_SRC" >&2
  fi
}

# check_issue_owner: --issue runs only for issues the authenticated gh user wrote. Anyone else's issue
# text is untrusted input the worker must never be asked to act on.
check_issue_owner() {
  local author me
  author=$(gh issue view "$ISSUE" --repo "$REPO" --json author --jq .author.login) || refuse "could not read issue #$ISSUE in $REPO"
  me=$(gh api user --jq .login) || refuse "could not read the authenticated gh user"
  [ -n "$author" ] && [ "$author" = "$me" ] \
    || refuse "issue #$ISSUE was not written by the authenticated gh user; only owner-authored issues can run with --issue (use --handoff for other work)"
}

# build_issue_handoff <out-file>: fills templates/handoff.md for --issue. The issue title and body are
# quoted (every line prefixed with "> ") into the Untrusted input section only, so they cannot open
# a heading that the worker would read as instructions.
build_issue_handoff() {
  local body quoted="$TMP_DIR/untrusted.md"
  ISSUE_TITLE=$(gh issue view "$ISSUE" --repo "$REPO" --json title --jq .title) || refuse "could not read issue #$ISSUE in $REPO"
  body=$(gh issue view "$ISSUE" --repo "$REPO" --json body --jq .body) || refuse "could not read issue #$ISSUE in $REPO"
  BASE=$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name) || refuse "could not read the default branch of $REPO"
  valid_base "$BASE" || refuse "the default branch name of $REPO is not a valid branch name"
  BRANCH="worker/$(slugify "$ISSUE_TITLE")-$ISSUE"
  valid_branch "$BRANCH" || refuse "could not derive a valid branch name from the issue"

  printf 'Issue #%s, title:\n\n%s\n\nIssue #%s, body:\n\n%s\n' "$ISSUE" "$ISSUE_TITLE" "$ISSUE" "$body" \
    | head -c 30000 | tr -d '\000-\010\013\014\016-\037\177' | sed 's/^/> /' > "$quoted"

  sed -e "s|{{REPO}}|$REPO|g" -e "s|{{BASE}}|$BASE|g" -e "s|{{BRANCH}}|$BRANCH|g" \
      -e "s|{{ISSUE}}|$ISSUE|g" -e "s|{{STATUS}}|new|g" "$TEMPLATE" \
    | QUOTED_FILE="$quoted" awk '
        $0 == "<!-- UNTRUSTED_INPUT -->" {
          while ((getline line < ENVIRON["QUOTED_FILE"]) > 0) print line
          close(ENVIRON["QUOTED_FILE"]); next
        }
        { print }' > "$1"
}

# acquire_lock: the lock is a symbolic link whose target is the holder's pid. Creating it is atomic, and the pid is
# in it from the first moment, so a racing run never sees an empty holder. A stale link (its holder is gone) is
# reclaimed under a second lock, so two racing reclaimers cannot both remove a live lock.
acquire_lock() {
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  LOCK_PATH="$STATE_DIR/run.lock"
  local holder
  while :; do
    if ln -s "$$" "$LOCK_PATH" 2>/dev/null; then
      LOCK_HELD=1
      return 0
    fi
    holder=$(readlink "$LOCK_PATH" 2>/dev/null || true)
    if ! [[ $holder =~ ^[0-9]+$ ]] || kill -0 "$holder" 2>/dev/null; then
      echo "busy: another worker run holds $LOCK_PATH (pid ${holder:-unknown}); wait for it to finish" >&2
      exit 5
    fi
    reclaim_stale_lock || {
      echo "busy: could not reclaim $LOCK_PATH; if no run is active, remove $STATE_DIR/run.lock.reclaim" >&2
      exit 5
    }
  done
}

# reclaim_stale_lock: under the reclaim lock, removes the lock only if its holder is still gone. Returns 1 if the
# reclaim lock cannot be taken within about five seconds.
reclaim_stale_lock() {
  local mutex="$STATE_DIR/run.lock.reclaim" i=0 holder
  until mkdir "$mutex" 2>/dev/null; do
    i=$((i + 1))
    [ "$i" -le 50 ] || return 1
    sleep 0.1
  done
  holder=$(readlink "$LOCK_PATH" 2>/dev/null || true)
  if [[ $holder =~ ^[0-9]+$ ]] && ! kill -0 "$holder" 2>/dev/null; then
    rm -f "$LOCK_PATH"
  fi
  rmdir "$mutex"
  return 0
}

# shellcheck disable=SC2329 # invoked by the EXIT trap
cleanup() {
  [ -z "$TMP_DIR" ] || rm -rf "$TMP_DIR"
  if [ "$LOCK_HELD" = 1 ] && [ "$(readlink "$LOCK_PATH" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$LOCK_PATH"
  fi
}

# remote <command>: runs one line through `sh -c` on the host, the same way remote-hosts does.
remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -- "$ALIAS" "sh -c $(shell_quote "$1")"
}

# run_bounded <seconds> <command...>: a hard wall-clock limit (perl alarm; macOS has no GNU timeout).
run_bounded() {
  local secs=$1
  shift
  perl -e 'alarm shift; exec @ARGV' "$secs" "$@"
}

# run_scan_bounded <seconds> <command...>: the same limit, for the secret scanner, which starts children (git, grep,
# awk) through pipes. The command runs in its own process group and the whole group is killed when the time is up
# (or when the command ends), so a stalled child cannot keep the output pipe open past the limit. Exits 142 on
# timeout, like a process killed by the alarm. stdin is closed: the scanner reads none.
run_scan_bounded() {
  local secs=$1
  shift
  # TMPDIR points at the host run's directory: when the limit SIGKILLs the scanner its EXIT trap cannot run, and
  # the directory its mktemp -d made would otherwise stay in the system temp directory. Here the host's own
  # cleanup removes it with the rest of the run. The single quotes hold a perl program, on purpose.
  # shellcheck disable=SC2016
  env "TMPDIR=${TMP_DIR:-${TMPDIR:-/tmp}}" perl -e '
    my $secs = shift;
    my $pid = fork();
    defined $pid or exit 127;
    if (!$pid) { setpgrp(0, 0); open(STDIN, "<", "/dev/null"); exec @ARGV; exit 127; }
    $SIG{ALRM} = sub { kill "KILL", -$pid; waitpid($pid, 0); exit 142; };
    alarm $secs;
    waitpid($pid, 0);
    my $st = $?;
    kill "KILL", -$pid;
    exit($st & 127 ? 128 + ($st & 127) : $st >> 8);
  ' "$secs" "$@"
}

# summary_value <key>: one value from the summary.env the container wrote.
summary_value() {
  awk -F= -v k="$1" '$1 == k { print substr($0, length(k) + 2); exit }' "$OUT_DIR/summary.env"
}

# section_of <file> <heading>: the body of one "## <heading>" section, control characters removed.
# The text is written by the worker, so it is shown or quoted as data and never acted on here.
section_of() {
  awk -v want="## $2" '
    { sub(/[ \t\r]+$/, "") }
    /^## / { keep = ($0 == want); next }
    keep { print }
  ' "$1" | tr -d '\000-\010\013\014\016-\037\177'
}

# run_on_blocked: runs the owner's on_blocked hook from the config, as an argument vector (never through
# a shell, never from the handoff). It gets the run id and the handoff path. Its failure does not change
# the exit code: the escalation is already printed and saved.
run_on_blocked() {
  if [ "${#HOOK[@]}" -eq 0 ]; then return 0; fi
  echo "worker: running the on_blocked hook from the config" >&2
  local rc=0
  "${HOOK[@]}" "$RUN_ID" "$OUT_DIR/HANDOFF-OUT.md" || rc=$?
  if [ "$rc" != 0 ]; then
    echo "worker: the on_blocked hook exited with $rc; the escalation is still in $OUT_DIR/HANDOFF-OUT.md" >&2
  fi
}

# prepare_out_dir: the output directory must be new or empty. A directory this script creates gets mode
# 0700; a directory the owner passed is used as it is and never chmodded.
prepare_out_dir() {
  if [ -e "$OUT_DIR" ]; then
    [ -d "$OUT_DIR" ] || refuse "--out exists and is not a directory"
    [ -z "$(ls -A "$OUT_DIR")" ] || refuse "--out is not empty; pass a new or empty directory"
  else
    mkdir -p "$OUT_DIR" || refuse "could not create --out $OUT_DIR"
    chmod 700 "$OUT_DIR"
  fi
}

# neutralise: stdin to stdout. Puts a zero-width space after every "@" that starts a mention and after every closing
# keyword (Fixes, Closes, Resolves and their forms) that is followed by an issue reference: #N, owner/repo#N or a
# full issue URL. GitHub then no longer sees a mention or a closing reference. This works on the text itself, not
# on Markdown, so backticks already in the text cannot undo it the way an inserted code span could.
neutralise() {
  awk '
    BEGIN { zw = "\342\200\213" }
    function mentions(s,   out) {
      out = ""
      while (match(s, /@[A-Za-z0-9]/)) {
        out = out substr(s, 1, RSTART) zw
        s = substr(s, RSTART + 1)
      }
      return out s
    }
    function keywords(s,   out, low, token, pre) {
      out = ""
      while (1) {
        low = tolower(s)
        # keyword, optional separator, then #N, owner/repo#N or a full issue URL
        if (!match(low, /(fix|fixes|fixed|close|closes|closed|resolve|resolves|resolved)[ \t:]*(([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)?#[0-9]+|https?:\/\/[^ \t]*\/issues\/[0-9]+)/)) break
        token = substr(s, RSTART, RLENGTH)
        pre = token
        sub(/[ \t:]*(([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)?#[0-9]+|[Hh][Tt][Tt][Pp][Ss]?:\/\/[^ \t]*\/[Ii][Ss][Ss][Uu][Ee][Ss]\/[0-9]+)$/, "", pre)
        out = out substr(s, 1, RSTART - 1) pre zw substr(token, length(pre) + 1)
        s = substr(s, RSTART + RLENGTH)
      }
      return out s
    }
    { print keywords(mentions($0)) }
  '
}

# text_clean <file>: fails closed. Returns 0 only when the scanner read the file and found nothing; otherwise
# it sets SECRET_KINDS (the kinds found, never the values, or "could not be scanned") and returns 1.
text_clean() {
  local rc=0 out
  out=$(run_scan_bounded "${WORKER_SCAN_TIMEOUT:-60}" "$SKILL_DIR/scripts/secret_scan.sh" --text "$1") || rc=$?
  case $rc in
    0) return 0 ;;
    1) SECRET_KINDS=$out ;;
    *) SECRET_KINDS="could not be scanned" ;;
  esac
  return 1
}

# repo_clean <clone> <base-ref> <branch-ref>: the same, for every blob and commit message the branch adds.
repo_clean() {
  local rc=0 out
  out=$(run_scan_bounded "${WORKER_SCAN_TIMEOUT:-300}" "$SKILL_DIR/scripts/secret_scan.sh" --repo "$1" "$2" "$3") || rc=$?
  case $rc in
    0) return 0 ;;
    1) SECRET_KINDS=$out ;;
    *) SECRET_KINDS="could not be scanned" ;;
  esac
  return 1
}

# fetch_run_file <name> <max-bytes>: copies one file of the run directory back as OUT_DIR/<name>. The remote
# side refuses symbolic links (the run directory or the file) and reads at most max+1 bytes; the copy has a
# wall-clock limit. A file that is refused, missing or too large is not copied and the function returns 1.
fetch_run_file() {
  local name=$1 max=$2 dest dir cmd size
  dest="$OUT_DIR/$name"
  dir="\$HOME/$REMOTE_DIR/runs/$RUN_ID"
  cmd="if [ -L \"$dir\" ] || [ -L \"$dir/$name\" ]; then echo 'symbolic link refused' >&2; exit 7; fi; [ -f \"$dir/$name\" ] || exit 8; head -c $((max + 1)) \"$dir/$name\""
  if ! run_bounded 120 ssh -o BatchMode=yes -o ConnectTimeout=10 -- "$ALIAS" "sh -c $(shell_quote "$cmd")" > "$dest.tmp"; then
    rm -f "$dest.tmp"
    return 1
  fi
  size=$(wc -c < "$dest.tmp" | tr -d ' ')
  if [ "$size" -gt "$max" ]; then
    rm -f "$dest.tmp"
    FETCH_TOO_LARGE="$FETCH_TOO_LARGE $name"
    echo "worker: $name is larger than $max bytes; not copied" >&2
    return 1
  fi
  mv "$dest.tmp" "$dest"
}

# write_pr_body: the pull request body. Built from the run's own report, quoted as untrusted text,
# length-capped, and always says where it came from.
write_pr_body() {
  echo "Produced by the background worker, run $RUN_ID, on the owner's host. It is a draft: review it like any other change."
  echo
  echo "The worker had no push or GitHub access. The owner's machine verified the run's bundle and published this branch."
  echo "Mentions and closing keywords in the quoted report were neutralised (a zero-width space breaks them), so they cannot notify anyone or close an issue."
  if [ "$ISSUE_SET" = 1 ]; then echo "Source: issue #$ISSUE in $REPO."; fi
  echo "Run status: $status."
  echo
  echo "Worker report (untrusted text from the run, quoted):"
  echo
  section_of "$OUT_DIR/HANDOFF-OUT.md" Checkpoint | head -c 6000 | sed 's/^/> /'
}

# publish_branch: verifies the run's bundle and publishes exactly refs/heads/$BRANCH from a fresh clone,
# with this machine's own git and gh logins. Hooks are disabled and --no-verify is passed. On success it
# sets PUBLISH=pr and PR_URL; on failure it sets PUBLISH_MSG and returns non-zero.
publish_branch() {
  local bundle="$OUT_DIR/branch.bundle" pub="$TMP_DIR/publish" heads count ref existing title title_file body_file url
  command -v gh >/dev/null 2>&1 || { PUBLISH_MSG="gh is needed to open the pull request"; return 1; }
  git clone --quiet "$GIT_BASE/$REPO.git" "$pub" 2>/dev/null || { PUBLISH_MSG="could not clone $REPO"; return 1; }

  # The bundle may carry exactly one ref: the run's own branch. Anything else is refused.
  heads=$(git -C "$pub" bundle list-heads "$bundle" 2>/dev/null) || { PUBLISH_MSG="the bundle could not be read"; return 1; }
  count=$(printf '%s\n' "$heads" | awk 'NF' | wc -l | tr -d ' ')
  ref=$(printf '%s\n' "$heads" | awk 'NF { print $2; exit }')
  if [ "$count" != 1 ] || [ "$ref" != "refs/heads/$BRANCH" ]; then
    PUBLISH_MSG="the bundle must hold exactly refs/heads/$BRANCH; anything else is refused"
    return 1
  fi
  valid_branch "$BRANCH" || { PUBLISH_MSG="the branch name is not a worker branch"; return 1; }
  git -C "$pub" bundle verify "$bundle" >/dev/null 2>&1 || { PUBLISH_MSG="git bundle verify failed"; return 1; }
  git -C "$pub" fetch --quiet "$bundle" "refs/heads/$BRANCH:refs/heads/$BRANCH" 2>/dev/null \
    || { PUBLISH_MSG="could not fetch the branch from the bundle"; return 1; }

  existing=$(git -C "$pub" ls-remote --heads origin "refs/heads/$BRANCH" 2>/dev/null) \
    || { PUBLISH_MSG="could not query origin for $BRANCH"; return 1; }
  [ -z "$existing" ] || { PUBLISH_MSG="branch $BRANCH already exists on origin; nothing was pushed"; return 1; }

  # The pull request text is built and scanned before anything is pushed, so a refused text leaves nothing public.
  if [ -n "$ISSUE_TITLE" ]; then
    title=$(printf '[worker] %s' "$(printf '%s' "$ISSUE_TITLE" | tr -d '\000-\037\177' | cut -c1-120)" | neutralise) \
      || { PUBLISH_MSG="the pull request title could not be prepared; nothing was pushed"; return 1; }
  else
    title="[worker] $BRANCH"
  fi
  [ -n "$title" ] || { PUBLISH_MSG="the pull request title is empty; nothing was pushed"; return 1; }
  body_file="$TMP_DIR/pr-body.md"
  title_file="$TMP_DIR/pr-title.txt"
  printf '%s\n' "$title" > "$title_file"
  if ! write_pr_body | neutralise > "$body_file" || [ ! -s "$body_file" ]; then
    PUBLISH_MSG="the pull request body could not be prepared; nothing was pushed"
    return 1
  fi
  if ! text_clean "$title_file"; then
    PUBLISH_MSG="the pull request title contains secret-like text ($SECRET_KINDS); nothing was pushed"
    return 1
  fi
  if ! text_clean "$body_file"; then
    PUBLISH_MSG="the pull request body contains secret-like text ($SECRET_KINDS); nothing was pushed"
    return 1
  fi

  # Nothing with a credential shape goes public, in the branch or in its commit messages. Fails closed.
  if ! repo_clean "$pub" "origin/$BASE" "refs/heads/$BRANCH"; then
    PUBLISH_MSG="the branch's changes or commit messages contain secret-like text ($SECRET_KINDS); nothing was pushed"
    return 1
  fi

  # Explicit refspec only; no hooks; no force. The branch name was validated above.
  git -c core.hooksPath=/dev/null -C "$pub" push --quiet --no-verify origin \
    "refs/heads/$BRANCH:refs/heads/$BRANCH" >/dev/null 2>&1 || { PUBLISH_MSG="git push of $BRANCH failed"; return 1; }
  url=$(gh pr create --repo "$REPO" --draft --head "$BRANCH" --base "$BASE" --title "$title" \
    --body-file "$body_file" 2>/dev/null) \
    || { PUBLISH_MSG="the branch is pushed, but gh pr create failed; open the draft pull request by hand"; return 1; }
  url=$(printf '%s\n' "$url" | tail -n 1)
  case $url in
    https://*) PR_URL=$url ;;
    *) PUBLISH_MSG="gh pr create did not print a pull request URL"; return 1 ;;
  esac
  PUBLISH="pr"
}

# publishable <status>: a run is published when it ended with work the owner should see.
publishable() {
  case $1 in
    done|checkpoint|blocked) return 0 ;;
    *) return 1 ;;
  esac
}

main() {
  [ "$#" -ge 2 ] || usage
  ALIAS=$1
  REPO=$2
  shift 2
  ISSUE=""
  HANDOFF_SRC=""
  ISSUE_SET=0
  HANDOFF_SET=0
  NO_PUBLISH=0
  MAX_TURNS=40
  TIMEOUT=90m
  OUT_DIR=""
  OUT_SET=0
  CONFIG="$HOME/.config/dotclaude-worker/config.json"
  while [ "$#" -gt 0 ]; do
    case $1 in
      --issue)      [ "$#" -ge 2 ] || usage; ISSUE=$2; ISSUE_SET=1; shift 2 ;;
      --handoff)    [ "$#" -ge 2 ] || usage; HANDOFF_SRC=$2; HANDOFF_SET=1; shift 2 ;;
      --max-turns)  [ "$#" -ge 2 ] || usage; MAX_TURNS=$2; shift 2 ;;
      --timeout)    [ "$#" -ge 2 ] || usage; TIMEOUT=$2; shift 2 ;;
      --out)        [ "$#" -ge 2 ] || usage; OUT_DIR=$2; OUT_SET=1; shift 2 ;;
      --config)     [ "$#" -ge 2 ] || usage; CONFIG=$2; shift 2 ;;
      --no-publish) NO_PUBLISH=1; shift ;;
      --accept-worker-handoff) ACCEPT_WORKER=1; shift ;;
      --original)   [ "$#" -ge 2 ] || usage; ORIGINAL_SRC=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  if [ "$ISSUE_SET" = 1 ] && [ "$HANDOFF_SET" = 1 ]; then usage; fi
  if [ "$ISSUE_SET" = 0 ] && [ "$HANDOFF_SET" = 0 ]; then usage; fi

  trap cleanup EXIT
  [[ $ALIAS =~ $ALIAS_RE ]] || refuse "the ssh alias must be a plain name (letters, digits, . _ -)"
  [[ $REPO =~ $REPO_RE ]] || refuse "the repo must be owner/name"
  local listed
  listed=$(config_check list hosts "$ALIAS") || exit 2
  [ "$listed" = yes ] || refuse "ssh alias '$ALIAS' is not listed under hosts in $CONFIG"
  listed=$(config_check list repos "$REPO") || exit 2
  [ "$listed" = yes ] || refuse "repo $REPO is not listed under repos in $CONFIG"
  REMOTE_DIR=$(config_check str remote_dir worker) || exit 2
  [[ $REMOTE_DIR =~ $DIR_RE ]] || refuse "remote_dir must be one plain directory name in the remote home"
  # The on_blocked hook comes only from the config file, never from arguments or the handoff.
  HOOK=()
  local hook_lines
  hook_lines=$(config_check argv on_blocked "") || exit 2
  if [ -n "$hook_lines" ]; then
    while IFS= read -r item; do HOOK+=("$item"); done <<< "$hook_lines"
  fi

  if [ "$ISSUE_SET" = 1 ]; then
    local issue_re='^[1-9][0-9]{0,8}$'
    [[ $ISSUE =~ $issue_re ]] || refuse "--issue must be a positive issue number"
  fi
  local turns_re='^[1-9][0-9]{0,2}$'
  [[ $MAX_TURNS =~ $turns_re ]] || refuse "--max-turns must be a number from 1 to 999"
  SECS=$(timeout_seconds "$TIMEOUT") || refuse "--timeout must look like 90, 90s, 90m or 2h, and be at most 24h"
  command -v perl >/dev/null 2>&1 || refuse "perl is needed for the wall-clock limit"
  [[ $STOP_GRACE =~ ^[0-9]{1,3}$ ]] || refuse "WORKER_STOP_GRACE must be a number of seconds from 0 to 999"

  RUN_ID="$(date -u +%Y%m%d-%H%M%S)-$$"
  if [ "$HANDOFF_SET" = 1 ]; then check_handoff_source; fi
  if [ "$ISSUE_SET" = 1 ]; then check_issue_owner; fi

  # The output directory is absolute from here on, and must be new or empty before anything runs.
  if [ "$OUT_SET" = 1 ] && [ -z "$OUT_DIR" ]; then
    refuse "--out needs a directory name"
  fi
  if [ -n "$OUT_DIR" ]; then
    case $OUT_DIR in
      /*) ;;
      *) OUT_DIR="$PWD/$OUT_DIR" ;;
    esac
  else
    OUT_DIR="$STATE_DIR/out/$RUN_ID"
  fi
  prepare_out_dir

  acquire_lock
  TMP_DIR=$(mktemp -d)
  HANDOFF_LOCAL="$TMP_DIR/handoff.md"
  if [ "$ISSUE_SET" = 1 ]; then
    build_issue_handoff "$HANDOFF_LOCAL"
  else
    cp "$HANDOFF_SRC" "$HANDOFF_LOCAL"
  fi

  echo "worker: run $RUN_ID starting on $ALIAS (log on the host: $REMOTE_DIR/runs/$RUN_ID/run.log)" >&2

  local started upload_ok=0
  started=$(date +%s)
  if remote "umask 077 && mkdir -p \"\$HOME/$REMOTE_DIR/inbox\" \"\$HOME/$REMOTE_DIR/runs\" && cat > \"\$HOME/$REMOTE_DIR/inbox/$RUN_ID.md\"" < "$HANDOFF_LOCAL"; then
    upload_ok=1
  fi
  [ "$upload_ok" = 1 ] || { echo "error: could not copy the handoff to $ALIAS (ssh failed)" >&2; exit 4; }

  # Remote command: refuse while another worker container exists, then run the service once.
  # Every value below was validated above, so none of them can carry shell syntax.
  local run_cmd rc
  run_cmd="cd \"\$HOME/$REMOTE_DIR\" && if [ -n \"\$(docker ps -q --filter 'name=^worker-')\" ]; then echo 'another worker container is running on this host' >&2; exit 75; fi && docker compose run --rm -T --name worker-$RUN_ID -e RUN_ID=$RUN_ID -e REPO=$REPO -e BRANCH=$BRANCH -e HANDOFF=/inbox/$RUN_ID.md -e MAX_TURNS=$MAX_TURNS worker"
  if run_bounded "$SECS" ssh -o BatchMode=yes -o ConnectTimeout=10 -- "$ALIAS" "sh -c $(shell_quote "$run_cmd")" >/dev/null; then
    rc=0
  else
    rc=$?
  fi

  if [ "$rc" = 75 ]; then
    echo "busy: a worker container is already running on $ALIAS; nothing was run" >&2
    exit 5
  fi
  # Stop the container with TERM and a grace period, so the entrypoint can finish its handoff, summary and bundle.
  # Remove it with rm -f only if it is still there after that: a run that hit the limit is killed on this side.
  remote "docker stop -t $STOP_GRACE worker-$RUN_ID >/dev/null 2>&1 || true; if [ -n \"\$(docker ps -aq --filter 'name=^worker-$RUN_ID\$')\" ]; then docker rm -f worker-$RUN_ID >/dev/null 2>&1 || true; fi" || true

  fetch_run_file summary.env "$SUMMARY_MAX" || true
  fetch_run_file HANDOFF-OUT.md "$HANDOFF_OUT_MAX" || true
  fetch_run_file branch.bundle "$BUNDLE_MAX" || true

  local status=error turns=0 auth=unknown duration="" reason="no summary came back from the run; check the remote runs directory"
  if [ -s "$OUT_DIR/summary.env" ]; then
    status=$(summary_value STATUS)
    turns=$(summary_value TURNS)
    auth=$(summary_value AUTH)
    duration=$(summary_value DURATION_S)
    reason=$(summary_value REASON)
    case $status in done|checkpoint|blocked|refused|error) ;; *) status=error ;; esac
    case $auth in ok|failed|unknown) ;; *) auth=unknown ;; esac
    case $turns in ''|*[!0-9]*) turns=0 ;; esac
    case $duration in ''|*[!0-9]*) duration="" ;; esac
  fi
  if [ "$rc" = 142 ]; then
    status=timeout
    reason="the wall-clock limit of $TIMEOUT was reached and the run was stopped"
  fi

  # Publishing: only a run that left a bundle and reached done, checkpoint or blocked. The owner can
  # skip it with --no-publish; the bundle then stays in the output directory.
  local publish_failed=0 commits_made=0
  if [ -s "$OUT_DIR/summary.env" ]; then
    commits_made=$(summary_value COMMITS)
    case $commits_made in ''|*[!0-9]*) commits_made=0 ;; esac
  fi
  if [ "$NO_PUBLISH" = 1 ]; then
    PUBLISH=skipped
  elif [[ " $FETCH_TOO_LARGE " == *" branch.bundle "* ]]; then
    # Explicit, not silent: the work exists on the host but is too big to copy, so nothing was published.
    PUBLISH=too-large
    publish_failed=1
    echo "worker: branch.bundle is larger than $BUNDLE_MAX bytes, so it was not copied and nothing was published" >&2
  elif [ ! -s "$OUT_DIR/branch.bundle" ] && [ "$commits_made" -gt 0 ] && publishable "$status"; then
    PUBLISH=missing-bundle
    publish_failed=1
    echo "worker: the run made $commits_made commit(s) but its bundle is missing, so nothing was published" >&2
  elif [ -s "$OUT_DIR/branch.bundle" ] && publishable "$status"; then
    if ! publish_branch; then
      PUBLISH=failed
      publish_failed=1
      echo "worker: publish failed: $PUBLISH_MSG" >&2
    fi
  fi

  local elapsed=$(( $(date +%s) - started )) code escalation=""
  # The container's own duration when the summary has one; wall-clock time (which includes startup) otherwise.
  [ -n "$duration" ] || duration=$elapsed
  local pr_part=""
  if [ -n "$PR_URL" ]; then pr_part=" pr=$PR_URL"; fi
  echo "worker: run $RUN_ID status=$status turns=$turns duration=${duration}s auth=$auth branch=$BRANCH publish=$PUBLISH$pr_part out=$OUT_DIR"
  case $status in
    done|checkpoint) code=0 ;;
    blocked|error) code=1 ;;
    refused) code=2 ;;
    timeout) code=124 ;;
  esac
  if [ "$code" != 0 ]; then echo "worker: $reason" >&2; fi
  # A run stopped at the time limit can still have written its question before it was stopped: it is shown too.
  if { [ "$status" = blocked ] || [ "$status" = timeout ]; } && [ -s "$OUT_DIR/HANDOFF-OUT.md" ]; then
    escalation=$(section_of "$OUT_DIR/HANDOFF-OUT.md" Escalation)
  fi
  if [ -n "$escalation" ] && [ -n "$(printf '%s' "$escalation" | tr -d '[:space:]')" ]; then
    # Blocked with a question for the owner: the question and options are printed, not decided here.
    echo "worker: ESCALATION from run $RUN_ID, the worker needs an owner decision. Its question and options:" >&2
    printf '%s\n' "$escalation" >&2
    echo "worker: full handoff: $OUT_DIR/HANDOFF-OUT.md" >&2
    # The on_blocked hook and exit 3 are for a blocked run. A timed-out run only shows the question: it was
    # stopped, nothing was published, and it keeps exit 124 (even when its bundle was too large to copy).
    if [ "$status" = blocked ]; then
      run_on_blocked
      code=3
    fi
  fi
  if [ "$publish_failed" = 1 ] && [ "$status" != timeout ]; then code=6; fi
  exit "$code"
}

main "$@"
