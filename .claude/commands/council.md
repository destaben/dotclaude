---
description: Convene the decision council and return its verdict. Quick (3 calls) by default; "full" adds two advisors.
argument-hint: [full] <the decision to make, with the options if you have them>
---

Convene the council on this decision: $ARGUMENTS

If $ARGUMENTS is empty, ask what decision to put to the council instead of
guessing. Follow the `council-policy` skill for when a decision deserves a
council, which mode to use, and the limits of its authority. If the first
word of $ARGUMENTS is `full`, use full mode and drop that word from the
decision; otherwise use quick mode.

1. **Frame it.** Write a short brief: the decision, the options, the
   constraints, and the facts that matter. Facts only, no recommendation —
   a leading brief biases every advisor.
2. **Advisors, in parallel, in one message.**
   - Quick: `council-contrarian` and `council-outsider`.
   - Full: those two plus `council-first-principles`, `council-visionary`,
     and `council-executor`.
   Give every advisor except the outsider the full brief. Give
   `council-outsider` only the question, the options, and the artifact
   itself (the text or diff being judged) — no conversation history, no
   rationale, no recommendation.
3. **Chair.** Invoke `council-chair` with the brief and every advisor report,
   verbatim, and say which mode ran. Its verdict is the council's decision.
4. **Report.** Show the verdict and a one-line summary per advisor. The
   verdict settles the choice; it does not authorize edits. If this ran
   inside `/plan`, carry it into the plan for the user to approve; if it was
   run on its own, report it and wait. If the chair's Dissent says a fatal
   flaw from the contrarian went unanswered, or its Confidence is low on
   something costly to reverse, hand the decision back to the user instead
   of acting.

If an advisor fails to answer, rerun that one rather than deciding with fewer.
Run at most one council per task unless the user asks for another.
