---
name: token-budget
description: Consumption warnings based on config/budgets.json — flags when a task, a subagent fan-out, or context growth crosses a threshold. Warnings are messages, not blockers.
---

## Thresholds
Read from `config/budgets.json`: `task_token_warning`, `task_token_critical`,
`subagent_spawn_warning`, `context_tokens_warning`. These are starting points —
adjust them in that file as actual usage patterns become clear; don't hardcode
numbers here that would drift out of sync with it.

## What to do when a threshold is crossed
- **Task tokens:** say so in one line (e.g. "this task has used more tokens
  than the warning threshold — consider `/clear` once it's done") and keep
  going. Don't abort work over a warning.
- **Subagent spawns:** if you're about to spawn more subagents than the
  warning count for one task, say why the fan-out is justified before doing
  it, or reconsider whether a single pass would do.
- **Context size:** suggest `/clear` between unrelated tasks; don't suggest it
  mid-task.

## What this skill cannot do
An agent can't measure its own token usage precisely mid-session. These
warnings come from transcript-derived estimates (see `session-cost-report`),
not a live counter — treat them as directional, not exact.
