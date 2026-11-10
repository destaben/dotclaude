# 0002 — Cost, quota, and automatic PR review

- Date: 2026-10-25 (consolidates the former 0007 and 0011); amended
  2026-11-08 (finished-review gate, secret-leak defence)
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
  marker itself stays exact apart from an allowed suffix after the number, as the issue's contract and the prompt specify.
  Anything stricter-looking than that is deliberate: the contract is a fixed
  first and last line, and a drifting agent fails visibly (red job, nothing
  posted) instead of posting something unverifiable.
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
  2026-11-08; re-check with the action version, see the note at the end of
  the workflow).
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
  - A line after the `Result:` line (a rule, a sign-off) makes a finished
    review fail both runs; the fixed last line is the issue's contract.
  - A `workflow_dispatch` run still performs the full review (quota only) and
    has no PR to post to, so its result is not validated or retried; nothing is
    posted and nothing waits on it.
  - The gate assumes `claude-code-action` posts no PR comment of its own with
    this configuration (none were seen on this repo's runs). If it ever mirrors
    an incomplete message into a comment, that text is outside this gate:
    re-check the action's behaviour when updating its version.
- **Secret-leak defence.** The agent can read files and its final message is
  posted verbatim, so a prompt-injected diff could try to make it read a
  secret (for example the process environment under `/proc`) and echo it into
  a public comment. Layers: the agent gets only `Read`, allowed solely inside
  the checked-out workspace (`github.workspace`), plus `gh pr diff` and
  `gh pr view`; it has no `Grep`, `Glob` (their path scoping is not
  guaranteed to follow `Read` rules) or `git show` (`--output=<path>` can write
  files), and `/proc`, `/etc` and `/run` are also denied. `--allowedTools`
  only adds approvals, and the checkout's `.claude/settings.json` grants
  unscoped `Read`, `Grep`, `Glob`, `Edit`, `Write` and some git commands for
  interactive use. Deleting it in the checkout does not help, because on pull
  request runs the action restores `.claude/` from the base branch, so the
  workflow passes `--setting-sources user` to keep project settings out (the
  prompt therefore tells the agent to Read the agent files and run subagents
  with their instructions, as project agents are not registered), and
  `--disallowedTools` also names `Grep`, `Glob`, `Edit`, `Write`,
  `MultiEdit`, `NotebookEdit` and `Bash(git:*)`, because a deny wins over any allow. A contract test checks that every
  write, search or git grant in the project settings has such a deny. Finally the gate
  refuses to post, with exit 2 and no retry, any review that contains the
  value of `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN` or `GITHUB_TOKEN`, or any
  16-character piece of a token longer than 16 characters (shorter secrets
  are matched whole). `/home` is not denied outright: the runner checks the
  repo out under the runner user's home directory. The gate cannot catch a
  transformed secret (for example base64), so the review stays advisory and
  fork PRs stay skipped on the automatic trigger. Open risks: the
  `Read(//...)` path syntax follows the Claude Code permissions reference but
  was confirmed only by a run that still reviewed the repo, not by a probe
  that tries to read outside it; and it is not verified that
  `claude-code-action` never writes the token inside the workspace.
- **Assumption: headless CI denies tools that are not pre-approved.**
  `.claude/agents/bug-hunter.md` lists `Grep` and `Glob` in its `tools`
  frontmatter, but the workflow's `--allowedTools` omits them on purpose. The
  no-Grep/Glob defence relies on `claude-code-action` running headless, where
  a tool outside `--allowedTools` is denied rather than prompted for. This is
  not verified by a probe; if a run ever shows the agent using `Grep` or
  `Glob`, scope them like `Read` or remove them from the agent file for CI.
- **Gating coverage:** the workflow gates are covered only by text-level
  `WorkflowContractTests` (they parse the `--allowedTools` and
  `--disallowedTools` values of `REVIEW_ARGS` and assert the exact sets, not
  substrings); real behaviour (the retry-file selection, the
  outcome combinations) needs a real action run. The validation logic they
  depend on is unit-tested.
- **An errored final result is retried once**, like an incomplete one, only
  when the action step still exits green; if the action step itself exits
  non-zero (for example on max-turns or quota) the job fails and nothing is
  retried or posted. A result that errors while the step exits green is the
  intermittent early stop this work targets, so one retry is worth its cost.
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

## Review convergence (2026-11-10, issue #11)
- **What changed:** the prompt is structured and asks for a checklist first pass, stable finding ids, a
  ledger, incremental later passes and respect for the author's justifications; `review_context.py` supplies
  the previous ledger, last reviewed commit, incremental diff and notes (the reviewed commit is stored as a
  hidden marker in the posted comment); `check_review.py` checks that a summary line, when present, agrees
  with the `Result:` line, and logs how many findings are tagged `pre-existing (missed earlier)`.
  Cost: the context step makes no model call; the longer ledger and diff add input tokens on later passes
  only, and a first pass reads more files, so expect a somewhat larger run, not a different tier.
- **Not done, owner's decision: model and effort.** The issue proposes `claude-sonnet-5-5` at medium for
  the first pass only. That is a tier change and spends more quota (decision 1 and 5), so it is not adopted
  here. Trying it would be new work: `REVIEW_ARGS` is static today, so a step
  would have to choose the model when the context step finds no previous review. Measure on the PR #9
  replay before keeping it.
- **Not done: running ShellCheck or the tests in the review job.** The agent has no tool to run them
  (that would widen the allowlist), so it reads the repo's CI results from `statusCheckRollup`; repos that want
  ShellCheck should add it as its own CI job.
- **Not verified:** the issue's acceptance numbers (80% of the findings on a PR #9 replay in the first
  pass, at most one `pre-existing` tag later, 80% id overlap across reruns) need real model runs and have
  not been measured. Ids are written by the model from file, rule and symbol, not hashed, so overlap
  depends on it naming them consistently.
- **Accepted limits:** the `Result:` line is the last line of the validated message; after validation the post step
  appends a hidden `<!-- claude-pr-review sha=... -->` marker, so the posted comment ends with the marker. The
  ledger is written by the bot itself, so a `justified` entry is the bot's record, not proof that a trusted author
  agreed: the context step shows it as `unverified-claim: justified` and the prompt honours it only when an author
  note backs it (an injected diff cannot suppress findings through the ledger). An unstamped review (the context step failed)
  is not used as a baseline, so the next pass falls back to the last stamped one. the summary line and the ledger are asked
  for by the prompt but a missing one does not fail the gate, to avoid red jobs over format.

## The `claudio` agent (phone calls for escalated decisions) (2026-11-07)
- `claudio` runs on Sonnet at `effort: medium`, only when a council verdict escalates to the owner or the
  owner asks to be called; it is outside the change pipeline, so it adds no cost to ordinary changes.
- Its cost is bounded by the script, not by the model: one ask places at most `attempts` calls (default 3),
  and the throttle refuses more than `max_per_hour` / `max_per_day` asks and any ask closer than `min_gap_s`
  to the previous one (see the `ceo-call` skill). The speech synthesis is local (Piper), so a call adds no
  paid API usage beyond the agent's own turns.

## The `worker` skill (2026-11-09)
- A worker run spends the owner's own subscription quota, on a host the owner chose. It is started by hand,
  one run at a time, and nothing schedules it, so it adds no cost to ordinary changes.
- A run is bounded by `--max-turns` (default 40) and `--timeout` (default 90 minutes), not by the model.

## Follow-ups (not yet done)
- Log escalations and missed defects per role.
