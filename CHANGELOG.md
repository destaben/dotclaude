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
