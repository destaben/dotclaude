---
name: playwright-ops
description: Browser automation via the Playwright MCP connector. Disabled by default — load this only when a task actually needs a real browser, and run the browser work in a subagent.
---

## Why this is isolated
Playwright's page snapshots are typically the heaviest tool output among the
MCP connectors in use. Run browser work in a Haiku subagent so snapshots
never land in the main conversation's context — the subagent returns a short
summary instead.

## Defaults
- Prefer **text snapshots** (accessibility tree / DOM text) over screenshots.
  Only take a screenshot when the task specifically needs visual confirmation.
- Close pages/contexts when done instead of leaving them open across turns.
- Scope navigation to the task — don't crawl beyond the page(s) the task
  names.

## Avoid
- Running Playwright in the main agent when a subagent would do.
- Taking a full-page screenshot when a targeted element snapshot answers the
  question.
- Leaving a browser session open after the task completes.
