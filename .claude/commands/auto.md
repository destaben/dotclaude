---
description: Autonomous mode for one task. You approve the plan once, then the pipeline runs unattended to an open PR and survives usage-limit resets.
argument-hint: <task> | --resume
---

Start autonomous mode for this task: $ARGUMENTS

Follow the `auto` skill; it owns the rules, the guardrails and the resume behavior. If
$ARGUMENTS is empty, ask what task to run instead of guessing.

1. If $ARGUMENTS is `--resume`, run the supervisor's `resume` subcommand with the same `--repo` (the task repository's top-level directory, as in step 4) or with `--state FILE`, the path printed when the run stopped (see the skill's "Running it"), and report; skip the rest.
2. **Plan, approved by you.** Invoke the `planner` agent as `/plan` does, convening `/council` for
   real design choices per `council-policy`. Show the plan and wait for explicit approval. This is
   the only point where autonomous mode asks you anything; it never approves a plan itself.
3. **Branch.** If the current branch is `main`, create a feature branch first.
4. **Hand over.** Save the approved plan to a file outside the repo and start
   `auto_supervisor.py start` as the skill describes, from `scripts/` in the `auto` skill's own directory,
   wherever it is installed, with `--repo` set to the task repository's top-level directory (from
   `git -C <task-repo> rev-parse --show-toplevel`, where the task repo is the one the owner named, never the
   skill's own checkout). Never rely on the current directory. Report its
   final summary.
