# 0003 — Default to the GitHub MCP connector, not `gh`

- Date: 2026-10-17
- Status: accepted

## Context
The GitHub MCP connector's tool schemas load into context on every turn
they're available, which costs tokens even on days with no GitHub work. The
`gh` CLI via Bash is usually cheaper for routine operations and was flagged as
an alternative worth considering.

## Decision
Default to the GitHub MCP connector, per explicit instruction, documented in
`.claude/skills/github-ops/SKILL.md`. That skill also documents a fallback to
`gh` via Bash for a single operation if the connector is unavailable, and says
so explicitly when it falls back.

## Consequences
Slightly higher per-turn context cost on days with GitHub work, in exchange
for the connector's structured results. If daily-ops cost becomes a measured
problem, switching the default to `gh` is a small, isolated change confined to
`github-ops/SKILL.md`.
