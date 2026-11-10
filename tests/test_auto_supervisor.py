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
if act.startswith("limit0:"):
    print(act[7:].replace("{reset}", str(int(time.time()) + 2)))
    sys.exit(0)
if act == "tamper":  # limit now; the notifier switches branches while the run waits
    open(os.path.join(d, "tamper"), "w").write(os.getcwd())
    print("Claude usage limit reached|%d" % (int(time.time()) + 1)); sys.exit(1)
if act == "fail":
    print("error: tests do not pass"); sys.exit(1)
open(stage + ".txt", "w").write("x")
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

    def test_weekly_limit_without_readable_reset_stops(self):
        self.script(["limit:You have hit your weekly limit."])
        r = self.start()
        self.assertEqual(r.returncode, 2)
        self.assertIn("weekly", r.stdout)
        self.assertEqual(len(self.calls()), 1)

    def test_five_hour_limit_without_readable_reset_uses_fallback_within_cap(self):
        self.script(["limit:Session limit reached."])
        r = self.start("--fallback-wait-minutes", "400", "--max-wait-hours", "6")
        self.assertEqual(r.returncode, 2)  # 400 min > 6h cap
        self.assertIn("maximum wait", r.stdout)


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

    def test_unreadable_is_none(self):
        self.assertIsNone(self.m.parse_reset("limit reached, try later", self.now))

    def test_classify(self):
        self.assertIsNone(self.m.classify("error: AssertionError"))
        self.assertIsNone(self.m.classify("FAILED test_api - expected rate limit handling, got 500"))
        self.assertEqual(self.m.classify("usage limit reached")["window"], "5h")
        self.assertEqual(self.m.classify("weekly usage limit reached")["window"], "weekly")


if __name__ == "__main__":
    unittest.main()
