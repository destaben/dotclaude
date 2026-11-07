#!/bin/sh
# shellcheck disable=SC1091,SC2016
# Read-only system inventory of a remote host. Usage: inventory.sh <alias> <outdir>
# Writes one text file per topic into <outdir>/<alias>/ (self-ignoring via .gitignore).
# Never dumps env vars or .env files; all output is passed through redact() to strip
# URL credentials and password/token-like values. Exit 1 if every ssh call failed.
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
h=$1; base=$2
valid_alias "$h" && [ -n "$base" ] || { echo "usage: inventory.sh <alias> <outdir> (alias must be a Host in ~/.ssh/config)" >&2; exit 2; }
out=$base/$h; mkdir -p "$out"; printf '*\n' > "$base/.gitignore"
ok=0; fail=0
r() { name=$1; shift
  if ssh -T -o BatchMode=yes -o ConnectTimeout=8 -- "$h" "$@" 2>&1 | redact > "$out/$name.txt" && [ "$(wc -c < "$out/$name.txt")" -gt 0 ]; then ok=$((ok+1)); else fail=$((fail+1)); fi; }
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
echo "inventory $h: $ok topics ok, $fail empty/failed -> $out"
[ "$ok" -gt 0 ]
