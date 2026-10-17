---
name: testing-mindset
description: Testing rules that apply to every change in every project — how to reproduce bugs, what to test, when to mock, and what every PR must state. Referenced by CLAUDE.md, implementer, bug-hunter, and commit-and-pr.
---

## Rules
1. **Reproduce before you fix.** A bug fix starts with a failing test that
   demonstrates the bug, not a patch you believe fixes it.
2. **Test behavior and contracts, not implementation.** Assert on inputs and
   outputs / observable state, not on internal call sequences that are free to
   change.
3. **Scoped first, full before release.** Run the tests for the files you
   touched while working. Run the full suite, using whatever test command
   the current project actually uses, before `/release` commits anything.
4. **Never weaken a test to make it pass.** If a test is actually wrong,
   change it and explain why in the commit message — don't loosen an assertion
   just to get green.
5. **Mock only at boundaries you don't own:** network calls, wall-clock time,
   external APIs/MCP connectors. Don't mock your own modules' internals.
6. **A flaky test is a bug.** Track it (an issue or a decision record), don't
   silence or delete it.
7. **Every PR states what is tested and what isn't.** Two short bullet lists
   in the PR body — not a blanket "tests pass."
