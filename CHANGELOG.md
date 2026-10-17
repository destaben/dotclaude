# Changelog

All notable changes to this repo are recorded here. Entries explain why a
change was made, not just what changed — the diff already shows what.

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
