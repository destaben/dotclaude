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

    def _release_md(self, titles):
        body = "\n".join(f"{i}. **{t}.** Do it." for i, t in enumerate(titles, start=1))
        return "---\ndescription: release\n---\n" + body + "\n"

    def test_release_steps_in_order_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "commands" / "release.md").write_text(self._release_md(
                ["Full test suite", "Bug hunter", "Severity routing", "Documenter", "Commit and PR"]))
            (root / "README.md").write_text(
                "# T\n\n<!-- pipeline:start -->\n```mermaid\nflowchart TD\n"
                "A[/plan/] --> B[planner]\nA --> C[/release/]\n```\n<!-- pipeline:end -->\n")
            self.assertEqual(validate_repo.run_all_checks(root), [])

    def test_release_step_title_without_trailing_period_still_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            titles = ["Full test suite", "Bug hunter", "Severity routing", "Documenter", "Commit and PR"]
            body = "\n".join(f"{i}. **{t}** — do it." for i, t in enumerate(titles, start=1))
            (root / ".claude" / "commands" / "release.md").write_text("---\ndescription: r\n---\n" + body + "\n")
            (root / "README.md").write_text(
                "# T\n\n<!-- pipeline:start -->\n```mermaid\nflowchart TD\n"
                "A[/plan/] --> B[planner]\nA --> C[/release/]\n```\n<!-- pipeline:end -->\n")
            self.assertEqual(validate_repo.run_all_checks(root), [])

    def test_release_steps_reordered_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "commands" / "release.md").write_text(self._release_md(
                ["Full test suite", "Documenter", "Bug hunter", "Severity routing", "Commit and PR"]))
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("release.md: steps must be" in e for e in errors))

    def test_release_step_missing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "commands" / "release.md").write_text(self._release_md(
                ["Full test suite", "Bug hunter", "Severity routing", "Commit and PR"]))
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("release.md: steps must be" in e for e in errors))

    def test_repo_without_release_command_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            self.assertEqual(validate_repo.run_all_checks(root), [])

    def test_this_repo_phrase_in_agent_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "agents" / "planner.md").write_text(
                "---\nname: planner\ndescription: plans things\n---\n"
                "This repo always writes plans to docs/plans/.\n"
            )
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("repo-specific reference" in e for e in errors))

    def test_docs_decisions_reference_in_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "skills" / "demo-skill" / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: a demo\n---\n"
                "See docs/decisions/0001-example.md for why.\n"
            )
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("docs/decisions/" in e for e in errors))

    def test_this_repo_phrase_in_pr_template_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".github").mkdir(parents=True)
            (root / ".github" / "pull_request_template.md").write_text(
                "Link a decision record from this repo if relevant.\n"
            )
            errors = validate_repo.run_all_checks(root)
            self.assertTrue(any("pull_request_template.md" in e for e in errors))

    def test_generic_agent_body_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_minimal_valid_repo(root)
            (root / ".claude" / "agents" / "planner.md").write_text(
                "---\nname: planner\ndescription: plans things\n---\n"
                "Write the plan to the current project's plans folder if it has one.\n"
            )
            errors = validate_repo.run_all_checks(root)
            self.assertEqual(errors, [])

    def test_shipped_council_files_are_valid_and_agnostic(self):
        names = [
            "council-contrarian", "council-first-principles", "council-visionary",
            "council-outsider", "council-executor", "council-chair",
        ]
        agents_dir = REPO_ROOT / ".claude" / "agents"
        for name in names:
            text = (agents_dir / f"{name}.md").read_text(encoding="utf-8")
            fm = text.split("---", 2)[1]
            self.assertIn(f"name: {name}", fm)
            self.assertRegex(fm, r"model: (haiku|sonnet)")
            self.assertRegex(fm, r"effort: (low|medium)")
            self.assertNotIn("Edit", fm)
            self.assertNotIn("Write", fm)
            self.assertNotIn("Bash", fm)
        self.assertEqual(validate_repo.run_all_checks(REPO_ROOT), [])

    def test_outsider_has_no_search_tools(self):
        text = (REPO_ROOT / ".claude" / "agents" / "council-outsider.md").read_text(encoding="utf-8")
        tools = [l for l in text.split("---", 2)[1].splitlines() if l.startswith("tools:")]
        self.assertEqual(tools, ["tools: Read"])

    def test_council_spawn_budget_matches_fallback(self):
        budgets = json.loads((REPO_ROOT / "config" / "budgets.json").read_text(encoding="utf-8"))
        n = budgets["subagent_spawn_warning"]
        self.assertGreaterEqual(n, 6)  # a full council is 6 calls
        skill = (REPO_ROOT / ".claude" / "skills" / "token-budget" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"{n} subagent spawns", skill)

    def test_shipped_files_reference_skills_by_name_not_path(self):
        for sub in ("agents", "commands"):
            for path in (REPO_ROOT / ".claude" / sub).glob("*.md"):
                self.assertNotIn(".claude/skills/", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
