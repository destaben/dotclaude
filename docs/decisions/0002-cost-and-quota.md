# 0002 — Cost, quota, and automatic PR review

- Date: 2026-10-25 (consolidates the former 0007 and 0011)
- Status: accepted; review again if usage patterns change

## Context
The pipeline runs on a Claude Pro subscription, heavy on weekends and light on
weekdays. Usage has a rolling 5-hour window and an undisclosed weekly cap;
`/status` is the only reliable source for headroom. Claude.ai, the CLI/IDE,
and the desktop app share one pool, and CI authenticated with
`CLAUDE_CODE_OAUTH_TOKEN` draws on that same pool. Third-party estimates of
Pro capacity are unofficial and not a budget.

## Decisions
1. **Tier models by role.** Planner on Sonnet/medium; implementer
   Haiku/high, escalating to Sonnet after two failures on the same task;
   bug-hunter Haiku/medium; documenter and token-auditor Haiku/low.
2. **Automatic review on every same-repo, non-draft PR**, on
   `claude-haiku-5-5` at low effort, running bug-hunter then documenter in one
   comment. A newer run on the same PR cancels the one in progress, and a
   draft is reviewed once it is marked ready. Comment
   (`@claude review`) and manual triggers stay as fallbacks. This narrows the
   earlier comment-only rule, which protected local weekend work; you accepted
   the added draw because each run is the cheapest combination available.
3. **The council is quota-aware.** Quick by default, one per task, never in a
   loop or CI (see `council-policy`).
4. **Secret propagation.** A separate tool (`destaben/github-config`'s
   `apply.sh`) copies `CLAUDE_CODE_OAUTH_TOKEN` to every public repo tagged
   `github-config`. It copies only the secret: the workflow and agent files
   must still be installed per repo.
5. **No paid fallback.** CI never moves to a pay-per-token API key. When the
   subscription quota runs out, review runs fail and post nothing, and that is
   accepted; the levers are the cheap model, one run per PR, and skipping
   drafts, not more spend.

## Validation (2026-10-25)
The council kept decisions 1 and 2, with changes:
- **CI (done):** the `concurrency` group and draft skipping above, because
  without them every push ran and commented. `claude-haiku-5-5`, `--effort`,
  and the action's inputs were checked against the action and the CLI
  reference.
- **Models:** the council flagged `bug-hunter` as the weak point, since Haiku
  reviews Haiku-written code, and proposed Sonnet for the local gate. **You
  declined it to protect quota: `bug-hunter` stays on Haiku at medium
  effort.** The risk stays real; the answer to it is to log escalations and
  missed defects per role and revisit with data, not to spend more by default.

## Follow-ups (not yet done)
- Log escalations and missed defects per role.
