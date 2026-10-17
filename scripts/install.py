#!/usr/bin/env python3
"""Install this dotclaude config into ~/.claude (user scope, default) or a
project's own .claude/ (project scope).

This script, scripts/validate_repo.py, tests/, and everything under docs/
are dotclaude's own dev tooling — they describe and check THIS repo and are
never installed anywhere. Only CLAUDE.md, .claude/{agents,commands,skills},
.claude/settings.json, the PR/issue templates, and scripts/session_cost.py
+ its config are part of the installed, portable config.

Usage:
    python3 scripts/install.py                       # user scope -> ~/.claude
    python3 scripts/install.py --mode project --target ~/some/other/repo
    python3 scripts/install.py --copy                # copy instead of symlink
    python3 scripts/install.py --dry-run
    python3 scripts/install.py --force                # overwrite conflicts
    python3 scripts/install.py --uninstall            # remove what this installer created
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (source path relative to REPO_ROOT, dest path relative to the install target)
USER_SCOPE_ENTRIES = [
    ("CLAUDE.md", "CLAUDE.md"),
    (".claude/settings.json", "settings.json"),
    (".github/pull_request_template.md", "templates/pull_request_template.md"),
    (".github/ISSUE_TEMPLATE/bug_report.yml", "templates/ISSUE_TEMPLATE/bug_report.yml"),
    (".github/ISSUE_TEMPLATE/feature_request.yml", "templates/ISSUE_TEMPLATE/feature_request.yml"),
    (".github/ISSUE_TEMPLATE/config.yml", "templates/ISSUE_TEMPLATE/config.yml"),
    ("scripts/session_cost.py", "dotclaude-scripts/scripts/session_cost.py"),
    ("config/pricing.json", "dotclaude-scripts/config/pricing.json"),
    ("config/budgets.json", "dotclaude-scripts/config/budgets.json"),
]

# Project scope only installs the parts a project itself needs/can use
# (no personal templates/scripts — those stay at user scope).
PROJECT_SCOPE_ENTRIES = [
    ("CLAUDE.md", "CLAUDE.md"),
]

DIR_ENTRIES = [
    # (source dir relative to REPO_ROOT, dest dir relative to target, scopes)
    (".claude/agents", "agents", ("user", "project")),
    (".claude/commands", "commands", ("user", "project")),
    (".claude/skills", "skills", ("user", "project")),
]


class Action:
    def __init__(self, src: Path, dst: Path, kind: str):
        self.src = src
        self.dst = dst
        self.kind = kind  # "linked" | "copied" | "skipped-exists" | "would-<kind>" | "removed"

    def __str__(self) -> str:
        return f"{self.kind}: {self.dst}"


def _same_content(src: Path, dst: Path) -> bool:
    if dst.is_symlink():
        try:
            return dst.resolve() == src.resolve()
        except OSError:
            return False
    if src.is_dir() or dst.is_dir():
        return False
    return filecmp.cmp(src, dst, shallow=False)


def install_one(src: Path, dst: Path, *, use_copy: bool, force: bool, dry_run: bool) -> Action:
    verb = "copied" if use_copy else "linked"
    if dst.exists() or dst.is_symlink():
        if _same_content(src, dst):
            return Action(src, dst, "already-installed")
        if not force:
            return Action(src, dst, "skipped-exists")
        if not dry_run:
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()

    if dry_run:
        return Action(src, dst, f"would-{verb}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if use_copy:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    else:
        dst.symlink_to(src.resolve(), target_is_directory=src.is_dir())
    return Action(src, dst, verb)


def install_dir_entries(target: Path, mode: str, *, use_copy: bool, force: bool, dry_run: bool) -> list[Action]:
    actions = []
    for src_rel, dst_rel, scopes in DIR_ENTRIES:
        if mode not in scopes:
            continue
        src_dir = REPO_ROOT / src_rel
        if not src_dir.is_dir():
            continue
        dst_dir = target / dst_rel
        # Install each child individually so we never clobber unrelated
        # content a user already has under ~/.claude/agents, etc.
        for child in sorted(src_dir.iterdir()):
            actions.append(install_one(child, dst_dir / child.name, use_copy=use_copy, force=force, dry_run=dry_run))
    return actions


def install_file_entries(target: Path, mode: str, *, use_copy: bool, force: bool, dry_run: bool) -> list[Action]:
    entries = USER_SCOPE_ENTRIES if mode == "user" else PROJECT_SCOPE_ENTRIES
    actions = []
    for src_rel, dst_rel in entries:
        src = REPO_ROOT / src_rel
        if not src.is_file():
            continue
        dst = target / dst_rel
        actions.append(install_one(src, dst, use_copy=use_copy, force=force, dry_run=dry_run))
    return actions


def uninstall(target: Path, mode: str) -> list[Action]:
    actions = []
    entries = USER_SCOPE_ENTRIES if mode == "user" else PROJECT_SCOPE_ENTRIES
    paths = [target / dst_rel for _, dst_rel in entries]
    for _, dst_rel, scopes in DIR_ENTRIES:
        if mode not in scopes:
            continue
        dst_dir = target / dst_rel
        if dst_dir.is_dir():
            paths.extend(sorted(dst_dir.iterdir()))

    for path in paths:
        if not (path.exists() or path.is_symlink()):
            continue
        src_rel = _source_for(path, target, mode)
        if src_rel is None or not _same_content(REPO_ROOT / src_rel, path):
            # Don't remove something this installer didn't create / that was modified.
            actions.append(Action(REPO_ROOT, path, "skipped-not-ours"))
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        actions.append(Action(REPO_ROOT, path, "removed"))
    return actions


def _source_for(path: Path, target: Path, mode: str) -> str | None:
    rel = path.relative_to(target)
    entries = USER_SCOPE_ENTRIES if mode == "user" else PROJECT_SCOPE_ENTRIES
    for src_rel, dst_rel in entries:
        if Path(dst_rel) == rel:
            return src_rel
    for src_dir_rel, dst_dir_rel, scopes in DIR_ENTRIES:
        if mode not in scopes:
            continue
        try:
            child_name = rel.relative_to(dst_dir_rel)
        except ValueError:
            continue
        return str(Path(src_dir_rel) / child_name)
    return None


def default_target(mode: str) -> Path:
    if mode == "user":
        return Path.home() / ".claude"
    return Path.cwd() / ".claude"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["user", "project"], default="user")
    parser.add_argument("--target", type=Path, default=None, help="Override the install target directory")
    parser.add_argument("--copy", action="store_true", help="Copy files instead of symlinking (default: symlink)")
    parser.add_argument("--force", action="store_true", help="Overwrite files that differ from this repo's version")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without changing anything")
    parser.add_argument("--uninstall", action="store_true", help="Remove what a prior run of this installer created")
    args = parser.parse_args(argv)

    target = args.target or default_target(args.mode)
    target = target.expanduser()

    if args.uninstall:
        actions = uninstall(target, args.mode)
    else:
        actions = install_file_entries(target, args.mode, use_copy=args.copy, force=args.force, dry_run=args.dry_run)
        actions += install_dir_entries(target, args.mode, use_copy=args.copy, force=args.force, dry_run=args.dry_run)

    for action in actions:
        print(action)

    skipped = [a for a in actions if a.kind == "skipped-exists"]
    if skipped:
        print(
            f"\n{len(skipped)} file(s) already exist with different content and were skipped. "
            "Re-run with --force to overwrite them, or resolve manually.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
