# 0004 — Tooling choices

- Date: 2026-10-25 (consolidates the former 0003, 0004, and 0006)
- Status: accepted; the license awaits your final confirmation

1. **GitHub MCP connector by default, not `gh`.** Per your instruction, as
   documented in the `github-ops` skill, which falls back to `gh` via Bash for
   one operation if the connector is unavailable and says so. The connector's
   schemas cost context every turn they are loaded; if that becomes a measured
   problem, switching the default is a change confined to that skill.
2. **MIT license**, with copyright held by "dotclaude contributors" because the
   repo is public and personal names stay out of tracked files. Compatible with
   the MIT sources listed in `docs/references.md`.
3. **Plain files, not Terraform**, for the PR template, issue forms, and review
   workflow. GitHub reads them by convention, so there is nothing to provision,
   and Terraform would add a provider, credentials, and state for no gain.
   Revisit if you need branch protection, required checks, or repo settings as
   code, or to roll the same files out across many repos.
