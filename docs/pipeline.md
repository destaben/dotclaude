# Pipeline

The diagram in `README.md` (between the `<!-- pipeline:start -->` /
`<!-- pipeline:end -->` markers) is the canonical picture; this page explains
each stage in prose.

## 1. `/plan`
Runs the `planner` agent (Sonnet, medium effort, read-only). It writes a plan
to `docs/plans/` and returns a summary. Nothing changes until you approve it.

## 2. Implementation
The `implementer` agent (Haiku, high effort) makes the change and runs scoped
tests. If scoped tests fail twice on the same root cause, the orchestrating
flow escalates to Sonnet instead of retrying Haiku a third time.

## 3. `/release`
A fixed sequence, defined in `.claude/commands/release.md`:
1. Full test suite.
2. `bug-hunter` agent (Haiku, medium effort) reviews the diff and classifies
   findings per the `release-policy` skill.
3. Severe findings: auto-fixed and re-tested, capped at 2 loops, then escalated
   to the user if still severe. Non-severe findings: listed, user decides (under `/auto`, listed in the PR description and not applied; on a PR the owner has explicitly delegated, cheap evident fixes are applied once, see `release-policy`).
4. `documenter` agent (Haiku, low effort) updates docs — this must complete
   before the next step.
5. `commit-and-pr` skill: stage, commit, push a branch, open a PR, write the
   session-cost footer.

## Why this isn't hooks
`settings.json` has no `hooks` key. Each step above is a sequential
instruction inside a command or skill — the agent reads and follows the
order, rather than the harness intercepting tool calls. See
`docs/decisions/0001-pipeline-and-agents.md` for the tradeoff.

## Decisions: `/council`
When the plan turns on a choice between real alternatives that is costly to
reverse, `/plan` convenes the council first. A quick council (default) runs
the contrarian and outsider advisors in parallel; `/council full` adds first
principles, visionary, and executor. Then `council-chair` issues the verdict.
Quick is 3 model calls, full is 6, so it is kept for real decisions. See
`docs/decisions/0001-pipeline-and-agents.md` and the `council-policy` skill. A
decision the council cannot resolve, in the two cases `council-policy` names, goes
back to the user, who is asked directly with numbered options (and a push notification when away): see
"When the council cannot resolve it" there.

## On demand, outside the pipeline
- `token-auditor` (Haiku, low effort): reports context bloat. Not run
  automatically — invoke it when you want a bloat check.
- `/pr`: skips the test/review/doc steps for a change you've already verified
  yourself.
- `remote-hosts` (skill): administering the user's own LAN devices over ssh,
  read-only by default, plus guarded Home Assistant reads and calls and an
  optional scheduled health check (details in its `SKILL.md`). It is not part of the change pipeline; see
  `docs/decisions/0004-tooling-choices.md`, item 7.
- `/auto` (command) and `auto` (skill): the same stages after you approve the plan once,
  run unattended by a foreground supervisor that pauses across usage-limit resets and
  resumes from a checkpoint kept under `.git/`. It ends at an open PR or a stop and
  never approves a plan itself; the rules live in the skill.
- `worker` (skill): a one-shot, owner-triggered Claude Code run in a container on
  an owner-listed SSH host, outside the change pipeline; see
  `docs/decisions/0004-tooling-choices.md`, item 10. The owner's machine publishes the
  result as a draft pull request, with these outcomes (exit codes are in the skill):
  - published: a `done`, `checkpoint` or `blocked` run (a `blocked` one with its
    question printed, exit 3);
  - not published, the bundle kept in the output directory: `--no-publish`, a run that
    timed out (exit 124), or one the publish checks refuse (exit 6);
  - not published, nothing usable: a run `refused` at the start (exit 2), a handoff or
    host failure before it started (exit 4 or 5), or an `error` (exit 1). A `blocked` run
    without an escalation also exits 1, and is published.

## GitHub PR review (`.github/workflows/claude-pr-review.yml`)
This workflow is dotclaude's own project-specific CI — it is *not* installed
by `install.py`; to use it in another repo, project-scope install the agents
there too (see the README's Install section) and copy this workflow file in,
together with `.github/scripts/check_review.py` (without it no review is posted) and, optionally,
`.github/scripts/review_context.py` (without it every pass is a full first pass with no ledger).
It runs the same `bug-hunter` agent against a GitHub pull request, instead of
a local diff, followed by the `documenter` — no new agent, see
`docs/decisions/0001-pipeline-and-agents.md`. Triggered on every
same-repo PR (opened/synchronize/reopened/ready_for_review; fork PRs are skipped) on Haiku at
low effort, by commenting
`@claude review` (owner, members and collaborators only; this path does also
run on fork PRs when a trusted user asks for it), or manually via
`workflow_dispatch` (see
`docs/decisions/0002-cost-and-quota.md`). Draft PRs are skipped until ready, and
a newer run on the same PR cancels the one in progress. The agent's final
message is the review; a workflow step posts it, so the agent has no
write tools. That step only posts a *finished* review: the message must start
with `## Review of PR #<n>` and end with
`Result: <total> findings (<severe> severe, <non-severe> non-severe)`
(`.github/scripts/check_review.py`, copy it with the workflow). An incomplete
message, such as a "waiting for the agents" status, is retried once; if it is
still incomplete, a one-time "not reviewed" notice is posted instead (the
unfinished text never is) and the job stays green. The workflow writes the PR diff
to `.review-diff.patch` first, because the agents can only `Read` the workspace. A review that
contains the value of one of the job's tokens is never posted either (exit 2,
no retry). The post also requires the action step to have succeeded; if it
failed, the job fails and nothing is posted or retried. The review is advisory: a
prompt-injected diff can still influence what it says. Reviews have memory: the first pass
runs a fixed checklist, every finding has a stable id, and the comment carries a ledger before the `Result:` line (the posted comment ends with the hidden marker)
(open, fixed, justified, withdrawn); a hidden marker records the reviewed commit, and
`.github/scripts/review_context.py` hands the next run that ledger, the diff since then and
the author's justifications (copy it with the workflow, it is best effort). Inactive until you
add a `CLAUDE_CODE_OAUTH_TOKEN` repository secret. There is no API-key
fallback: when the subscription quota runs out, the run fails and posts nothing.

To wait for a run's review after a push, `github-ops` uses `gh run watch` (see
`docs/decisions/0004-tooling-choices.md`, item 6); that wait does not change the
severity routing of `/release`.

## PR and issue templates
Unlike the workflow above, these *are* personal and portable — see
`docs/decisions/0003-shipped-config-is-portable.md`. The
source lives at `.github/pull_request_template.md` and
`.github/ISSUE_TEMPLATE/*.yml` (also usable natively by GitHub for PRs/issues
against dotclaude itself), and `install.py` copies them to
`~/.claude/templates/`. `commit-and-pr` and `github-ops` use whichever
project's own `.github/` template exists first, falling back to the personal
copy at `~/.claude/templates/` — never the dotclaude repo's copy directly.
