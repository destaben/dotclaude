# 0011 — Automatic, per-PR review on Haiku 5.5 / low effort narrows 0007

- Date: 2026-10-17
- Status: accepted

## Context
`0007-pro-plan-cost-sustainability.md` decided `claude-pr-review.yml` should
trigger only on an `@claude review` comment (plus manual dispatch), because
an automatic every-push trigger would compete with local interactive use for
the same shared Pro-plan quota. The user has since asked for the opposite:
every PR, in every public repo tagged with the `github-config` topic, gets
an automatic Claude Code review with no comment required.

## What changed since 0007
The review now runs the `claude-haiku-5-5` model at `low` effort (via
`claude_args: '--model claude-haiku-5-5 --effort low'`), and invokes both
`bug-hunter` and `documenter` rather than `bug-hunter` alone. Haiku at low
effort is the cheapest model/effort combination this repo's agents use —
cheaper per run than the Haiku/medium `bug-hunter` already used for the
comment-triggered path. The user explicitly accepted the added quota draw
from firing on every `opened`/`synchronize`/`reopened` event instead of once
per comment, given how cheap each run now is.

## Decision
1. `claude-pr-review.yml`'s `on:` gains a `pull_request` trigger
   (`opened`, `synchronize`, `reopened`) alongside the existing
   `issue_comment` and `workflow_dispatch` triggers. The comment and manual
   paths stay as a fallback — this is additive, not a replacement.
2. The review step passes `claude_args: '--model claude-haiku-5-5 --effort low'`
   so every automatic run uses the cheapest model/effort combination
   available, bounding the per-PR cost this record exists to control.
3. The prompt now runs `documenter` after `bug-hunter`, posting both sets of
   findings in one PR comment.
4. `0007` is **not** superseded wholesale: its guidance to watch `/status`
   for headroom and to fall back to `ANTHROPIC_API_KEY` if usage outgrows
   the Pro plan still applies. This record only narrows point 1 of 0007's
   decision — the trigger — given the cost mitigation in point 2 above.
5. `destaben/github-config`'s `apply.sh` propagates the `CLAUDE_CODE_OAUTH_TOKEN`
   secret to every public repo it manages (tagged `github-config`), so the
   same auth works once this workflow is copied into another repo. It does
   not copy the workflow or agent files themselves — see the workflow's own
   header comment for that manual step.

## Verdict
Haiku-5.5-at-low-effort is cheap enough, and valuable enough as an always-on
safety net, that automatic per-PR review is worth the added quota draw. If
`/status` ever shows this crowding out interactive work, the documented
escape hatch is still `ANTHROPIC_API_KEY` (0007, point 3), not reverting to
comment-only.
