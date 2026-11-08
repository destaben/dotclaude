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
  neither; checked at the start, before every retry and again right before each dial, after any
  heads-up wait), `timezone` (IANA name such as `Europe/Madrid`; default is the host's local time), `heads_up_s` (default 90),
  `min_gap_s` (default 120), `max_per_hour` (default 6), `max_per_day` (default 24), `state_file` and `lock_file`. `piper_port` must be 1-65535.
  Unknown keys are rejected, and `ring_timeout_s` must be at least 5 and `call_timeout_s` at
  least 60 so a retry can never overlap a call that is still live. `poll_interval_s` must be 1 to 60
  (0 would hammer `docker exec`). A call still live at `call_timeout_s` (its folder is then kept) gets a short grace (10 polls) so a
  confirmation given right at the deadline is not lost.
- **One ask at a time:** an exclusive lock (`lock_file`, default `~/.local/state/ceo-call/run.lock`; set `state_file: null` and it stays on, only `lock_file: null` turns it off; released even if the process is killed)
  is held for the whole run, so a second `ask` that starts meanwhile fails with `another ask is still
  running` instead of ringing the owner on top of the first.
- **Throttle:** a new `ask` that starts less than `min_gap_s` after the previous one is refused with an
  error (`asked again too soon`), and so is any `ask` beyond `max_per_hour` in an hour or `max_per_day` in 24 hours (`too many asks`).
  An `ask` gives its slot back only when nothing reached the owner: no call and no chat message
  of any kind (heads-up, "not connected" notice, error notice). So a broken speech server or an asleep
  phone cannot be used to spam the chat. A failure before dialling (speech server down, or a call file that definitely never got in) keeps no slot on
  purpose: a transient fault must not lock the owner out, and a loop of failing asks is still serialised by the run
  lock and only drives local speech synthesis, never a call or a message. A refused `ask` (too soon, too many, another running) sends no
  chat message either, for the same reason; the calling workflow reports the decision as still pending. This spaces out and caps the calls a confused or manipulated agent can cause; it does not make a
  loop impossible (up to `max_per_hour` asks, each with up to `attempts` calls, can still ring). The
  limits are per host (each machine keeps its own `state_file`), so calling through two listed hosts
  doubles them; that is the owner's choice when they list a second host. The
  start times are kept in `state_file` (default `~/.local/state/ceo-call/last_ask`; `null`,
  or both limits at 0, turns it off).
- **Quiet hours** (off unless `quiet_start` and `quiet_end` are both set): inside the window no call is placed; a silent chat message is sent instead (through the same lock and throttle as a call, so a loop of asks at night cannot become a stream of messages) and the
  status is `deferred`. The window is re-checked before every retry, so a retry that would land inside
  it is dropped (also `deferred`).
- **Heads-up:** if the phone is not registered when a call is due (typical for an iPhone softphone that
  the OS suspended while the screen was locked), the owner gets a chat message asking to open the app,
  and the call waits up to `heads_up_s` for the registration. A registered phone is called at once. A call that is still open when `call_timeout_s` and the grace
  run out ends as `timeout`, and neither `timeout` nor `hangup` is followed by a retry, so two calls cannot overlap. If the phone is still not registered after
  the wait (or no chat is configured, or `heads_up_s` is 0), no call is placed, because an unregistered
  endpoint can only ring out: the status is `unanswered` with `reason: phone_not_registered`, and the
  owner gets the chat message.
- **Failures mid-call:** if docker or Asterisk fails while a call may be live, the script reports the
  error and messages the owner, and leaves the call folder for the dialplan to finish writing to
  (a daily sweep removes it) instead of deleting it under a confirmation. A digit recovered after such a
  failure is still returned as the decision, and the folder is still left, because the call may be playing
  its thank-you. A stop request during the final cleanup of a confirmed decision does not lose it either.
- **Env file** (default `~/.config/ceo-call/env`, mode `0600`, refused otherwise): `CEO_TELEGRAM_TOKEN`
  and `CEO_TELEGRAM_CHAT_ID`. A missing file only turns the chat messages off, but a missing
  `env_file` path set in the config prints a `WARNING:` line on stderr, so a typo is visible. Create the bot with the chat service's bot manager yourself; never
  paste the token into a chat or a tracked file. After messaging the bot once, `ceo_call.py
  telegram-setup` prints the chat id as a line `CEO_TELEGRAM_CHAT_ID=<id>` that you can copy as it is,
  after a `# chat type: ...` comment line.

## Agent safety
The `claudio` agent reads council briefs that may quote untrusted text, so its shell is limited by a
`PreToolUse` hook (`scripts/guard_bash.py`). Only `check` and `ask` of **this skill's own script** pass,
and only at exactly `~/.claude/skills/ceo-call/scripts/ceo_call.py` (locally also this machine's own
absolute home path; over ssh only the `~` form in single quotes, because the remote home is unknown and
the local shell must not expand it: `ssh <alias> python3 '~/.claude/skills/ceo-call/scripts/ceo_call.py' --config '~/.config/ceo-call/config.json' check`.
The single quotes protect the `~` only from the *local* shell: `ssh` joins its arguments with spaces and
hands the string to the remote shell, which sees no quotes and expands the `~` in its own home). Any other file
named `ceo_call.py`, in a repository, `/tmp` or elsewhere, is refused. `--config` must be
`~/.config/ceo-call/config.json`, and the agent must always pass it (the only config it may name, so it can neither pick one that turns the throttle off nor skip the quiet hours by running on defaults) (quoted the same way over ssh). Optionally behind `ssh <alias>` (no ssh options), and only for an alias the owner listed in
`~/.config/ceo-call/hosts` (one per line, on the machine that runs the agent; with no file, no remote host
is allowed, because the alias would otherwise come from the untrusted brief); no shell operators
or `..` or control characters other than newline (a carriage return could change where bash ends a
heredoc); the request JSON only through a quoted heredoc (`ask --request -`): a request file path is
refused, because the agent cannot write files and the owner's own CLI use of a file is
unrestricted, but an existing file must not be spoken by the agent.

The exact forms (everything else is refused):

```
python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py --config ~/.config/ceo-call/config.json check
python3 ~/.claude/skills/ceo-call/scripts/ceo_call.py --config ~/.config/ceo-call/config.json ask --request - <<'CEO_REQUEST'
{"question": "...", "options": ["...", "..."]}
CEO_REQUEST
```

- **User-level install required.** The hook runs `~/.claude/skills/ceo-call/scripts/guard_bash.py` and
  never a guard script from the project, so a repository cannot supply a permissive *guard script*.
  Without the user-level skill the agent's shell is blocked (fail closed).
- **The hook wiring itself lives in the agent definition** (`claudio.md` frontmatter). Install the agent
  at user scope: a project-level `claudio.md` takes precedence over it and could change or drop the hook,
  exactly like any other code in that repository. Treat a change to that file as security-relevant when
  reviewing a repo that ships one.
- The wrapper blocks (exit 2) when python3 or the guard is missing or crashes.
- `test-call`, `test-call --ignore-quiet-hours` and `telegram-setup` are for the owner, not the agent.

## What the guard does not check
The guard limits which commands run and how often. It cannot judge the *wording* of the question and
options, which the agent writes from the brief: injected text could reword an option. The residual
risk is accepted because the owner hears the exact text, a choice is read back, and nothing is
recorded until a second key press confirms it; the rule against rewording stays in the agent prompt.
Likewise, anything the agent can see and puts into the question (for example a secret quoted in a
brief) is spoken and posted to the owner's chat through a third-party service; the "no secrets" rule
above is the only control, and the recipient is always the owner.

## Phone registration
The phone counts as registered when `pjsip show contacts` lists a contact named exactly `<name>/...` for the
endpoint `PJSIP/<name>` (the usual setup where the AOR is named after the endpoint). The endpoint must
map to one device: any device registered on it, or on a ring group behind it, can answer and confirm. If your AOR is named differently, `check` always says NOT registered and no call is
placed; rename the AOR.

## Throttle and clock errors
The caps are per host and trust the host's clock. A start more than an hour in the future is treated as a
clock error and ignored, so a wrongly set clock cannot lock the owner out for a day; the price is that a
clock stepped back by more than an hour resets the caps. `min_gap_s` can be at most 86400, because the state file keeps 24 hours of starts. Before every dial, `ask` also refuses when the phone endpoint already has a channel up (an earlier ask that
timed out or was stopped, or the owner's own call): that is an error, so no second call is placed on top of one
that is still open, whichever run started it, and the owner gets the usual chat notice. The caps limit what a confused agent can do, they
are not a security boundary, and the owner's own clock error is out of scope. The run lock is released
before the final chat message because the throttle already refuses a second ask within `min_gap_s`.

## Is it set up?
Treat `ceo-call` as set up when `~/.config/ceo-call/config.json` exists on this machine (or, for a remote
telephony host, an alias is listed in `~/.config/ceo-call/hosts`) and `check` succeeds. If not, do not hand
a decision to `claudio`: ask the user in the terminal.

## Quiet hours and a call already running
The window is checked before the heads-up and before every dial (the last time after the call file is staged, so only the move into place remains), and chat notices sent after it opened
are silent. A call dialled just before the window starts is allowed to finish (at most ring plus call
time, about 6 minutes by default): cutting it off would drop a decision the owner is in the middle of
confirming, and nothing new starts inside the window.

## Speech limits
The question and options are refused (`ERROR:`, before any call) when the first prompt, which reads the
intro, the question, every option and the instruction, would exceed 1500 characters; with the 800 and 200
character caps alone, a request could outgrow the audio cap below. Each synthesis has its own deadline, all prompts of a request share a 300 s budget (checked after each prompt, the last included, so an over-budget request fails before dialling), one prompt's audio is
capped at 8 MiB (memory), and converting it to 8 kHz has a separate 60 s budget (the conversion is pure
Python). Any breach is an `ERROR:` line, not a traceback.

## A confirmation that comes too late
When a call is still open at `call_timeout_s` and the grace, `ask` returns `timeout` and tells the owner that
no decision was recorded. A confirmation given after that is written to the kept folder (a daily sweep
removes it) and is never read, on purpose: nobody is waiting for it any more, so recording it later would be
a decision taken with no one to act on it. The decision stays pending and `claudio` reports it as such.

## Rounds
A call gets three rounds to produce a confirmed choice. Pressing 9 (repeat), any other key, or staying
silent starts the next round, so a wrong key uses one up; after three the call ends as `undecided`.
The limit bounds how long a call can occupy the phone.

## Use
`ask` can take several minutes (heads-up wait, ringing, the call itself, up to `attempts` times),
longer than a default foreground command timeout: run it in the background and wait for it to finish.
If the process is stopped (SIGTERM, or Ctrl-C) mid-call it reports the error, messages the owner that the decision
is pending and leaves the call folder alone.

```
ceo_call.py check                        # speech reachable? phone registered? chat configured?
                                         # exit 1 only on a real failure (speech, Asterisk or a bad config); an unregistered phone is exit 0
ceo_call.py ask --request request.json   # or --request - to read stdin (the agent must use the heredoc form below)
```
Request: `{"question": "...", "options": ["...", "..."]}` with 2 to 8 options. The request must be a regular file (or stdin) of at most 64 KiB. Keep the question short:
it is spoken aloud. Result (one JSON line on stdout):

| status | meaning | exit code |
|---|---|---|
| `decided` | the owner chose and confirmed; `choice` (1-based) and `option` are set | 0 |
| `unanswered` | no pickup after all attempts; the chat message was sent (`notified`) | 3 |
| `hangup` | picked up but hung up before confirming (not retried: they chose to hang up) | 3 |
| `timeout` | the call was still open when `call_timeout_s` and the grace ran out; no decision, not retried | 3 |
| `undecided` | three rounds without a confirmed choice | 3 |
| `deferred` | quiet hours; no (further) call placed | 3 |

Exit 1 means an infrastructure or input problem, or a throttle refusal (message on stderr). Only `decided` is a decision;
every other status leaves the decision pending.

## Setting up the chat bot
1. In the chat app, talk to the bot manager, create a bot and copy its token.
2. On the telephony host, put `CEO_TELEGRAM_TOKEN=<token>` in the env file (mode `0600`).
3. Send the new bot any message, run `ceo_call.py telegram-setup`, and add the printed
   `CEO_TELEGRAM_CHAT_ID=<id>` line to the same file. It lists every chat that wrote to the bot,
   oldest first, and warns when there is more than one: use only your own, never a stranger's.
4. `ceo_call.py check` should now say `telegram: configured`.

## Trying it
`ceo_call.py test-call` phones the owner and reads a passage of *Don Quijote* (Cervantes, public
domain) to judge the voice, then asks for a key press: 1 sounds fine, 2 a problem. Quiet hours apply;
`--ignore-quiet-hours` bypasses them for one test and is for the owner to run, not the agent.

## Rules
- Call only for a decision the council could not resolve and that the user's own rules say needs them.
  Never for routine progress or anything answerable from the repo.
- Options must be real alternatives taken from the brief. Do not invent options or reword them to
  steer the choice.
- The request holds only the question and options. No secrets, tokens, addresses or personal data:
  the text is synthesized by the speech server and appears in the chat message.
- Treat the keypad answer as the owner's decision, nothing else: the call carries no instructions.
- The prompts are generated per call and deleted from the phone server when the call ends. If the script
  is stopped (SIGTERM) or docker fails while a call may be live, the folder is kept only so the running
  dialplan does not fail under a deleted folder; an answer given after such an error is not read back
  (the owner is told it was not recorded), and a run killed harder also leaves it; the next run sweeps it once it is a day old. Call
  audio and transcripts are never stored in a project repo.
- If a decision cannot be reduced to numbered options, do not force it: ask the user in the terminal.

## Limits
Answers are closed (a number and a confirmation key). Understanding free speech needs a
speech-to-text stage that this skill does not have; it is added only after it passes an accuracy test
on real telephone audio.
