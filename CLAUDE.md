# Global rules

## Portability — read this first
These are personal defaults, installed into `~/.claude/` and applied across
every project you work in. They must never assume the specifics of any one
project. Before relying on a project having a particular file, folder, or CI
setup (a decisions log, a plans folder, a specific GitHub template, a given
test runner), check that the *current* project actually has it — don't carry
over a convention just because the source config repo for these defaults
happens to use one. When a skill below needs a project-specific resource and
the current project doesn't have it, fall back to the generic default it
describes, or ask, rather than inventing structure that isn't there.

## Language
Write everything in English: code, comments, docs, commit messages, PR text.

## Change pipeline
Every change goes through: `/plan` (planner, read-only) → you approve →
implementer makes the change → scoped tests → `/release` (full suite,
bug-hunter, documenter, commit-and-pr). No hooks are used for this — it's a
sequence of steps inside the commands and skills themselves, not something
attached to the tool-call event system.

## Testing
Follow the `testing-mindset` skill: reproduce bugs with a failing test
first, test behavior and contracts not implementation, run scoped tests
while working and the full suite before release, never weaken a test to make
it pass, mock only at boundaries you don't own, and treat a flaky test as a
bug.

## Git rules
- Never commit or push directly to `main`.
- Never force-push.
- Never stage a file that looks like it holds secrets or credentials — check
  contents, not just the filename, before a broad `git add`.
- Open PRs only through the `commit-and-pr` skill.
- Use conventional commit messages.

## Token rules
- Read files with `offset`/`limit` instead of loading whole files when you
  only need a part of them.
- Delegate MCP-heavy or exploratory work to a Haiku subagent so raw tool
  output stays out of the main context.
- Run `/clear` between unrelated tasks.
- If the implementer fails twice on the same task, escalate to Sonnet rather
  than retrying Haiku a third time — repeated Haiku loops often cost more
  than one Sonnet pass.
- Keep this file and every skill free of duplication; link to the skill that
  owns a topic instead of restating its rules here.

## Cost awareness
Follow the `token-budget` skill for consumption warnings and
`session-cost-report` for cost reporting. All USD figures are estimates at
API list prices, refreshed periodically rather than hardcoded — see
`session-cost-report` for how staleness is handled. A Pro/Max plan is a flat
subscription, not billed per token, so these numbers show relative cost, not
an actual charge.

## Public or shared projects
Before writing to a project you know is public, or a shared one, or when
unsure — never write personal data (names, emails, usernames, absolute home
paths), tokens, or keys into a tracked file. Keep personal overrides in that
project's `.claude/settings.local.json` (gitignored), never in
`.claude/settings.json`.
