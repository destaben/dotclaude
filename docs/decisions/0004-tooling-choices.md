# 0004 — Tooling choices

- Date: 2026-10-25 (consolidates the former 0003, 0004, and 0006); items 5, 6, 7 and 9 added 2026-11-01, 2026-11-07, 2026-11-07 and 2026-11-07 respectively; item 8 added 2026-11-08, item 10 added 2026-11-09 and item 11 added 2026-11-10 and items 12 and 13 added 2026-11-10
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
9. **(Superseded by item 12, 2026-11-10.) `claudio` phones the user; keypad answers, quiet hours, a chat fallback
   (2026-11-07).** An unresolved decision goes to the user by phone instead of
   waiting in a terminal. Answers are keypad digits confirmed by a second press,
   not speech recognition: telephone audio is least reliable on exactly the
   short words (yes, no, numbers) that binding decisions rest on. Quiet hours
   are checked before every attempt, so a retry never rings inside the window. A
   phone that is not registered is not dialled until it registers: the owner
   gets a heads-up chat message and the call waits up to `heads_up_s` (default 90 s); if the phone still
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
   nothing is recorded until a second key press. A failure before dialling
   (speech server or Docker down) gives the throttle slot back on purpose, so a
   transient fault does not lock the owner out, but only when no chat message
   reached the owner (an error notice that did go out keeps the slot); a loop of
   such failures is serialised by the run lock. The spoken prompts and the owner's chat messages
   are in Spanish on purpose (product output for the owner's phone, not docs); the
   rule and its limit live in the skill's design notes. The single-hook exception is
   repeated briefly in CLAUDE.md, the README, `docs/pipeline.md` and the ADRs, and the
   two escalation cases in the README, `docs/pipeline.md`, `council-policy` and
   `council.md`, because each file is read on its own.
   **Deferred (2026-11-10): speech recognition (phase 2b) and a warmer voice.** The
   owner chose to keep keypad answers for now. Speech-to-text, if added, must be local,
   restricted to a closed grammar (yes/no/option number) with the keypad kept as
   the fallback, and gated on a benchmark on real 8 kHz telephone audio: at least 95% accuracy
   on closed answers, under 5 s per turn, and a memory cap of about 1 GiB so it cannot
   starve the host's other services. Cloud speech is opt-in only. A more natural voice is
   also deferred (local first, cloud only if local falls short). Tracked in issue #13.
   **Reaching a locked phone (2026-11-10):** a suspended iPhone softphone cannot be
   rung by Asterisk alone, so the optional Siperb push bridge (homelab-infra) registers
   outward and is meant to wake the app; the dial target is the `iphone` endpoint. It was
   tried first because it needs no inbound port and no monthly fee. Status: the bridge
   registers and the endpoint exists, but the first test calls to `PJSIP/iphone` ended
   with `Call Failure` before anything rang, so it is NOT yet shown to work. Until a locked-phone call is
   confirmed, the SIP trunk to the owner's mobile number remains the fallback option. Tracked in issue #13.
10. **`worker` container holds no GitHub credential; publishing happens on the owner's
   machine (2026-11-09).** An unattended run that could push would be able to push
   anywhere its token reaches, including after a prompt injection. So the container
   clones public repos anonymously and only edits files. The owner's machine fetches
   the bundle, checks that it holds exactly one ref, the run's own `worker/` branch, scans the branch and
   the pull request text, refuses a branch that changes anything under `.github/` (a
   pushed workflow file runs with the repository's secrets before anyone reads the
   draft), then pushes that branch and opens a draft pull request with
   the owner's own `gh`. The cost is that nothing is published until the owner's
   machine picks the run up, and private repos are out of scope for this version.
   A saved bundle has no publish command: the owner reviews it and, to publish, repeats the run
   (a new result, at the cost of more quota), because a manual push would skip these checks.
   The residual risks are listed in the skill's own section. The one the owner accepted
   for the spike: the allowed test runners execute code the worker wrote, with network
   access and read access to the login, so tasks come only from owner-authored input and
   the login stays revocable; a network allow-list is the future hardening. A related
   judgment call: a pushed branch opens the repository's `pull_request` workflows on its
   own code. Two workflows here run on `pull_request`: `docs-check` runs the branch's
   scripts and tests and declares a read-only token (`permissions: contents: read`);
   `claude-pr-review` holds `CLAUDE_CODE_OAUTH_TOKEN` and keeps write permission on pull
   requests and issues (unlike `docs-check`, so draft-until-read is its only guard), skips
   drafts, and runs for a draft only on an `@claude review` comment from the owner, a
   member or a collaborator.
   So worker pull requests stay drafts until read, and the skill tells the owner to use
   the worker only on repositories whose `push` and `pull_request` workflows hold no
   secrets or wait for an approval (the skill's wording).

11. **`/auto`: a foreground supervisor, no self-approval (2026-11-10).** Autonomous mode
    (issue 12) runs the stages after the owner approves the plan once. A quick council chose
    an owner-started foreground supervisor around the unmodified `claude -p` over cron or a
    scheduled restart, because an unattended relaunch loop drifts toward the always-on use
    that the subscription constraints rule out: only the unmodified `claude` binary on the
    owner's own subscription, own repositories only, owner-triggered runs, nothing shared or
    served to others, small and finite use rather than continuous self-directed operation
    (recorded in issue 15). The issue's self-approval by a council or checklist was dropped:
    a checklist is gameable and the owner's approval gate stays. A usage limit is a pause,
    not a failure; the reset is parsed from the message, and a weekly limit with no readable
    reset stops rather than guessing. Defaults: 6 h maximum wait, 3 automatic resumes, 330
    min fallback for an unreadable 5-hour reset. Unattended, non-severe review findings are
    listed in the PR description and not applied (the one deviation from `release-policy`).
    The hard budget cap is opt-in (`AUTO_MAX_BUDGET_USD`). Unverified: the real limit
    wording and `claude -p --resume` after a limit, so resume re-sends the prompt at stage
    boundaries.
12. **The CEO agent, the phone calls and their telephony stack are removed (2026-11-10).**
    `claudio`, the `ceo-call` skill, its shell guard and the Asterisk and Piper stacks in the
    homelab infrastructure repo are gone; this supersedes item 9. Why: the calls could not be made
    reliable. A locked iPhone suspends its softphone, and every route that fixes that needs a
    cost or a public port the owner does not have or want: Siperb's push proxy has to register
    into the PBX from the internet, which a CGNAT connection cannot allow; a SIP trunk to the
    owner's mobile number adds a monthly fee. A Telegram bot was built as a fallback and then
    judged unnecessary: the owner already has the Claude app on the phone. What replaces it: when
    a decision goes back to the user (`council-policy`, "When the council cannot resolve it"), ask
    directly with numbered options (`AskUserQuestion`) and, if the user may be away, send a push
    notification (`PushNotification`) that reaches the Claude app. Nothing runs in between and no
    credential or open port is involved. The repo has no hooks again (the `claudio` guard was the
    one exception). The removed code stays in git history (the last commit that has it is `f1d9034`) if a
    phone channel is ever wanted again; the deferred speech-recognition conditions in item 9 then still apply.
13. **Cheap non-severe findings may be fixed when the owner delegates the PR (2026-11-10).**
    `release-policy` listed non-severe findings and asked before changing anything, because an
    agent's judgment on style or scope is a worse proxy for the owner's intent than asking. With
    the owner away and the PR explicitly handed over, asking means a stalled PR for a typo, so one
    pass is allowed in the same PR for findings that are cheap, clearly right, or in code already
    touched; the rest are listed with a reason and anything needing a design choice is left to the
    owner. It is limited on purpose: severe findings and the severity definitions are unchanged,
    `/auto` still lists and applies none (nobody can be asked mid-run and its scope fence applies),
    and the `github-ops` review loop keeps its own precondition. Interactive `/release` without a
    delegation behaves as before.
