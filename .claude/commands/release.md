---
description: Run the release pipeline on the current change — full tests, bug-hunter review, documentation, then commit-and-pr.
argument-hint: (none — operates on the current working tree)
---

Run this sequence in order. Each step must complete before the next starts; this
is a sequence of steps inside this command, not a hook on any tool-call event.

1. **Full test suite.** Run every test, not just the scoped ones from
   implementation. If it fails, stop and report — don't proceed to review.
2. **Bug hunter.** Invoke the `bug-hunter` agent on the diff. Classify every
   finding as severe or non-severe per
   `.claude/skills/release-policy/SKILL.md`.
3. **Severity routing.**
   - Severe: auto-fix, then re-run step 1 and step 2. Cap this loop at 2
     passes. If still severe after 2 passes, stop and ask the user — do not
     keep looping.
   - Non-severe: list the findings and ask the user before changing anything.
   - None: continue.
4. **Documenter.** Invoke the `documenter` agent. It must complete — and
   `scripts/validate_repo.py` must pass — before step 5 starts.
5. **Commit and PR.** Run `.claude/skills/commit-and-pr/SKILL.md`: stage,
   commit with a conventional message, push a branch (never `main`), open the
   PR, and write or update the session-cost footer.

Report what happened at each step, not just the final state — if a step was
skipped (e.g. no findings to route), say so rather than staying silent.
