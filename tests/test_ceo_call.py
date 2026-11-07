import importlib.util
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import wave
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / ".claude/skills/ceo-call/scripts/ceo_call.py"
spec = importlib.util.spec_from_file_location("ceo_call", SCRIPT)
ceo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ceo)


def fake_synth(host, port, text):
    return (22050, 2, 1, b"\x10\x00" * 2205)  # 0.1 s of a constant tone


class FakeClock:
    """Time only moves when the code sleeps, so the polling loop runs for real and instantly."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeAsterisk:
    """Simulates the call folder. Each script entry says what one originated call leaves behind:
    a plain string is the result written at once ("unanswered" and "hangup" are special), a dict
    maps a read count (reads of the call folder after the call started) to the markers that appear."""

    def __init__(self, script):
        self.files = {}
        self.script = list(script)
        self.dirs = set()
        self.originated = 0
        self.swept = 0
        self.timeline = {}
        self.reads = 0

    def sweep_stale(self):
        self.swept += 1

    def make_dir(self, path):
        self.dirs.add(path)

    def write_file(self, path, data):
        self.files[path] = data

    def read_file(self, path):
        self.reads += 1
        base = next(iter(self.dirs)) if self.dirs else ""
        for when in [w for w in self.timeline if w <= self.reads]:
            for name, value in self.timeline.pop(when).items():
                self.files[base + "/" + name] = value
        value = self.files.get(path)
        return value.decode() if isinstance(value, bytes) else value

    def remove(self, *paths):
        for path in paths:
            for key in [k for k in self.files if k == path or k.startswith(path + "/")]:
                del self.files[key]
            self.dirs.discard(path)

    def originate(self, name, call_file):
        self.originated += 1
        base = next(iter(self.dirs))
        outcome = self.script.pop(0)
        self.reads = 0
        if isinstance(outcome, dict):
            self.timeline = dict(outcome)
            return
        if outcome == "unanswered":
            return
        self.files[base + "/answered"] = "1"
        if outcome != "hangup":
            self.files[base + "/result"] = outcome
        self.files[base + "/done"] = "1"


def run_ask(script, request=None, env=None, notifier=None, config=None, clock_time=(12, 0)):
    cfg = dict(ceo.DEFAULT_CONFIG, retry_delay_s=0, poll_interval_s=2, ring_timeout_s=30, call_timeout_s=300, attempts=3)
    cfg.update(config or {})
    clock = FakeClock()
    asterisk = FakeAsterisk(script)
    sent = []

    def default_notifier(token, chat, text, silent=False):
        sent.append((token, chat, text, silent))
        return True

    request = request or {"question": "Ship it?", "options": ["Yes", "No", "Later"]}
    result = ceo.ask(
        request, cfg, env if env is not None else {}, asterisk,
        synth=fake_synth, notifier=notifier or default_notifier,
        sleep=clock.sleep, clock=clock,
        now=lambda: datetime(2026, 1, 1, *clock_time),
    )
    run_ask.clock = clock
    return result, asterisk, sent


class ValidateRequestTests(unittest.TestCase):
    def test_accepts_a_normal_request(self):
        clean = ceo.validate_request({"question": " Ship? ", "options": ["a", " b "]})
        self.assertEqual(clean, {"question": "Ship?", "options": ["a", "b"]})

    def test_rejects_bad_requests(self):
        bad = [
            None, [], {}, {"question": "", "options": ["a", "b"]},
            {"question": "q", "options": ["only one"]},
            {"question": "q", "options": [str(i) for i in range(9)]},
            {"question": "q", "options": ["a", ""]},
            {"question": "q", "options": ["a", 3]},
            {"question": "x" * 501, "options": ["a", "b"]},
            {"question": "q", "options": ["a", "b" * 201]},
            {"question": "q\x00", "options": ["a", "b"]},
            {"question": "q", "options": ["a", "b\nc"]},
        ]
        for request in bad:
            with self.subTest(request=request):
                with self.assertRaises(ceo.CallError):
                    ceo.validate_request(request)


class PromptTests(unittest.TestCase):
    def test_each_option_has_a_readback_prompt_naming_it(self):
        prompts = ceo.build_prompts("Ship it?", ["Yes", "No"])
        self.assertTrue(prompts["prompt"].startswith("Hola, soy Claudio."))
        self.assertIn("Opción 1: Yes", prompts["prompt"])
        self.assertIn("Opción 2: No", prompts["prompt"])
        self.assertIn("opción 2: No", prompts["confirm_2"])
        self.assertIn("confirm_1", prompts)
        self.assertNotIn("confirm_3", prompts)
        self.assertIn("thanks", prompts)
        self.assertIn("giveup", prompts)


class AudioTests(unittest.TestCase):
    def test_wav_is_mono_8k_because_asterisk_opens_no_other_wav_rate(self):
        wav = ceo.to_wav(22050, 2, 1, b"\x10\x00" * 22050)  # one second
        with wave.open(io.BytesIO(wav)) as handle:
            self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()), (1, 2, 8000))
            self.assertAlmostEqual(handle.getnframes(), 8000 + 2000, delta=5)  # 1 s + 0.25 s silence

    def test_downsampling_keeps_a_steady_level_and_averages_out_fast_noise(self):
        import array
        steady = ceo.resample(array.array("h", [1000] * 2205), 22050, 8000)
        self.assertTrue(all(v == 1000 for v in steady))
        noisy = ceo.resample(array.array("h", [3000, -3000] * 2205), 22050, 8000)
        self.assertLess(max(abs(v) for v in noisy), 1500)

    def test_stereo_is_mixed_down_to_mono(self):
        left, right = (100).to_bytes(2, "little", signed=True), (300).to_bytes(2, "little", signed=True)
        wav = ceo.to_wav(16000, 2, 2, (left + right) * 1600)
        with wave.open(io.BytesIO(wav)) as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertAlmostEqual(handle.getnframes(), 800 + 2000, delta=5)
            first = int.from_bytes(handle.readframes(1), "little", signed=True)
        self.assertEqual(first, 200)

    def test_rejects_non_16_bit_audio(self):
        with self.assertRaises(ceo.CallError):
            ceo.to_wav(22050, 1, 1, b"\x00" * 100)


class WyomingServer:
    def __init__(self, events):
        self.events = events
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.received = None
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.listener.accept()
        handle = conn.makefile("rwb")
        self.received = json.loads(handle.readline())
        for header, payload in self.events:
            header = dict(header)
            if payload:
                header["payload_length"] = len(payload)
            handle.write((json.dumps(header) + "\n").encode() + payload)
            handle.flush()
        threading.Event().wait(0.5)  # the real server keeps the connection open after audio-stop
        conn.close()
        self.listener.close()


class SynthesizeTests(unittest.TestCase):
    def test_reads_audio_until_audio_stop(self):
        server = WyomingServer([
            ({"type": "audio-start", "data": {"rate": 22050, "width": 2, "channels": 1}}, b""),
            ({"type": "audio-chunk", "data": {"rate": 22050, "width": 2, "channels": 1}}, b"\x01\x00\x02\x00"),
            ({"type": "audio-chunk", "data": {"rate": 22050, "width": 2, "channels": 1}}, b"\x03\x00"),
            ({"type": "audio-stop"}, b""),
        ])
        rate, width, channels, pcm = ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)
        self.assertEqual((rate, width, channels), (22050, 2, 1))
        self.assertEqual(pcm, b"\x01\x00\x02\x00\x03\x00")
        self.assertEqual(server.received["data"]["text"], "hola")

    def test_error_event_and_early_close_fail_cleanly(self):
        server = WyomingServer([({"type": "error", "data": {"text": "boom"}}, b"")])
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)
        server = WyomingServer([({"type": "audio-start", "data": {"rate": 1, "width": 2, "channels": 1}}, b"")])
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)

    def test_unreachable_server_fails_cleanly(self):
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", 1, "hola", timeout=1)


class CallFileTests(unittest.TestCase):
    def test_call_file_carries_only_ids_and_counts(self):
        text = ceo.build_call_file("PJSIP/phone", "ab" * 8, 3, 30)
        self.assertIn("Channel: PJSIP/phone", text)
        self.assertIn("Setvar: CEO_ID=" + "ab" * 8, text)
        self.assertIn("Setvar: CEO_OPTIONS=3", text)
        self.assertIn("MaxRetries: 0", text)

    def test_rejects_injection_in_parameters(self):
        for endpoint, call_id in [("PJSIP/phone\nApplication: System", "ab" * 8), ("PJSIP/phone", "ab\nx"), ("SIP/x", "ab" * 8)]:
            with self.subTest(endpoint=endpoint, call_id=call_id):
                with self.assertRaises(ceo.CallError):
                    ceo.build_call_file(endpoint, call_id, 2, 30)


class ConfigTests(unittest.TestCase):
    def write(self, content):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(content)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_defaults_without_a_file(self):
        self.assertEqual(ceo.load_config(None)["endpoint"], "PJSIP/phone")

    def test_call_windows_that_could_overlap_a_live_call_are_refused(self):
        for content in ['{"ring_timeout_s": 0}', '{"ring_timeout_s": 4}', '{"call_timeout_s": 30}', '{"piper_host": 5}', '{"env_file": ""}']:
            with self.subTest(content=content):
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(self.write(content))

    def test_rejects_unknown_keys_and_bad_values(self):
        for content in ['{"nope": 1}', '{"endpoint": "SIP/x"}', '{"attempts": 0}', '{"attempts": "3"}', '{"container": "a b"}', "[]", "not json"]:
            with self.subTest(content=content):
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(self.write(content))


class EnvFileTests(unittest.TestCase):
    def make(self, mode):
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        handle.write("# comment\nCEO_TELEGRAM_TOKEN=abc\nCEO_TELEGRAM_CHAT_ID='42'\n")
        handle.close()
        os.chmod(handle.name, mode)
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_private_file_is_read(self):
        self.assertEqual(ceo.load_env_file(self.make(0o600)), {"CEO_TELEGRAM_TOKEN": "abc", "CEO_TELEGRAM_CHAT_ID": "42"})

    def test_group_or_world_readable_file_is_refused(self):
        for mode in (0o640, 0o644, 0o604):
            with self.subTest(mode=oct(mode)):
                with self.assertRaises(ceo.CallError):
                    ceo.load_env_file(self.make(mode))

    def test_unreadable_env_path_is_a_clean_error(self):
        folder = tempfile.mkdtemp()
        os.chmod(folder, 0o700)
        self.addCleanup(os.rmdir, folder)
        with self.assertRaises(ceo.CallError):
            ceo.load_env_file(folder)

    def test_missing_file_means_nothing_configured(self):
        self.assertEqual(ceo.load_env_file("/nonexistent/ceo-env"), {})


class TelegramTests(unittest.TestCase):
    def test_posts_to_the_bot_api_and_reports_success(self):
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout):
            seen["url"], seen["body"] = request.full_url, request.data.decode()
            return Response(b'{"ok": true}')

        self.assertTrue(ceo.send_telegram("TOKEN", "42", "hello world", opener=opener))
        self.assertEqual(seen["url"], "https://api.telegram.org/botTOKEN/sendMessage")
        self.assertIn("chat_id=42", seen["body"])
        self.assertIn("hello+world", seen["body"])

    def test_any_failure_returns_false_without_raising(self):
        def opener(request, timeout):
            raise OSError("https://api.telegram.org/botTOKEN/sendMessage failed")

        self.assertFalse(ceo.send_telegram("TOKEN", "42", "x", opener=opener))


class AskFlowTests(unittest.TestCase):
    def test_confirmed_choice_is_returned_with_its_option_text(self):
        result, asterisk, sent = run_ask(["2"])
        self.assertEqual(result["status"], "decided")
        self.assertEqual((result["choice"], result["option"], result["attempt"]), (2, "No", 1))
        self.assertEqual(sent, [])

    def test_everything_is_removed_after_the_call_and_old_folders_are_swept_first(self):
        result, asterisk, _ = run_ask(["1"])
        self.assertEqual(asterisk.files, {})
        self.assertEqual(asterisk.dirs, set())
        self.assertEqual(asterisk.swept, 1)

    def test_prompts_exist_while_the_call_runs(self):
        seen = []
        original = FakeAsterisk.originate

        def spy(self, name, call_file):
            seen.extend(sorted(k.rsplit("/", 1)[1] for k in self.files))
            original(self, name, call_file)

        FakeAsterisk.originate = spy
        try:
            run_ask(["1"])
        finally:
            FakeAsterisk.originate = original
        self.assertEqual(seen, ["confirm_1.wav", "confirm_2.wav", "confirm_3.wav", "giveup.wav", "prompt.wav", "thanks.wav"])

    def test_no_answer_retries_then_notifies_once(self):
        result, asterisk, sent = run_ask(["unanswered"] * 3, env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual(result["status"], "unanswered")
        self.assertEqual(asterisk.originated, 3)
        self.assertTrue(result["notified"])
        self.assertEqual(len(sent), 1)
        self.assertIn("Ship it?", sent[0][2])
        self.assertIn("1. Yes", sent[0][2])
        self.assertFalse(sent[0][3])

    def test_answer_on_a_later_attempt_is_accepted_without_notifying(self):
        result, asterisk, sent = run_ask(["unanswered", "hangup", "3"], env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual((result["status"], result["choice"], result["attempt"]), ("decided", 3, 3))
        self.assertEqual(asterisk.originated, 3)
        self.assertEqual(sent, [])

    def test_hanging_up_before_confirming_is_not_a_decision(self):
        result, _, sent = run_ask(["hangup"] * 3, env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual(result["status"], "hangup")
        self.assertEqual(len(sent), 1)

    def test_undecided_is_final_and_notifies(self):
        result, asterisk, sent = run_ask(["undecided"], env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual(result["status"], "undecided")
        self.assertEqual(asterisk.originated, 1)
        self.assertEqual(len(sent), 1)

    def test_a_result_outside_the_option_range_is_never_accepted(self):
        for bad in ["4", "0", "9", "x", "12", "1 2", "-1"]:
            with self.subTest(result=bad):
                with self.assertRaises(ceo.CallError):
                    run_ask([bad])

    def test_files_are_removed_even_when_the_call_errors(self):
        asterisk = FakeAsterisk(["7"])
        cfg = dict(ceo.DEFAULT_CONFIG, retry_delay_s=0)
        clock = FakeClock()
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, cfg, {}, asterisk, synth=fake_synth,
                    sleep=clock.sleep, clock=clock)
        self.assertEqual(asterisk.files, {})
        self.assertEqual(asterisk.dirs, set())

    def test_a_call_nobody_picks_up_gives_up_after_the_ring_window(self):
        run_ask(["unanswered"], config={"attempts": 1})
        self.assertGreaterEqual(run_ask.clock.now, 45)   # ring_timeout_s + 15
        self.assertLess(run_ask.clock.now, 50)

    def test_the_owner_takes_a_while_to_answer_and_to_choose(self):
        late = {3: {"answered": "1"}, 40: {"result": "2"}, 44: {"done": "1"}}
        result, asterisk, _ = run_ask([late])
        self.assertEqual((result["status"], result["choice"]), ("decided", 2))
        self.assertEqual(asterisk.originated, 1)
        self.assertEqual(asterisk.files, {})

    def test_the_result_waits_for_the_thank_you_message_to_finish(self):
        late = {2: {"answered": "1", "result": "1"}, 6: {"done": "1"}}
        result, asterisk, _ = run_ask([late])
        self.assertEqual(result["status"], "decided")
        self.assertGreaterEqual(asterisk.reads, 6)

    def test_answering_then_never_finishing_ends_at_the_call_deadline_as_hangup(self):
        stuck = {2: {"answered": "1"}}
        result, _, _ = run_ask([stuck], config={"attempts": 1})
        self.assertEqual(result["status"], "hangup")
        self.assertGreaterEqual(run_ask.clock.now, 330)  # ring_timeout_s + call_timeout_s
        self.assertLess(run_ask.clock.now, 335)

    def test_an_answered_call_is_not_reported_as_unanswered_when_the_marker_is_seen_late(self):
        result, _, _ = run_ask([{40: {"answered": "1", "done": "1"}}], config={"attempts": 1})
        self.assertEqual(result["status"], "hangup")

    def test_without_chat_settings_nothing_is_sent_and_it_says_so(self):
        result, _, sent = run_ask(["unanswered"] * 3)
        self.assertFalse(result["notified"])
        self.assertEqual(sent, [])

    def test_invalid_request_places_no_call(self):
        asterisk = FakeAsterisk([])
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG), {}, asterisk, synth=fake_synth)
        self.assertEqual(asterisk.originated, 0)


class QuietHoursTests(unittest.TestCase):
    ENV = {"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"}

    def test_window_wrapping_midnight(self):
        quiet = lambda hm: ceo.in_quiet_hours(hm, "23:00", "08:00")
        self.assertTrue(quiet("23:00") and quiet("03:30") and quiet("07:59"))
        self.assertFalse(quiet("08:00") or quiet("12:00") or quiet("22:59"))

    def test_window_within_one_day_and_unset_windows(self):
        self.assertTrue(ceo.in_quiet_hours("13:00", "12:00", "14:00"))
        self.assertFalse(ceo.in_quiet_hours("14:00", "12:00", "14:00"))
        self.assertFalse(ceo.in_quiet_hours("03:00", None, None))
        self.assertFalse(ceo.in_quiet_hours("03:00", "08:00", "08:00"))

    def test_during_quiet_hours_no_call_is_placed_and_the_message_is_silent(self):
        result, asterisk, sent = run_ask([], env=self.ENV, config={"quiet_start": "23:00", "quiet_end": "08:00"}, clock_time=(3, 0))
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(asterisk.originated, 0)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][3])

    def test_outside_quiet_hours_the_call_is_placed(self):
        result, asterisk, sent = run_ask(["1"], env=self.ENV, config={"quiet_start": "23:00", "quiet_end": "08:00"}, clock_time=(12, 0))
        self.assertEqual(result["status"], "decided")

    def test_config_requires_both_ends(self):
        for cfg in ('{"quiet_start": "23:00"}', '{"quiet_start": "25:00", "quiet_end": "08:00"}', '{"quiet_start": "23:00", "quiet_end": 8}'):
            with self.subTest(cfg=cfg):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(cfg)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)


class DockerStateTests(unittest.TestCase):
    def asterisk(self, returncode, stdout=b"", stderr=b""):
        class Result:
            pass

        result = Result()
        result.returncode, result.stdout, result.stderr = returncode, stdout, stderr
        return ceo.DockerAsterisk("asterisk", run=lambda command, **kwargs: result)

    def test_a_missing_file_means_no_marker_yet(self):
        self.assertIsNone(self.asterisk(1, stderr=b"cat: /x: No such file or directory").read_file("/x"))

    def test_a_docker_failure_is_an_error_not_a_missing_marker(self):
        for stderr in (b"Error response from daemon: container is not running", b"", b"Cannot connect to the Docker daemon"):
            with self.subTest(stderr=stderr):
                with self.assertRaises(ceo.CallError):
                    self.asterisk(1, stderr=stderr).read_file("/x")

    def test_endpoint_match_is_exact(self):
        contacts = (b" Contact:  phone2/sip:u@192.0.2.1:5060;ob   abc Avail  1.0\n"
                    b" Contact:  phone-old/sip:u@192.0.2.1:5061   abc Avail  1.0\n")
        self.assertFalse(self.asterisk(0, contacts).endpoint_available("PJSIP/phone"))
        self.assertTrue(self.asterisk(0, contacts + b" Contact:  phone/sip:u@192.0.2.2:5060;ob   abc Avail  1.0\n").endpoint_available("PJSIP/phone"))
        self.assertFalse(self.asterisk(0, b" Contact:  phone/sip:u@192.0.2.2:5060;ob   abc Unavail  nan\n").endpoint_available("PJSIP/phone"))

    def test_stale_folders_older_than_a_day_are_swept(self):
        seen = []

        class Result:
            returncode, stdout, stderr = 0, b"", b""

        ceo.DockerAsterisk("asterisk", run=lambda command, **kwargs: seen.append(command) or Result()).sweep_stale()
        command = seen[0]
        self.assertIn("+1440", command)
        self.assertEqual(command[command.index("find") + 1], "/var/spool/asterisk/ceo")


class DockerAsteriskTests(unittest.TestCase):
    def test_commands_run_as_the_asterisk_user_without_a_shell_from_text(self):
        calls = []

        class Result:
            returncode = 0
            stdout = b" 3 \n"

        def run(command, **kwargs):
            calls.append((command, kwargs.get("input")))
            return Result()

        asterisk = ceo.DockerAsterisk("asterisk", run=run)
        asterisk.write_file("/var/spool/asterisk/ceo/x/prompt.wav", b"RIFF")
        self.assertEqual(asterisk.read_file("/var/spool/asterisk/ceo/x/result"), "3")
        asterisk.originate("ceo-abc", "Channel: PJSIP/phone\n")
        self.assertEqual(calls[0][0][:6], ["docker", "exec", "-i", "-u", "asterisk", "asterisk"])
        self.assertEqual(calls[0][1], b"RIFF")
        self.assertEqual(calls[0][0][-2:], ["sh", "/var/spool/asterisk/ceo/x/prompt.wav"])
        self.assertEqual(calls[-1][0][-3:], ["mv", "/var/spool/asterisk/tmp/ceo-abc.call", "/var/spool/asterisk/outgoing/ceo-abc.call"])


class DialplanTests(unittest.TestCase):
    """The dialplan cannot run here, so pin the order of the steps that protect the decision."""

    def setUp(self):
        path = SCRIPT.parent.parent / "dialplan" / "ceo-ask.conf"
        self.lines = [line.strip() for line in path.read_text().splitlines()]

    def index(self, fragment):
        matches = [i for i, line in enumerate(self.lines) if fragment in line]
        self.assertEqual(len(matches), 1, fragment)
        return matches[0]

    def test_ids_are_validated_before_anything_else_runs(self):
        self.assertLess(self.index('REGEX("^[0-9a-f]+$" ${CEO_ID})} = 0]?bad'), self.index("Answer()"))
        self.assertLess(self.index('REGEX("^[1-8]$" ${CEO_OPTIONS})'), self.index("Answer()"))

    def test_the_result_is_written_only_after_the_confirmation_key(self):
        confirm_read = self.index("Read(CONFIRM")
        gate = self.index('"${CONFIRM}" != "1"')
        write = self.index("Set(FILE(${CEO_DIR}/result)=${CHOICE})")
        self.assertLess(confirm_read, gate)
        self.assertLess(gate, write)

    def test_a_choice_must_be_a_valid_option_before_it_is_read_back(self):
        self.assertLess(self.index('REGEX("^[1-8]$" ${CHOICE})'), self.index("Read(CONFIRM"))
        self.assertLess(self.index("${CHOICE} > ${CEO_OPTIONS}"), self.index("Read(CONFIRM"))

    def test_rounds_are_capped_and_the_end_of_call_marker_is_always_written(self):
        self.index("${ROUND} > 3")
        self.index("(giveup),Set(FILE(${CEO_DIR}/result)=undecided)")
        self.assertTrue(any(line.startswith("exten => h,1") for line in self.lines))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.request = Path(self.tmp.name) / "request.json"
        self.request.write_text(json.dumps({"question": "Ship it?", "options": ["Yes", "No"]}))
        self.config = Path(self.tmp.name) / "config.json"
        self.config.write_text(json.dumps({"env_file": str(Path(self.tmp.name) / "env")}))
        self.originals = (ceo.DockerAsterisk, ceo.synthesize)
        self.addCleanup(self.restore)
        ceo.synthesize = fake_synth

    def restore(self):
        ceo.DockerAsterisk, ceo.synthesize = self.originals

    def run_main(self, argv, script=None):
        import contextlib
        script = script if script is not None else ["2"]
        ceo.DockerAsterisk = lambda container: FakeAsterisk(script)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ceo.main(["--config", str(self.config)] + argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_confirmed_decision_exits_zero_and_prints_one_json_line(self):
        code, out, _ = self.run_main(["ask", "--request", str(self.request)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["option"], "No")

    def test_a_pending_decision_exits_three(self):
        code, out, _ = self.run_main(["ask", "--request", str(self.request)], script=["undecided"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["status"], "undecided")

    def test_input_problems_exit_one_with_an_error_line_and_no_traceback(self):
        for argv in (["ask", "--request", str(Path(self.tmp.name) / "missing.json")],):
            code, out, err = self.run_main(argv)
            self.assertEqual(code, 1)
            self.assertTrue(err.startswith("ERROR:"))
            self.assertNotIn("Traceback", err)
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{")
        code, _, err = self.run_main(["ask", "--request", str(bad)])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("ERROR:"))

    def test_check_reports_a_registered_phone(self):
        for registered, expected in ((True, 0), (False, 1)):
            with self.subTest(registered=registered):
                class Fake(FakeAsterisk):
                    def endpoint_available(self, endpoint):
                        return registered

                import contextlib
                ceo.DockerAsterisk = lambda container: Fake([])
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = ceo.main(["--config", str(self.config), "check"])
                self.assertEqual(code, expected)
                self.assertIn("speech: ok", out.getvalue())

    def test_telegram_setup_prints_the_chat_id_and_never_the_token(self):
        import contextlib
        import unittest.mock as mock
        env = Path(self.tmp.name) / "env"
        env.write_text("CEO_TELEGRAM_TOKEN=SECRETTOKEN\n")
        os.chmod(env, 0o600)

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = json.dumps({"result": [{"message": {"chat": {"id": 4242, "type": "private", "first_name": "Someone"}}}]}).encode()
        out = io.StringIO()
        with mock.patch.object(ceo.urllib.request, "urlopen", lambda url, timeout: Response(payload)):
            with contextlib.redirect_stdout(out):
                code = ceo.main(["--config", str(self.config), "telegram-setup"])
        self.assertEqual(code, 0)
        self.assertIn("CEO_TELEGRAM_CHAT_ID=4242", out.getvalue())
        self.assertNotIn("SECRETTOKEN", out.getvalue())
        self.assertNotIn("Someone", out.getvalue())


if __name__ == "__main__":
    unittest.main()
