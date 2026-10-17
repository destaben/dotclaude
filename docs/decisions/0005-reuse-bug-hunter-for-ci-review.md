# 0005 — Reuse `bug-hunter` for GitHub PR review, don't duplicate it

- Date: 2026-10-17
- Status: accepted

## Context
The user wants automatic PR review on GitHub in the future, and asked for a
new agent wired into the code-review pipeline at the same position as
`bug-hunter` — with an explicit fallback: if having two review agents doesn't
make sense, rename `bug-hunter` instead, because they believed GitHub looks
for a specific agent name by default.

Verified before building anything:
- The official `anthropics/claude-code-action` does **not** look for any
  hardcoded agent/skill/job name. Everything is referenced explicitly in the
  workflow's own YAML (`prompt:`, or an explicit skill invocation). The
  premise that GitHub expects a particular name was incorrect — confirmed
  against `code.claude.com/docs/en/github-actions` and the action's own
  example, which uses an arbitrarily-named skill.
- A separate "Code Review" product (fully automatic, no workflow file) exists
  but is Team/Enterprise only — not available on the Pro plan this repo
  targets. So for Pro, `claude-code-action` in a custom workflow is the only
  path to automatic PR review.

## Decision
No second review agent was created, and `bug-hunter` keeps its name. Its
frontmatter/body in `.claude/agents/bug-hunter.md` now says explicitly that
it runs in two contexts — locally via `/release`, and in CI via
`.github/workflows/claude-pr-review.yml` — with the same checks and severity
policy either way. Only the output sink differs (return findings vs. post a
PR comment).

## Consequences
One definition to maintain instead of two that could drift apart, which also
matches this repo's own anti-duplication rule in `CLAUDE.md`. If a real
GitHub-side naming requirement surfaces later (e.g. a future Anthropic
product convention), revisit this decision — it was a documented judgment
call, not a hard constraint discovered during research.
