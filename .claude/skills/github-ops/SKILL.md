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
- **Open a PR:** title + a body with a Summary and a Test plan section (what
  was tested, what wasn't — see `testing-mindset`). Never leave the body empty.
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
