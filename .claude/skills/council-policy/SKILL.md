---
name: council-policy
description: When to convene the decision council, which mode to use, what its verdict binds, and what it never overrides. Use with /council, and whenever a plan contains a design choice between real alternatives.
---

# Council policy

The council gives a decision structured challenge: advisors with distinct
lenses, then a chair that issues one verdict. Run it with `/council`. It
costs quota that is shared with everything else, so it is for decisions, not
for routine work.

## Modes
- **Quick (default), 3 calls:** contrarian (risk), outsider (cold read), chair.
  Use for most real choices.
- **Full, 6 calls:** adds first principles, visionary (opportunity), and
  executor (next action). Use only when the decision is costly to reverse or
  spans several areas. If a quick verdict comes back low-confidence, ask the
  user whether to spend a full one; don't escalate on your own.

## Convene it for
- A design or technical choice between real alternatives.
- A decision that is costly to reverse or touches several areas.
- Checking that something already decided still holds.

Inside `/plan`, convene it only for choices that are costly to reverse.

## Skip it for
- Anything with one obvious answer, or a choice a convention already makes.
- Wording, formatting, naming, or anything easily undone.
- Questions of fact — look them up instead.
- A choice the user has already made. Don't re-litigate it.

## Budget
One council per task unless the user asks for more. Never run it in a loop,
on a schedule, or in CI. Advisors answer in 150 words and the chair in 200,
which keeps a quick council to a few thousand tokens. If the session is
already near a `token-budget` warning, say so before convening one.

## What the verdict binds
The chair's verdict settles the choice; carry it out without reopening it.
It does not authorize edits: implementation still follows the user's approval
of the plan. Low confidence is still a decision — record what would change it.

## What it never overrides
- The user's approval of a plan, and every confirmation the global rules
  require (pushes, PRs, deletions, anything outward-facing).
- The git rules and the severity gates in `release-policy`.
- An unanswered security or data-loss flaw: it goes back to the user.

## Model and effort
The contrarian, first principles, and the chair run on Sonnet at medium
effort. The rest run on Haiku at low effort. Change these in the agents'
frontmatter, not at call time.
