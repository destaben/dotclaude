#!/usr/bin/env python3
"""PreToolUse guard for the `claudio` agent: allow only ceo_call.py invocations through Bash.

The agent reads council positions that can quote untrusted text, so its shell must not be able to
do anything else (for example print the env file that holds the chat token). Reads the hook JSON on
stdin; exits 0 to allow and 2 to block (the message on stderr goes back to the agent). Fails closed.

`test-call` (it phones the owner with no decision pending), `test-call --ignore-quiet-hours` and
`telegram-setup` are deliberately not allowed: they are for the owner to run.

Allowed (optionally prefixed by `ssh <alias>`, with no ssh options), only with the script at exactly
`~/.claude/skills/ceo-call/scripts/ceo_call.py` (over ssh, only this `~` form, single-quoted so the remote
shell expands it; locally, also this machine's own absolute home path), no quotes, no shell operators, no `..`:
    python3 <script> --config ~/.config/ceo-call/config.json check
    python3 <script> --config ~/.config/ceo-call/config.json ask --request - <<'CEO_REQUEST'   (JSON lines follow, the last line
        is CEO_REQUEST; the quoted delimiter means the body is never expanded). A request file path
        is not accepted: the agent has no way to write a file, and an existing one must not be spoken.
"""
import json
import os
import re
import sys

HOME_SCRIPT = "~/.claude/skills/ceo-call/scripts/ceo_call.py"
# Exactly one config file: a second one could switch the throttle off (state_file: null).
HOME_CONFIG = r"~/\.config/ceo-call/config\.json"
# The ssh prefix below takes no ssh options: -o ProxyCommand would run anything.
DELIMITER = "CEO_REQUEST"


def build_patterns(home: str):
    """Pin the script to the one installed copy. Only that exact path passes: the `~` form (which a
    remote host expands for itself) or this machine's own absolute home path. Any other file named
    ceo_call.py, however deep its path ends in .claude/skills/ceo-call/scripts, is refused."""
    local_script = home.rstrip("/") + "/.claude/skills/ceo-call/scripts/ceo_call.py"
    local_config = home.rstrip("/") + "/.config/ceo-call/"
    script_local = r"(?:python3 +)?(?:%s|%s)" % (re.escape(HOME_SCRIPT), re.escape(local_script))
    # Over ssh the local shell must not expand the ~, so the remote paths are single-quoted: the local
    # shell strips the quotes and the remote shell expands the ~ in its own home.
    script_remote = r"(?:python3 +)?'%s'" % re.escape(HOME_SCRIPT)
    # The config is mandatory: without it the script falls back to defaults, which have no quiet hours.
    config_local = r"--config +(?:%s|%sconfig\.json) +" % (HOME_CONFIG, re.escape(local_config))
    config_remote = r"--config +'%s' +" % HOME_CONFIG
    action = r"check"
    heredoc = r"ask +--request +- +<<'CEO_REQUEST'"
    patterns = []
    for ssh, script, config in (("", script_local, config_local), (r"ssh +[A-Za-z0-9_.@][A-Za-z0-9_.@-]* +", script_remote, config_remote)):
        patterns.append((re.compile(r"^%s%s +%s%s\Z" % (ssh, script, config, action)),
                         re.compile(r"^%s%s +%s%s\Z" % (ssh, script, config, heredoc))))
    return patterns


def allowed(command: str, home: str = None) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    # Only "\n" may separate lines. Any other control character (a carriage return, a vertical tab,
    # NUL ...) could make bash read a heredoc delimiter or a command differently from this guard.
    if any(ord(ch) < 32 and ch != "\n" or ord(ch) == 127 for ch in command):
        return False
    if ".." in command.split("<<")[0]:
        return False
    patterns = build_patterns(home if home is not None else os.path.expanduser("~"))
    if command.endswith("\n"):
        command = command[:-1]  # one trailing newline is harmless; no other surrounding whitespace is
    if "\n" not in command:
        return any(plain.match(command) for plain, _ in patterns)
    lines = command.split("\n")
    head, body, tail = lines[0], lines[1:-1], lines[-1]
    if tail != DELIMITER or any(line == DELIMITER for line in body):
        return False
    return any(heredoc.match(head) for _, heredoc in patterns)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command")
    except Exception:  # noqa: BLE001 - anything unreadable is blocked
        command = None
    if allowed(command):
        return 0
    print("Blocked: this agent may only run ceo_call.py (check, ask). See the ceo-call skill.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
