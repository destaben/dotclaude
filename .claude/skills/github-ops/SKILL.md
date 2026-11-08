---
name: github-ops
description: Daily GitHub operations (PRs, issues, reviews) via the GitHub MCP connector, with output-limited recipes to keep tool results out of the main context. Use for any routine GitHub task that isn't the commit-and-pr flow itself.
---

## Default: GitHub MCP
Default to the GitHub MCP connector (not `gh` via Bash) for GitHub work — a
personal preference, not a per-project setting. Its tool schemas cost
context on every turn they're loaded, so only call it for GitHub work —
don't reach for it as a general shell substitute.

## Recipes (keep results short)
- **Open a PR:** this is `commit-and-pr`'s job — see that skill for the PR
  template lookup order. Don't open a PR from this skill directly.
- **Open an issue:** look for a template, in this order, before writing a
  body from scratch:
  1. The *current project's* own `.github/ISSUE_TEMPLATE/` — if it has bug
     report / feature request forms, use those; a project's own convention
     always wins.
  2. Otherwise, your personal defaults at
     `~/.claude/templates/ISSUE_TEMPLATE/bug_report.yml` and
     `feature_request.yml` (installed from your dotclaude config).
  3. Otherwise, a minimal inline shape: what happened/what's missing, repro
     or proposal, and say no template was found.
  Whichever template you used (field ids are `what-happened`, `repro`,
  `area`, `evidence` for a bug report; `problem`, `proposal`, `alternatives`
  for a feature request, in the personal defaults — re-read the template if
  the project's own form differs): when creating the issue through the MCP
  connector, pass a body that answers every field under a heading matching
  its label — the connector doesn't render a YAML issue form for you, so the
  body text has to carry the same structure by hand. Apply the template's
  `labels:` value if it has one.
  - If asked to open an issue that fits neither template, say so and ask
    whether to extend a template rather than inventing a one-off shape.
- **Check PR status:** ask for status/checks only, not the full diff, unless
  you specifically need to review code.
- **Wait for a workflow run (e.g. an automated PR review) after a push:** don't
  guess with fixed sleeps or timed wakeups. The MCP connector has no "watch", so
  use `gh` via Bash for this one operation (and say so):
  1. Find the run for the pushed commit:
     `gh run list --branch <branch> --limit 5 --json databaseId,workflowName,status,headSha --jq '.[]|"\(.databaseId) \(.workflowName) \(.status) \(.headSha[0:7])"'`
     — pick the run whose sha is your push (retry once after a few seconds if it
     isn't listed yet).
  2. Watch it **in the background** so you are notified when it finishes, with no
     polling: `gh run watch <id> --exit-status --interval 10` (Bash with
     `run_in_background`). Don't wrap it in `timeout`; macOS doesn't ship it.
  3. When it ends, read only the new feedback, not the whole PR: issue comments and
     review bodies (`gh pr view <n> --json comments,reviews`) and inline comments
     (`gh api --paginate repos/<owner>/<repo>/pulls/<n>/comments`; REST lists are paged at 30, so
     always pass `--paginate` or you will silently miss the newest entries), and answer per the "Comments" rule below.
     Confirm the comment belongs to the run you watched (its time is after your push, and the run
     itself succeeded): a red run may post nothing, so the newest comment can be an older push's review.
     A green run whose newest comment is a status-only message rather than a review
     (no findings list, no stated outcome) is not "zero findings": the review never happened.
     Re-run it (e.g. `gh run rerun <id>`) instead of counting it toward the stop condition,
     at most once per push; if it is still red or status-only, stop and report that to the user.
  4. **Precondition: the user asked, in this session, to iterate on the PR's automated review until
     it has no findings.** Without that request, and in every other context (including `/release`),
     justify nothing: report the non-severe findings to the user and follow `release-policy`. This
     recipe never authorizes auto-fixing or dismissing non-severe findings by itself. With the
     request in place, the goal of this wait is zero findings, severe and non-severe. Repeat push
     → find run → watch → read until a review reports none (or the PR is merged/closed). For every
     finding, do exactly one of:
     - **Fix it**, with a test that fails without the fix when the change is
       testable, and run the full suite before pushing.
     - **Justify it** only when it is not a real defect or is a documented trade-off, and never
       for a severe finding (fix those). That session request is what allows a justification,
       and it is never silent: every justification is listed in your final
       report for the user to overrule, and anything that needs a design choice is asked, not decided:
       write the reason for the user and for future readers (a code comment at the
       spot, plus a "Design notes" or equivalent section in the relevant doc), and state it in a
       PR comment. It explains the decision; it is not a way to steer the reviewer. The aim is that the same finding is never
       raised twice, so the justification must be specific (what, why, what
       control makes it acceptable), not "by design".
     Never merge the PR, and never skip or silently defer a finding, and never weaken a test
     to make a review pass. Bundle the fixes for one review into a single push
     so each push costs one review run.
- **List issues/PRs:** request a narrow filter (author, label, state) rather
  than paging through everything.
- **Comments:** post once, update in place on revision — don't accumulate
  duplicate status comments on the same PR.

## If the MCP connector is unavailable
Fall back to `gh` via Bash for that one operation and say you did, so it's
clear why the output didn't go through the connector.

## Never
- Force-push via any GitHub operation.
- Close or merge a PR without being asked.
- Push to `main`.
