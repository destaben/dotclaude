---
name: auto
description: Autonomous mode for one owner-approved task, run to an open PR without prompts, pausing and resuming across usage-limit resets. Use only when the owner invokes /auto.
---

# Autonomous mode

Runs the stages after plan approval (implement, scoped tests, `/release`) without prompting,
and stops at an open PR. Started only by the owner's explicit `/auto`; never active by
default, never carried to the next task. Every `scripts/...` path is relative to this skill's
directory.

## What it is not
- **Not self-approving.** The owner approves the plan once, at the start (`/plan` flow). A
  council or a checklist never approves a plan; the council only settles design choices inside it
  (`council-policy`).
- **Not a service.** The supervisor runs in the foreground in the owner's own terminal, ends at
  a PR or a stop, and is never scheduled, daemonized or run from cron. It calls the unmodified
  `claude -p` on the owner's own subscription, never `--bare`, never an SDK app or a copied
  token. A long run is still one owner-started task; if it drifts toward continuous
  self-directed operation, re-check the subscription terms first.

## Guardrails
None of these is relaxed by the mode or by a resume; each is owned elsewhere, so follow it there:
git rules in `CLAUDE.md`; PRs only through `commit-and-pr`; severity gates in `release-policy`;
tests in `testing-mindset`; escalation (Haiku fails twice, then Sonnet) as in the pipeline.
Autonomous mode adds:
- Nobody can be asked mid-run, so `release-policy`'s "ask the user" for non-severe findings becomes: the stage prompt tells the run to list them in the
  PR description and not apply them (enforced by that instruction, not by the supervisor). Severe findings are fixed or the run stops, as there.
- Scope fence: only what the approved plan needs; anything else goes in the report.
- No merging, no deleting branches or repos, no other repos, no external sends (the owner's own
  `AUTO_NOTIFY_CMD` aside).
- Stop and report, never guess, on repeated failure, a severe finding that cannot be auto-fixed,
  or the budget cap. The `token-budget` warnings stay advisory; the hard cap is
  `AUTO_MAX_BUDGET_USD` (unset by default, so a run is bounded by its three stages, the per-wait and resume caps, and the plan's own usage limits), passed to `claude --max-budget-usd` when set. It caps each stage call, not the whole run, so a resumed stage gets a fresh cap. Hitting the cap stops the
  run; hitting a usage limit pauses it. They are different events.

## Running it
`scripts/auto_supervisor.py start --repo DIR --task TEXT --plan-file FILE` on a feature branch (`--repo`
is required for `start`, and for `resume` without `--state`, so the script can never act on the repository that merely holds the skill) (it refuses
`main`, `master`, a detached HEAD and a dirty tree), then `resume --repo DIR` (or `resume --state FILE`) after a stop. A manual resume gives a fresh budget of
automatic resumes. Stages run in order; each is one `claude -p`
call whose prompt carries the task and approved plan, so any stage can be re-run from the
checkpoint alone. Resume is at stage boundaries only: an interrupted stage restarts and is told
to continue from the workspace. Exit codes: 0 finished, 2 stopped with the checkpoint saved, 3 refused to start or resume.
Permissions are the owner's normal settings; the supervisor
never skips them.

## Usage limits
A limit is a pause, not a failure: it does not count toward the escalation rule.
- **Detect:** a stage whose last three stdout lines or last three stderr lines include a line that starts with the CLI's usage-limit sentence (5-hour or
  weekly window), at any exit code. Prose that only mentions the wording, or a failure that quotes it
  mid-output, is not a limit. Any other failure stops the run, unretried.
  A stage also stops the run unless its output has an `AUTO-STAGE-RESULT: ok` line (the prompt asks
  for one; `blocked <reason>` or no line is a stop), so a stage that exits 0 without succeeding is
  never recorded as complete. The reverse holds too: a stage that exits 0 with `AUTO-STAGE-RESULT: ok` as its last
  reported result is a success even if its output also contains a line that looks like a limit, because a limit line is read only
  when the stage did not report success.
- **Reset time:** parsed from that same line and the hint lines after it only (epoch, "in N hours", or a clock time such as "3pm" only when the message names its zone, UTC or an IANA name; a clock time without one is not trusted and takes the unreadable-reset path). If unreadable, a 5-hour
  limit falls back to 330 minutes; a weekly limit stops, because a guess could be days wrong.
- **Wait:** until reset plus a 120 s margin, only if that is within the maximum wait (default 6 h)
  and automatic resumes so far are under the maximum (default 3). Otherwise stop with the
  checkpoint saved and the `resume` command printed. Defaults are flags: `--max-wait-hours`,
  `--max-resumes`, `--margin-seconds`, `--fallback-wait-minutes`.
- **Checkpoint:** `auto-<id>.json` under the git common directory (`.git/auto/` in a normal clone), so it can
  never be committed. It holds the task, the approved plan, stage progress, branch, HEAD, a fingerprint of
  the working tree contents, pauses and resume count. No credentials. The plan is stored in it,
  so keep secrets out of plans.
- **Re-verify** before every stage and after every wait: same branch, not `main`, same HEAD (no
  unexpected commits), same working tree. Any mismatch stops the run.
- A killed supervisor resumes the same way; the unrecorded partial edits are accepted after branch and HEAD match.
- Unverified assumptions: the exact limit wording (kept as fixtures in the tests) and
  `claude -p --resume` after a limit, which is why resume re-sends the prompt instead.

## Notifications
`AUTO_NOTIFY_CMD` unset (default) means no-op beyond a line on stderr. When set, it is run as
`<cmd> <event> <message>` for `start`, `pause`, `resume`, `give-up`, `done`. Messages carry no
task text. A failing notifier never affects the run.

## Final report
The supervisor prints status, completed stages, pause count and total wait, resumes, and the
resume command if stopped. In the last stage's PR description and the terminal report, add the
decisions taken and by whom (council or plan), tests run, the PR link and the session-cost
footer (`session-cost-report`).
