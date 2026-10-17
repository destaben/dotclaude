---
description: Turn a change request into a step-by-step plan for approval, via the planner agent.
argument-hint: <description of the change you want>
---

Invoke the `planner` agent with this change request: $ARGUMENTS

The planner is read-only — it writes the plan to the project's plans folder if
it has one, or presents it directly otherwise; either way it does not touch
any other file. Once it returns, show the plan summary and wait for explicit
approval before any implementation work starts. If $ARGUMENTS is empty, ask what
change to plan for instead of guessing.
