# dotclaude — global rules

## Language
Write everything in English: code, comments, docs, commit messages, PR text.

## Change pipeline
Every change goes through: `/plan` (planner, read-only) → you approve → implementer
makes the change → scoped tests → `/release` (full suite, bug-hunter, documenter,
commit-and-pr). See `docs/pipeline.md` and the diagram in `README.md`. There are no
hooks in this repo — the pipeline is a sequence of steps inside commands and skills,
not something attached to the tool-call event system.

## Testing
Follow `.claude/skills/testing-mindset/SKILL.md`: reproduce bugs with a failing test
first, test behavior and contracts not implementation, run scoped tests while working
and the full suite before release, never weaken a test to make it pass, mock only at
boundaries you don't own, and treat a flaky test as a bug.

## Git rules
- Never commit or push directly to `main`.
- Never force-push.
- Never stage a file that looks like it holds secrets or credentials — check contents,
  not just the filename, before a broad `git add`.
- Open PRs only through `.claude/skills/commit-and-pr/SKILL.md`.
- Use conventional commit messages.

## Token rules
- Read files with `offset`/`limit` instead of loading whole files when you only need
  a part of them.
- Delegate MCP-heavy or exploratory work to a Haiku subagent so raw tool output stays
  out of the main context.
- Run `/clear` between unrelated tasks.
- If the implementer fails twice on the same task, escalate to Sonnet rather than
  retrying Haiku a third time — repeated Haiku loops often cost more than one Sonnet
  pass.
- Keep this file and every skill free of duplication; link to the skill that owns a
  topic instead of restating its rules here.

## Cost awareness
Follow `.claude/skills/token-budget/SKILL.md` for consumption warnings and
`.claude/skills/session-cost-report/SKILL.md` for the PR cost footer. All USD figures
are estimates at API list prices — a Pro/Max plan is a flat subscription, not billed
per token.

## This repo is public
Never write personal data (names, emails, usernames, absolute home paths), tokens, or
keys into any tracked file. Personal overrides belong in `.claude/settings.local.json`,
which is gitignored. `scripts/validate_repo.py` checks for this on every PR.
