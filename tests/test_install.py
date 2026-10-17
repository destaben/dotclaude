import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import install  # noqa: E402


class InstallOneTest(unittest.TestCase):
    def test_symlinks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            src = REPO_ROOT / "CLAUDE.md"
            action = install.install_one(src, dst, use_copy=False, force=False, dry_run=False)
            self.assertEqual(action.kind, "linked")
            self.assertTrue(dst.is_symlink())
            self.assertEqual(dst.resolve(), src.resolve())

    def test_copies_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            src = REPO_ROOT / "CLAUDE.md"
            action = install.install_one(src, dst, use_copy=True, force=False, dry_run=False)
            self.assertEqual(action.kind, "copied")
            self.assertFalse(dst.is_symlink())
            self.assertEqual(dst.read_text(), src.read_text())

    def test_skips_existing_different_content_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            dst.write_text("pre-existing, unrelated content\n")
            src = REPO_ROOT / "CLAUDE.md"
            action = install.install_one(src, dst, use_copy=True, force=False, dry_run=False)
            self.assertEqual(action.kind, "skipped-exists")
            self.assertEqual(dst.read_text(), "pre-existing, unrelated content\n")

    def test_force_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            dst.write_text("pre-existing, unrelated content\n")
            src = REPO_ROOT / "CLAUDE.md"
            action = install.install_one(src, dst, use_copy=True, force=True, dry_run=False)
            self.assertEqual(action.kind, "copied")
            self.assertEqual(dst.read_text(), src.read_text())

    def test_already_installed_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            src = REPO_ROOT / "CLAUDE.md"
            install.install_one(src, dst, use_copy=True, force=False, dry_run=False)
            action = install.install_one(src, dst, use_copy=True, force=False, dry_run=False)
            self.assertEqual(action.kind, "already-installed")

    def test_dry_run_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "CLAUDE.md"
            src = REPO_ROOT / "CLAUDE.md"
            action = install.install_one(src, dst, use_copy=True, force=False, dry_run=True)
            self.assertEqual(action.kind, "would-copied")
            self.assertFalse(dst.exists())


class DirEntriesTest(unittest.TestCase):
    def test_installs_each_agent_individually_without_clobbering_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "agents").mkdir(parents=True)
            unrelated = target / "agents" / "my-own-agent.md"
            unrelated.write_text("not from dotclaude\n")

            actions = install.install_dir_entries(target, "user", use_copy=True, force=False, dry_run=False)

            self.assertTrue(any(a.kind == "copied" for a in actions))
            self.assertEqual(unrelated.read_text(), "not from dotclaude\n")
            self.assertTrue((target / "agents" / "planner.md").is_file())
            self.assertTrue((target / "skills" / "testing-mindset" / "SKILL.md").is_file())


class FileEntriesTest(unittest.TestCase):
    def test_user_scope_installs_templates_and_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install.install_file_entries(target, "user", use_copy=True, force=False, dry_run=False)

            self.assertTrue((target / "CLAUDE.md").is_file())
            self.assertTrue((target / "settings.json").is_file())
            self.assertTrue((target / "templates" / "pull_request_template.md").is_file())
            self.assertTrue((target / "dotclaude-scripts" / "scripts" / "session_cost.py").is_file())
            self.assertTrue((target / "dotclaude-scripts" / "config" / "pricing.json").is_file())

    def test_project_scope_installs_only_claude_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install.install_file_entries(target, "project", use_copy=True, force=False, dry_run=False)

            self.assertTrue((target / "CLAUDE.md").is_file())
            self.assertFalse((target / "templates").exists())
            self.assertFalse((target / "dotclaude-scripts").exists())


class UninstallTest(unittest.TestCase):
    def test_removes_unmodified_installed_files_but_not_edited_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install.install_file_entries(target, "user", use_copy=True, force=False, dry_run=False)
            install.install_dir_entries(target, "user", use_copy=True, force=False, dry_run=False)

            # Simulate the user hand-editing one installed file after the fact.
            (target / "settings.json").write_text('{"edited": true}')

            actions = install.uninstall(target, "user")
            kinds = {str(a.dst): a.kind for a in actions}

            self.assertEqual(kinds[str(target / "CLAUDE.md")], "removed")
            self.assertFalse((target / "CLAUDE.md").exists())
            self.assertEqual(kinds[str(target / "settings.json")], "skipped-not-ours")
            self.assertTrue((target / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
