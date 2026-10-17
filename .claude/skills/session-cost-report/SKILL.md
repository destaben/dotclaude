---
name: session-cost-report
description: Runs session_cost.py and formats its output as a cost footer/status line. Used by commit-and-pr; also the source for the optional statusLine.
---

## Where the script lives
`session_cost.py` and its pricing/budget config are installed (not copied
per-project) at `~/.claude/dotclaude-scripts/scripts/session_cost.py` and
`~/.claude/dotclaude-scripts/config/`. Run it from there regardless of which
project you're currently in — it locates the current session's transcript
from the working directory automatically, so it still reports on *this*
project's session even though the script itself lives elsewhere:

```
python3 ~/.claude/dotclaude-scripts/scripts/session_cost.py
```

(If you're working inside the `dotclaude` config repo itself for
development, its own `./scripts/session_cost.py` is equivalent — same file,
installed copy vs. source copy.) Pass `--transcript <path>` if it picks the
wrong session.

## Keeping pricing current
Prices change between model generations, so `config/pricing.json` carries a
`_fetched_at` date and a `_max_age_days`. Before trusting the script's dollar
figures:
1. Check `_fetched_at` in the pricing file the script used.
2. If it's older than `_max_age_days` (or missing), refresh it yourself:
   look up current per-model API list prices (the `claude-api` skill's rate
   table is the fastest source; the official pricing page is the
   authoritative one), update `input_per_mtok`/`output_per_mtok` for each
   model, and bump `_fetched_at` to today — in the installed copy at
   `~/.claude/dotclaude-scripts/config/pricing.json`.
3. Then run the script. Don't invent a price if you can't verify a current
   one — leave that model's fields as `"TODO"`; the script reports it as
   unknown rather than guessing.

## How to produce a PR cost footer
1. Run the script (see above).
2. Wrap its Markdown table between `<!-- session-cost:start -->` and
   `<!-- session-cost:end -->`.
3. Add one line stating the update time (UTC) above the table.
4. If the PR body already has a footer block, replace the content between
   the markers in place — never append a second footer.

## What the figure means
It's an **estimate at API list prices**, computed from local transcript
token counts. A Claude Pro/Max plan is a flat subscription, not billed per
token, so this number shows relative cost across models used in the
session — not what was actually charged. Say this in the footer text
itself, not just here, so it travels with the PR.
