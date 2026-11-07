#!/bin/sh
# shellcheck disable=SC1091,SC2016
# Read-only system inventory of a remote host. Usage: inventory.sh <alias> <outdir>
# Writes one text file per topic into <outdir>/<alias>/ (self-ignoring via .gitignore).
# Never dumps env vars or .env files; all output is passed through redact() to strip
# URL credentials and password/token-like values (best-effort, see lib.sh). A topic that fails
# (ssh error 255 or remote timeout 124) keeps its previous file and leaves a .err note; the
# script then lists the failed topics and exits 1. Exit 2 means bad usage, a missing prerequisite
# (perl) or an unwritable output directory.
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
h=$1; base=$2
valid_alias "$h" && [ -n "$base" ] || { echo "usage: inventory.sh <alias> <outdir> (alias must be a Host in ~/.ssh/config)" >&2; exit 2; }
command -v perl >/dev/null 2>&1 || { echo "inventory.sh needs perl for redaction" >&2; exit 2; }
umask 077
out=$base/$h
# chmod also tightens a pre-existing directory
if ! mkdir -p "$out" || ! chmod 700 "$out"; then echo "cannot create $out" >&2; exit 2; fi
# Raw (unredacted) files are removed on exit and on Ctrl-C/TERM. SIGKILL cannot be trapped, so
# after a kill -9 they could remain: they live in a 0700 directory, mode 0600, and git-ignored.
trap 'rm -f "$out"/*.raw "$out"/*.new' EXIT
trap 'exit 130' INT TERM                  # Ctrl-C stops the run (the EXIT trap cleans up)
[ -e "$out/.gitignore" ] || printf '*\n' > "$out/.gitignore" || { echo "cannot write in $out" >&2; exit 2; }   # self-ignoring; never touches the caller's own .gitignore
ok=0; fail=0; failed=""
# GNU `timeout` bounds each remote command so a wedged one cannot block the run. Detect it once:
# without it, exit status 127 would be ambiguous (missing wrapper vs. a missing optional tool at
# the end of a chained probe), so run unwrapped instead and say so.
if ssh -n -T -o BatchMode=yes -o ConnectTimeout=8 -- "$h" 'command -v timeout >/dev/null 2>&1' >/dev/null 2>&1; then
  use_timeout=1
else
  use_timeout=0; echo "note: remote has no 'timeout' (or is unreachable); commands run without a time limit" >&2
fi
# r <topic> <remote command>: data goes to <topic>.txt, ssh stderr to <topic>.err (both redacted).
# ssh exits 255 on connection/auth failure and `timeout` exits 124; the remote command's own status
# is ignored on purpose because probes are chained and may legitimately end on a missing optional tool.
# A failed topic never overwrites its previous <topic>.txt: new data is written to .new and moved in
# only on success.
r() { name=$1; shift
  if [ "$use_timeout" = 1 ]; then cmd="timeout 90 sh -c $(shell_quote "$*")"; else cmd=$*; fi
  ssh -n -T -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -- "$h" "$cmd" > "$out/$name.raw" 2> "$out/$name.err.raw"
  rc=$?   # taken directly from ssh, not from a pipeline
  # a failing redactor must never produce a "successful" topic
  redact < "$out/$name.raw" > "$out/$name.new" && redact < "$out/$name.err.raw" > "$out/$name.err" || rc=255
  rm -f "$out/$name.raw" "$out/$name.err.raw"
  [ "$rc" -eq 124 ] && echo "timed out after 90 s: some output may be missing" >> "$out/$name.err"
  [ -s "$out/$name.err" ] || rm -f "$out/$name.err"
  # 255 = ssh connection/auth failure (or redaction failure), 124 = remote timeout
  if [ "$rc" -eq 255 ] || [ "$rc" -eq 124 ]; then
    rm -f "$out/$name.new"; fail=$((fail+1)); failed="$failed $name"
  else
    mv "$out/$name.new" "$out/$name.txt"; ok=$((ok+1))
  fi; }
r os 'hostnamectl 2>/dev/null; echo; cat /etc/os-release; echo; uname -a; echo; uptime; echo; cat /proc/device-tree/model 2>/dev/null; echo; lscpu | head -20; echo; free -h; echo; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL; echo; df -hT -x tmpfs -x devtmpfs; echo; findmnt -t ext4,vfat,nfs,cifs,btrfs'
r users 'id; echo; getent passwd | awk -F: "\$3>=1000 && \$3<65000"; echo; getent group sudo docker; echo; last -n 15 2>/dev/null; echo; ls -la ~ ~/.ssh | grep -v private'
r network 'ip -br a; echo; ip r; echo; cat /etc/resolv.conf; echo; ss -tulpn 2>/dev/null; echo; nmcli -t dev status 2>/dev/null; ls /etc/netplan /etc/network/interfaces.d /etc/NetworkManager/system-connections 2>/dev/null'
r services 'systemctl list-units --type=service --state=running --no-pager; echo; systemctl list-unit-files --state=enabled --no-pager; echo; systemctl --failed --no-pager; echo; systemctl list-timers --no-pager; echo; crontab -l 2>&1; ls /etc/cron.d 2>/dev/null'
r docker 'docker version --format "{{.Server.Version}}" 2>&1; echo; docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>&1; echo; docker compose ls -a 2>&1; echo; docker network ls 2>&1; echo; docker volume ls 2>&1; echo; docker system df 2>&1; echo; docker inspect --format "{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} net={{.HostConfig.NetworkMode}} mounts={{range .Mounts}}{{.Source}}->{{.Destination}} {{end}}" $(docker ps -aq) 2>&1; echo; cat /etc/docker/daemon.json 2>&1'
r compose 'docker inspect -f "{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}" $(docker ps -aq) 2>/dev/null | sort -u | while read -r d; do [ -n "$d" ] || continue; echo "### $d"; ls -la "$d"; [ -d "$d/.git" ] && git -C "$d" remote -v && git -C "$d" log --oneline -3; done; echo; ls /opt 2>&1'
r repos 'find / -maxdepth 4 -name .git -type d -not -path "/proc/*" -not -path "*/node_modules/*" 2>/dev/null | while read -r g; do d=$(dirname "$g"); echo "$d  $(git -C "$d" remote get-url origin 2>/dev/null)  $(git -C "$d" log -1 --format="%h %cs" 2>/dev/null)"; done'
r health 'cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null; vcgencmd measure_temp 2>/dev/null; vcgencmd get_throttled 2>/dev/null; vcgencmd measure_volts 2>/dev/null; sensors 2>/dev/null; echo; journalctl -k -p warning --no-pager -n 60 2>&1; echo; journalctl -p err -b --no-pager -n 60 2>&1; echo; dmesg 2>&1 | grep -iE "under-?voltage|throttl|i/o error|oom|usb.*(reset|disconnect)|mmc.*error|ext4.*error" | tail -20; echo; journalctl --list-boots --no-pager 2>&1 | tail -5; smartctl -H /dev/sda 2>&1 | head -5'
r hardware 'lsusb 2>&1; echo; ls -l /dev/serial/by-id /dev/serial/by-path /dev/ttyACM* /dev/ttyUSB* /dev/video* 2>&1; echo; lspci 2>&1 | head -20; echo; ls /dev/disk/by-id 2>&1 | head'
r packages 'apt-mark showmanual 2>/dev/null | tr "\n" " "; echo; ls ~/.local/bin /usr/local/bin 2>&1; echo; grep -rhE "^(deb|URIs)" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | head; echo; grep -vE "^\s*(#|$)" /etc/fstab; echo; cat /etc/hosts; echo; cat /etc/ssh/sshd_config.d/* 2>/dev/null; echo; timedatectl 2>&1 | head -8; echo; cat /boot/config.txt /boot/firmware/config.txt /boot/armbianEnv.txt 2>/dev/null | grep -vE "^\s*(#|$)"; echo; cat /etc/sysctl.d/* /etc/udev/rules.d/* /etc/systemd/system.conf.d/* /etc/systemd/journald.conf.d/* 2>/dev/null | grep -vE "^\s*(#|$)"'
echo "inventory $h: $ok topics ok, $fail failed${failed:+ ($failed )} -> $out"
[ "$fail" -eq 0 ]
