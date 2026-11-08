#!/usr/bin/env python3
"""PreToolUse guard for the `claudio` agent: allow only ceo_call.py invocations through Bash.

The agent reads council positions that can quote untrusted text, so its shell must not be able to
do anything else (for example print the env file that holds the chat token). Reads the hook JSON on
stdin; exits 0 to allow and 2 to block (the message on stderr goes back to the agent). Fails closed.

`test-call` (it phones the owner with no decision pending), `test-call --ignore-quiet-hours` and
`telegram-setup` are deliberately not allowed: they are for the owner to run.

Allowed, with <path> = `~/.claude/skills/ceo-call/scripts` or an absolute path ending in
`/.claude/skills/ceo-call/scripts` (optionally prefixed by `ssh <alias>`), made only of plain
path/word characters, no quotes, no shell operators:
    python3 <path>/ceo_call.py [--config <path>] check
    python3 <path>/ceo_call.py [--config <path>] ask --request <path>
    python3 <path>/ceo_call.py [--config <path>] ask --request - <<'CEO_REQUEST'   (JSON lines follow,
        the last line is CEO_REQUEST; the quoted delimiter means the body is never expanded)
"""
import json
import re
import sys

WORD = r"[A-Za-z0-9_./@:=~+-]+"
# Pinned to the installed skill: a ceo_call.py planted elsewhere (a cloned repo, /tmp) must not pass.
# Absolute or ~ paths only (a relative one depends on the working directory), and no ".." segment.
SCRIPT = r"(?:python3\s+)?(?:~/|/)(?:(?!\.{1,2}/)[A-Za-z0-9_.+-]+/)*\.claude/skills/ceo-call/scripts/ceo_call\.py"
CONFIG = r"(?:--config\s+%s\s+)?" % WORD
SSH = r"(?:ssh\s+[A-Za-z0-9_.@][A-Za-z0-9_.@-]*\s+)?"  # no ssh options: -o ProxyCommand would run anything
ACTION = r"(?:check|ask\s+--request\s+(?:-|%s))" % WORD
PLAIN = re.compile(r"^%s%s\s*%s\s*%s$" % (SSH, SCRIPT, CONFIG, ACTION))
HEREDOC_HEAD = re.compile(r"^%s%s\s*%s\s*ask\s+--request\s+-\s+<<'CEO_REQUEST'$" % (SSH, SCRIPT, CONFIG))
DELIMITER = "CEO_REQUEST"


def allowed(command: str) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    command = command.strip("\n")
    if "\n" not in command:
        return bool(PLAIN.match(command.strip()))
    lines = command.split("\n")
    head, body, tail = lines[0].strip(), lines[1:-1], lines[-1]
    if tail != DELIMITER or any(line == DELIMITER for line in body):
        return False
    return bool(HEREDOC_HEAD.match(head))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command")
    except Exception:  # noqa: BLE001 - anything unreadable is blocked
        command = None
    if allowed(command):
        return 0
    print("Blocked: this agent may only run ceo_call.py (check, ask, test-call). See the ceo-call skill.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
