# 0010 — settings.json is merged by the installer, not linked or copied

- Date: 2026-10-17
- Status: accepted, enforced in scripts/install.py

## Context
Every other installed file (`CLAUDE.md`, agents, commands, skills,
templates, scripts) is a clean, ownable unit — dotclaude's copy is the only
thing that should ever be at that path, so a symlink (or a plain copy) is
correct and complete.

`settings.json` isn't like that. The first real install against this
machine's actual `~/.claude/settings.json` hit exactly the case this
decision exists for: it already had `hooks` pointing at an unrelated tool
(`.copilot-pixel-agents/hook.sh`), a `theme`, and a `model` the user had just
set moments earlier with `/model`. A symlink or a forced copy would have
silently deleted all of that. Handling it by hand once and telling the user
"you'll have to re-merge manually next time" is not a guarantee — it's a
chore that gets forgotten, exactly the kind of drift this repo's whole
purpose (durable, reliable personal config) exists to prevent.

## Decision
`scripts/install.py` never links or copies `settings.json`. Instead,
`merge_settings_json()` runs on every install (user scope only — project
scope never touches it), every time, and:
- Adds `permissions.allow` / `permissions.deny` entries dotclaude wants, as
  a **union** — existing entries are never removed or reordered.
- Sets `statusLine` only if the file has none at all. If one already exists
  and differs, it's left alone and the mismatch is reported as a note
  rather than silently dropped or silently overwritten.
- Sets `model` only if the file has no `model` key yet — an existing choice
  (interactive, via `/model`, or otherwise) always wins.
- Never touches any other key (`hooks`, `theme`, `mcpServers`, or anything
  else). The merge function doesn't even look at keys it doesn't own.
- Is idempotent: running it again when nothing changed reports `unchanged`
  and rewrites nothing.

`uninstall` mirrors this: it never deletes `settings.json` (removing it
could delete content the installer never put there), and reports
`left-as-is` with a note instead.

## Consequences
Future changes to dotclaude's own `.claude/settings.json` (new permission
entries, a different statusLine) now propagate automatically on the next
`python3 scripts/install.py` run, without the user ever having to remember
to re-merge by hand. The tradeoff: this merge logic only understands the
three keys above. A fourth dotclaude-owned top-level key would need its own
merge rule added to `merge_settings_json()`, not just an entry in a generic
list — slightly more code than a symlink, in exchange for never being
destructive to content dotclaude doesn't own.
