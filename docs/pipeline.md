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
   findings per `.claude/skills/release-policy/SKILL.md`.
3. Severe findings: auto-fixed and re-tested, capped at 2 loops, then escalated
   to the user if still severe. Non-severe findings: listed, user decides.
4. `documenter` agent (Haiku, low effort) updates docs — this must complete
   before the next step.
5. `commit-and-pr` skill: stage, commit, push a branch, open a PR, write the
   session-cost footer.

## Why this isn't hooks
`settings.json` has no `hooks` key. Each step above is a sequential
instruction inside a command or skill — the agent reads and follows the
order, rather than the harness intercepting tool calls. See
`docs/decisions/0002-no-hooks-sequential-pipeline.md` for the tradeoff.

## On demand, outside the pipeline
- `token-auditor` (Haiku, low effort): reports context bloat. Not run
  automatically — invoke it when you want a bloat check.
- `/pr`: skips the test/review/doc steps for a change you've already verified
  yourself.

## GitHub PR review (`.github/workflows/claude-pr-review.yml`)
This workflow is dotclaude's own project-specific CI — it is *not* installed
by `install.py`; to use it in another repo, project-scope install the agents
there too (see the README's Install section) and copy this workflow file in.
It runs the same `bug-hunter` agent against a GitHub pull request, instead of
a local diff — no second agent, see
`docs/decisions/0005-reuse-bug-hunter-for-ci-review.md`. Triggered on every
PR (opened/synchronize/reopened) on Haiku at low effort, by commenting
`@claude review` (owner, members and collaborators only), or manually via
`workflow_dispatch` (see
`docs/decisions/0011-propagated-auto-pr-review.md`, which narrows
`docs/decisions/0007-pro-plan-cost-sustainability.md`). The agent only writes
`review.md`; a workflow step posts it, so the agent has no write path to
GitHub. Inactive until you
add either a `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` repository
secret — see the workflow file's header comment for the tradeoff between the
two.

## PR and issue templates
Unlike the workflow above, these *are* personal and portable — see
`docs/decisions/0009-templates-are-personal-not-github-native.md`. The
source lives at `.github/pull_request_template.md` and
`.github/ISSUE_TEMPLATE/*.yml` (also usable natively by GitHub for PRs/issues
against dotclaude itself), and `install.py` copies them to
`~/.claude/templates/`. `commit-and-pr` and `github-ops` use whichever
project's own `.github/` template exists first, falling back to the personal
copy at `~/.claude/templates/` — never the dotclaude repo's copy directly.
