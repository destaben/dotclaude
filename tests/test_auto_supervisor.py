"""Behavior tests for the auto skill (.claude/skills/auto/scripts/auto_supervisor.py).

`claude` is a stub (the boundary we do not own): a script that reads a per-call behavior list from a
file, logs each call, and either completes a stage, prints a stubbed usage-limit message with a short
reset time, fails, or tampers with the repo during a "pause". git is real, on a temp repo.

Run: python3 -m unittest tests/test_auto_supervisor.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".claude" / "skills" / "auto" / "scripts" / "auto_supervisor.py"

STUB = r'''
import json, os, subprocess, sys, time
d = os.environ["STUB_DIR"]
log = open(os.path.join(d, "calls.log"), "a")
prompt = sys.argv[sys.argv.index("-p") + 1]
stage = prompt.split("Stage: ")[1].split(".")[0]
log.write(json.dumps({"stage": stage, "args": sys.argv[1:]}) + "\n"); log.close()
plan = json.load(open(os.path.join(d, "plan.json")))
n = sum(1 for _ in open(os.path.join(d, "calls.log"))) - 1
act = plan[n] if n < len(plan) else "ok"
if act.startswith("limit:"):
    open("partial.txt", "w").write("half done")
    print(act[6:].replace("{reset}", str(int(time.time()) + 2)))
    sys.exit(1)
if act.startswith("quote:"):  # a failing stage that merely quotes limit wording, then the usual failure summary
    print("AssertionError: expected %r" % act[6:].replace("{reset}", str(int(time.time()) + 2)))
    print("1 failed, 3 passed")
    sys.exit(1)
if act.startswith("longlimit0:"):  # exit 0, a long progress summary, then the limit line last
    print("\n".join("progress line %d" % i for i in range(8)))
    print(act[11:].replace("{reset}", str(int(time.time()) + 2)))
    sys.exit(0)
if act.startswith("limiterr:"):  # the limit sentence on stdout, then unrelated noise on stderr, exit 0
    print(act[9:].replace("{reset}", str(int(time.time()) + 2)))
    sys.stderr.write("(node) ExperimentalWarning: something unrelated\n")
    sys.exit(0)
if act.startswith("limittail:"):  # the limit sentence, then a trailing hint line, exit 0
    print(act[10:].replace("{reset}", str(int(time.time()) + 2)))
    print("Run /usage for details.")
    sys.exit(0)
if act.startswith("prose0:"):  # a successful stage whose last line is prose that merely mentions the wording
    print("AUTO-STAGE-RESULT: ok"); print(act[7:]); sys.exit(0)
if act.startswith("limit0:"):
    print(act[7:].replace("{reset}", str(int(time.time()) + 2)))
    sys.exit(0)
if act == "tamper":  # limit now; the notifier switches branches while the run waits
    open(os.path.join(d, "tamper"), "w").write(os.getcwd())
    print("Claude usage limit reached|%d" % (int(time.time()) + 1)); sys.exit(1)
if act == "fail":
    print("error: tests do not pass"); sys.exit(1)
if act == "silent":  # exits 0 but never reports success
    print("I stopped as instructed."); sys.exit(0)
if act.startswith("blocked:"):
    print("AUTO-STAGE-RESULT: blocked " + act[8:]); sys.exit(0)
open(stage + ".txt", "w").write("x")
print("done.\nAUTO-STAGE-RESULT: ok")
'''


def load_module():
    spec = importlib.util.spec_from_file_location("auto_supervisor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo, self.stub = t / "repo", t / "stub"
        self.repo.mkdir(); self.stub.mkdir()
        (self.stub / "claude_stub.py").write_text(STUB)
        (self.stub / "notify.py").write_text(
            "import sys,os,subprocess\nd=os.environ['STUB_DIR']\nopen(os.path.join(d,'notes.log'),'a').write(sys.argv[1]+'\\n')\n"
            "t=os.path.join(d,'tamper')\nif sys.argv[1]=='pause' and os.path.exists(t):\n"
            "    subprocess.run(['git','-C',open(t).read(),'checkout','-q','-b','other'])\n")
        self.plan_file = t / "plan.md"
        self.plan_file.write_text("1. do the thing\n")
        self.env = {**os.environ, "STUB_DIR": str(self.stub),
                    "AUTO_CLAUDE_BIN": f"{sys.executable} {self.stub / 'claude_stub.py'}"}
        self.env.pop("AUTO_NOTIFY_CMD", None)
        self.env.pop("AUTO_MAX_BUDGET_USD", None)
        for c in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"],
                  ["commit", "-q", "--allow-empty", "-m", "init"], ["checkout", "-q", "-b", "feat/x"]):
            subprocess.run(["git", "-C", str(self.repo), *c], check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, behaviors):
        (self.stub / "plan.json").write_text(json.dumps(behaviors))

    def sup(self, *args, notify=False):
        env = dict(self.env)
        if notify:
            env["AUTO_NOTIFY_CMD"] = f"{sys.executable} {self.stub / 'notify.py'}"
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(self.repo)],
                              capture_output=True, text=True, env=env, timeout=60)

    def start(self, *extra, **kw):
        return self.sup("start", "--task", "demo", "--plan-file", str(self.plan_file), "--margin-seconds", "0", *extra, **kw)

    def calls(self):
        p = self.stub / "calls.log"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def checkpoint(self):
        files = list((self.repo / ".git" / "auto").glob("auto-*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text())


class TestLimitPauseResume(Base):
    def test_limit_pauses_waits_resumes_and_completes_without_repeating_stages(self):
        self.script(["ok", "limit:Claude usage limit reached|{reset}", "ok", "ok"])
        r = self.start(notify=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        cp = self.checkpoint()
        self.assertGreater(cp["pauses"][0]["wait_seconds"], 0)
        self.assertGreaterEqual(time.time(), cp["reset_at"])  # it waited until the reset had passed
        self.assertEqual([c["stage"] for c in self.calls()],
                         ["implement", "scoped-tests", "scoped-tests", "release"])  # completed stage not repeated
        cp = self.checkpoint()
        self.assertEqual((cp["status"], cp["resumes"], len(cp["pauses"])), ("done", 1, 1))
        self.assertEqual((self.stub / "notes.log").read_text().split(), ["start", "pause", "resume", "done"])
        self.assertIn("usage-limit pauses: 1", r.stdout)

    def test_checkpoint_is_not_version_controlled(self):
        self.script(["ok", "ok", "ok"])
        self.assertEqual(self.start().returncode, 0)
        # untracked work files exist, but nothing from the checkpoint shows up in git
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertNotIn("auto", status)
        self.assertTrue(any((self.repo / ".git" / "auto").glob("*.json")))

    def test_limit_is_not_a_failure_but_a_task_error_is_not_retried(self):
        self.script(["fail"])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.checkpoint()["resumes"], 0)
        self.assertIn("resume with", r.stdout)


class TestLimits(Base):
    def test_reset_beyond_max_wait_stops_and_manual_resume_completes(self):
        self.script(["limit:Claude usage limit reached|{reset}"])
        r = self.start("--max-wait-hours", "0")  # reset is ~2s away: over a zero cap
        self.assertEqual(r.returncode, 2)
        self.assertIn("maximum wait", r.stdout)
        self.assertEqual(self.checkpoint()["status"], "stopped")
        r = self.sup("resume", "--max-wait-hours", "6", "--margin-seconds", "0")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["status"], "done")

    def test_max_resumes_stops_a_misdetected_limit_loop(self):
        self.script(["limit:Claude usage limit reached|{reset}"] * 10)
        r = self.start("--max-resumes", "2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("maximum", r.stdout)
        self.assertEqual(len(self.calls()), 3)  # first try plus two resumes, then stop
        self.assertEqual(self.checkpoint()["resumes"], 2)

    def test_limit_with_unknown_window_and_no_reset_stops(self):
        self.script(["limit:You've hit your limit, resets Fri 9am"])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(self.calls()), 1)

    def test_weekly_limit_without_readable_reset_stops(self):
        self.script(["limit:You have hit your weekly limit."])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertIn("weekly", r.stdout)
        self.assertEqual(len(self.calls()), 1)

    def test_five_hour_limit_without_readable_reset_over_the_cap_stops(self):
        self.script(["limit:Session limit reached."])
        r = self.start("--fallback-wait-minutes", "400", "--max-wait-hours", "6")
        self.assertEqual(r.returncode, 2)  # 400 min > 6h cap
        self.assertIn("maximum wait", r.stdout)

    def test_five_hour_fallback_wait_is_used_when_within_cap(self):
        self.script(["limit:Session limit reached.", "ok", "ok", "ok"])
        r = self.start("--fallback-wait-minutes", "0.05", "--max-wait-hours", "6")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        cp = self.checkpoint()
        self.assertEqual(cp["reset_source"], "fallback")
        self.assertEqual(cp["pauses"][0]["wait_seconds"], 3)  # 0.05 min, no margin

    def test_missing_claude_binary_stops_cleanly_with_resume_hint(self):
        self.env["AUTO_CLAUDE_BIN"] = "/nonexistent/claude"
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertIn("resume with", r.stdout)


class TestReverify(Base):
    def test_branch_change_during_pause_stops_the_run(self):
        self.script(["tamper"])
        r = self.start(notify=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("branch", r.stdout)
        self.assertEqual(len(self.calls()), 1)

    def test_refuses_to_start_on_main(self):
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "main"], check=True)
        self.script([])
        r = self.start()
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])

    def test_unexpected_commit_or_edit_on_resume_stops(self):
        self.script(["limit:Claude usage limit reached|{reset}"])
        r = self.start("--max-wait-hours", "0")
        self.assertEqual(r.returncode, 2)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "sneaky"], check=True)
        r = self.sup("resume", "--margin-seconds", "0")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unexpected commits", r.stdout)

    def test_working_tree_edit_while_away_stops_on_resume(self):
        self.script(["limit:Claude usage limit reached|{reset}"])
        self.assertEqual(self.start("--max-wait-hours", "0").returncode, 2)
        (self.repo / "partial.txt").write_text("changed while away")
        r = self.sup("resume", "--margin-seconds", "0")
        self.assertEqual(r.returncode, 2)
        self.assertIn("working tree", r.stdout)

    def test_dirty_tree_is_refused_at_start(self):
        (self.repo / "mine.txt").write_text("unrelated work")
        self.script([])
        self.assertEqual(self.start().returncode, 3)
        self.assertEqual(self.calls(), [])

    def test_killed_mid_stage_can_be_resumed(self):
        self.script(["ok"])
        self.assertEqual(self.start("--max-wait-hours", "0").returncode, 0)
        cp_path = next((self.repo / ".git" / "auto").glob("auto-*.json"))
        cp = json.loads(cp_path.read_text())
        cp.update(status="running", completed=["implement"])  # as if killed during scoped-tests
        cp_path.write_text(json.dumps(cp))
        (self.repo / "half.txt").write_text("partial edits")
        self.assertEqual(self.sup("resume", "--state", str(cp_path)).returncode, 0)

    def test_empty_plan_is_refused(self):
        self.plan_file.write_text("  \n")
        self.script([])
        self.assertEqual(self.start().returncode, 3)


class TestInvocationAndNotify(Base):
    def test_limit_message_with_exit_zero_is_still_a_pause(self):
        self.script(["limit0:Claude usage limit reached|{reset}", "ok", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 1)

    def test_claude_is_invoked_plainly(self):
        self.script(["ok", "ok", "ok"])
        self.assertEqual(self.start().returncode, 0)
        for c in self.calls():
            for bad in ("--bare", "--dangerously-skip-permissions"):
                self.assertNotIn(bad, c["args"])
            self.assertNotIn("--max-budget-usd", c["args"])
            self.assertEqual(c["args"][0], "-p")

    def test_failure_that_quotes_limit_wording_is_not_a_pause(self):
        self.script(["quote:Claude usage limit reached|{reset}"])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(self.calls()), 1)
        cp = self.checkpoint()
        self.assertEqual((cp["resumes"], cp["pauses"]), (0, []))

    def test_limit_line_after_long_output_with_exit_zero_is_a_pause(self):
        self.script(["longlimit0:Claude usage limit reached|{reset}", "ok", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 1)
        self.assertEqual(self.calls()[0]["stage"], self.calls()[1]["stage"])  # same stage re-run, not skipped

    def test_successful_stage_ending_in_prose_about_limits_is_not_a_pause(self):
        self.script(["prose0:Added usage limit reached detection; PR opened.", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 0)
        self.assertEqual(len(self.calls()), 3)

    def test_limit_on_stdout_followed_by_stderr_noise_is_still_a_pause(self):
        self.script(["limiterr:Claude usage limit reached|{reset}", "ok", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 1)
        self.assertEqual(self.calls()[0]["stage"], self.calls()[1]["stage"])

    def test_exit_zero_without_the_success_marker_stops_the_run(self):
        self.script(["ok", "silent"])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertEqual([c["stage"] for c in self.calls()], ["implement", "scoped-tests"])
        self.assertEqual(self.checkpoint()["completed"], ["implement"])
        self.assertIn("did not report success", r.stdout)

    def test_a_blocked_stage_report_stops_the_run_and_shows_the_reason(self):
        self.script(["ok", "blocked:2 tests still fail"])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.checkpoint()["completed"], ["implement"])
        self.assertIn("2 tests still fail", r.stdout)

    def test_corrupt_checkpoint_is_a_refusal(self):
        self.script([])
        d = self.repo / ".git" / "auto"
        d.mkdir(parents=True)
        (d / "auto-bad.json").write_text('{"version": 1}')
        self.assertEqual(self.sup("resume").returncode, 3)

    def test_limit_sentence_followed_by_a_hint_line_is_still_a_pause(self):
        self.script(["limittail:Claude usage limit reached|{reset}", "ok", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 1)
        self.assertEqual(self.calls()[0]["stage"], self.calls()[1]["stage"])

    def test_prose_that_starts_with_the_limit_words_is_not_a_pause(self):
        self.script(["prose0:Usage limit reached handling is now in place.", "ok", "ok"])
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.checkpoint()["resumes"], 0)

    def test_resume_without_state_prefers_an_unfinished_run_over_a_newer_finished_one(self):
        self.script(["limit:Claude usage limit reached|{reset}"])
        self.assertEqual(self.start("--max-wait-hours", "0").returncode, 2)
        d = self.repo / ".git" / "auto"
        stopped = next(d.glob("auto-*.json"))
        done = json.loads(stopped.read_text())
        done.update(status="done", state_file=str(d / "auto-zzzzzzzz.json"))
        (d / "auto-zzzzzzzz.json").write_text(json.dumps(done))  # newer mtime
        r = self.sup("resume", "--margin-seconds", "0")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(stopped.read_text())["status"], "done")

    def test_budget_cap_is_passed_only_when_configured(self):
        self.env["AUTO_MAX_BUDGET_USD"] = "5"
        self.script(["ok", "ok", "ok"])
        self.assertEqual(self.start().returncode, 0)
        self.assertIn("--max-budget-usd", self.calls()[0]["args"])

    def test_notification_is_a_noop_by_default(self):
        self.script(["ok", "ok", "ok"])
        self.assertEqual(self.start().returncode, 0)
        self.assertFalse((self.stub / "notes.log").exists())

    def test_broken_notifier_does_not_break_the_run(self):
        self.env["AUTO_NOTIFY_CMD"] = "/nonexistent/notifier"
        self.script(["ok", "ok", "ok"])
        self.assertEqual(self.start().returncode, 0)


class TestSnapshot(Base):
    def setUp(self):
        super().setUp()
        self.m = load_module()

    def test_edit_to_non_ascii_untracked_file_changes_the_fingerprint(self):
        f = self.repo / "notes-\u00e9.txt"
        f.write_text("one")
        before = self.m.snapshot(self.repo)["tree"]
        f.write_text("two")
        self.assertNotEqual(before, self.m.snapshot(self.repo)["tree"])

    def test_untracked_file_with_a_leading_space_can_be_fingerprinted(self):
        f = self.repo / " lead.txt"
        f.write_text("one")
        before = self.m.snapshot(self.repo)["tree"]
        f.write_text("two")
        self.assertNotEqual(before, self.m.snapshot(self.repo)["tree"])

    def test_replaced_tracked_binary_changes_the_fingerprint(self):
        b = self.repo / "logo.bin"
        b.write_bytes(b"\x00\x01")
        subprocess.run(["git", "-C", str(self.repo), "add", "logo.bin"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "bin"], check=True)
        before = self.m.snapshot(self.repo)["tree"]
        b.write_bytes(b"\x00\x02")
        self.assertNotEqual(before, self.m.snapshot(self.repo)["tree"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
    def test_unhashable_file_fails_closed(self):
        f = self.repo / "secret.txt"
        f.write_text("x")
        f.chmod(0)
        try:
            with self.assertRaises(self.m.Stop):
                self.m.snapshot(self.repo)
        finally:
            f.chmod(0o600)


class TestParseReset(unittest.TestCase):
    def setUp(self):
        self.m = load_module()
        self.now = 1_800_000_000.0

    def test_epoch_form(self):
        self.assertEqual(self.m.parse_reset("Claude AI usage limit reached|1800003600", self.now), 1800003600)

    def test_relative_form(self):
        self.assertEqual(self.m.parse_reset("Your limit resets in 2 hours 30 minutes", self.now), self.now + 9000)

    def test_clock_form_is_in_the_future(self):
        got = self.m.parse_reset("limit reached, resets at 3pm", self.now)
        self.assertGreater(got, self.now)
        self.assertLessEqual(got - self.now, 86400)

    def test_a_duration_is_not_a_clock_time(self):
        self.assertIsNone(self.m.parse_reset("Resets 3 hours after your first message.", self.now))

    def test_two_digit_duration_is_not_a_clock_time(self):
        self.assertIsNone(self.m.parse_reset("Resets 12 hours after your first message.", self.now))

    def test_reset_is_read_from_the_limit_block_only(self):
        out = "your plan resets in 3 hours\nworking...\nSession limit reached."
        info = self.m.classify(out)
        self.assertEqual(info["block"], "Session limit reached.")
        self.assertIsNone(self.m.parse_reset(info["block"], self.now))  # the earlier line must not leak in

    def test_unreadable_is_none(self):
        self.assertIsNone(self.m.parse_reset("limit reached, try later", self.now))

    def test_classify_requires_the_limit_sentence_at_the_start_of_the_last_line(self):
        self.assertIsNone(self.m.classify("Added usage limit reached detection; PR opened."))
        self.assertIsNone(self.m.classify("Usage limit reached handling is now in place."))
        self.assertIsNone(self.m.classify("Limit reached. Stopping."))
        info = self.m.classify("Claude usage limit reached|1800003600\nRun /usage for details.")
        self.assertEqual(self.m.parse_reset(info["block"], 0), 1800003600)
        self.assertIsNotNone(self.m.classify("noise\nClaude AI usage limit reached|1800003600"))
        self.assertIsNotNone(self.m.classify("You've hit your weekly limit. Resets Fri 9am"))
        self.assertIsNotNone(self.m.classify("Session limit reached. Your limit will reset at 3pm."))

    def test_classify(self):
        self.assertIsNone(self.m.classify("error: AssertionError"))
        self.assertIsNone(self.m.classify("FAILED test_api - expected rate limit handling, got 500"))
        self.assertIsNone(self.m.classify("FAILED test_retry - expected 'limit reached' message"))
        self.assertIsNone(self.m.classify("Added usage limit handling to the retry code."))
        self.assertEqual(self.m.classify("Session limit reached.")["window"], "5h")
        self.assertEqual(self.m.classify("usage limit reached")["window"], "unknown")
        self.assertIsNone(self.m.classify("Usage limit reached - PR 12 opened"))
        self.assertEqual(self.m.classify("weekly usage limit reached")["window"], "weekly")


if __name__ == "__main__":
    unittest.main()
