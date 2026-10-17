# 0001 — Agent/skill frontmatter supports an `effort` field

- Date: 2026-10-17
- Status: confirmed

## Context
The original design called for per-agent reasoning effort (e.g. planner at
medium, implementer at high) and asked whether that's a real frontmatter field
or needs a workaround (e.g. stating it in the description only).

## Decision
Confirmed against the Claude Code docs: `effort` (`low`/`medium`/`high`/
`xhigh`/`max`) is a directly supported frontmatter field on both subagents
(`.claude/agents/*.md`) and skills (`SKILL.md`). No workaround needed — every
agent in this repo sets `effort` directly in its frontmatter.

## Consequences
None — this matched the original plan exactly.
