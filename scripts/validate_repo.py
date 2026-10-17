#!/usr/bin/env python3
"""Structural checks for the dotclaude repo.

Run with: python scripts/validate_repo.py
Exits non-zero and prints every failure if any check fails.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH_RE = re.compile(r"/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/")
HOME_PATH_ALLOWED_SUBSTRINGS = ("/Users/you/", "/Users/<", "/home/you/")
TRACKED_TEXT_SUFFIXES = {".md", ".json", ".py", ".yml", ".yaml", ".txt", ""}

# Files that get installed into ~/.claude (or a project's .claude/) by
# scripts/install.py must stay agnostic to dotclaude's own repo layout —
# none of these substrings should appear in them. Case-insensitive.
REPO_SPECIFIC_PATTERNS = (
    "this repo",
    "docs/decisions/",
    "docs/plans/",
    "scripts/validate_repo.py",
    "docs-check.yml",
)


def fail(errors: list, message: str) -> None:
    errors.append(message)


def iter_tracked_files(repo_root: Path):
    """Best-effort: walk the repo, skipping .git, tests, and known-local-only files.

    `tests/` is excluded because its fixtures and assertions deliberately contain
    decoy emails/paths to exercise this exact detector, not real secrets.
    """
    skip_dirs = {".git", "tests"}
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.name == "settings.local.json":
            continue
        yield path


def _rel(path: Path, repo_root: Path):
    try:
        return path.relative_to(repo_root)
    except ValueError:
        return path


def check_frontmatter(path: Path, errors: list, repo_root: Path, required=("name", "description")) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        fail(errors, f"{_rel(path, repo_root)}: missing frontmatter block")
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        fail(errors, f"{_rel(path, repo_root)}: malformed frontmatter block")
        return {}
    fm_text = parts[1]
    fm = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    for field in required:
        if field not in fm:
            fail(errors, f"{_rel(path, repo_root)}: frontmatter missing '{field}'")
    return fm


def check_agents(errors: list, repo_root: Path) -> list:
    names = []
    agents_dir = repo_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        fail(errors, ".claude/agents is missing")
        return names
    for path in sorted(agents_dir.glob("*.md")):
        fm = check_frontmatter(path, errors, repo_root)
        if "name" in fm:
            names.append(fm["name"])
    return names


def check_commands(errors: list, repo_root: Path) -> list:
    names = []
    commands_dir = repo_root / ".claude" / "commands"
    if not commands_dir.is_dir():
        fail(errors, ".claude/commands is missing")
        return names
    for path in sorted(commands_dir.glob("*.md")):
        check_frontmatter(path, errors, repo_root, required=("description",))
        names.append(path.stem)
    return names


def check_skills(errors: list, repo_root: Path) -> list:
    names = []
    skills_dir = repo_root / ".claude" / "skills"
    if not skills_dir.is_dir():
        fail(errors, ".claude/skills is missing")
        return names
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            fail(errors, f"{_rel(skill_dir, repo_root)}: missing SKILL.md")
            continue
        fm = check_frontmatter(skill_md, errors, repo_root)
        if "name" in fm:
            names.append(fm["name"])
    return names


def check_settings_no_hooks(errors: list, repo_root: Path) -> None:
    settings_path = repo_root / ".claude" / "settings.json"
    if not settings_path.is_file():
        fail(errors, ".claude/settings.json is missing")
        return
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    if "hooks" in data:
        fail(errors, ".claude/settings.json must not contain a 'hooks' key")


def check_claude_md_length(errors: list, repo_root: Path) -> None:
    claude_md = repo_root / "CLAUDE.md"
    if not claude_md.is_file():
        fail(errors, "CLAUDE.md is missing")
        return
    lines = claude_md.read_text(encoding="utf-8").splitlines()
    if len(lines) > 150:
        fail(errors, f"CLAUDE.md has {len(lines)} lines, must be <= 150")


def check_readme_pipeline(errors: list, repo_root: Path, agent_names: list, command_names: list) -> None:
    readme = repo_root / "README.md"
    if not readme.is_file():
        fail(errors, "README.md is missing")
        return
    text = readme.read_text(encoding="utf-8")
    if "<!-- pipeline:start -->" not in text or "<!-- pipeline:end -->" not in text:
        fail(errors, "README.md is missing pipeline markers")
        return
    if "```mermaid" not in text:
        fail(errors, "README.md pipeline block must contain a mermaid diagram")

    start = text.index("<!-- pipeline:start -->")
    end = text.index("<!-- pipeline:end -->")
    pipeline_block = text[start:end]

    for name in command_names:
        if f"/{name}" not in pipeline_block:
            fail(errors, f"README.md pipeline diagram does not mention command '/{name}'")
    for name in agent_names:
        if name not in pipeline_block:
            fail(errors, f"README.md pipeline diagram does not mention agent '{name}'")


def check_no_secrets(errors: list, repo_root: Path) -> None:
    for path in iter_tracked_files(repo_root):
        if path.suffix not in TRACKED_TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = _rel(path, repo_root)
        for match in EMAIL_RE.finditer(text):
            fail(errors, f"{rel}: looks like an email address ({match.group(0)})")
        for match in HOME_PATH_RE.finditer(text):
            snippet = match.group(0)
            if any(allowed in snippet for allowed in HOME_PATH_ALLOWED_SUBSTRINGS):
                continue
            fail(errors, f"{rel}: looks like an absolute home path ({snippet})")


def check_shipped_files_are_repo_agnostic(errors: list, repo_root: Path) -> None:
    """CLAUDE.md, agents, commands, and skills get installed elsewhere by
    install.py — they must not assume dotclaude's own repo layout exists
    wherever they end up installed."""
    shipped_files = []
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.is_file():
        shipped_files.append(claude_md)
    for subdir in ("agents", "commands"):
        shipped_files.extend(sorted((repo_root / ".claude" / subdir).glob("*.md")))
    shipped_files.extend(sorted((repo_root / ".claude" / "skills").glob("*/SKILL.md")))
    pr_template = repo_root / ".github" / "pull_request_template.md"
    if pr_template.is_file():
        shipped_files.append(pr_template)
    shipped_files.extend(sorted((repo_root / ".github" / "ISSUE_TEMPLATE").glob("*.yml")))

    for path in shipped_files:
        text = path.read_text(encoding="utf-8").lower()
        rel = _rel(path, repo_root)
        for pattern in REPO_SPECIFIC_PATTERNS:
            if pattern in text:
                fail(errors, f"{rel}: contains repo-specific reference '{pattern}' — shipped files must stay project-agnostic")


def run_all_checks(repo_root: Path) -> list:
    errors: list = []
    agent_names = check_agents(errors, repo_root)
    command_names = check_commands(errors, repo_root)
    check_skills(errors, repo_root)
    check_settings_no_hooks(errors, repo_root)
    check_claude_md_length(errors, repo_root)
    check_readme_pipeline(errors, repo_root, agent_names, command_names)
    check_no_secrets(errors, repo_root)
    check_shipped_files_are_repo_agnostic(errors, repo_root)
    return errors


def main() -> int:
    errors = run_all_checks(REPO_ROOT)

    if errors:
        print(f"validate_repo.py: {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("validate_repo.py: all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
