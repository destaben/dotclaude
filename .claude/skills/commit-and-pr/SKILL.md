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
5. Open the PR through the GitHub MCP connector (see `github-ops`), **starting
   from the body in `.github/pull_request_template.md`** — don't write a PR
   body from scratch. GitHub pre-fills new PRs with that file automatically
   in the web UI, but MCP/API-created PRs do not get it for free, so:
   1. Read `.github/pull_request_template.md`.
   2. Fill in every section (`Summary`, `Why`, `Test plan`, `Severity
      findings`) — delete the `Severity findings` section entirely if this
      PR skipped `/release` (e.g. via `/pr`), since it only applies after a
      bug-hunter pass.
   3. Leave the `<!-- session-cost:start -->` / `<!-- session-cost:end -->`
      markers in place (empty) — step 6 fills them.
   4. Pass the filled template as the PR body when creating the PR.
6. Run `session-cost-report` and write its footer into the PR body between
   `<!-- session-cost:start -->` and `<!-- session-cost:end -->`. If the PR
   already has a footer, update it in place — don't duplicate it.

## If the tree is clean
Say so and stop. There is nothing to commit.

## Branch naming
Prefer a Conventional-Branch-style name: `<type>/<short-slug>`, matching the
commit type (e.g. `fix/session-cost-dedup`).
