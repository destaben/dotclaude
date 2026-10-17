---
name: mcp-docs-ops
description: Operations, parameters, and result limits for the Claude Docs MCP connector. Use whenever a task needs to create or update a living doc (as opposed to a file in this repo).
---

## When to use a doc vs. a repo file
A decision record, a plan, or anything meant to live in this repo's history
belongs under `docs/` as a tracked file, not a Claude Doc. Reach for the Claude
Docs connector only when the user explicitly wants a shareable, collaboratively
edited document outside the repo.

## Operations actually used here
- **Create**: start with a skeleton (title + section placeholders) before
  filling in content, per the connector's own guidance.
- **Read/update**: read the current doc before editing it; update sections in
  place rather than duplicating them.

## Result limits
Keep each section's content focused — don't paste raw tool output or full file
contents into a doc; summarize and link back to the repo file instead.
