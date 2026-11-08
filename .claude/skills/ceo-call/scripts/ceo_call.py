#!/usr/bin/env python3
"""Phone the owner for a decision.

Speaks a question with numbered options over a phone call, captures one keypad answer, reads it
back and records it only after the owner confirms with a second key press. If the owner does not
pick up, it retries and finally sends a chat message instead.

Standard library only. It runs on the host that runs Asterisk (in Docker) and a Piper
text-to-speech server (Wyoming protocol over TCP). See SKILL.md for the setup.

Subcommands:
  ask               place the call (request JSON on --request, or "-" for stdin)
  check             verify that speech synthesis and the phone endpoint are reachable
  test-call         phone the owner and read a public-domain passage to judge the voice
  telegram-setup    print the id of every chat that wrote to the bot (newest last)
"""

import argparse
import array
import fcntl
import io
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import wave
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SPOOL = "/var/spool/asterisk"
# Asterisk's WAV format only opens 8 kHz files, which is also the rate of the ulaw/alaw phone codecs.
SAMPLE_RATE = 8000
MAX_OPTIONS = 8
MAX_QUESTION_CHARS = 800
MAX_OPTION_CHARS = 200
MAX_WYOMING_PAYLOAD = 16 * 1024 * 1024
MAX_PCM_BYTES = 64 * 1024 * 1024  # total audio for one prompt
MAX_HEADER_BYTES = 64 * 1024  # one Wyoming header line
MAX_REQUEST_BYTES = 64 * 1024  # the request JSON

DEFAULT_CONFIG = {
    "container": "asterisk",
    "piper_host": "127.0.0.1",
    "piper_port": 10200,
    "endpoint": "PJSIP/phone",
    "attempts": 3,
    "retry_delay_s": 300,
    "ring_timeout_s": 30,
    "call_timeout_s": 300,
    "poll_interval_s": 2,
    "env_file": "~/.config/ceo-call/env",
    "quiet_start": None,  # "HH:MM" host-local time; with quiet_end, no calls are placed in between
    "quiet_end": None,
    "timezone": None,  # IANA name such as "Europe/Madrid"; default is the host's local time
    "heads_up_s": 90,  # when the phone is not registered, message the owner and wait this long
    "max_per_hour": 6,  # refuse more than this many asks within an hour (0 = off)
    "min_gap_s": 120,  # refuse a new ask this soon after the previous one started (0 = off)
    "state_file": "~/.local/state/ceo-call/last_ask",  # remembers when the last ask started; None = off
}

TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]\Z")
ENDPOINT_RE = re.compile(r"^PJSIP/[A-Za-z0-9_.-]+\Z")
CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Spoken and chat phrases (Spanish): the owner's language. They are data for the voice and the chat,
# not code comments or documentation, so the English-only rule does not apply to them.
PHRASES = {
    "intro": "Hola, soy Claudio. Necesito una decisión.",
    "option": "Opción {n}: {text}.",
    "choose": "Pulsa el número de tu elección, o el nueve para repetir.",
    "confirm": "Has elegido la opción {n}: {text}. Pulsa uno para confirmar, o cualquier otra tecla para elegir de nuevo.",
    "thanks": "Decisión registrada. Gracias.",
    "giveup": "No he recibido una confirmación. Dejo la decisión pendiente. Hasta luego.",
}
NOTIFY = {
    "unanswered": "No contestaste a la llamada.",
    "hangup": "Colgaste antes de confirmar una decisión.",
    "undecided": "Contestaste, pero no llegaste a confirmar una opción.",
    "deferred": "Estamos en horas de silencio, así que no llamé.",
    "error": "No pude llamar por un fallo técnico.",
    "error_live": "Hubo un fallo técnico durante la llamada. Si ya respondiste, tu respuesta no se ha registrado: la decisión sigue pendiente.",
    "timeout": "La llamada seguía abierta cuando se acabó el tiempo, así que no se registró ninguna decisión.",
    "phone_not_registered": "Tu teléfono no estaba conectado, así que no llamé.",
}


class CallError(Exception):
    """An infrastructure or input problem; the message never contains secrets."""


class MayBeLive(CallError):
    """An error after which a call that was already placed may still be live."""


class DockerError(MayBeLive):
    """Docker or the Asterisk container failed."""


class Interrupted(MayBeLive):
    """The process was asked to stop (SIGTERM)."""


# ---------------------------------------------------------------------------------- request


def validate_request(request) -> Dict:
    """Return a cleaned request or raise CallError. Text only ever reaches the voice engine."""
    if not isinstance(request, dict):
        raise CallError("request must be a JSON object")
    question = request.get("question")
    options = request.get("options")
    if not isinstance(question, str) or not question.strip():
        raise CallError("request needs a non-empty 'question' string")
    if len(question) > MAX_QUESTION_CHARS:
        raise CallError("question is longer than %d characters" % MAX_QUESTION_CHARS)
    if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
        raise CallError("request needs 2 to %d options" % MAX_OPTIONS)
    clean = []
    for option in options:
        if not isinstance(option, str) or not option.strip():
            raise CallError("every option must be a non-empty string")
        if len(option) > MAX_OPTION_CHARS:
            raise CallError("an option is longer than %d characters" % MAX_OPTION_CHARS)
        clean.append(option.strip())
    for text in [question] + clean:
        if CONTROL_RE.search(text):
            raise CallError("text must not contain control characters")
        try:
            text.encode("utf-8")  # a lone surrogate would crash the final JSON output after the call
        except UnicodeEncodeError:
            raise CallError("text must be valid Unicode")
    return {"question": question.strip(), "options": clean}


def build_prompts(question: str, options: List[str]) -> Dict[str, str]:
    """Map a prompt file name to the text that is spoken."""
    spoken = [PHRASES["intro"], question.rstrip(".!? ") + "."]
    for number, text in enumerate(options, 1):
        spoken.append(PHRASES["option"].format(n=number, text=text.rstrip(".!? ")))
    spoken.append(PHRASES["choose"])
    prompts = {"prompt": " ".join(spoken)}
    for number, text in enumerate(options, 1):
        prompts["confirm_%d" % number] = PHRASES["confirm"].format(n=number, text=text.rstrip(".!? "))
    prompts["thanks"] = PHRASES["thanks"]
    prompts["giveup"] = PHRASES["giveup"]
    return prompts


# ---------------------------------------------------------------------------------- config / env


def load_config(path: Optional[str]) -> Dict:
    config = dict(DEFAULT_CONFIG)
    if path:
        try:
            with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, ValueError):
            raise CallError("cannot read the config file")
        if not isinstance(loaded, dict):
            raise CallError("the config file must hold a JSON object")
        unknown = set(loaded) - set(DEFAULT_CONFIG)
        if unknown:
            raise CallError("unknown config keys: %s" % ", ".join(sorted(unknown)))
        config.update(loaded)
    if not ENDPOINT_RE.match(str(config["endpoint"])):
        raise CallError("endpoint must look like PJSIP/<name>")
    if not CONTAINER_RE.match(str(config["container"])):
        raise CallError("container is not a valid Docker container name")
    quiet = (config["quiet_start"], config["quiet_end"])
    if any(quiet) and not all(isinstance(v, str) and TIME_RE.match(v) for v in quiet):
        raise CallError("quiet_start and quiet_end must both be HH:MM")
    for key in ("piper_port", "attempts", "retry_delay_s", "ring_timeout_s", "call_timeout_s", "poll_interval_s", "heads_up_s", "min_gap_s", "max_per_hour"):
        if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 0:
            raise CallError("%s must be a non-negative integer" % key)
    # The whole run must stay far below the one-day age at which another run sweeps its folder.
    # One attempt: heads-up wait, ring, call, the grace and the thank-you waits (polls), then the retry delay.
    polls = (GRACE_POLLS + 8) * config["poll_interval_s"]
    worst_case = config["attempts"] * (config["ring_timeout_s"] + config["call_timeout_s"] + config["retry_delay_s"] + config["heads_up_s"] + polls)
    if worst_case > 20 * 3600:
        raise CallError("attempts, delays and timeouts add up to more than 20 hours")
    if not 1 <= config["piper_port"] <= 65535:
        raise CallError("piper_port must be between 1 and 65535")
    if config["state_file"] is not None and not isinstance(config["state_file"], str):
        raise CallError("state_file must be a path or null")
    if not 1 <= config["poll_interval_s"] <= 60:
        # 0 would run `docker exec` back to back for the whole call window; a huge value would let a
        # run outlast the one-day age at which another run sweeps its folder.
        raise CallError("poll_interval_s must be between 1 and 60")
    if not 1 <= config["attempts"] <= 10:
        raise CallError("attempts must be between 1 and 10")
    if config["ring_timeout_s"] < 5 or config["call_timeout_s"] < 60:
        # A call must be allowed to ring and to finish; otherwise a retry could overlap a live call.
        raise CallError("ring_timeout_s must be at least 5 and call_timeout_s at least 60")
    if config["timezone"] is not None:
        try:
            ZoneInfo(str(config["timezone"]))
        except Exception:  # noqa: BLE001 - unknown zone names raise several error types
            raise CallError("timezone is not a known IANA zone name")
    for key in ("piper_host", "env_file"):
        if not isinstance(config[key], str) or not config[key]:
            raise CallError("%s must be a non-empty string" % key)
    return config


def load_env_file(path: str) -> Dict[str, str]:
    """Read KEY=VALUE lines from a private file. The file must not be readable by others."""
    resolved = Path(os.path.expanduser(path))
    try:
        mode = resolved.stat().st_mode & 0o777
    except FileNotFoundError:
        return {}
    except OSError:
        raise CallError("cannot read the env file")
    if mode & 0o077:
        raise CallError("the env file must have mode 0600")
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise CallError("cannot read the env file")
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export") and key[6:7].isspace():
            key = key[6:].strip()  # shell style: "export NAME=value"
        values[key] = value.strip().strip("'\"")
    return values


# ---------------------------------------------------------------------------------- speech (Piper)


class DeadlineReader:
    """Buffered reads from a socket that all stop at one overall deadline. A plain socket timeout
    restarts on every received byte, so a server trickling one byte at a time could hold it forever."""

    def __init__(self, sock, deadline: float, clock=time.monotonic):
        self.sock, self.deadline, self.clock = sock, deadline, clock
        self.buffer = b""

    def _fill(self) -> bool:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise CallError("speech server took too long")
        self.sock.settimeout(remaining)
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            raise CallError("speech server took too long")
        self.buffer += chunk
        return bool(chunk)

    def readline(self, limit: int) -> bytes:
        while b"\n" not in self.buffer[:limit] and len(self.buffer) < limit:
            if not self._fill():
                break
        end = self.buffer.find(b"\n", 0, limit)
        end = end + 1 if end != -1 else min(len(self.buffer), limit)
        line, self.buffer = self.buffer[:end], self.buffer[end:]
        return line

    def read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            if not self._fill():
                break
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data


def _read_event(handle):
    line = handle.readline(MAX_HEADER_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_HEADER_BYTES:
        raise CallError("speech server sent an oversized message")
    header = json.loads(line)
    data = header.get("data") or {}
    extra = header.get("data_length", 0)
    payload_len = header.get("payload_length", 0)
    if not (isinstance(extra, int) and isinstance(payload_len, int)) or extra < 0 or payload_len < 0:
        raise CallError("speech server sent a malformed message")
    if extra > MAX_WYOMING_PAYLOAD or payload_len > MAX_WYOMING_PAYLOAD:
        raise CallError("speech server sent an oversized message")
    if extra:
        body = handle.read(extra)
        if len(body) != extra:
            raise CallError("speech server sent a truncated message")
        data = dict(data, **json.loads(body))
    payload = handle.read(payload_len) if payload_len else b""
    if len(payload) != payload_len:
        raise CallError("speech server sent a truncated message")
    return header["type"], data, payload


def synthesize(host: str, port: int, text: str, timeout: int = 120) -> Tuple[int, int, int, bytes]:
    """Return (rate, width, channels, pcm) for one text using the Wyoming protocol."""
    try:
        deadline = time.monotonic() + timeout
        with socket.create_connection((host, port), timeout=timeout) as sock:
            request = {"type": "synthesize", "data": {"text": text}}
            sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
            handle = DeadlineReader(sock, deadline)
            fmt = None
            pcm = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise CallError("speech server took too long")
                event = _read_event(handle)
                if event is None:
                    raise CallError("speech server closed the connection early")
                kind, data, payload = event
                if kind == "audio-start":
                    fmt = (int(data["rate"]), int(data["width"]), int(data["channels"]))
                    if min(fmt) <= 0:
                        raise CallError("speech server sent an invalid audio format")
                    # Bounded so a bogus format cannot make the conversion build absurd buffers.
                    if not 8000 <= fmt[0] <= 192000 or fmt[2] > 8:
                        raise CallError("speech server sent an unsupported audio format")
                elif kind == "audio-chunk":
                    pcm += payload
                    if len(pcm) > MAX_PCM_BYTES:
                        raise CallError("speech server sent too much audio")
                elif kind == "audio-stop":
                    break
                elif kind == "error":
                    raise CallError("speech server reported an error")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        # TypeError/AttributeError: a malformed message (non-object data, null rate) must end as a
        # clean "ERROR:" line, never a traceback.
        raise CallError("cannot get speech from the speech server")
    if fmt is None or not pcm:
        raise CallError("speech server returned no audio")
    return fmt[0], fmt[1], fmt[2], bytes(pcm)


def resample(samples, src_rate: int, dst_rate: int):
    """Resample 16-bit mono audio. Down-sampling averages the source samples under each output
    sample, which acts as a cheap low-pass filter so the extra high frequencies do not alias."""
    if src_rate <= 0 or dst_rate <= 0:
        raise CallError("invalid audio sample rate")
    if src_rate == dst_rate or not len(samples):
        return samples
    out_len = int(len(samples) * dst_rate / src_rate)
    last = len(samples) - 1
    out = array.array("h")
    step = src_rate / dst_rate
    for i in range(out_len):
        start = i * step
        if step > 1:
            lo = int(start)
            hi = min(max(int(start + step), lo + 1), len(samples))
            window = samples[lo:hi]
            out.append(int(sum(window) / len(window)))
        else:
            j = int(start)
            a = samples[j]
            b = samples[j + 1] if j < last else a
            out.append(int(a + (b - a) * (start - j)))
    return out


def to_wav(rate: int, width: int, channels: int, pcm: bytes) -> bytes:
    """Convert 16-bit PCM to a mono 8 kHz WAV, the only WAV rate Asterisk can open."""
    if width != 2:
        raise CallError("expected 16-bit speech audio")
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        frames = len(samples) // channels
        samples = array.array("h", [sum(samples[i * channels:(i + 1) * channels]) // channels for i in range(frames)])
    try:
        samples = resample(samples, rate, SAMPLE_RATE)
    except MemoryError:
        raise CallError("speech audio is too large to convert")
    tail = array.array("h", [0] * (SAMPLE_RATE // 4))  # a quarter second of silence after each prompt
    samples.extend(tail)
    if sys.byteorder == "big":
        samples.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


# ---------------------------------------------------------------------------------- Asterisk (Docker)


class DockerAsterisk:
    """Talks to Asterisk by running small commands inside its container as the asterisk user."""

    def __init__(self, container: str, run: Callable = subprocess.run):
        self.container = container
        self._run = run

    def _exec(self, args: List[str], data: Optional[bytes] = None, check: bool = True):
        command = ["docker", "exec", "-i", "-u", "asterisk", self.container] + args
        try:
            result = self._run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise DockerError("cannot run docker")
        if check and result.returncode != 0:
            raise DockerError("a command inside the Asterisk container failed")
        return result

    def make_dir(self, path: str) -> None:
        self._exec(["mkdir", "-p", path])

    def write_file(self, path: str, data: bytes) -> None:
        self._exec(["sh", "-c", 'cat > "$1"', "sh", path], data=data)

    def read_file(self, path: str) -> Optional[str]:
        # A missing file is told by exit code 3, not by error text, which is translated in other locales.
        result = self._exec(["sh", "-c", 'if [ -e "$1" ]; then cat "$1"; else exit 3; fi', "sh", path], check=False)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", "replace").strip()
        if result.returncode == 3:
            return None
        # Anything else (container stopped, docker unavailable) must not look like "no marker yet".
        raise DockerError("cannot read call state from the Asterisk container")

    def remove(self, *paths: str) -> None:
        self._exec(["rm", "-rf"] + list(paths), check=False)

    def sweep_stale(self) -> None:
        """Remove prompt folders left behind by a killed run (older than a day). Best effort."""
        self._exec(["find", SPOOL + "/ceo", "-mindepth", "1", "-maxdepth", "1", "-mmin", "+1440", "-exec", "rm", "-rf", "{}", "+"], check=False)

    def originate(self, name: str, call_file: str) -> None:
        """Write the call file outside the watched folder, then move it in atomically."""
        staging = "%s/tmp/%s.call" % (SPOOL, name)
        target = "%s/outgoing/%s.call" % (SPOOL, name)
        self.write_file(staging, call_file.encode("utf-8"))
        self._exec(["mv", staging, target])

    def endpoint_available(self, endpoint: str) -> bool:
        name = endpoint.split("/", 1)[1]
        result = self._exec(["asterisk", "-rx", "pjsip show contacts"])  # a failure is an error, not "no contacts"
        text = result.stdout.decode("utf-8", "replace")
        pattern = re.compile(r"^\s*Contact:\s+%s/" % re.escape(name))
        # Asterisk shows "Avail" for a qualified contact and "NonQual" for a registered contact whose
        # endpoint has qualify turned off; "Unavail" is a contact that stopped answering.
        return any(pattern.match(line) and re.search(r"\b(Avail|NonQual)\b", line) for line in text.splitlines())


def build_call_file(endpoint: str, call_id: str, option_count: int, ring_timeout: int) -> str:
    if not ENDPOINT_RE.match(endpoint) or not re.match(r"^[0-9a-f]{16,64}\Z", call_id):
        raise CallError("invalid call parameters")
    return "\n".join(
        [
            "Channel: %s" % endpoint,
            "CallerID: Claudio <0>",
            "MaxRetries: 0",
            "WaitTime: %d" % ring_timeout,
            "Context: ceo-ask",
            "Extension: s",
            "Priority: 1",
            "Setvar: CEO_ID=%s" % call_id,
            "Setvar: CEO_OPTIONS=%d" % option_count,
            "",
        ]
    )


def in_quiet_hours(now_hm: str, start: Optional[str], end: Optional[str]) -> bool:
    """True when now_hm ("HH:MM") falls in [start, end), where the window may wrap past midnight."""
    if not start or not end or start == end:
        return False
    if start < end:
        return start <= now_hm < end
    return now_hm >= start or now_hm < end


# ---------------------------------------------------------------------------------- one attempt


SYNTH_BUDGET_S = 300  # all prompts of one request; each single synthesis also has its own deadline
GRACE_POLLS = 10  # polls to wait for a call that is still live at call_timeout_s


def run_attempt(asterisk, config: Dict, call_id: str, option_count: int, sleep=time.sleep, clock=time.monotonic) -> Dict:
    """Place one call and wait for its outcome. Never trusts the result file beyond a digit check."""
    base = "%s/ceo/%s" % (SPOOL, call_id)
    asterisk.remove(*["%s/%s" % (base, marker) for marker in ("answered", "result", "done")])
    asterisk.originate(
        "ceo-%s" % call_id,
        build_call_file(config["endpoint"], call_id, option_count, config["ring_timeout_s"]),
    )
    started = clock()
    answer_deadline = started + config["ring_timeout_s"] + 15
    total_deadline = started + config["ring_timeout_s"] + config["call_timeout_s"]
    answered = False
    result = None
    while clock() < total_deadline:
        # Asterisk's FILE() truncates before it writes, so an empty result means "being written".
        result = asterisk.read_file(base + "/result") or None
        if result is not None:
            break
        if asterisk.read_file(base + "/done") is not None:
            break
        if not answered:
            answered = asterisk.read_file(base + "/answered") is not None
            if not answered and clock() > answer_deadline:
                return {"status": "unanswered"}
        sleep(config["poll_interval_s"])
    if result is not None:
        # Let the thank-you message finish before the audio files are removed.
        for _ in range(8):
            try:
                if asterisk.read_file(base + "/done") is not None:
                    break
            except DockerError:
                break  # the digit is already read: do not lose the decision over the thank-you wait
            sleep(config["poll_interval_s"])
    else:
        result = asterisk.read_file(base + "/result") or None
        if result is None and answered:
            # The call is still live at the deadline: the owner may be confirming right now. Give the
            # dialplan a short grace to finish before the folder is removed, so a confirmation is not lost.
            for _ in range(GRACE_POLLS):
                sleep(config["poll_interval_s"])
                done = asterisk.read_file(base + "/done") is not None
                result = asterisk.read_file(base + "/result") or None
                if result is not None or done:
                    break
    if result is None:
        if not answered and asterisk.read_file(base + "/answered") is None:
            return {"status": "unanswered"}
        if asterisk.read_file(base + "/done") is None:
            # The dialplan never signalled its end, so the call may still be open: it is not a hangup,
            # and `ask` must not start a second call on top of it.
            return {"status": "timeout"}
        return {"status": "hangup"}
    if result == "undecided":
        return {"status": "undecided"}
    if re.fullmatch(r"[1-8]", result) and int(result) <= option_count:
        return {"status": "decided", "choice": int(result)}
    raise CallError("unexpected value in the call result")


# ---------------------------------------------------------------------------------- notification


def send_telegram(token: str, chat_id: str, text: str, opener: Callable = urllib.request.urlopen, silent: bool = False) -> bool:
    """Send a chat message. Returns False on any failure; the token never appears in output."""
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    fields = {"chat_id": chat_id, "text": text}
    if silent:
        fields["disable_notification"] = "true"
    body = urllib.parse.urlencode(fields).encode("utf-8")
    try:
        with opener(urllib.request.Request(url, data=body), timeout=15) as response:
            return bool(json.loads(response.read().decode("utf-8")).get("ok"))
    except Interrupted:
        raise  # a stop request must not be swallowed by a failed send
    except Exception:  # noqa: BLE001 - any failure means "not sent"; details could contain the token
        return False


def notification_text(question: str, options: List[str], status: str) -> str:
    lines = ["Decisión pendiente. " + NOTIFY.get(status, ""), "", question, ""]
    lines += ["%d. %s" % (n, text) for n, text in enumerate(options, 1)]
    return "\n".join(lines).strip()


HEADS_UP = "Hola, soy Claudio. Te voy a llamar en un momento, ¿puedes atender?"


def wait_for_phone(asterisk, config: Dict, env: Dict[str, str], notifier: Callable, sleep, clock, state: Optional[Dict] = None) -> bool:
    """Make sure the phone is registered before calling. A phone that is not registered (for
    example an iPhone app that went to sleep) gets a chat message, then we wait a while."""
    if asterisk.endpoint_available(config["endpoint"]):
        return True
    token, chat_id = env.get("CEO_TELEGRAM_TOKEN"), env.get("CEO_TELEGRAM_CHAT_ID")
    if not (token and chat_id) or not config["heads_up_s"]:
        return False
    state = state if state is not None else {}
    if not state.get("messaged"):  # one heads-up per run, even if the phone drops again on a retry
        if notifier(token, chat_id, HEADS_UP):
            state["messaged"] = True  # only a heads-up that really went out counts
    deadline = clock() + config["heads_up_s"]
    while clock() < deadline:
        sleep(config["poll_interval_s"])
        if asterisk.endpoint_available(config["endpoint"]):
            return True
    return False


# ---------------------------------------------------------------------------------- the whole flow


def ask(
    request,
    config: Dict,
    env: Dict[str, str],
    asterisk,
    synth: Optional[Callable] = None,
    notifier: Optional[Callable] = None,
    sleep=time.sleep,
    clock=time.monotonic,
    now: Optional[Callable] = None,
    wall: Callable = time.time,
) -> Dict:
    synth = synth or synthesize
    notifier = notifier or send_telegram
    if now is None:
        zone = ZoneInfo(config["timezone"]) if config.get("timezone") else None
        now = lambda: datetime.now(zone)  # noqa: E731
    clean = validate_request(request)
    options = clean["options"]
    quiet = lambda: in_quiet_hours(now().strftime("%H:%M"), config.get("quiet_start"), config.get("quiet_end"))  # noqa: E731
    if quiet():
        return notify_outcome({"status": "deferred", "attempt": 0}, clean, env, notifier, silent=True)
    reached = {"owner": False}
    send = notifier

    def notifier(*args, **kwargs):  # noqa: F811 - remembers whether anything reached the owner
        sent = send(*args, **kwargs)
        reached["owner"] = reached["owner"] or bool(sent)
        return sent
    run_lock = acquire_run_lock(config)  # one ask at a time: two runs must never ring together
    try:
        stamp = check_throttle(config, wall)
    except BaseException:
        run_lock.close()
        raise
    dialled = False
    keep_folder = False
    completed = False

    def settle():
        """Give the throttle slot back only if nothing reached the owner: no call, no chat message."""
        if not (dialled or reached["owner"]):
            release_throttle(config, stamp)

    call_id = secrets.token_hex(8)
    base = "%s/ceo/%s" % (SPOOL, call_id)
    try:
        asterisk.sweep_stale()
        asterisk.make_dir(base)
        synth_started = clock()
        for name, text in build_prompts(clean["question"], options).items():
            if clock() - synth_started > SYNTH_BUDGET_S:
                raise CallError("speech took too long for the whole request")
            wav = to_wav(*synth(config["piper_host"], config["piper_port"], text))
            asterisk.write_file("%s/%s.wav" % (base, name), wav)
        outcome = {"status": "unanswered"}
        heads_up_state: Dict = {}
        for attempt in range(1, config["attempts"] + 1):
            # Quiet hours are checked before every attempt, not only the first: a retry that lands
            # after the window opens must not ring.
            if attempt > 1 and quiet():
                outcome = {"status": "deferred", "attempt": attempt - 1}
                break
            if not wait_for_phone(asterisk, config, env, notifier, sleep, clock, heads_up_state):
                # An unregistered endpoint can only ring out, so dialling is pointless; the heads-up
                # message (if configured) was already sent. Stop and tell the owner.
                outcome = {"status": "unanswered", "reason": "phone_not_registered", "attempt": attempt}
                break
            if quiet():
                # The heads-up wait can take minutes: look at the clock again right before dialling.
                outcome = {"status": "deferred", "attempt": attempt - 1}
                break
            dialled = True  # a call is about to be placed: this ask keeps its throttle slot
            outcome = run_attempt(asterisk, config, call_id, len(options), sleep=sleep, clock=clock)
            outcome["attempt"] = attempt
            # A hangup is the owner's choice: they picked up and put the phone down, so no re-ring.
            if outcome["status"] == "timeout":
                keep_folder = True  # the owner may still be on the line, and the dialplan still needs its prompts
            if outcome["status"] in ("decided", "undecided", "hangup", "timeout"):
                break
            if attempt < config["attempts"]:
                sleep(config["retry_delay_s"])
        completed = True  # the final chat message (if any) is sent below, and settle() runs after it
    except CallError as error:
        # With docker failing mid-call the owner may still be confirming: leave the folder for the
        # dialplan to write into (the daily sweep removes it) instead of deleting it underneath.
        keep_folder = dialled and isinstance(error, MayBeLive)
        if keep_folder and isinstance(error, DockerError):
            # One failed read must not lose a confirmation that is already on disk: try once more.
            try:
                digit = asterisk.read_file("%s/result" % base)
            except CallError:
                digit = None
            if digit and re.fullmatch(r"[1-8]", digit) and int(digit) <= len(options):
                keep_folder = False
                return {"status": "decided", "choice": int(digit), "option": options[int(digit) - 1],
                        "attempt": max(1, locals().get("attempt", 1)), "notified": False}
        # The decision is still pending: tell the owner by chat, then let the error reach the caller.
        # If the call may be live, say that an answer given now is not recorded.
        notify_outcome({"status": "error_live" if keep_folder else "error"}, clean, env, notifier)
        raise
    except BaseException:
        # Anything else (an unexpected bug) must not delete the folder of a call that may be live, and
        # the owner still hears that the decision is pending.
        keep_folder = dialled
        try:
            notify_outcome({"status": "error_live" if keep_folder else "error"}, clean, env, notifier)
        except Exception:  # noqa: BLE001 - never hide the original problem
            pass
        raise
    finally:
        if not completed:
            settle()  # an error is propagating; its chat message (if any) was sent above
        if not keep_folder:
            try:
                asterisk.remove(base)
            except Interrupted:
                raise  # a stop request is never swallowed
            except CallError:
                pass  # best effort: the daily sweep removes it, and the real error must not be replaced
        run_lock.close()
    if outcome["status"] == "decided":
        outcome["option"] = options[outcome["choice"] - 1]
        outcome["notified"] = False  # same keys on every outcome; a decision needs no chat message
        return outcome
    try:
        return notify_outcome(outcome, clean, env, notifier, silent=outcome["status"] == "deferred")
    finally:
        settle()


class _NoLock:
    def close(self) -> None:
        pass


def acquire_run_lock(config: Dict):
    """Hold an exclusive lock for the length of one ask. The lock vanishes with the process, even when
    it is killed. Without a state file there is nothing to lock on, and the lock is off."""
    path = config.get("state_file")
    if not path:
        return _NoLock()
    resolved = Path(os.path.expanduser(path + ".lock"))
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = open(resolved, "a+", encoding="utf-8")
    except OSError:
        raise CallError("cannot create the run lock file")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise CallError("another ask is still running; wait for it to finish")
    return handle


def _read_starts(path: Path, now_s: float) -> List[float]:
    starts = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")  # a damaged file must not crash
    except OSError:
        return starts
    for line in text.splitlines():
        try:
            value = float(line.strip())
        except ValueError:
            continue
        if abs(now_s - value) < 86400:  # a start slightly in the future (clock stepped back) still counts
            starts.append(value)
    return starts


def _write_starts(path: Path, starts: List[float]) -> None:
    """Replace the state file whole (temp file + rename), so a kill can never leave it empty."""
    temp = path.with_name(path.name + ".tmp.%d" % os.getpid())
    try:
        temp.write_text("".join("%.6f\n" % value for value in starts), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        raise CallError("cannot write the throttle state file")
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _state_lock(path: Path):
    """Lock for read-modify-write of the state file. It is a separate file, because the state file
    itself is replaced (a new inode) and a lock on the old one would protect nothing."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(path.with_name(path.name + ".state.lock"), "a+", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def check_throttle(config: Dict, wall: Callable = time.time) -> Optional[float]:
    """Refuse a new ask that starts too soon after the previous one, or beyond `max_per_hour`, so a
    confused or manipulated agent cannot ring the owner over and over. The state file keeps one start
    time per line (the last 24 hours); a start is recorded when an ask passes these checks."""
    path, gap, per_hour = config.get("state_file"), config.get("min_gap_s", 0), config.get("max_per_hour", 0)
    if not path or not (gap or per_hour):
        return None
    resolved = Path(os.path.expanduser(path))
    now_s = wall()
    try:
        lock = _state_lock(resolved)
    except OSError:
        raise CallError("cannot write the throttle state file")
    with lock:
        starts = _read_starts(resolved, now_s)
        if gap and starts and now_s - max(starts) < gap:  # also true for a start in the future
            raise CallError("asked again too soon: wait %d more seconds" % (gap - (now_s - max(starts))))
        if per_hour and sum(1 for value in starts if now_s - value < 3600) >= per_hour:  # future starts count
            raise CallError("too many asks in the last hour (limit %d)" % per_hour)
        _write_starts(resolved, starts + [now_s])
    return now_s


def release_throttle(config: Dict, stamp: Optional[float]) -> None:
    """Take back the start recorded by check_throttle when nothing reached the owner (no call and no
    chat message), so such asks do not use up the limits."""
    path = config.get("state_file")
    if stamp is None or not path:
        return
    resolved = Path(os.path.expanduser(path))
    try:
        with _state_lock(resolved):
            starts = _read_starts(resolved, stamp)
            for index, value in enumerate(starts):
                if abs(value - stamp) < 1e-6:
                    del starts[index]  # only our own line, not another ask's from the same second
                    break
            _write_starts(resolved, starts)
    except Interrupted:
        raise
    except (OSError, CallError):
        pass  # best effort: the limit then stays slightly stricter than needed


def notify_outcome(outcome: Dict, clean: Dict, env: Dict[str, str], notifier: Callable, silent: bool = False) -> Dict:
    """Tell the owner by chat message that the decision is still pending."""
    token, chat_id = env.get("CEO_TELEGRAM_TOKEN"), env.get("CEO_TELEGRAM_CHAT_ID")
    outcome["notified"] = False
    if token and chat_id:
        text = notification_text(clean["question"], clean["options"], outcome.get("reason") or outcome["status"])
        sent = notifier(token, chat_id, text, silent=True) if silent else notifier(token, chat_id, text)
        outcome["notified"] = bool(sent)
    return outcome


# ---------------------------------------------------------------------------------- CLI


def exit_cleanly_on_sigterm() -> None:
    """Turn a polite kill into a normal exit so the per-call folder is still removed."""
    def stop(signum, frame):
        raise Interrupted("interrupted before the call finished")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)  # Ctrl-C ends the same way as a kill


def read_request(source: str) -> str:
    """Read the request JSON: stdin or a regular file, never more than MAX_REQUEST_BYTES (a device
    such as /dev/zero must not be able to fill memory)."""
    try:
        if source == "-":
            raw = sys.stdin.read(MAX_REQUEST_BYTES + 1)
            if len(raw.encode("utf-8", "replace")) > MAX_REQUEST_BYTES:
                raise CallError("the request is longer than %d bytes" % MAX_REQUEST_BYTES)
        else:
            if not stat.S_ISREG(os.stat(source).st_mode):
                raise CallError("the request must be a regular file")
            with open(source, "rb") as handle:
                data = handle.read(MAX_REQUEST_BYTES + 1)
            raw = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise CallError("cannot read the request file")
    if len(raw) > MAX_REQUEST_BYTES:
        raise CallError("the request is longer than %d bytes" % MAX_REQUEST_BYTES)
    return raw


def cmd_ask(args) -> int:
    config = load_config(args.config)
    env = load_env_file(config["env_file"])
    exit_cleanly_on_sigterm()
    raw = read_request(args.request)
    try:
        request = json.loads(raw)
    except (ValueError, RecursionError):
        raise CallError("the request is not valid JSON")
    outcome = ask(request, config, env, DockerAsterisk(config["container"]))
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "decided" else 3


# Public-domain text (Miguel de Cervantes, Don Quijote de la Mancha, 1605) for test calls: it is
# long enough to judge the voice and free of any copyright.
TEST_PASSAGE = (
    "Esto es una llamada de prueba. Te leo un fragmento del Quijote, de Cervantes, que es de dominio público. "
    "En un lugar de la Mancha, de cuyo nombre no quiero acordarme, no ha mucho tiempo que vivía un hidalgo "
    "de los de lanza en astillero, adarga antigua, rocín flaco y galgo corredor. "
    "Una olla de algo más vaca que carnero, salpicón las más noches, duelos y quebrantos los sábados, "
    "lentejas los viernes, algún palomino de añadidura los domingos, consumían las tres partes de su hacienda."
)
TEST_OPTIONS = ["Suena bien", "Hay un problema con el sonido"]


def cmd_test_call(args) -> int:
    config = load_config(args.config)
    if args.ignore_quiet_hours:
        config["quiet_start"] = config["quiet_end"] = None
    env = load_env_file(config["env_file"])
    exit_cleanly_on_sigterm()
    request = {"question": TEST_PASSAGE, "options": TEST_OPTIONS}
    outcome = ask(request, config, env, DockerAsterisk(config["container"]))
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "decided" else 3


def cmd_check(args) -> int:
    config = load_config(args.config)
    ok = True
    try:
        synthesize(config["piper_host"], config["piper_port"], "prueba")
        print("speech: ok")
    except CallError as error:
        ok = False
        print("speech: FAILED (%s)" % error)
    try:
        available = DockerAsterisk(config["container"]).endpoint_available(config["endpoint"])
        # Not a failure: a sleeping softphone is normal, and `ask` sends a heads-up and waits for it.
        print("phone endpoint: %s" % ("registered" if available else "NOT registered (ask will send a heads-up message and wait)"))
    except CallError as error:
        ok = False
        print("asterisk: FAILED (%s)" % error)
    env = load_env_file(config["env_file"])
    print("telegram: %s" % ("configured" if env.get("CEO_TELEGRAM_TOKEN") and env.get("CEO_TELEGRAM_CHAT_ID") else "not configured"))
    return 0 if ok else 1


def telegram_api(token: str, method: str):
    """Call a read-only bot API method. Errors never mention the URL, which holds the token."""
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot%s/%s" % (token, method), timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Interrupted:
        raise
    except Exception:  # noqa: BLE001 - the URL holds the token, so report nothing specific
        raise CallError("cannot reach the chat service, or the token was refused (%s)" % method)
    if not isinstance(body, dict) or not body.get("ok"):
        raise CallError("the chat service refused the request (%s)" % method)
    return body.get("result")


def expect_type(value, kind, method: str):
    """The chat service's answer must have the documented shape; None counts as empty."""
    if value is None:
        return kind()
    if not isinstance(value, kind):
        raise CallError("unexpected answer from the chat service (%s)" % method)
    return value


def cmd_telegram_setup(args) -> int:
    config = load_config(args.config)
    token = load_env_file(config["env_file"]).get("CEO_TELEGRAM_TOKEN")
    if not token:
        raise CallError("put CEO_TELEGRAM_TOKEN in the env file first")
    bot = expect_type(telegram_api(token, "getMe"), dict, "getMe")
    print("This token belongs to the bot @%s" % bot.get("username", "?"))
    webhook = expect_type(telegram_api(token, "getWebhookInfo"), dict, "getWebhookInfo")
    if webhook.get("url"):
        print("A webhook is set on this bot, which stops getUpdates from returning messages.")
        return 1
    seen = {}
    for update in expect_type(telegram_api(token, "getUpdates"), list, "getUpdates"):
        if not isinstance(update, dict):
            continue
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            part = update.get(key)
            chat = part.get("chat") if isinstance(part, dict) else None
            if isinstance(chat, dict) and isinstance(chat.get("id"), (int, str)):
                seen.pop(chat["id"], None)  # move to the end: the dict then runs oldest to newest
                seen[chat["id"]] = chat.get("type", "?")
    if not seen:
        print("No messages found. Open the bot @%s in the chat app, press Start, send any message, then run this again." % bot.get("username", "?"))
        return 1
    if len(seen) > 1:
        print("%d chats have written to this bot; pick only your own. Listed oldest first; the last one is the most recent." % len(seen))
    for chat_id, kind in seen.items():
        print("CEO_TELEGRAM_CHAT_ID=%s  (chat type: %s)" % (chat_id, kind))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="JSON config file (see SKILL.md); defaults are used without it")
    sub = parser.add_subparsers(dest="command", required=True)
    ask_parser = sub.add_parser("ask", help="place the call")
    ask_parser.add_argument("--request", required=True, help="request JSON file, or - for stdin")
    ask_parser.set_defaults(func=cmd_ask)
    test_parser = sub.add_parser("test-call", help="phone the owner and read a public-domain passage")
    test_parser.add_argument("--ignore-quiet-hours", action="store_true", help="call even inside the quiet hours")
    test_parser.set_defaults(func=cmd_test_call)
    sub.add_parser("check", help="verify speech and the phone endpoint").set_defaults(func=cmd_check)
    sub.add_parser("telegram-setup", help="find the chat id for the bot").set_defaults(func=cmd_telegram_setup)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CallError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
