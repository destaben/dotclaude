# Changelog

All notable changes to this repo are recorded here. Entries explain why a
change was made, not just what changed — the diff already shows what.

## 2026-10-17 — Make the PR review workflow actually post

Every review run failed with `Could not fetch an OIDC token`: without a
`github_token`, `claude-code-action` tries an OIDC exchange for the Claude
GitHub App token, which needs `id-token: write` and the app installed. The
workflow now passes `GITHUB_TOKEN`. Fixing that exposed more: the agent
needs the PR number (HEAD is detached) and an explicit tool allowlist, and
Haiku ended its run before posting unless told to wait. The review of this
very change flagged that letting the agent run `gh pr comment` plus read
`.git/config` was a secret-leak path via a prompt-injected diff, so the agent
now only returns the review as its final message and a workflow step posts
it; the comment trigger
is limited to owner/member/collaborator. The review no longer runs the test
suite (it executes untrusted code); `docs-check` still does, though advisory
(`continue-on-error`). PRs from forks are skipped.

## 2026-10-17 — Price `claude-sonnet-5` and guard `pricing.json`

Added `claude-sonnet-5` ($2 input / $10 output per MTok) to
`config/pricing.json`. Without it, `session_cost.py` reported sessions on that
model as unpriced, because the lookup is an exact match and does not fall back
to `claude-sonnet-5-5`. The rates were checked against the official pricing
page the same day (the introductory price became the standard one), so
`_fetched_at` is accurate. Added tests that reject duplicate keys and
non-numeric or non-positive rates in the shipped file, since
`validate_repo.py` does not inspect its contents.

## 2026-10-17 — Automatic, per-PR review on Haiku 5.5 / low effort

`claude-pr-review.yml` now also triggers on `pull_request`
(`opened`/`synchronize`/`reopened`), not just on an `@claude review` comment,
and runs both `bug-hunter` and `documenter` via
`claude_args: '--model claude-haiku-5-5 --effort low'` to keep the per-run
cost low enough to justify firing on every push. Added
`docs/decisions/0011-propagated-auto-pr-review.md`, which narrows (without
superseding) `0007-pro-plan-cost-sustainability.md`'s comment-only trigger
decision now that the cost per run is this low.

## 2026-10-17 — Initial scaffold

Bootstrapped the repo: global rules (`CLAUDE.md`), the planner / implementer /
bug-hunter / documenter / token-auditor agents, the `/plan`, `/release`, `/pr`
commands, eleven skills covering commit/PR flow, GitHub ops, testing,
release severity, token budgeting, session-cost reporting, four MCP
connectors, and Playwright. Added `scripts/session_cost.py` and
`scripts/validate_repo.py` with unit tests, pricing/budget config
placeholders, and an advisory `docs-check.yml` workflow. No hooks, no remote
resources created — see `docs/decisions/` for the judgment calls made along
the way.

## 2026-10-17 — GitHub PR review, templates, and real pricing

Added `.github/workflows/claude-pr-review.yml`, reusing `bug-hunter` for
GitHub PR review instead of a second agent — confirmed there's no required
agent name on GitHub's side, and that the action's OAuth-token auth bills
against a Claude subscription rather than per-token API, which shaped the
decision to gate the trigger behind a comment mention rather than every
push. Added `.github/pull_request_template.md` and
`.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml`, with
`commit-and-pr` and `github-ops` updated to fill them explicitly. Filled
`config/pricing.json` with real API list prices (previously `TODO`
placeholders). Added a sustainability review
(`docs/decisions/0007-pro-plan-cost-sustainability.md`) of the whole
pipeline's model routing against a Claude Pro subscription's shared usage
quota.

## 2026-10-17 — Make shipped config repo-agnostic; add the installer

Caught and fixed a foundational mistake: several agents/skills/commands
assumed dotclaude's own layout (`docs/plans/`, `docs/decisions/`,
`scripts/validate_repo.py`, a bare `scripts/session_cost.py`,
`config/budgets.json` relative to cwd, literal "this repo" phrasing) would
exist wherever this config gets installed — it won't, in any other project.
Rewrote `CLAUDE.md`, `planner`, `implementer`, `bug-hunter`, `documenter`,
`token-auditor`, `/plan`, `/release`, `commit-and-pr`, `github-ops`,
`token-budget`, `session-cost-report`, `testing-mindset`, `playwright-ops`,
and `mcp-docs-ops` to either reference the *installed* path or check the
current project's own convention with a generic fallback. Rewrote the two
GitHub issue form templates, which had been dotclaude-specific (an agent-name
dropdown, a dotclaude-rules checklist) despite being installed as the user's
personal default for every project.

Added `scripts/install.py` (symlink-by-default, `--copy`/`--dry-run`/
`--force`/`--uninstall`, user or project scope) as the actual mechanism that
performs the install this repo has always implied but never provided. Added
`config/pricing.json._fetched_at`/`_max_age_days` plus a staleness warning in
`session_cost.py`'s output, so pricing is treated as a time-limited cache
with a documented refresh procedure instead of a value that goes silently
stale. Added `check_shipped_files_are_repo_agnostic` to
`scripts/validate_repo.py` so this class of mistake fails CI going forward.
See `docs/decisions/0008-config-must-be-repo-agnostic.md` and
`docs/decisions/0009-templates-are-personal-not-github-native.md`.

## 2026-10-17 — Pushed to GitHub, installed, and made settings.json merge automatic

Pushed the initial commits to the (previously empty) `origin` remote and ran
the installer for real against this machine's actual `~/.claude/`. That run
surfaced exactly the risk `install.py` was designed to guard against: an
existing `~/.claude/settings.json` with unrelated `hooks` (a different tool
entirely) and a `model` set moments earlier via `/model` — both of which a
naive overwrite would have destroyed. Handling that one instance by hand and
documenting "merge manually next time" wasn't good enough — it's a
guarantee that would quietly lapse the next time this file needed to change.

Replaced the one-time manual merge with `merge_settings_json()`: every
`install.py` run (user scope) now unions `permissions.allow`/`deny`, adds
`statusLine`/`model` only if entirely absent, and never touches any other
key — on every run, not just the first, and reports `unchanged` when
there's nothing to do. `--uninstall` now explicitly leaves `settings.json`
alone rather than attempting to remove it. See
`docs/decisions/0010-settings-json-is-merged-not-linked.md`.
