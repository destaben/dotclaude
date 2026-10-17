---
description: Turn a change request into a step-by-step plan for approval, via the planner agent.
argument-hint: <description of the change you want>
---

Invoke the `planner` agent with this change request: $ARGUMENTS

The planner is read-only — it writes a plan to `docs/plans/`, it does not touch
any other file. Once it returns, show the plan summary and wait for explicit
approval before any implementation work starts. If $ARGUMENTS is empty, ask what
change to plan for instead of guessing.
