---
name: github-ops
description: Daily GitHub operations (PRs, issues, reviews) via the GitHub MCP connector, with output-limited recipes to keep tool results out of the main context. Use for any routine GitHub task that isn't the commit-and-pr flow itself.
---

## Default: GitHub MCP
Default to the GitHub MCP connector (not `gh` via Bash) for GitHub work — a
personal preference, not a per-project setting. Its tool schemas cost
context on every turn they're loaded, so only call it for GitHub work —
don't reach for it as a general shell substitute.

## Recipes (keep results short)
- **Open a PR:** this is `commit-and-pr`'s job — see that skill for the PR
  template lookup order. Don't open a PR from this skill directly.
- **Open an issue:** look for a template, in this order, before writing a
  body from scratch:
  1. The *current project's* own `.github/ISSUE_TEMPLATE/` — if it has bug
     report / feature request forms, use those; a project's own convention
     always wins.
  2. Otherwise, your personal defaults at
     `~/.claude/templates/ISSUE_TEMPLATE/bug_report.yml` and
     `feature_request.yml` (installed from your dotclaude config).
  3. Otherwise, a minimal inline shape: what happened/what's missing, repro
     or proposal, and say no template was found.
  Whichever template you used (field ids are `what-happened`, `repro`,
  `area`, `evidence` for a bug report; `problem`, `proposal`, `alternatives`
  for a feature request, in the personal defaults — re-read the template if
  the project's own form differs): when creating the issue through the MCP
  connector, pass a body that answers every field under a heading matching
  its label — the connector doesn't render a YAML issue form for you, so the
  body text has to carry the same structure by hand. Apply the template's
  `labels:` value if it has one.
  - If asked to open an issue that fits neither template, say so and ask
    whether to extend a template rather than inventing a one-off shape.
- **Check PR status:** ask for status/checks only, not the full diff, unless
  you specifically need to review code.
- **List issues/PRs:** request a narrow filter (author, label, state) rather
  than paging through everything.
- **Comments:** post once, update in place on revision — don't accumulate
  duplicate status comments on the same PR.

## If the MCP connector is unavailable
Fall back to `gh` via Bash for that one operation and say you did, so it's
clear why the output didn't go through the connector.

## Never
- Force-push via any GitHub operation.
- Close or merge a PR without being asked.
- Push to `main`.
