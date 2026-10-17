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
