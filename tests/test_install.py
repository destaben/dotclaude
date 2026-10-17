import json
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
            self.assertFalse((target / "settings.json").exists())  # merged separately, not linked/copied
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


class MergeSettingsJsonTest(unittest.TestCase):
    def _src(self):
        return REPO_ROOT / ".claude" / "settings.json"

    def test_creates_file_with_permissions_statusline_model_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            action = install.merge_settings_json(self._src(), dst, dry_run=False)
            self.assertEqual(action.kind, "merged")
            data = json.loads(dst.read_text())
            self.assertIn("permissions", data)
            self.assertIn("statusLine", data)
            self.assertIn("model", data)

    def test_preserves_foreign_keys_like_hooks_and_theme(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            dst.write_text(json.dumps({
                "hooks": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "/some/other/hook.sh"}]}]},
                "theme": "dark",
            }))
            install.merge_settings_json(self._src(), dst, dry_run=False)
            data = json.loads(dst.read_text())
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "/some/other/hook.sh")
            self.assertIn("permissions", data)

    def test_does_not_overwrite_existing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            dst.write_text(json.dumps({"model": "claude-sonnet-5"}))
            install.merge_settings_json(self._src(), dst, dry_run=False)
            data = json.loads(dst.read_text())
            self.assertEqual(data["model"], "claude-sonnet-5")

    def test_does_not_overwrite_existing_statusline_but_notes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            dst.write_text(json.dumps({"statusLine": {"type": "command", "command": "my-own-statusline.sh"}}))
            action = install.merge_settings_json(self._src(), dst, dry_run=False)
            data = json.loads(dst.read_text())
            self.assertEqual(data["statusLine"]["command"], "my-own-statusline.sh")
            self.assertTrue(any("statusLine" in note for note in action.notes))

    def test_unions_permission_lists_without_duplicating_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            dst.write_text(json.dumps({"permissions": {"allow": ["Read", "Bash(my-own-tool:*)"]}}))
            install.merge_settings_json(self._src(), dst, dry_run=False)
            data = json.loads(dst.read_text())
            self.assertIn("Bash(my-own-tool:*)", data["permissions"]["allow"])
            self.assertEqual(data["permissions"]["allow"].count("Read"), 1)
            self.assertIn("Edit", data["permissions"]["allow"])  # from dotclaude's defaults

    def test_is_idempotent_on_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            install.merge_settings_json(self._src(), dst, dry_run=False)
            first = dst.read_text()
            action = install.merge_settings_json(self._src(), dst, dry_run=False)
            self.assertEqual(action.kind, "unchanged")
            self.assertEqual(dst.read_text(), first)

    def test_dry_run_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings.json"
            action = install.merge_settings_json(self._src(), dst, dry_run=True)
            self.assertEqual(action.kind, "would-merge")
            self.assertFalse(dst.exists())

    def test_project_scope_does_not_install_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            actions = install.install_settings_json(target, "project", dry_run=False)
            self.assertEqual(actions, [])
            self.assertFalse((target / "settings.json").exists())


class UninstallTest(unittest.TestCase):
    def test_removes_unmodified_installed_files_but_not_edited_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install.install_file_entries(target, "user", use_copy=True, force=False, dry_run=False)
            install.install_dir_entries(target, "user", use_copy=True, force=False, dry_run=False)

            # Simulate the user hand-editing one installed file after the fact.
            (target / "CLAUDE.md").write_text("edited by hand\n")

            actions = install.uninstall(target, "user")
            kinds = {str(a.dst): a.kind for a in actions}

            self.assertEqual(kinds[str(target / "CLAUDE.md")], "skipped-not-ours")
            self.assertTrue((target / "CLAUDE.md").exists())
            self.assertEqual(kinds[str(target / "templates" / "pull_request_template.md")], "removed")

    def test_never_touches_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install.install_settings_json(target, "user", dry_run=False)
            before = (target / "settings.json").read_text()

            actions = install.uninstall(target, "user")

            self.assertEqual((target / "settings.json").read_text(), before)
            left_as_is = [a for a in actions if str(a.dst) == str(target / "settings.json")]
            self.assertEqual(len(left_as_is), 1)
            self.assertEqual(left_as_is[0].kind, "left-as-is")


if __name__ == "__main__":
    unittest.main()
