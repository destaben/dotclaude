import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check_review.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_review  # noqa: E402

GOOD = (
    "## Review of PR #9\n\n### bug-hunter\nNothing.\n\n### documenter\nNothing.\n\n"
    "Result: 0 findings (0 severe, 0 non-severe)\n"
)
# Paraphrase of the interim message posted on PR #9 (see issue #10).
PROVISIONAL = (
    "I'm waiting for the bug-hunter and documenter agents to finish. "
    "I'll write the combined review once both have reported."
)


class ValidateTests(unittest.TestCase):
    def test_finished_review_is_accepted(self):
        self.assertIsNone(check_review.validate(GOOD, "9"))

    def test_heading_may_carry_a_sha(self):
        text = GOOD.replace("#9", "#9 (08e77a7)")
        self.assertIsNone(check_review.validate(text, "9"))

    def test_provisional_message_without_heading_is_rejected(self):
        self.assertIsNotNone(check_review.validate(PROVISIONAL, "9"))

    def test_empty_and_none_are_rejected(self):
        self.assertIsNotNone(check_review.validate("", "9"))
        self.assertIsNotNone(check_review.validate(None, "9"))

    def test_heading_may_have_a_colon_suffix(self):
        self.assertIsNone(check_review.validate(GOOD.replace("#9", "#9: summary"), "9"))

    def test_heading_with_glued_suffix_is_rejected(self):
        self.assertIsNotNone(check_review.validate(GOOD.replace("#9", "#9abc"), "9"))

    def test_wrong_pr_number_is_rejected(self):
        self.assertIsNotNone(check_review.validate(GOOD, "90"))
        self.assertIsNotNone(check_review.validate(GOOD.replace("#9", "#90"), "9"))

    def test_missing_result_line_is_rejected(self):
        text = GOOD.rsplit("Result:", 1)[0]
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_result_line_must_be_last(self):
        self.assertIsNotNone(check_review.validate(GOOD + "trailing prose\n", "9"))

    def test_sentence_naming_an_agent_is_not_its_section(self):
        text = (
            "## Review of PR #9\n\nStill waiting for the documenter and "
            "the bug-hunter.\n\nResult: 0 findings (0 severe, 0 non-severe)\n"
        )
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_bold_or_spaced_agent_labels_are_accepted(self):
        bold = GOOD.replace("### bug-hunter", "**bug-hunter**").replace(
            "### documenter", "**Documenter**"
        )
        self.assertIsNone(check_review.validate(bold, "9"))
        spaced = GOOD.replace("### bug-hunter", "### Bug Hunter")
        self.assertIsNone(check_review.validate(spaced, "9"))

    def test_one_heading_naming_both_agents_is_rejected(self):
        text = (
            "## Review of PR #9\n\n### bug-hunter and documenter\n"
            "Still waiting.\n\nResult: 0 findings (0 severe, 0 non-severe)\n"
        )
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_hash_prefixed_body_line_is_not_a_heading(self):
        text = GOOD.replace("### documenter", "#12 documenter docs are stale")
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_formatted_heading_is_tolerated(self):
        self.assertIsNone(check_review.validate(GOOD.replace("## Review of PR #9", "**## Review of PR #9**"), "9"))

    def test_review_missing_an_agent_section_is_rejected(self):
        self.assertIsNotNone(check_review.validate(GOOD.replace("documenter", "docs"), "9"))
        self.assertIsNotNone(check_review.validate(GOOD.replace("bug-hunter", "bugs"), "9"))

    def test_result_line_formatting_is_tolerated(self):
        for last in (
            "**Result: 0 findings (0 severe, 0 non-severe)**",
            "`Result: 0 findings (0 severe, 0 non-severe)`",
            "Result: 0 findings (0 severe, 0 non-severe).  ",
        ):
            text = GOOD.replace("Result: 0 findings (0 severe, 0 non-severe)", last)
            self.assertIsNone(check_review.validate(text, "9"), last)

    def test_code_fenced_review_is_accepted(self):
        self.assertIsNone(check_review.validate("```markdown\n" + GOOD + "```\n", "9"))

    def test_noun_must_match_the_count(self):
        text = GOOD.replace(
            "Result: 0 findings (0 severe, 0 non-severe)",
            "Result: 2 finding (0 severe, 2 non-severe)",
        )
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_counts_must_add_up(self):
        text = GOOD.replace("0 findings (0 severe", "3 findings (1 severe")
        self.assertIsNotNone(check_review.validate(text, "9"))

    def test_singular_finding_and_nonzero_counts(self):
        text = GOOD.replace(
            "Result: 0 findings (0 severe, 0 non-severe)",
            "Result: 1 finding (0 severe, 1 non-severe)",
        )
        self.assertIsNone(check_review.validate(text, "9"))


class WorkflowContractTests(unittest.TestCase):
    """Cheap text-level guards on the workflow the validation depends on.

    They catch accidental edits to the gates, not inverted logic; behaviour
    needs a real action run (see docs/decisions/0002-cost-and-quota.md).
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / ".github" / "workflows" / "claude-pr-review.yml").read_text()

    def test_post_step_is_gated_on_review_and_check(self):
        self.assertIn("steps.review.outcome == 'success'", self.text)
        self.assertIn("steps.check.outcome != 'failure'", self.text)

    def test_retry_runs_only_on_an_incomplete_result(self):
        self.assertIn("steps.check.outputs.valid == 'false'", self.text)

    def test_post_step_uses_retry_output_only_when_retry_succeeded(self):
        self.assertIn('[ "$RETRY_OUTCOME" = "success" ]', self.text)
        self.assertIn('[ "$RETRY_OUTCOME" = "failure" ]', self.text)

    def test_prompt_names_both_required_marker_lines(self):
        self.assertIn("## Review of PR #", self.text)
        self.assertIn("Result: <total> findings", self.text)


class CliTests(unittest.TestCase):
    def run_cli(self, messages):
        with tempfile.TemporaryDirectory() as tmp:
            exec_file = Path(tmp) / "exec.json"
            out = Path(tmp) / "review.md"
            if messages is not None:
                exec_file.write_text(json.dumps(messages))
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(exec_file), "9", str(out)],
                capture_output=True,
                text=True,
            )
            return proc.returncode, out.read_text() if out.exists() else None

    @staticmethod
    def result(text, **kw):
        return {"type": "result", "subtype": "success", "is_error": False, "result": text, **kw}

    def test_posts_last_successful_result(self):
        code, body = self.run_cli([self.result(PROVISIONAL), self.result(GOOD)])
        self.assertEqual(code, 0)
        self.assertEqual(body, GOOD)

    def test_provisional_last_result_fails_and_writes_nothing(self):
        code, body = self.run_cli([self.result(GOOD), self.result(PROVISIONAL)])
        self.assertEqual(code, 3)
        self.assertIsNone(body)

    def test_error_results_are_ignored(self):
        err = self.result(GOOD, is_error=True)
        code, _ = self.run_cli([err])
        self.assertEqual(code, 3)

    def test_fenced_review_is_posted_without_the_fence(self):
        code, body = self.run_cli([self.result("```markdown\n" + GOOD + "```")])
        self.assertEqual(code, 0)
        self.assertEqual(body, GOOD)

    def test_missing_execution_file_fails(self):
        self.assertEqual(self.run_cli(None)[0], 3)

    def test_final_error_result_does_not_fall_back_to_earlier_success(self):
        code, body = self.run_cli([self.result(GOOD), self.result(GOOD, is_error=True)])
        self.assertEqual(code, 3)
        self.assertIsNone(body)

    def test_non_success_subtype_is_ignored(self):
        msg = self.result(GOOD, subtype="error_max_turns")
        self.assertEqual(self.run_cli([msg])[0], 3)

    def test_invalid_json_and_non_list_json_fail(self):
        for raw in ("not json", "42", '"text"'):
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "exec.json"
                f.write_text(raw)
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), str(f), "9", str(Path(tmp) / "o.md")],
                    capture_output=True,
                )
                self.assertEqual(proc.returncode, 3, raw)

    def test_single_result_object_is_accepted(self):
        self.assertEqual(self.run_cli(self.result(GOOD))[0], 0)

    def test_unwritable_output_exits_2_not_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "exec.json"
            f.write_text(json.dumps([self.result(GOOD)]))
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(f), "9", str(Path(tmp) / "no" / "o.md")],
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 2)

    def test_bad_usage_exits_2(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
