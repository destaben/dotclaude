#!/usr/bin/env python3
"""auto_supervisor.py: runs the stages of an approved plan with the unmodified `claude -p`, pausing
across usage-limit resets. Owner-launched and foreground: it ends at an open PR, a stop, or the
resume limit, and it never daemonizes or schedules itself.

    auto_supervisor.py start --task TEXT --plan-file FILE [limits]
    auto_supervisor.py resume [--state FILE] [limits]

Exit codes: 0 finished, 2 stopped with the checkpoint saved (resume with `resume`), 3 refused to start.
Environment: AUTO_CLAUDE_BIN (default `claude`), AUTO_NOTIFY_CMD (unset = notifications are a no-op),
AUTO_MAX_BUDGET_USD (optional hard cap passed to claude as --max-budget-usd).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

VERSION = 1
STAGES = ["implement", "scoped-tests", "release"]
PROTECTED = {"main", "master"}
DEFAULTS = {"max_wait_hours": 6.0, "max_resumes": 3, "margin_seconds": 120, "fallback_wait_minutes": 330}

STAGE_PROMPTS = {
    "implement": "Implement the approved plan with the implementer agent. Make only the changes the plan needs.",
    "scoped-tests": "Run the scoped tests for this change and fix failures. Never weaken a test to make it pass.",
    "release": "Run /release on the current change. Stop at the open PR.",
}
PROMPT_RULES = (
    "You are in autonomous mode: do not ask the user anything. Follow the auto skill's guardrails. "
    "If you cannot proceed safely, stop and say why. The workspace may hold partial work from an "
    "interrupted run: inspect git status and continue from it rather than starting over. "
    "Non-severe review findings are never applied and never asked about: list them in the PR "
    "description. Severe findings follow release-policy; if they cannot be auto-fixed, stop and report. "
    "End your final message with exactly one line: `AUTO-STAGE-RESULT: ok` only if this stage's goal is fully met "
    "(for tests, they pass; for release, the PR is open), otherwise `AUTO-STAGE-RESULT: blocked <reason>`."
)
RESULT_RE = re.compile(r"^AUTO-STAGE-RESULT:\s*(ok|blocked)\b\s*(.*)$", re.M)

# The CLI's limit sentence, anchored at the start of the last line: prose that merely mentions
# "usage limit reached" (a commit summary, a quoted test failure) must not pause the run.
# the sentence ends there: end of line or punctuation, so "limit reached handling is ..." is prose
END = r"(?=\s*(?:$|[.|,;:!\u00b7]))"
LIMIT_RE = re.compile((
    r"^\W*(?:claude(?:\s+ai)?\s+)?(?:(?:(?:weekly|session|opus|5-hour)\s+)+(?:usage\s+)?|usage\s+)limit\s+(?:reached|hit)\b{END}"
    r"|^\W*(?:claude(?:\s+ai)?\s+)?limit\s+reached\s*\|\s*\d{9,}"
    r"|^\W*you(?:'ve|\s+have)\s+(?:hit|reached)\s+your\s+.{0,30}limit\b{END}").replace("{END}", END), re.I)
WEEKLY_RE = re.compile(r"week", re.I)
FIVE_RE = re.compile(r"5-hour|5 hour|five-hour|session", re.I)


class Stop(Exception):
    """The run must stop with the checkpoint saved; str() is the reason."""


def git(repo, *args, check=True, raw=False):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout if raw else p.stdout.strip()  # raw keeps NUL-separated names exact


def snapshot(repo):
    """Branch, HEAD and a hash of the working tree state, for re-verification."""
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all") + "\n" + git(repo, "diff", "HEAD", "--binary")
    for name in git(repo, "ls-files", "-z", "--others", "--exclude-standard", raw=True).split("\0"):
        if name:  # content, not just the name; a file that cannot be hashed fails closed
            status += f"\n{name} {git(repo, 'hash-object', '--', name)}"
    return {
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(repo, "rev-parse", "HEAD"),
        "tree": hashlib.sha256(status.encode()).hexdigest(),
    }


def state_dir(repo):
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common / "auto"  # inside .git: never tracked, never committed


def parse_reset(text, now):
    """Return the reset time as epoch seconds, or None when the message does not say."""
    m = re.search(r"limit reached\s*\|\s*(\d{9,11})\b", text, re.I) or re.search(r"reset[s]?[^0-9\n]{0,20}(\d{10})\b", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"reset[s]?\s+in\s+(?:(\d+)\s*h\w*)?\s*(?:(\d+)\s*m\w*)?\s*(?:(\d+)\s*s\w*)?", text, re.I)
    if m and any(m.groups()):
        h, mi, s = (int(g or 0) for g in m.groups())
        return now + h * 3600 + mi * 60 + s
    m = re.search(r"reset[s]?\s+(?:at\s+)?(\d{1,2})(?!\d)(?::(\d{2}))?(?!\s*(?:h|m|d|s)\w*\b)\s*(am|pm)?", text, re.I)
    if m:
        hour, minute, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        base = dt.datetime.fromtimestamp(now)
        cand = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand.timestamp() <= now:
            cand += dt.timedelta(days=1)
        return cand.timestamp()
    return None


def classify(output):
    """None when none of the last three lines is a usage-limit sentence, else the window ('5h' or
    'weekly') and the block (that line and what follows it) the reset time must be read from."""
    lines = [x.strip() for x in output.splitlines() if x.strip()][-3:]
    # the limit message is claude's last word, at most followed by a hint line; a quote buried
    # earlier in the output (a failing test, a log) is an ordinary failure
    for n, line in reversed(list(enumerate(lines))):
        if len(line) <= 300 and LIMIT_RE.search(line):
            block = "\n".join(lines[n:])
            window = "weekly" if WEEKLY_RE.search(block) else "5h" if FIVE_RE.search(block) else "unknown"
            return {"window": window, "block": block}
    return None


def _status(path):
    try:
        return json.loads(Path(path).read_text()).get("status")
    except (OSError, ValueError):
        return None  # a corrupt checkpoint is skipped when picking one


def load(path):
    cp = json.loads(Path(path).read_text())
    if cp.get("version") != VERSION:
        raise Stop(f"unsupported checkpoint version {cp.get('version')}")
    return cp


def save(cp):
    path = Path(cp["state_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, indent=2))
    os.replace(tmp, path)


def notify(event, message):
    print(f"[auto] {event}: {message}", file=sys.stderr, flush=True)
    cmd = os.environ.get("AUTO_NOTIFY_CMD", "").strip()
    if not cmd:
        return  # no-op by default
    try:
        subprocess.run([*shlex.split(cmd), event, message], timeout=60, check=False,
                       stdin=subprocess.DEVNULL, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass  # a broken notifier never changes the run


def reverify(cp):
    snap = snapshot(cp["repo"])
    if snap["branch"] in PROTECTED:
        raise Stop(f"on protected branch {snap['branch']}")
    if snap["branch"] != cp["branch"]:
        raise Stop(f"branch is {snap['branch']}, checkpoint expects {cp['branch']}")
    if snap["head"] != cp["head"]:
        raise Stop("unexpected commits: HEAD differs from the checkpoint")
    if snap["tree"] != cp["tree"]:
        raise Stop("working tree differs from the checkpoint")


def record(cp):
    cp.update(snapshot(cp["repo"]))
    save(cp)


def run_claude(cp, stage):
    prompt = "\n\n".join([
        f"Task: {cp['task']}", f"Approved plan:\n{cp['plan']}", f"Stage: {stage}. {STAGE_PROMPTS[stage]}", PROMPT_RULES])
    cmd = [*shlex.split(os.environ.get("AUTO_CLAUDE_BIN", "claude")), "-p", prompt]
    budget = os.environ.get("AUTO_MAX_BUDGET_USD", "").strip()
    if budget:
        cmd += ["--max-budget-usd", budget]
    try:
        p = subprocess.run(cmd, cwd=cp["repo"], capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL)
    except OSError as e:
        raise Stop(f"cannot run claude ({e})")
    return p.returncode, [p.stdout or "", p.stderr or ""]  # each stream is judged on its own last line


def wait_seconds(cp, info, limits, now):
    reset = parse_reset(info["block"], now)
    if reset is None:
        if info["window"] != "5h":
            raise Stop(f"{info['window']} limit hit and its reset time could not be read; not guessing a wait")
        reset = now + limits["fallback_wait_minutes"] * 60
        cp["reset_source"] = "fallback"
    else:
        cp["reset_source"] = "message"
    wait = max(0.0, reset - now) + limits["margin_seconds"]
    if wait > limits["max_wait_hours"] * 3600:
        raise Stop(f"reset in {wait / 3600:.1f}h exceeds the {limits['max_wait_hours']}h maximum wait")
    cp["reset_at"] = reset
    return wait


def execute(cp, limits):
    while True:
        pending = [s for s in STAGES if s not in cp["completed"]]
        if not pending:
            cp["status"] = "done"
            save(cp)
            return
        stage = pending[0]
        reverify(cp)
        cp.update(stage=stage, status="running")
        save(cp)
        code, streams = run_claude(cp, stage)
        reported = RESULT_RE.findall("\n".join(streams))
        succeeded = code == 0 and bool(reported) and reported[-1][0] == "ok"
        info = None if succeeded else next((i for i in map(classify, streams) if i), None)
        if info:
            if cp["resumes"] >= limits["max_resumes"]:
                record(cp)
                raise Stop(f"usage limit hit again after {cp['resumes']} automatic resumes (maximum)")
            record(cp)  # the partial work of this stage is what resume must find, even if we stop below
            wait = wait_seconds(cp, info, limits, time.time())
            cp.update(status="paused")
            cp["pauses"].append({"stage": stage, "window": info["window"], "wait_seconds": round(wait)})
            save(cp)
            notify("pause", f"usage limit ({info['window']}) during {stage}; resuming in about {wait / 60:.0f} min")
            time.sleep(wait)
            reverify(cp)
            cp["resumes"] += 1
            save(cp)
            notify("resume", f"resuming {stage} (resume {cp['resumes']} of {limits['max_resumes']})")
            continue
        if code != 0:
            record(cp)
            raise Stop(f"stage {stage} failed with exit code {code}; a failure is reported, not retried here")
        if not succeeded:
            record(cp)
            why = reported[-1][1] if reported else "no AUTO-STAGE-RESULT line"
            raise Stop(f"stage {stage} did not report success ({why or 'blocked'})")
        cp["completed"].append(stage)
        record(cp)


def finish(cp, reason=None):
    total = sum(p["wait_seconds"] for p in cp["pauses"])
    lines = [f"status: {cp['status']}", f"branch: {cp['branch']}", f"completed stages: {', '.join(cp['completed']) or 'none'}",
             f"usage-limit pauses: {len(cp['pauses'])} (total wait {total // 60} min)", f"automatic resumes: {cp['resumes']}"]
    if reason:
        lines.append(f"stopped: {reason}")
        lines.append(f"resume with: auto_supervisor.py resume --state {cp['state_file']}")
    print("\n".join(lines))


def run(cp, limits):
    try:
        execute(cp, limits)
    except (Stop, OSError, KeyError, ValueError) as e:
        cp["status"] = "stopped"
        cp["stop_reason"] = str(e)
        save(cp)
        # the stop reason can hold the model's own words; the notification carries only the stage
        notify("give-up", f"stopped at stage {cp.get('stage')}. Checkpoint saved: {cp['state_file']}")
        finish(cp, str(e))
        return 2
    notify("done", f"all stages completed on {cp['branch']}")
    finish(cp)
    return 0


def limits_from(args):
    return {k: getattr(args, k) if getattr(args, k) is not None else v for k, v in DEFAULTS.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "resume"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", help="the task repository (required for start; for resume only without --state)")
        sp.add_argument("--max-wait-hours", dest="max_wait_hours", type=float)
        sp.add_argument("--max-resumes", dest="max_resumes", type=int)
        sp.add_argument("--margin-seconds", dest="margin_seconds", type=float)
        sp.add_argument("--fallback-wait-minutes", dest="fallback_wait_minutes", type=float)
        if name == "start":
            sp.add_argument("--task", required=True)
            sp.add_argument("--plan-file", required=True)
        else:
            sp.add_argument("--state")
    args = ap.parse_args(argv)
    limits = limits_from(args)
    try:
        if not args.repo and (args.cmd == "start" or not args.state):
            raise Stop("--repo is required: pass the task repository explicitly, never the current directory")
        repo = Path(git(args.repo, "rev-parse", "--show-toplevel")) if args.repo else None
        if args.cmd == "start":
            snap = snapshot(repo)
            if snap["branch"] in PROTECTED or snap["branch"] == "HEAD":
                raise Stop(f"refusing to start on '{snap['branch']}': create a feature branch first")
            if git(repo, "status", "--porcelain", "--untracked-files=all"):
                raise Stop("the working tree has uncommitted changes: commit or stash them first")
            plan = Path(args.plan_file).read_text()
            if not plan.strip():
                raise Stop("the plan file is empty: autonomous mode runs only an approved plan")
            sid = hashlib.sha256(f"{snap['branch']}{time.time()}".encode()).hexdigest()[:8]
            cp = {"version": VERSION, "repo": str(repo), "task": args.task, "plan": plan, "completed": [],
                  "resumes": 0, "pauses": [], "status": "new", "stage": None,
                  "state_file": str(state_dir(repo) / f"auto-{sid}.json"), **snap}
            save(cp)
            notify("start", f"autonomous run started on {cp['branch']}")
        else:
            path = args.state
            if not path:
                files = sorted(state_dir(repo).glob("auto-*.json"), key=lambda f: f.stat().st_mtime)
                open_runs = [f for f in files if _status(f) not in ("done", None)]
                files = open_runs or files  # a finished run must not shadow an unfinished one
                if not files:
                    raise Stop("no checkpoint found")
                path = files[-1]
            cp = load(path)
            cp["resumes"] = 0  # the owner chose to resume: a fresh budget of automatic resumes
            if cp["status"] == "done":
                raise Stop("that run is already done")
            if cp["status"] == "running":  # killed mid-stage: partial edits were never recorded
                snap = snapshot(cp["repo"])
                if (snap["branch"], snap["head"]) != (cp["branch"], cp["head"]):
                    raise Stop("branch or HEAD differs from the checkpoint")
                cp["tree"] = snap["tree"]
            notify("resume", f"manual resume of {cp['branch']} at stage {cp['stage']}")
    except (Stop, OSError, KeyError, ValueError) as e:  # a missing file or corrupt checkpoint is a refusal, not a traceback
        print(f"refused: {e}", file=sys.stderr)
        return 3
    return run(cp, limits)


if __name__ == "__main__":
    sys.exit(main())
