# 0002 — Pipeline is sequential steps, not hooks

- Date: 2026-10-17
- Status: accepted

## Context
Settings.json's `hooks` key is a real, documented feature (confirmed against
the Claude Code settings reference) that intercepts tool-call events. The
plan calls the release gate "blocking" in the sense that the documenter must
finish before commit-and-pr runs, which could be read as requiring a hook.

## Decision
`/release` implements this as an ordered sequence of steps written directly
into `.claude/commands/release.md`: the agent reads the command and executes
step N+1 only after step N is reported done. `.claude/settings.json` contains
no `hooks` key, and `scripts/validate_repo.py` enforces that on every PR.

## Consequences
The gate only holds if the agent follows the command's documented order —
there's no harness-level enforcement. This is an accepted tradeoff: it keeps
the repo hook-free as required, and the ordering is simple enough (4 steps)
that drift is unlikely. If stronger enforcement is ever needed, that would
require revisiting this decision and adding a hook deliberately.
