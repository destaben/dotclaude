import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_repo  # noqa: E402


def build_minimal_valid_repo(root: Path) -> None:
    (root / ".claude" / "agents").mkdir(parents=True)
    (root / ".claude" / "commands").mkdir(parents=True)
    (root / ".claude" / "skills" / "demo-skill").mkdir(parents=True)

    (root / ".claude" / "agents" / "planner.md").write_text(
        "---\nname: planner\ndescription: plans things\n---\nBody.\n"
    )
    (root / ".claude" / "commands" / "plan.md").write_text(
        "---\ndescription: runs planner\n---\nBody.\n"
    )
    (root / ".claude" / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: a demo\n---\nBody.\n"
    )
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {}}))
    (root / "CLAUDE.md").write_text("\n".join(f"line {i}" for i in range(10)))
    (root / "README.md").write_text(
        "# Title\n\n<!-- pipeline:start -->\n```mermaid\nflowchart TD\n"
        "A[/plan/] --> B[planner]\n```\n<!-- pipeline:end -->\n"
    )


class ValidateRepoTest(unittest.TestCase):
    def test_minimal_valid_repo_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            errors = validate_repo.run_all_checks(root)
            self.assertEqual(errors, [])

    def test_hooks_key_in_settings_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("hooks" in e for e in errors))

    def test_claude_md_over_150_lines_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / "CLAUDE.md").write_text("\n".join(f"line {i}" for i in range(200)))
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("CLAUDE.md" in e and "150" in e for e in errors))

    def test_missing_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "agents" / "planner.md").write_text("No frontmatter here.\n")
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("missing frontmatter" in e for e in errors))

    def test_readme_missing_pipeline_markers_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / "README.md").write_text("# Title\n\nNo pipeline here.\n")
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("pipeline markers" in e for e in errors))

    def test_email_address_in_tracked_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / "CLAUDE.md").write_text("Contact: someone@example.com\n")
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("email address" in e for e in errors))

    def test_absolute_home_path_in_tracked_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / "CLAUDE.md").write_text("See /Users/alice/projects/secret for details.\n")
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("absolute home path" in e for e in errors))

    def test_placeholder_home_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / "CLAUDE.md").write_text("Install into /Users/you/.claude/ for user scope.\n")
            errors = validate_repo.run_all_checks(root)
            self.assertEqual(errors, [])

    def test_settings_local_json_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "settings.local.json").write_text(
                json.dumps({"email": "secret@example.com"})
            )
            errors = validate_repo.run_all_checks(root)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
