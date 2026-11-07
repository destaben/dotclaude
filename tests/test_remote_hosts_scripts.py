import http.server
import os
import signal
import time
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "remote-hosts" / "scripts"


def sh(script: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", script], input=stdin, capture_output=True, text=True, timeout=30)


class RedactTests(unittest.TestCase):
    def redact(self, text: str) -> str:
        return sh(f". {SCRIPTS}/lib.sh; redact", text).stdout

    def test_url_userinfo_is_stripped(self):
        self.assertEqual(self.redact("https://user:tok@host/x.git\n"), "https://host/x.git\n")

    def test_underscore_prefixed_names_are_redacted(self):
        out = self.redact("POSTGRES_PASSWORD=hunter2\nGITHUB_TOKEN=ghp_abc\n")
        self.assertNotIn("hunter2", out)
        self.assertNotIn("ghp_abc", out)

    def test_authorization_header_loses_scheme_and_credential(self):
        out = self.redact("Authorization: Bearer eyJhbGciOi.payload.sig\n")
        self.assertNotIn("eyJhbGciOi", out)

    def test_bare_bearer_token_is_redacted(self):
        self.assertNotIn("abcdefgh12345", self.redact("sent Bearer abcdefgh12345 here\n"))

    def test_ordinary_text_is_untouched(self):
        text = "passenger: ok\nplain line\nBasic authentication failed\nMax tokens: 4096\n"
        self.assertEqual(self.redact(text), text)

    def test_space_separated_and_flag_style_secrets(self):
        cases = {
            "0 3 * * * /usr/local/bin/backup --password hunter2": "hunter2",
            "curl -u bob:hunter2 http://x": "hunter2",
            "mysql -u root -psecret123 db": "secret123",
            "backup --token=abcd1234 --x": "abcd1234",
            "ACCESS_KEY=AKIAEXAMPLE1": "AKIAEXAMPLE1",
            "PASS=letmein": "letmein",
            "pwd = letmein2": "letmein2",
        }
        for line, secret in cases.items():
            with self.subTest(line=line):
                self.assertNotIn(secret, self.redact(line + "\n"))

    def test_url_userinfo_with_at_and_slash_in_the_secret(self):
        for url, leaked in (("https://bot:p@ss@git.example/x.git", "ss@"), ("https://bot:tok/en@host/x", "tok")):
            with self.subTest(url=url):
                out = self.redact(url + "\n")
                self.assertNotIn(leaked, out)
                self.assertIn("host" if "host" in url else "git.example", out)


class AliasValidationTests(unittest.TestCase):
    def test_option_like_and_unknown_aliases_are_refused(self):
        for alias in ("-oProxyCommand=touch /tmp/x", "a b", "", "no-such-host-alias-xyz"):
            with self.subTest(alias=alias):
                r = sh(f". {SCRIPTS}/lib.sh; valid_alias '{alias}'")
                self.assertNotEqual(r.returncode, 0)

    def test_real_alias_is_accepted_case_insensitively_and_through_include(self):
        with tempfile.TemporaryDirectory() as home:
            ssh = Path(home, ".ssh")
            ssh.mkdir()
            (ssh / "config").write_text("Include extra.conf\nHOST printer # server\n  HostName 10.0.0.1\n")
            (ssh / "extra.conf").write_text("Host viainclude\n  HostName 10.0.0.2\n")
            for alias, ok in (("printer", True), ("viainclude", True), ("server", False), ("nope", False)):
                with self.subTest(alias=alias):
                    r = subprocess.run(["sh", "-c", f". {SCRIPTS}/lib.sh; valid_alias '{alias}'"],
                                       env={**os.environ, "HOME": home}, capture_output=True, timeout=30)
                    self.assertEqual(r.returncode == 0, ok)

    def test_include_path_under_a_home_with_spaces_is_honoured(self):
        with tempfile.TemporaryDirectory() as base:
            home = Path(base, "My Home")
            (home / ".ssh" / "conf.d").mkdir(parents=True)
            (home / ".ssh" / "config").write_text("Include conf.d/*.conf\n")
            (home / ".ssh" / "conf.d" / "a.conf").write_text("Host spaced\n  HostName 10.0.0.3\n")
            r = subprocess.run(["sh", "-c", f". {SCRIPTS}/lib.sh; valid_alias spaced"],
                               env={**os.environ, "HOME": str(home)}, capture_output=True, timeout=30)
            self.assertEqual(r.returncode, 0)

    def test_probe_and_inventory_refuse_bad_alias_without_running_ssh(self):
        r = subprocess.run([str(SCRIPTS / "probe.sh"), "-oProxyCommand=false"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([str(SCRIPTS / "inventory.sh"), "-oProxyCommand=false", d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(list(Path(d).iterdir()), [])


class InventoryTests(unittest.TestCase):
    """inventory.sh against a stub `ssh` on PATH, so no network is touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "home" / ".ssh").mkdir(parents=True)
        (t / "home" / ".ssh" / "config").write_text("Host box\n  HostName 10.0.0.9\n")
        (t / "bin").mkdir()
        stub = t / "bin" / "ssh"
        stub.write_text('#!/bin/sh\n'
                        'for last; do :; done\n'
                        'printf "%s\\n" "$last" > "$STUB_LOG"\n'
                        '[ "$STUB_MODE" = timeout ] && exit 124\n'
                        '[ "$STUB_MODE" = sleep ] && exec sleep 5\n'
                        '[ "$STUB_MODE" = fail ] && { echo "Permission denied (publickey)." >&2; exit 255; }\n'
                        'echo "DB_PASSWORD=hunter2 remote=https://u:tok@host/r.git"\n'
                        'exit 0\n')
        stub.chmod(0o755)
        self.env = {**os.environ, "HOME": str(t / "home"), "PATH": f"{t / 'bin'}:{os.environ['PATH']}",
                    "STUB_LOG": str(t / "last-command")}
        self.out = t / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_inventory(self, mode):
        return subprocess.run([str(SCRIPTS / "inventory.sh"), "box", str(self.out)],
                              env={**self.env, "STUB_MODE": mode}, capture_output=True, text=True, timeout=60)

    def test_happy_path_writes_redacted_topics_and_leaves_no_raw_files(self):
        r = self.run_inventory("ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("10 topics ok, 0 failed", r.stdout)
        topic = (self.out / "box" / "os.txt").read_text()
        self.assertNotIn("hunter2", topic)
        self.assertNotIn("tok@", topic)
        self.assertEqual(list((self.out / "box").glob("*.raw")), [])

    def test_all_ssh_failures_exit_nonzero_and_keep_errors_out_of_data_files(self):
        r = self.run_inventory("fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("0 topics ok, 10 failed", r.stdout)
        self.assertEqual((self.out / "box" / "os.txt").read_text(), "")
        self.assertIn("Permission denied", (self.out / "box" / "os.err").read_text())

    def test_output_dir_ignores_itself_and_callers_gitignore_is_untouched(self):
        (self.out / ".gitignore").write_text("keep\n")
        self.run_inventory("ok")
        self.assertEqual((self.out / ".gitignore").read_text(), "keep\n")
        self.assertEqual((self.out / "box" / ".gitignore").read_text(), "*\n")

    def test_remote_command_is_wrapped_in_a_timeout_with_balanced_quoting(self):
        self.run_inventory("ok")
        last = Path(self.env["STUB_LOG"]).read_text().strip()
        self.assertTrue(last.startswith("timeout 90 sh -c '"), last)
        self.assertEqual(subprocess.run(["sh", "-n", "-c", last]).returncode, 0)

    def test_remote_timeout_counts_as_failed(self):
        r = self.run_inventory("timeout")
        self.assertEqual(r.returncode, 1)
        self.assertIn("0 topics ok, 10 failed", r.stdout)
        self.assertIn("timed out", (self.out / "box" / "os.err").read_text())

    def test_failing_redactor_never_reports_success(self):
        fake = Path(self.tmp.name, "bin", "perl")
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
        r = self.run_inventory("ok")
        self.assertEqual(r.returncode, 1)
        self.assertIn("0 topics ok", r.stdout)

    def test_ctrl_c_stops_the_run_and_leaves_no_raw_files(self):
        p = subprocess.Popen([str(SCRIPTS / "inventory.sh"), "box", str(self.out)],
                             env={**self.env, "STUB_MODE": "sleep"}, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        os.killpg(p.pid, signal.SIGINT)   # what Ctrl-C does: signals the whole foreground group
        try:
            rc = p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            self.fail("inventory.sh kept running after SIGINT")
        self.assertNotEqual(rc, 0)
        self.assertEqual(list((self.out / "box").glob("*.raw")), [])

    def test_unwritable_output_location_is_an_error_not_a_success(self):
        blocker = Path(self.tmp.name, "afile")
        blocker.write_text("x")
        r = subprocess.run([str(SCRIPTS / "inventory.sh"), "box", str(blocker)], env={**self.env, "STUB_MODE": "ok"},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)


class PrintStateTests(unittest.TestCase):
    def run_against(self, body: str) -> subprocess.CompletedProcess:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return subprocess.run([str(SCRIPTS / "print-state.sh"), f"127.0.0.1:{server.server_port}"],
                                  capture_output=True, text=True, timeout=30)
        finally:
            server.shutdown()
            server.server_close()

    @staticmethod
    def payload(state: str, progress="0.5") -> str:
        return ('{"result":{"status":{"print_stats":{"state":"%s","filename":"a.gcode"},'
                '"display_status":{"progress":%s}}}}' % (state, progress))

    def test_exit_codes_follow_the_contract(self):
        cases = {"standby": 0, "complete": 0, "cancelled": 0, "printing": 10, "paused": 10, "error": 20}
        for state, code in cases.items():
            with self.subTest(state=state):
                self.assertEqual(self.run_against(self.payload(state)).returncode, code)

    def test_malformed_answers_are_unknown_not_a_traceback(self):
        for body in ("not json", self.payload("standby", '"abc"')[:-10], "{}"):
            with self.subTest(body=body[:20]):
                r = self.run_against(body)
                self.assertEqual(r.returncode, 20)
                self.assertNotIn("Traceback", r.stderr)

    def test_non_numeric_progress_does_not_break_a_valid_state(self):
        self.assertEqual(self.run_against(self.payload("printing", '"abc"')).returncode, 10)

    def test_unreachable_host_is_unknown(self):
        r = subprocess.run([str(SCRIPTS / "print-state.sh"), "127.0.0.1:1"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 20)

    def test_bad_usage_is_refused(self):
        r = subprocess.run([str(SCRIPTS / "print-state.sh"), "-x"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)


class ShellcheckTests(unittest.TestCase):
    def test_scripts_are_shellcheck_clean(self):
        if not shutil.which("shellcheck"):
            # Locally this is optional; in CI a missing linter must fail, not silently pass.
            if os.environ.get("CI"):
                self.fail("shellcheck is required in CI")
            self.skipTest("shellcheck not installed")
        for script in sorted(SCRIPTS.glob("*.sh")):
            with self.subTest(script=script.name):
                r = subprocess.run(["shellcheck", str(script)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
