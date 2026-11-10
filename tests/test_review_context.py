import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_review  # noqa: E402
import review_context as rc  # noqa: E402

SHA1 = "a" * 40
SHA2 = "b" * 40
BOT = {"login": "github-actions[bot]", "type": "Bot"}
OWNER = {"login": "owner", "type": "User"}

REVIEW = (
    "## Review of PR #9\n\nNew: 1 · Open: 1 · Fixed: 0 · Justified: 1\n\n### bug-hunter\nx\n\n"
    "### documenter\nx\n\n### Ledger\n"
    "- F-probe.sh-ssh-no-n-probe | open | probe.sh:12 ssh reads stdin\n"
    "- F-skill.md-ssh-copy-id-setup | justified (https://x/y) | SKILL.md:40 setup\n"
    "- F-print-state.sh-float-progress | fixed (abc1234) | print-state.sh:9\n"
    "- F-old | withdrawn | gone\n\n"
    "Result: 2 findings (1 severe, 1 non-severe)\n\n" + rc.make_marker(SHA1) + "\n"
)


def comment(body, user=BOT, assoc="NONE"):
    return {"body": body, "user": user, "author_association": assoc}


class LedgerTests(unittest.TestCase):
    def test_all_four_statuses_parse_with_their_ids(self):
        ledger = rc.parse_ledger(REVIEW)
        self.assertEqual(
            {k: v[0] for k, v in ledger.items()},
            {
                "F-probe.sh-ssh-no-n-probe": "open",
                "F-skill.md-ssh-copy-id-setup": "justified",
                "F-print-state.sh-float-progress": "fixed",
                "F-old": "withdrawn",
            },
        )

    def test_text_without_ledger_lines_is_empty(self):
        self.assertEqual(rc.parse_ledger("## Review\nnothing\n- a bullet\n"), {})

    def test_ids_with_hyphens_survive_a_dash_separator(self):
        ledger = rc.parse_ledger("- F-a-b-c - open - file:1 claim")
        self.assertEqual(list(ledger), ["F-a-b-c"])


class PreviousStateTests(unittest.TestCase):
    def test_newest_stamped_bot_review_wins(self):
        newer = REVIEW.replace(SHA1, SHA2).replace("F-old | withdrawn", "F-new | open")
        sha, ledger = rc.previous_state([comment(REVIEW), comment("chat"), comment(newer)])
        self.assertEqual(sha, SHA2)
        self.assertIn("F-new", ledger)

    def test_no_review_means_first_pass(self):
        self.assertEqual(rc.previous_state([comment("hello", OWNER)]), (None, {}))

    def test_a_human_cannot_forge_a_review(self):
        self.assertEqual(rc.previous_state([comment(REVIEW, OWNER, "OWNER")]), (None, {}))

    def test_unstamped_review_is_not_a_baseline(self):
        unstamped = REVIEW.replace(rc.make_marker(SHA1), "")
        self.assertEqual(rc.previous_state([comment(unstamped)]), (None, {}))


class NotesTests(unittest.TestCase):
    def test_pr_body_and_trusted_comments_count_untrusted_and_bot_do_not(self):
        notes = rc.author_notes(
            "Design notes: ssh -n is deliberate",
            [
                comment("Justified: ssh -n", OWNER, "OWNER"),
                comment("drive-by", {"login": "rando", "type": "User"}, "NONE"),
                comment(REVIEW, BOT, "NONE"),
            ],
        )
        titles = [t for t, _ in notes]
        self.assertEqual(len(notes), 2)
        self.assertEqual(titles[0], "PR description")
        self.assertIn("owner", titles[1])


class RenderTests(unittest.TestCase):
    def test_first_pass_says_so_and_has_no_diff(self):
        text = rc.render("9", SHA2, None, {}, [], None)
        self.assertIn("FIRST pass", text)
        self.assertIn("(empty)", text)
        self.assertNotIn("INCREMENTAL", text)

    def test_incremental_pass_carries_ledger_notes_and_diff(self):
        text = rc.render("9", SHA2, SHA1, rc.parse_ledger(REVIEW), [("PR description", "why")], "+x\n")
        self.assertIn(f"covered commit: {SHA1}", text)
        self.assertIn("INCREMENTAL", text)
        self.assertIn("- F-old | withdrawn", text)
        self.assertIn("why", text)
        self.assertIn("+x", text)

    def test_missing_history_asks_for_the_full_diff(self):
        text = rc.render("9", SHA2, SHA1, {}, [], None, "not in the history")
        self.assertIn("review the full `gh pr diff`", text)

    def test_huge_diff_is_cut(self):
        text = rc.render("9", SHA2, SHA1, {}, [], "x" * (rc.DIFF_LIMIT + 10))
        self.assertIn("cut at", text)


class StampTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, "-I", str(SCRIPTS / "review_context.py"), *args],
                              capture_output=True, text=True)

    def test_stamp_appends_a_marker_that_the_next_pass_can_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "review.md"
            f.write_text(REVIEW.replace(rc.make_marker(SHA1), ""))
            self.assertEqual(self.run_script("stamp", SHA2, str(f)).returncode, 0)
            self.assertEqual(rc.previous_state([comment(f.read_text())])[0], SHA2)

    def test_stamp_ignores_a_malformed_sha(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "review.md"
            f.write_text("x\n")
            self.assertEqual(self.run_script("stamp", "nonsense", str(f)).returncode, 0)
            self.assertEqual(f.read_text(), "x\n")

    def test_bad_usage_exits_2(self):
        self.assertEqual(self.run_script().returncode, 2)

    def test_stamped_review_still_passes_the_gate_before_stamping(self):
        # The gate runs on the unstamped message; the marker is appended after it.
        self.assertIsNone(check_review.validate(REVIEW.replace(rc.make_marker(SHA1), ""), "9"))


class GitDiffTests(unittest.TestCase):
    def test_unknown_commit_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            cwd = Path.cwd()
            try:
                import os
                os.chdir(d)
                diff, error = rc.git_diff(SHA1, SHA2)
            finally:
                os.chdir(cwd)
            self.assertIsNone(diff)
            self.assertIn("history", error)


if __name__ == "__main__":
    unittest.main()
