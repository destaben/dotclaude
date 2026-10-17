import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import session_cost  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_transcript.jsonl"


class ParseUsageByModelTest(unittest.TestCase):
    def test_dedupes_by_message_id_and_sums_per_model(self):
        usage = session_cost.parse_usage_by_model(FIXTURE)

        self.assertEqual(set(usage), {"claude-sonnet-5-5", "claude-haiku-5-5"})

        sonnet = usage["claude-sonnet-5-5"]
        # msg_001 counted once despite appearing twice, plus msg_002 once.
        self.assertEqual(sonnet["input_tokens"], 10 + 5)
        self.assertEqual(sonnet["cache_creation_input_tokens"], 100 + 0)
        self.assertEqual(sonnet["cache_read_input_tokens"], 200 + 300)
        self.assertEqual(sonnet["output_tokens"], 50 + 20)

        haiku = usage["claude-haiku-5-5"]
        self.assertEqual(haiku["input_tokens"], 1)
        self.assertEqual(haiku["output_tokens"], 5)


class EstimateCostTest(unittest.TestCase):
    def test_known_pricing_computes_cost(self):
        totals = {
            "input_tokens": 1_000_000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 1_000_000,
        }
        pricing = {"models": {"m": {"input_per_mtok": 3, "output_per_mtok": 15}}}
        self.assertAlmostEqual(session_cost.estimate_cost("m", totals, pricing), 18.0)

    def test_todo_pricing_returns_none(self):
        totals = {
            "input_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 1,
        }
        pricing = {"models": {"m": {"input_per_mtok": "TODO", "output_per_mtok": "TODO"}}}
        self.assertIsNone(session_cost.estimate_cost("m", totals, pricing))

    def test_unknown_model_returns_none(self):
        totals = {
            "input_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 1,
        }
        self.assertIsNone(session_cost.estimate_cost("unknown-model", totals, {"models": {}}))


class FormatTest(unittest.TestCase):
    def test_markdown_table_marks_unknown_pricing_as_todo(self):
        usage = {"m": {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}}
        pricing = {"models": {}}
        table = session_cost.format_markdown_table(usage, pricing)
        self.assertIn("TODO", table)
        self.assertIn("Pro/Max", table)

    def test_oneline_flags_unknown_pricing(self):
        usage = {"m": {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}}
        pricing = {"models": {}}
        line = session_cost.format_oneline(usage, pricing)
        self.assertIn("+", line)
        self.assertIn("1 model(s)", line)


class MainIntegrationTest(unittest.TestCase):
    def test_main_runs_against_fixture_with_real_pricing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pricing_path = Path(tmp) / "pricing.json"
            pricing_path.write_text(json.dumps({
                "models": {
                    "claude-sonnet-5-5": {"input_per_mtok": 3, "output_per_mtok": 15},
                    "claude-haiku-5-5": {"input_per_mtok": 0.8, "output_per_mtok": 4},
                }
            }))
            exit_code = session_cost.main([
                "--transcript", str(FIXTURE),
                "--pricing", str(pricing_path),
            ])
            self.assertEqual(exit_code, 0)

    def test_main_reports_missing_transcript(self):
        exit_code = session_cost.main(["--transcript", "/nonexistent/path.jsonl"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
