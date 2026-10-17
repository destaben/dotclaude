# 0007 — Is this pipeline sustainable on a Claude Pro subscription?

- Date: 2026-10-17
- Status: accepted, review this again if usage patterns change

## Context
The user runs this repo's pipeline under a Claude Pro subscription (not Max,
not pay-per-token API), with heavy use on weekends and light use on
weekdays. They asked for an explicit check on whether the full design —
local pipeline plus the new GitHub Actions PR review — stays within that
plan rather than silently exceeding it.

## What's confirmed about the Pro plan
- Usage is governed by two layers: a rolling **5-hour session window** and
  an **undisclosed weekly cap**. Anthropic has stated it does not publish
  exact numbers and adjusts them without notice — `/status` in Claude Code,
  or Settings → Usage on claude.ai, is the only reliable source for current
  headroom, not this document.
- `claude.ai`, the Claude Code CLI/IDE, and the desktop app **share the same
  usage pool** — there's one quota, not one per surface.
- Third-party (unofficial) estimates put Pro's Sonnet-equivalent usage
  around 40–80 hours/week, but these aren't confirmed by Anthropic and
  shouldn't be treated as a budget to plan against precisely.

## What this repo's design already does right
- Of the five agents, only `planner` uses Sonnet (medium effort, invoked
  once per change, read-only). `implementer`, `bug-hunter`, `documenter`,
  and `token-auditor` all use Haiku — the cheapest, fastest tier — which is
  also the lightest draw on the shared Pro quota per unit of work.
- `bug-hunter`'s full test suite + review pass is the heaviest recurring
  step, but it's Haiku at medium effort, not Sonnet or Opus.
- `token-auditor` runs on demand only, not on every change.

## The real risk: CI competes with local usage for the same quota
`docs/decisions/0005-reuse-bug-hunter-for-ci-review.md` confirmed that
authenticating `claude-pr-review.yml` with `CLAUDE_CODE_OAUTH_TOKEN` bills
against the **same subscription quota** as local interactive use — it is not
separately metered. That's good news for cost (no surprise API bill) and
exactly the risk this review needs to flag: if that workflow fired on every
push, it would eat into the same weekend budget the user wants for
interactive work, right when weekend usage is heaviest.

## Decision
1. Keep `claude-pr-review.yml`'s trigger as comment-mention
   (`@claude review`) plus manual `workflow_dispatch`, **not** automatic on
   every `pull_request` push. This was already built this way in
   `0005`/the workflow file itself; this record is what justifies it.
2. Before ever switching that trigger to automatic, check `/status` across a
   few representative weekends to see actual headroom — don't estimate from
   the unofficial numbers above.
3. If usage does grow past what Pro supports, the documented escape hatch
   (in the workflow's own header comment) is to switch CI's auth from the
   OAuth token to `ANTHROPIC_API_KEY`. That decouples CI's token spend from
   the interactive quota and bills it separately, at the rates now recorded
   in `config/pricing.json`. This keeps local interactive work from ever
   being crowded out by CI, at the cost of a real per-token bill for CI
   runs only.

## Verdict
As configured — Haiku-dominant local pipeline, Sonnet limited to planning,
and CI gated behind a manual trigger sharing (not adding to) the same quota
— this is a conservative design that shouldn't push a typical weekend-heavy
/ weekday-light usage pattern past a Pro plan. The one concrete lever to
pull if that turns out wrong is already documented in step 3 above, not a
redesign.
