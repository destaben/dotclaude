# 0004 — Tooling choices

- Date: 2026-10-25 (consolidates the former 0003, 0004, and 0006); item 5 added 2026-11-01
- Status: accepted; the license awaits your final confirmation

1. **GitHub MCP connector by default, not `gh`.** Per your instruction, as
   documented in the `github-ops` skill, which falls back to `gh` via Bash for
   one operation if the connector is unavailable and says so. The connector's
   schemas cost context every turn they are loaded; if that becomes a measured
   problem, switching the default is a change confined to that skill.
2. **codebase-memory-mcp is a complement, installed with `--skip-config`.** Its
   installer would otherwise write its own skill, agents and `PreToolUse` hooks
   into `~/.claude`, competing with this repo as the source of truth. We install
   the binary, register the MCP once, and teach it through one skill
   (`codebase-memory-ops`) that no-ops when the connector is absent. Revisit its
   hooks only if a measured gain justifies the extra injected context.
3. **MIT license**, with copyright held by "dotclaude contributors" because the
   repo is public and personal names stay out of tracked files. Compatible with
   the MIT sources listed in `docs/references.md`.
4. **Plain files, not Terraform**, for the PR template, issue forms, and review
   workflow. GitHub reads them by convention, so there is nothing to provision,
   and Terraform would add a provider, credentials, and state for no gain.
   Revisit if you need branch protection, required checks, or repo settings as
   code, or to roll the same files out across many repos.
5. **agent-browser CLI, not the Playwright MCP connector, for browser work.**
   The `browser-ops` skill drives the CLI through Bash from a subagent, so the
   connector's tool schemas stay out of every turn's context and page output
   stays out of the main conversation. Its compact `@eN` snapshot refs are
   expected to cost fewer tokens than Playwright's page snapshots; that is not
   measured yet. A CLI also needs no connector configured. The version is
   pinned and bumped deliberately. If the measured cost is no better, switching
   back is a change confined to that skill.
6. **`gh run watch` for waiting on a workflow run (2026-11-07).** Item 1 keeps the
   GitHub MCP connector as the default; this is a deliberate exception, not a
   change to it. The connector has no operation that waits for a run to finish,
   and the alternative was fixed sleeps or timed wake-ups that either wait too
   long or poll for nothing. The `github-ops` skill therefore uses `gh run list`
   and `gh run watch` via Bash for this one operation, in the background, and
   says so. Everything else stays on the connector.
