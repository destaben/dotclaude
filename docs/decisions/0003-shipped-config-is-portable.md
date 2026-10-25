# 0003 — Shipped config is project-agnostic

- Date: 2026-10-25 (consolidates the former 0008, 0009, and 0010)
- Status: accepted and enforced; this is the repo's foundational rule

## Decision
1. **Two categories of file.** *Shipped* files get installed into `~/.claude/`
   or a project's `.claude/` and must work in any project: `CLAUDE.md`,
   agents, commands, skills, `settings.json`, the PR/issue templates, and
   `scripts/session_cost.py` with its config. They refer to other installed
   config by name or installed path, or check the current project for a
   convention and fall back to a generic default. *Dev-only* files describe or
   validate this repo and are never installed: the validator, `tests/`, `docs/`,
   `README.md`, `CHANGELOG.md`, `.github/workflows/*`. The test for a shipped
   file: would it make sense read from `~/.claude/` in an unrelated project?
   `scripts/validate_repo.py` rejects dotclaude-specific strings in shipped
   files, and shipped files name skills rather than `.claude/skills/` paths.
   That catches literal strings only; assumptions like a named test framework
   still need manual review. `scripts/install.py` does the install: symlinks
   by default so edits here apply at once, with `--copy`, `--dry-run`,
   `--force`, and `--uninstall`.
2. **Templates are personal defaults.** PR and issue templates are generic.
   They live in `.github/` (GitHub auto-fills from them here as a side
   benefit) and `install.py` copies them to `~/.claude/templates/`. Lookup
   order for `commit-and-pr` and `github-ops`: the project's own template,
   then the personal default, then a minimal inline shape.
3. **`settings.json` is merged, never linked or copied.** On a first real
   install it already held unrelated hooks, a theme, and a model, which a
   symlink or copy would have deleted. `install.py` merges on every user-scope
   install: it unions `permissions.allow`/`deny` (never removing), sets
   `statusLine` and `model` only when absent (a mismatch is reported, not
   overwritten, so a changed upstream value does not reach a machine that
   already has one), touches no other key, and is idempotent. Uninstall never
   deletes the file. A fourth owned key needs its own merge rule in code.
   The write is atomic (temp file plus `os.replace`), keeps the previous
   version as `settings.json.bak` (one generation: the next changed merge
   replaces it), and goes through a symlinked file. A dangling symlink is
   refused rather than creating directories outside the install target. It is
   crash-safe, not safe against another process writing the file at the same
   instant. A file
   that is not valid JSON, or whose `permissions` has the wrong shape, stops
   the merge with a clear error and is left untouched.

## Validation (2026-10-25)
The council kept the merge design and asked for the atomic write, the backup,
and tests for malformed input, all now done. Its claim that a malformed
`settings.json` was silently overwritten was wrong: that already raised before
any write.
