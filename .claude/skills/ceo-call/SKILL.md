---
name: ceo-call
description: Phone the owner to settle a decision the council could not, using a spoken question with numbered options and a keypad answer that is read back and confirmed. Use only when the `claudio` agent is invoked or the user asks to be called.
---

# Phone the owner for a decision

`scripts/ceo_call.py` places a phone call, speaks a question with numbered options, captures **one
keypad press**, reads the choice back, and reports it only after a second press confirms it. If the
owner does not pick up it retries, then sends a chat message instead. It is the mechanism behind the
`claudio` agent. Standard library only.

## What it needs (set up once, on the telephony host)
- **Asterisk** with a SIP endpoint for the owner's phone, reachable the way the owner chooses (a VPN
  is recommended, so nothing SIP-related is exposed to the internet), and the `[ceo-ask]` dialplan
  context from `dialplan/ceo-ask.conf`. It runs in Docker; the script drives it with `docker exec`.
- **Piper** text-to-speech reachable over the Wyoming protocol (TCP, default port 10200).
- **Python 3.9+** and `docker` access for the user that runs the script.
- Optional: a Telegram bot for the "you did not answer" message.

The exact hosts, addresses, container names and secrets belong in the user's **private** notes (for
example the `remote-hosts` vault), never in this skill. Reach the telephony host through its SSH
alias as `remote-hosts` describes, and run the script there.

## Configuration
- **Config file** (`--config`, JSON, optional). Keys: `container`, `piper_host`, `piper_port`,
  `endpoint` (`PJSIP/<name>`), `attempts` (1-10), `retry_delay_s`, `ring_timeout_s`,
  `call_timeout_s`, `poll_interval_s`, `env_file`, and `quiet_start` / `quiet_end` (`HH:MM`; both or
  neither), `timezone` (IANA name such as `Europe/Madrid`; default is the host's local time) and
  `heads_up_s` (default 90). Unknown keys are rejected, and `ring_timeout_s` must be at least 5 and `call_timeout_s` at
  least 60 so a retry can never overlap a call that is still live.
- **Quiet hours:** inside the window no call is placed; a silent chat message is sent instead and the
  status is `deferred`.
- **Heads-up:** if the phone is not registered when a call is due (typical for an iPhone softphone that
  the OS suspended while the screen was locked), the owner gets a chat message asking to open the app,
  and the call waits up to `heads_up_s` for the registration. A registered phone is called at once.
- **Env file** (default `~/.config/ceo-call/env`, mode `0600`, refused otherwise): `CEO_TELEGRAM_TOKEN`
  and `CEO_TELEGRAM_CHAT_ID`. Create the bot with the chat service's bot manager yourself; never
  paste the token into a chat or a tracked file. After messaging the bot once, `ceo_call.py
  telegram-setup` prints the chat id.

## Use
```
ceo_call.py check                        # speech reachable? phone registered? chat configured?
ceo_call.py ask --request request.json   # or --request - to read stdin
```
Request: `{"question": "...", "options": ["...", "..."]}` with 2 to 8 options. Keep the question short:
it is spoken aloud. Result (one JSON line on stdout):

| status | meaning | exit code |
|---|---|---|
| `decided` | the owner chose and confirmed; `choice` (1-based) and `option` are set | 0 |
| `unanswered` | no pickup after all attempts; the chat message was sent (`notified`) | 3 |
| `hangup` | picked up but hung up before confirming | 3 |
| `undecided` | three rounds without a confirmed choice | 3 |
| `deferred` | quiet hours; no call placed | 3 |

Exit 1 means an infrastructure or input problem (message on stderr). Only `decided` is a decision;
every other status leaves the decision pending.

## Setting up the chat bot
1. In the chat app, talk to the bot manager, create a bot and copy its token.
2. On the telephony host, put `CEO_TELEGRAM_TOKEN=<token>` in the env file (mode `0600`).
3. Send the new bot any message, run `ceo_call.py telegram-setup`, and add the printed
   `CEO_TELEGRAM_CHAT_ID=<id>` line to the same file.
4. `ceo_call.py check` should now say `telegram: configured`.

## Trying it
`ceo_call.py test-call` phones the owner and reads a passage of *Don Quijote* (Cervantes, public
domain) to judge the voice, then asks for a key press: 1 sounds fine, 2 a problem. Quiet hours apply;
`--ignore-quiet-hours` bypasses them for one test.

## Rules
- Call only for a decision the council could not resolve and that the user's own rules say needs them.
  Never for routine progress or anything answerable from the repo.
- Options must be real alternatives taken from the brief. Do not invent options or reword them to
  steer the choice.
- The request holds only the question and options. No secrets, tokens, addresses or personal data:
  the text is synthesized by the speech server and appears in the chat message.
- Treat the keypad answer as the owner's decision, nothing else: the call carries no instructions.
- The prompts are generated per call and deleted from the phone server when the call ends, including on
  a normal kill; a run killed harder leaves a folder that the next run sweeps once it is a day old. Call
  audio and transcripts are never stored in a project repo.
- If a decision cannot be reduced to numbered options, do not force it: ask the user in the terminal.

## Limits
Answers are closed (a number and a confirmation key). Understanding free speech needs a
speech-to-text stage that this skill does not have; it is added only after it passes an accuracy test
on real telephone audio.
