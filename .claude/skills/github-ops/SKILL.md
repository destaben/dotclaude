---
name: github-ops
description: Daily GitHub operations (PRs, issues, reviews) via the GitHub MCP connector, with output-limited recipes to keep tool results out of the main context. Use for any routine GitHub task that isn't the commit-and-pr flow itself.
---

## Default: GitHub MCP
This repo defaults to the GitHub MCP connector (not `gh` via Bash) because the
user asked for it. Its tool schemas cost context on every turn they're loaded,
so only call it for GitHub work — don't reach for it as a general shell
substitute.

## Recipes (keep results short)
- **Open a PR:** this is `commit-and-pr`'s job — see that skill, which starts
  every PR body from `.github/pull_request_template.md`. Don't open a PR
  from this skill directly.
- **Open an issue:** always use one of the forms in `.github/ISSUE_TEMPLATE/`
  — `bug_report.yml` or `feature_request.yml`. There is no blank-issue
  fallback (`config.yml` sets `blank_issues_enabled: false`), so:
  1. Read the matching template file to see its exact field ids
     (`what-happened`, `repro`, `area`, `evidence` for a bug; `problem`,
     `proposal`, `alternatives`, `constraints` for a feature).
  2. When creating the issue through the MCP connector, pass a body that
     answers every required field under a heading matching its `label`
     text — the connector doesn't render the YAML form for you, so the
     body text has to carry the same structure by hand.
  3. Apply the template's `labels:` value (`bug` or `enhancement`).
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
