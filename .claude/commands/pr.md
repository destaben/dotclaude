---
description: Commit the current working tree and open a PR, without running the full release pipeline.
argument-hint: (none — operates on the current working tree)
---

Run `.claude/skills/commit-and-pr/SKILL.md` directly on the current working
tree: stage, commit with a conventional message, push a branch (never `main`),
open the PR, and write or update the session-cost footer.

This skips the test suite, bug-hunter, and documenter steps that `/release`
runs — use it for small changes you've already verified yourself. If the tree
has changes that look like they'd benefit from the full pipeline, say so and
suggest `/release` instead of running this silently.
