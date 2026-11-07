import http.server
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
        self.assertEqual(self.redact("passenger: ok\nplain line\n"), "passenger: ok\nplain line\n")


class AliasValidationTests(unittest.TestCase):
    def test_option_like_and_unknown_aliases_are_refused(self):
        for alias in ("-oProxyCommand=touch /tmp/x", "a b", "", "no-such-host-alias-xyz"):
            with self.subTest(alias=alias):
                r = sh(f". {SCRIPTS}/lib.sh; valid_alias '{alias}'")
                self.assertNotEqual(r.returncode, 0)

    def test_probe_and_inventory_refuse_bad_alias_without_running_ssh(self):
        r = subprocess.run([str(SCRIPTS / "probe.sh"), "-oProxyCommand=false"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([str(SCRIPTS / "inventory.sh"), "-oProxyCommand=false", d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(list(Path(d).iterdir()), [])


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


@unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
class ShellcheckTests(unittest.TestCase):
    def test_scripts_are_shellcheck_clean(self):
        for script in sorted(SCRIPTS.glob("*.sh")):
            with self.subTest(script=script.name):
                r = subprocess.run(["shellcheck", str(script)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
