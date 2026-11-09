# Changelog

All notable changes to this repo are recorded here. Entries explain why a
change was made, not just what changed — the diff already shows what.

## 2026-11-08 — PR review only posts finished reviews

The `claude-pr-review` workflow could post an interim message ("waiting for the
agents...") as the review and still pass, which a wait-for-zero-findings loop
reads as an empty review. The workflow now validates the message (a
`## Review of PR #<n>` first line and a `Result: ... findings (...)` last line
with consistent counts) in a tested script, retries the review once when it is
incomplete, and fails the job rather than posting it. The prompt states the
format explicitly. One-comment-per-PR editing and a higher effort level were
considered and left out; reasons are in `docs/decisions/0002-cost-and-quota.md`.
A separate check step validates the message and the posting step re-checks it.
The gate also refuses to post a review that contains a secret's value, and the
agent's file access is narrowed to `Read` inside the checked-out workspace, to
close a path by which an injected diff could have leaked a token into a
comment. The review job also runs with `--setting-sources user`, since the repo's own
`.claude/settings.json` grants would otherwise add to the workflow's tool list. The allow and deny lists and their limits are in the "Secret-leak
defence" section of `docs/decisions/0002-cost-and-quota.md`.
Only an incomplete result (exit 3 of the script) is retried; a crash or setup
error fails the job at once, and a run where the action itself failed is never
posted.
`github-ops` also tells the waiting recipe not to count a green run with a
status-only comment as zero findings.

## 2026-11-08 — remote-hosts: allow the user's read-only sudoers whitelist

The `remote-hosts` skill said to never run `sudo`, which left Claude unable to read root-only
state (firewall rules, root's crontab, `dmesg`) on the user's hosts. It now allows one
exception: a read-only whitelist the user sets up on their own hosts, run non-interactively with
exactly the listed arguments and under the same print-state and ask-before-change rules as
anything else. The host's sudoers file decides what may run, not the vault note, and an
open-ended entry is not used. A new rule says reading state never means printing secrets, and
that a whitelist does not waive it. The whitelist is described as a convenience list, not a
security boundary, because `docker` group membership is root-equivalent. The whitelist and the
host facts stay in the user's private vault.

## 2026-11-07 — Claudio, a CEO agent that phones the user

Added `claudio`, a CEO agent above the council, and a `ceo-call` skill, so a decision the council
cannot resolve reaches the user by phone instead of waiting in a terminal. It asks with text-to-
speech and takes a keypad answer, not spoken words, because speech recognition on telephone audio is
least reliable on exactly the short words (yes, no, numbers) that binding decisions depend on; a
choice counts only after a second key press confirms it. Night calls, a sleeping phone, retries and
abuse by a manipulated agent are handled by the skill's rules, and the agent's shell is limited by a
hook to the call script, since its briefs can quote untrusted text. `council-policy` and `/council`
now hand two named cases back to the user, by phone when this is set up; install `claudio` and `ceo-call` at
user scope, because a project-level copy takes precedence and can change its hook. No instance data
enters this repo. Why: `docs/decisions/0004-tooling-choices.md`, item 9.

## 2026-11-07 — Administer LAN devices over SSH

Added a `remote-hosts` skill so Claude can act as sysadmin for the user's own
machines without any instance data entering this public repo. Access goes
through named SSH aliases with key-only, non-interactive ssh, so a missing key
fails fast instead of hanging on a prompt Claude cannot answer. Work is
read-only by default, and device facts live in a separate private vault that
the skill points to. For 3D printers the first check is one HTTP request to
Moonraker, because heavy commands on a Pi-class host can disturb a running
print. `github-ops` also gains a recipe for waiting on a workflow run with
`gh run watch` instead of guessing with fixed sleeps. The design choices are
recorded in `docs/decisions/0004-tooling-choices.md`, items 6 and 7.

## 2026-11-01 — Browser automation via agent-browser

Replaced the `playwright-ops` skill with `browser-ops`, which drives the
`agent-browser` CLI through Bash instead of the Playwright MCP connector. Its
accessibility-tree snapshots with short refs are expected to cost fewer tokens
than Playwright's page snapshots (not yet measured), and a CLI needs no
connector configured. The guidance to run browser work in a subagent and prefer
text over screenshots is kept; a unique named session per task is added so
agents don't share one browser. The guide's `session id` example is not used
because it yields one id per worktree and relies on an exported variable that
doesn't survive between Bash calls.

## 2026-10-25 — Use codebase-memory-mcp graph-first

Added a `codebase-memory-ops` skill so exploration goes through the code graph
(search, snippets, callers, change impact) before whole-file reads, which is
faster and cheaper. It is a complement, not a replacement: the skill applies only
when the connector is present and falls back to `Read`/`Grep` otherwise, keeping
the shipped config portable. `planner`, `implementer` and `bug-hunter` get the
read-only graph tools and a one-line pointer; the read-only tools are
pre-allowed, while indexing, delete, ADR writes and trace ingestion stay behind
a prompt. The MCP was installed with `--skip-config`, so this repo
stays the single source of truth for skills, agents and hooks.

## 2026-10-25 — Harden what the council review flagged

The council's review of earlier decisions asked for three fixes, now made.
The PR review workflow skips drafts and cancels a superseded run on the same
PR, since every push used to start a run and post a comment; its concurrency
group is unique for comments that don't ask for a review, so they can't cancel
a real one. `install.py` writes `settings.json` atomically, keeps a `.bak`,
writes through a symlink, and refuses (touching nothing) a file that isn't
valid JSON or whose `permissions` has the wrong shape. The validator now checks
that `release.md` numbers its steps in the documented order, because with no
hooks that order is the whole gate. `bug-hunter` stays on Haiku at medium
effort: the council suggested Sonnet, declined to protect the subscription quota.

## 2026-10-25 — Consolidate decision records

Eleven decision records overlapped (0007 and 0011 told one story, as did
0008-0010) and cost tokens to read. They are now four topic records, and the council's own decision lives in the
pipeline one:
pipeline and agents, cost and quota, portable shipped config, and tooling
choices. Old numbers are gone; git history has the originals. Reviewing them
with the new council also produced the follow-ups listed at the end of each
record.

## 2026-10-25 — Add a decision council

Design choices had one proposer and no structured challenge. `/council` now
runs advisors with distinct lenses in parallel (two by default, five in full
mode) and a chair that issues the binding verdict, cheap models for the shallow lenses and Sonnet for the
ones that need depth. A quick council (3 calls) is the default so it fits
alongside normal work on a shared subscription; a full one (6) is for costly
decisions. The spawn-warning budget moved from 5 to 7 so a full council
doesn't trigger it. See `docs/decisions/0001-pipeline-and-agents.md`.

## 2026-10-17 — Make the PR review workflow actually post

Every review run failed with `Could not fetch an OIDC token`: without a
`github_token`, `claude-code-action` tries an OIDC exchange for the Claude
GitHub App token, which needs `id-token: write` and the app installed. The
workflow now passes `GITHUB_TOKEN`. Fixing that exposed more: the agent
needs the PR number (HEAD is detached) and an explicit tool allowlist, and
Haiku ended its run before posting unless told to wait. The review of this
very change flagged that letting the agent run `gh pr comment` plus read
`.git/config` was a secret-leak path via a prompt-injected diff, so the agent
now only returns the review as its final message and a workflow step posts
it; the comment trigger
is limited to owner/member/collaborator. The review no longer runs the test
suite (it executes untrusted code); `docs-check` still does, though advisory
(`continue-on-error`). Automatic runs skip fork PRs; the comment trigger
does not, and the review text can still be steered by the diff, so it is
advisory.

## 2026-10-17 — Price `claude-sonnet-5` and guard `pricing.json`

Added `claude-sonnet-5` ($2 input / $10 output per MTok) to
`config/pricing.json`. Without it, `session_cost.py` reported sessions on that
model as unpriced, because the lookup is an exact match and does not fall back
to `claude-sonnet-5-5`. The rates were checked against the official pricing
page the same day (the introductory price became the standard one), so
`_fetched_at` is accurate. Added tests that reject duplicate keys and
non-numeric or non-positive rates in the shipped file, since
`validate_repo.py` does not inspect its contents.

## 2026-10-17 — Automatic, per-PR review on Haiku 5.5 / low effort

`claude-pr-review.yml` now also triggers on `pull_request`
(`opened`/`synchronize`/`reopened`), not just on an `@claude review` comment,
and runs both `bug-hunter` and `documenter` via
`claude_args: '--model claude-haiku-5-5 --effort low'` to keep the per-run
cost low enough to justify firing on every push. Recorded in
`docs/decisions/0002-cost-and-quota.md`, which relaxes the earlier comment-only
trigger now that the cost per run is this low.

## 2026-10-17 — Initial scaffold

Bootstrapped the repo: global rules (`CLAUDE.md`), the planner / implementer /
bug-hunter / documenter / token-auditor agents, the `/plan`, `/release`, `/pr`
commands, eleven skills covering commit/PR flow, GitHub ops, testing,
release severity, token budgeting, session-cost reporting, four MCP
connectors, and Playwright. Added `scripts/session_cost.py` and
`scripts/validate_repo.py` with unit tests, pricing/budget config
placeholders, and an advisory `docs-check.yml` workflow. No hooks, no remote
resources created — see `docs/decisions/` for the judgment calls made along
the way.

## 2026-10-17 — GitHub PR review, templates, and real pricing

Added `.github/workflows/claude-pr-review.yml`, reusing `bug-hunter` for
GitHub PR review instead of a second agent — confirmed there's no required
agent name on GitHub's side, and that the action's OAuth-token auth bills
against a Claude subscription rather than per-token API, which shaped the
decision to gate the trigger behind a comment mention rather than every
push. Added `.github/pull_request_template.md` and
`.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml`, with
`commit-and-pr` and `github-ops` updated to fill them explicitly. Filled
`config/pricing.json` with real API list prices (previously `TODO`
placeholders). Added a sustainability review
(`docs/decisions/0002-cost-and-quota.md`) of the whole
pipeline's model routing against a Claude Pro subscription's shared usage
quota.

## 2026-10-17 — Make shipped config repo-agnostic; add the installer

Caught and fixed a foundational mistake: several agents/skills/commands
assumed dotclaude's own layout (`docs/plans/`, `docs/decisions/`,
`scripts/validate_repo.py`, a bare `scripts/session_cost.py`,
`config/budgets.json` relative to cwd, literal "this repo" phrasing) would
exist wherever this config gets installed — it won't, in any other project.
Rewrote `CLAUDE.md`, `planner`, `implementer`, `bug-hunter`, `documenter`,
`token-auditor`, `/plan`, `/release`, `commit-and-pr`, `github-ops`,
`token-budget`, `session-cost-report`, `testing-mindset`, `playwright-ops`,
and `mcp-docs-ops` to either reference the *installed* path or check the
current project's own convention with a generic fallback. Rewrote the two
GitHub issue form templates, which had been dotclaude-specific (an agent-name
dropdown, a dotclaude-rules checklist) despite being installed as the user's
personal default for every project.

Added `scripts/install.py` (symlink-by-default, `--copy`/`--dry-run`/
`--force`/`--uninstall`, user or project scope) as the actual mechanism that
performs the install this repo has always implied but never provided. Added
`config/pricing.json._fetched_at`/`_max_age_days` plus a staleness warning in
`session_cost.py`'s output, so pricing is treated as a time-limited cache
with a documented refresh procedure instead of a value that goes silently
stale. Added `check_shipped_files_are_repo_agnostic` to
`scripts/validate_repo.py` so this class of mistake fails CI going forward.
See `docs/decisions/0003-shipped-config-is-portable.md`.

## 2026-10-17 — Pushed to GitHub, installed, and made settings.json merge automatic

Pushed the initial commits to the (previously empty) `origin` remote and ran
the installer for real against this machine's actual `~/.claude/`. That run
surfaced exactly the risk `install.py` was designed to guard against: an
existing `~/.claude/settings.json` with unrelated `hooks` (a different tool
entirely) and a `model` set moments earlier via `/model` — both of which a
naive overwrite would have destroyed. Handling that one instance by hand and
documenting "merge manually next time" wasn't good enough — it's a
guarantee that would quietly lapse the next time this file needed to change.

Replaced the one-time manual merge with `merge_settings_json()`: every
`install.py` run (user scope) now unions `permissions.allow`/`deny`, adds
`statusLine`/`model` only if entirely absent, and never touches any other
key — on every run, not just the first, and reports `unchanged` when
there's nothing to do. `--uninstall` now explicitly leaves `settings.json`
alone rather than attempting to remove it. See
`docs/decisions/0003-shipped-config-is-portable.md`.
