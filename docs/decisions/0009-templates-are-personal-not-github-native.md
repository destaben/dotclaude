# 0009 — PR/issue templates are personal defaults, not GitHub-repo-native config

- Date: 2026-10-17
- Status: accepted

## Context
The first version of the PR template and the two issue forms were written
as if they only mattered for GitHub's native auto-fill on *this* repo: the
PR template told readers to link `docs/decisions/`, and the issue forms had
an "Area" dropdown listing dotclaude's own agent names
(`planner`/`implementer`/`bug-hunter`/...) and a constraints checklist about
dotclaude's own rules (no hooks, 150-line `CLAUDE.md`). That's backwards —
the user wants these as *their* personal template for opening PRs/issues in
any project, with GitHub's own native use on this repo as a secondary bonus,
not the design driver.

## Decision
- The templates' content was rewritten to be generic — no dotclaude-specific
  dropdown options, no dotclaude-specific checklist, no hardcoded
  `docs/decisions/` path.
- They still live at `.github/pull_request_template.md` and
  `.github/ISSUE_TEMPLATE/*.yml` (single source, no duplicated copies), and
  GitHub still auto-fills from them natively for PRs/issues against
  dotclaude itself — a side benefit, not the point.
- `scripts/install.py` copies them to `~/.claude/templates/` as the personal
  default.
- `commit-and-pr` and `github-ops` look for a template in this order: the
  *current project's own* `.github/` template (a project's own convention
  always wins) → the personal default at `~/.claude/templates/` → a minimal
  inline shape if neither exists.

## Consequences
Opening a PR or issue in some unrelated project now gets the user's own
consistent shape (Summary/Why/Test plan; What happened/repro/evidence) rather
than either a blank body or content that only made sense for dotclaude's own
issues. `scripts/validate_repo.py`'s repo-agnosticism check (see `0008`) also
scans these two files, so a future edit that reintroduces a dotclaude-specific
assumption here fails CI the same way it would in an agent or skill.
