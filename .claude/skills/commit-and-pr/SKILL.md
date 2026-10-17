---
name: commit-and-pr
description: Stage, commit, push a branch, open a PR, and write the session-cost footer. Use whenever a change needs to land in a PR — called by /release and /pr.
---

## When the tree is dirty
1. Run `git status`. Never stage with a broad `git add -A` or `git add .` if
   anything secret-like is present (`.env`, credentials, keys) — stage files
   explicitly by name instead.
2. Before staging, skim the contents of anything unfamiliar, not just the
   filename — a file named `notes.txt` can still hold a token.
3. Commit with a Conventional Commits message (`feat:`, `fix:`, `docs:`,
   `refactor:`, `test:`, `chore:`) describing *why*, not a diff restatement.
4. Push to a feature branch. **Never push to `main`. Never force-push.**
5. Open the PR through the GitHub MCP connector (see `github-ops`), **never
   starting from a blank body** — don't write a PR body from scratch when a
   template exists. GitHub pre-fills new PRs from a template automatically
   in the web UI, but MCP/API-created PRs don't get that for free, so find
   one yourself, in this order:
   1. The *current project's own* `.github/pull_request_template.md`, if it
      has one — a project's own convention always wins.
   2. Otherwise, your personal default at
      `~/.claude/templates/pull_request_template.md` (installed from your
      dotclaude config — see that repo's `install.py`). Use it as-is in any
      project that has no template of its own.
   3. Otherwise (neither exists — e.g. the installer hasn't been run on this
      machine), use a minimal inline shape: `Summary`, `Why`, `Test plan`
      (tested / not tested, per `testing-mindset`), and say in the PR that
      no template was found.
   Whichever template you used: fill in every section, drop a "Severity
   findings" section entirely if this PR skipped `/release` (e.g. via `/pr`),
   and leave any `<!-- session-cost:start -->` / `<!-- session-cost:end -->`
   markers in place (empty) for step 6 to fill.
6. Run `session-cost-report` and write its footer into the PR body between
   `<!-- session-cost:start -->` and `<!-- session-cost:end -->` (add the
   markers yourself if the template you used didn't have them). If the PR
   already has a footer, update it in place — don't duplicate it.

## If the tree is clean
Say so and stop. There is nothing to commit.

## Branch naming
Prefer a Conventional-Branch-style name: `<type>/<short-slug>`, matching the
commit type (e.g. `fix/session-cost-dedup`).
