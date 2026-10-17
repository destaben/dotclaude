# References — adopted from awesome-copilot

Source: https://github.com/github/awesome-copilot (MIT license, repo-wide).
Each item below was read for its idea and adapted into a dotclaude skill or
agent in our own words — nothing is copied verbatim. Attribution is kept here
per the MIT license's requirement to retain notice of reuse.

| awesome-copilot item | Adapted into | Why |
|---|---|---|
| [`instructions/code-review-generic.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/code-review-generic.instructions.md) | `.claude/agents/bug-hunter.md` | General review checklist shape (security, contracts, bad patterns) informed the agent's "what you check" list. |
| [`skills/conventional-commit`](https://github.com/github/awesome-copilot/tree/main/skills/conventional-commit) | `.claude/skills/commit-and-pr/SKILL.md` | Conventional Commits format for commit messages. |
| [`skills/commit-message-storyteller`](https://github.com/github/awesome-copilot/tree/main/skills/commit-message-storyteller) | `.claude/skills/commit-and-pr/SKILL.md` | "Why, not diff restatement" framing for commit messages. |
| [`instructions/devops-core-principles.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/devops-core-principles.instructions.md) | `.claude/skills/release-policy/SKILL.md` | Informed the severity-gate philosophy (fast, safe feedback loops). |
| [`instructions/github-actions-ci-cd-best-practices.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/github-actions-ci-cd-best-practices.instructions.md) | `.github/workflows/docs-check.yml` | Minimal, advisory-only CI shape; no secrets, no blocking local work. |
| [`instructions/context-engineering.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/context-engineering.instructions.md) | `.claude/skills/token-budget/SKILL.md` | Context-size awareness and when to suggest clearing it. |
| [`instructions/exclude-prompt-data.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/exclude-prompt-data.instructions.md) | `CLAUDE.md` (general rules) | Output only the resulting content, not meta-commentary about the process. |
| [`instructions/agent-safety.instructions.md`](https://github.com/github/awesome-copilot/blob/main/instructions/agent-safety.instructions.md) | `.claude/skills/release-policy/SKILL.md` | Severity-based gating instead of agents freely taking irreversible actions. |
| [`skills/conventional-branch`](https://github.com/github/awesome-copilot/tree/main/skills/conventional-branch) | `.claude/skills/commit-and-pr/SKILL.md` | Branch naming convention (`type/slug`). |
| [`skills/create-architectural-decision-record`](https://github.com/github/awesome-copilot/tree/main/skills/create-architectural-decision-record) | `docs/decisions/` format used in this repo | ADR shape (context / decision / consequences) used for every record in this directory. |

## Not adopted
awesome-copilot does not have `prompts/` or `chatmodes/` directories (an
earlier assumption in planning); its actual top-level layout is `agents/`,
`instructions/`, `skills/`, `plugins/`, `cookbook/`, `docs/`, `workflows/`,
`hooks/`. Nothing from `agents/`, `plugins/`, or `hooks/` was adopted here —
this repo's own agents were written from scratch for Claude Code's frontmatter
rather than ported from Copilot's chat-mode format.

## Future candidate
An `adr-writer` skill (formalizing the `create-architectural-decision-record`
pattern into a reusable Claude Code skill) is a reasonable next addition, not
built in this pass.
