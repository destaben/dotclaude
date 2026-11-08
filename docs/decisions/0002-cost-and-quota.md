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

## Only finished reviews are posted (2026-11-08, issue #10)
On PR #9 a green run posted an interim message ("I'm waiting for the
bug-hunter and documenter agents...") as the review, so anything waiting for
"no findings" read it as an empty review. Decisions:
- **Validate, then post.** The agent's final message must start with
  `## Review of PR #<n>` and end with a `Result: ... findings (...)` line whose
  counts add up. The check lives in `.github/scripts/check_review.py` and is
  unit-tested; the prompt alone was already ignored once.
- **Completeness is a heuristic.** The check also requires a markdown heading
  naming each of `bug-hunter` and `documenter`, which catches a message
  written before the documenter reported; a sentence that only mentions an
  agent does not count. It cannot prove both ran; the prompt asks for one
  section per agent and the review stays advisory. Format slips on the first
  or `Result:` line (bold, backticks, a trailing period) are tolerated so a
  good review is not discarded over cosmetics; the `## Review of PR #<n>`
  marker itself stays exact, as the issue's contract and the prompt specify. Anything stricter-looking than
  that is deliberate: the contract is a fixed first and last line, and a
  drifting agent fails visibly (red job, nothing posted) instead of posting
  something unverifiable.
- **Fail closed on the action's outcome.** The post step now needs the action
  step to have succeeded. Before, a finished review was posted even if the
  action exited non-zero; now it is not, and the retry covers incomplete
  results only, not failed runs. Only exit 3 means "incomplete"; any other
  failure (exit 2, a crash or syntax error, or the script itself missing)
  fails the job at once; a missing or unreadable execution file is an
  incomplete review (exit 3) and is retried. A failed retry run is never
  posted.
- **Depends on** GitHub expanding `env` inside the action's `with:` inputs (an
  Actions expression feature, not the action itself) and the action
  populating the `execution_file` output (observed on this repo's review runs,
  2026-11-08;
  re-check with the action version, see the note at the end of the workflow).
  An uncaught script error (for example an unwritable output path) exits 2, so
  it fails the job instead of retrying. An empty `execution_file` output counts
  as an incomplete review and costs the one retry; that is intended, since
  nothing was produced to post. A setup error in the check step also skips the
  post step, so the real cause stays visible.
- **Known limits, accepted** (so reviews need not raise them again):
  - The check does not judge section bodies or compare the `Result:` counts
    with the findings listed; that would need a second model pass. The review
    stays advisory, and humans read it.
  - `WorkflowContractTests` are text-level guards against accidental edits to
    the gates, not behavioural tests; behaviour needs a real action run.
  - The retry step repeats the first step's `uses:` and its four inputs. The
    prompt and arguments live once in job-level `env`, so only the action
    reference and the two token inputs can drift; GitHub Actions has no
    anchors or reusable step.
  - A branch that predates the script (and a `@claude review` comment run,
    which checks out the default branch) fails loudly with exit 2 instead of
    posting; the `pull_request` run on the PR head is the one that matters.
  - The gate checks the shape of the message, not whether it is true. A
    prompt-injected diff can still produce a well-formed `Result: 0 findings`;
    the review is advisory (see `docs/pipeline.md`).
  - A `workflow_dispatch` run still performs the full review (quota only) and
    has no PR to post to, so its result is not validated or retried; nothing is
    posted and nothing waits on it.
  - The gate assumes `claude-code-action` posts no PR comment of its own with
    this configuration (none were seen on this repo's runs). If it ever mirrors
    an incomplete message into a comment, that text is outside this gate:
    re-check the action's behaviour when updating its version.
- **Not unit-tested:** the workflow gating and the retry-file fallback need a
  real action run; the validation logic they depend on is tested.
- **Retry once, then fail.** One extra run only when the first result is
  incomplete (so the normal cost is unchanged); if it is still incomplete the
  job goes red and nothing is posted.
- **Not done: one edited comment per PR** (`gh pr comment --edit-last`). An
  edit raises no new comment, so a session or automation waiting for new
  comments would miss it, and the per-commit history would be lost. A comment
  per push stays.
- **Not done: raising the effort.** The early turn end is intermittent (seen once
  in about six runs on PR #9, an observation, not a measured rate) and
  unproven to be an effort problem. If an incomplete result still survives the
  retry, raise `--effort` for this workflow only and weigh
  the cost then; the failed runs are visible as red checks with a warning line.

## Follow-ups (not yet done)
- Log escalations and missed defects per role.
