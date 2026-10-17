---
name: token-budget
description: Consumption warnings based on a budgets config — flags when a task, a subagent fan-out, or context growth crosses a threshold. Warnings are messages, not blockers.
---

## Thresholds
Read `task_token_warning`, `task_token_critical`, `subagent_spawn_warning`,
and `context_tokens_warning` from a budgets file, checked in this order:
1. The current project's own `config/budgets.json` or `.claude/budgets.json`,
   if it has one — a project-specific override always wins.
2. Otherwise, your personal default at
   `~/.claude/dotclaude-scripts/config/budgets.json` (installed from your
   dotclaude config).
3. Otherwise, fall back to reasonable defaults (e.g. 150k/400k task tokens,
   5 subagent spawns, 120k context tokens) and say you're using built-in
   defaults rather than a configured file.
These are starting points — adjust them in whichever file you're reading
from as actual usage patterns become clear; don't hardcode numbers here that
would drift out of sync with it.

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
