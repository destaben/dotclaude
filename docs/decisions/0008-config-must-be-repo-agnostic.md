# 0008 — This repo ships installable config, not a project; shipped files must be repo-agnostic

- Date: 2026-10-17
- Status: accepted, enforced — this is the repo's foundational rule

## Context
Early work on this repo (the initial bootstrap and the first GitHub-review
addition) treated `dotclaude` as if it were a normal software project: agent
bodies wrote plans to `docs/plans/`, the documenter assumed a
`docs/decisions/` folder and a `<!-- pipeline:start -->` README marker, the
release command hard-coded `scripts/validate_repo.py`, `session-cost-report`
ran `python3 scripts/session_cost.py` relative to a cwd that was implicitly
"this repo," and `token-budget` read `config/budgets.json` the same way.
None of that is true of an arbitrary project this config gets installed
into. The user caught this directly: these files end up in `~/.claude/` (or
a project's own `.claude/`) and get used in *every* project, so any
assumption baked in from dotclaude's own layout silently breaks elsewhere.

## Decision
A hard line, split the repo into two categories:
- **Shipped / installed** (must be project-agnostic): `CLAUDE.md`,
  `.claude/agents/*`, `.claude/commands/*`, `.claude/skills/*`,
  `.claude/settings.json`, the GitHub PR/issue templates (see `0009`), and
  `scripts/session_cost.py` + its config. These either reference only other
  installed config (by its installed path, e.g.
  `~/.claude/dotclaude-scripts/...`), or they check the *current* project for
  a convention before relying on it, with a generic fallback when it's
  missing.
- **Dev-only** (describe/validate dotclaude's own repo, never installed):
  `scripts/validate_repo.py`, `tests/`, `docs/` (pipeline, decisions,
  references, plans), `README.md`, `CHANGELOG.md`, `.github/workflows/*`
  (project-specific CI is inherently not portable — see `0005`'s workflow).

`scripts/validate_repo.py` now has `check_shipped_files_are_repo_agnostic`,
which scans every shipped file for telltale dotclaude-specific substrings
(`"this repo"`, `docs/decisions/`, `docs/plans/`, a bare
`scripts/validate_repo.py` reference, `docs-check.yml`) and fails if any
appear — so this rule is enforced by CI, not just remembered.

`scripts/install.py` is the new mechanism that actually performs the install
(user scope to `~/.claude/`, or project scope to one target repo's own
`.claude/`), symlinking by default so edits in this repo are reflected
immediately, with `--copy`, `--dry-run`, `--force`, and `--uninstall`.

## Consequences
Every future agent/skill/command addition must be written and reviewed
against this rule before it ships — "would this make sense read from
`~/.claude/agents/foo.md` while working on a completely unrelated project?"
is the test. The automated check catches the most common failure mode
(a literal reference to dotclaude's own paths) but not every possible one
(e.g. a skill that assumes a specific test framework by name) — manual
review still matters for those.
