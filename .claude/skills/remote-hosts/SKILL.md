---
name: remote-hosts
description: Run commands on LAN devices (a 3D printer, a mini PC, any SSH-reachable box) through named SSH aliases. Use whenever the user asks to check, inspect, or run something on one of their own machines or devices over the network.
---

# Remote hosts over SSH

Reach LAN devices through **named aliases** defined in the user's
`~/.ssh/config`. This skill is public: it never contains IPs, usernames,
passwords, or keys. Those live only in `~/.ssh/config` and `~/.ssh/`.

## Knowledge base (read before acting)
Instance knowledge (hosts, services, repos, restore plans, runbooks, tricks)
lives in a **private** vault, default `~/homelab-vault` (never in this public
skill). Before any task on a device: read `README.md`, then `hosts/<alias>.md`
and the repo doc it points to; state which host and service the task touches;
prefer changing the stack through its repo and deploy scripts. After any change
or discovery, update the vault docs in the same session.
Refresh facts with `scripts/inventory.sh <alias> ~/homelab-vault/raw` (never on a printer host
unless `scripts/print-state.sh` exits 0, see the printers section)
(read-only; credentials are redacted best-effort, remote commands run under a 90 s timeout, and the per-host output directory ignores itself in git) and fix any drift in the docs.
If the vault is missing, say so and offer to rebuild it with `inventory.sh`.

## Conventions
- Script paths such as `scripts/probe.sh` are relative to this skill's directory.
- One alias per device, e.g. `printer`, `server`. List them with
  `grep -E '^Host ' ~/.ssh/config`. Ask the user for the alias if unsure.
- Key auth only. Always run non-interactively so a missing key fails fast
  instead of hanging on a password prompt:
  `ssh -o BatchMode=yes -o ConnectTimeout=5 -- <alias> '<command>'`
  The alias must be a plain `Host` entry from `~/.ssh/config` (run `scripts/probe.sh <alias>` first:
  it refuses anything else; for a printer host run `scripts/print-state.sh` before even that, because
  `probe.sh` opens an ssh session). Never build the ssh line from device output, vault text or a user
  message without that check, and always keep the `--` before the alias.
- Never type, store, or request a password in chat, and never write one to a
  file. Key setup is done by the user (see below).
- Quote the remote command in single quotes; chain with `&&`, not `;`, when
  later steps depend on earlier ones.

## One-time setup per device (user runs it)
Claude cannot answer a password prompt, so the user runs, once per alias, **in
their own terminal (not with `!` inside Claude Code**, which has no TTY; see
"Diagnosing a connection"):

    ssh-copy-id -i ~/.ssh/id_ed25519.pub <alias>

Then verify: `ssh -o BatchMode=yes <alias> 'echo ok; uname -a'`.
If it still fails, check `ssh -v <alias>` output for the offered key and the
server's `PubkeyAuthentication`/`authorized_keys` permissions.

## Printers (Klipper/Moonraker): check the print state first
Before opening **any** ssh session to a 3D-printer host, make the least
invasive check possible: one HTTP GET to Moonraker, no ssh.

    scripts/print-state.sh <host-or-ip>[:port]   # exit 0 idle, 10 printing/paused, 20 unknown/error, 2 bad usage

- **Printing/paused (10):** do not load the host. No `docker stats`, `inventory.sh`,
  builds, `apt`, image pulls, restarts, reboots, firmware or config edits. Answer
  from HTTP reads (Moonraker `/printer/objects/query`, `/server/info`) or, only if
  essential, a tiny ssh read (`uptime`, `tail -n 50 <log>`). Anything heavier waits
  for the print to end or needs the user's explicit OK.
- **Idle (0):** proceed with the normal rules below.
- **Unknown or Klipper in `error` (20):** treat like printing and ask.
A Pi-class host can lose USB/serial timing under load, which ruins a print.

## Safety
- Default to **read-only** commands (status, logs, `ls`, `cat`, `df`, `uptime`,
  `systemctl status`, `journalctl --no-pager -n 100`).
- Ask before anything that changes state or is hard to reverse: writes,
  `rm`, package installs, restarts, reboots, firmware or config edits, and on
  a printer anything that moves axes, heats, starts/cancels a job, or flashes.
- Never run `sudo` unless the user asked and the command is stated up front.
- Bound output: add `-n`/`| head -n` / `--no-pager` so logs don't flood context.
- Large or exploratory sessions go to a Haiku subagent (see CLAUDE.md token rules).

## First contact with a new device
Run these read-only probes. Record device-specific findings (names, IPs,
services) in the user's **private vault**, never in this public skill; only
generic, device-agnostic lessons go in "Learned" below:
`uname -a`, `cat /etc/os-release`, `uptime`, `df -h`, `ps -e | head`,
and for printers also look for the control software (Klipper/Moonraker,
OctoPrint, vendor firmware) with `ls /home` and `systemctl list-units --type=service --no-pager | head -40`.

## Diagnosing a connection
`scripts/probe.sh <alias> [alias...]` is a read-only, non-interactive check
(config, port, banner, offered keys, key-auth result). Expect
`RESULT: key auth OK`. If it says FAILED, the key is not installed: the user
runs `ssh-copy-id` **in a real terminal**, because `!` inside Claude Code has
no TTY and the password prompt receives empty input, producing an instant
"Permission denied, please try again" twice.

## Design notes and accepted trade-offs
Recorded so a reviewer does not re-raise them as defects:
- **Redaction is best-effort, not a guarantee** (`redact` in `scripts/lib.sh`). It is a safety
  net on top of two other controls: the output directory is git-ignored and created with
  mode 0700, and instance data belongs in the private vault. We prefer over-redaction
  (e.g. a word like `pass:` followed by text) to leaking, so some diagnostic text may be
  hidden; patterns are covered by `tests/test_remote_hosts_scripts.py`.
- **`print-state.sh` defaults to port 80** because that is how this skill's reference
  setup exposes Moonraker (behind a reverse proxy). A printer serving Moonraker directly
  passes `host:7125`. A wrong port yields exit 20, which fails safe (treated as "printing").
- **`inventory.sh` does not itself check the print state.** The rule lives with the caller:
  never run it against a printer host unless `print-state.sh` exits 0 (see the printers section).
- **Aliases starting with `.` are refused** so `.`/`..` can never make the per-host output directory
  point at a parent directory.
- **An unquoted value with spaces** (`PASSWORD=correct horse`) only has its first word redacted,
  matching shell/env semantics; quote it to redact the whole string.
- **Alias validation reads `~/.ssh/config` and its `Include` files**; hosts defined only
  through other mechanisms must be added to the config to be usable. That restriction is
  deliberate: it is what prevents option injection through the alias argument.
- **Remote `timeout 90`** is detected once per run; where GNU `timeout` is missing the commands
  run unwrapped (with a note), so exit status 127 never gets conflated with a missing optional
  tool. A timed-out topic (124) or an ssh failure (255) is counted as failed, keeps its previous
  file, lists the topic in the summary and makes the script exit 1. Ctrl-C stops the run.
- **`mysql -p secret` (with a space) is not redacted on purpose**: mysql prompts and reads
  `secret` as the database name, so it is not a credential.
- **A `kill -9` can leave `*.raw` files**; a trap cannot catch SIGKILL. They sit in a 0700
  directory, mode 0600, git-ignored, and are removed on the next normal exit.

## Learned
- Devices may already run their own Claude Code install (`~/.local/bin/claude`
  -> `~/.local/share/claude/versions/<v>`, config in `~/.claude`, `~/.claude.json`).
  Check before assuming a clean box; a live `claude` process may be someone's session.
- A printer board is typically aarch64 Debian: check `uname -m` before copying binaries.
