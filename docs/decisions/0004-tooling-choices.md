# 0004 — Tooling choices

- Date: 2026-10-25 (consolidates the former 0003, 0004, and 0006); items 5, 6, 7, 8 and 9 added 2026-11-01, 2026-11-07, 2026-11-07, 2026-11-08 and 2026-11-07 respectively
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
7. **`remote-hosts`: ssh aliases, a private vault, and an HTTP check first for printers
   (2026-11-07).** Administering the user's own machines goes through named aliases
   in `~/.ssh/config` with key-only, non-interactive ssh (`BatchMode`), not a
   device-specific MCP: nothing to install or keep running, and a missing key fails
   fast instead of hanging on a prompt the agent cannot answer. Instance facts
   (addresses, services, restore plans) live in a separate private vault repo, never
   here, because this repo is public (CLAUDE.md, "Public or shared projects"). For
   printers the first look is a single HTTP request to Moonraker, because heavy
   commands on a Pi-class host can disturb a running print; the scripts apply that
   as a safety net for the aliases the user lists (and aliases with the same
   configured `HostName`), and the guard is inactive when no printer list exists.
   Device output is treated as
   untrusted data (the skill's own section says how).
8. **`remote-hosts`: allow a user-maintained read-only sudoers whitelist (2026-11-08).**
   The skill used to forbid `sudo` outright, which blocked root-only reads
   (firewall rules, root's crontab, `dmesg`). The alternatives were keeping the ban
   (the user types a password for every read) or full passwordless sudo (any
   prompt-injected command runs as root). The chosen middle path is a whitelist the
   user maintains on their own hosts, with exact paths and arguments, listed in the
   private vault; the skill only says how to use it. It is a convenience list, not a
   security boundary, because `docker` group membership is root-equivalent. The
   host's sudoers file is the gate, not the vault text, and the skill adds a rule
   that reading state never means dumping secrets. If the whitelist ever needs write
   entries, revisit this item.
9. **`claudio` phones the user; keypad answers, quiet hours, a chat fallback
   (2026-11-07).** An unresolved decision goes to the user by phone instead of
   waiting in a terminal. Answers are keypad digits confirmed by a second press,
   not speech recognition: telephone audio is least reliable on exactly the
   short words (yes, no, numbers) that binding decisions rest on. Quiet hours
   are checked before every attempt, so a retry never rings inside the window. A
   phone that is not registered is not dialled until it registers: the owner
   gets a heads-up chat message and the call waits briefly; if the phone still
   has not registered, the result is `unanswered` with `reason:
   phone_not_registered`. A repeat key (9) or a wrong key uses up a round on
   purpose: the round limit bounds how long a call can occupy the phone, and the
   skill's "Rounds" section documents it. Telephony instance data stays in the
   user's private notes. The agent's shell is restricted to the call script by a
   hook, because it reads council briefs that can quote untrusted text and the
   env file holds the chat token; the details (guard location, user-level
   install, what is allowed) live in the skill's "Agent safety" section. The guard cannot check the wording of
   the question, so injected text could reword an option; that residual risk is
   accepted because the owner hears the text, the choice is read back, and
   nothing is recorded until a second key press.
