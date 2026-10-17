---
name: session-cost-report
description: Runs scripts/session_cost.py and formats its output as the PR cost footer. Used by commit-and-pr; also the source for the optional statusLine.
---

## How to produce the footer
1. Run `python3 scripts/session_cost.py` from the repo root. It locates the
   current session's transcript automatically; pass `--transcript <path>` if
   it picks the wrong one.
2. Wrap the Markdown table it prints between `<!-- session-cost:start -->` and
   `<!-- session-cost:end -->`.
3. Add one line stating the update time (UTC) above the table.
4. If the PR body already has a footer block, replace the content between the
   markers in place — never append a second footer.

## What the figure means
It's an **estimate at API list prices**, computed from local transcript token
counts via `config/pricing.json`. A Claude Pro/Max plan is a flat subscription,
not billed per token, so this number shows relative cost across models used in
the session — not what was actually charged. Say this in the footer text
itself, not just here, so it travels with the PR.

## If pricing.json still has TODO placeholders
The script prints `TODO (pricing not set)` per affected model instead of
guessing a number. Don't invent a price to fill the gap — leave the TODO
visible until the real figure is filled in from the official pricing page.
