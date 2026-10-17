#!/usr/bin/env bash
set -euo pipefail
cd /opt/tio-emulator
archive=/root/tio-combat-multiplayer-20260924.tar.gz
test -s "$archive"
stage=$(mktemp -d /root/tio-combat-stage-XXXXXX)
tar -xzf "$archive" -C "$stage" --no-same-owner
files=(server/team_arena.py server/battle_events.py tio/protocol/battle_turn.py tio/protocol/battle_attack.py)
echo '5c60c46dad7ae3cf5286eb6b6da89a68b7d783d42cb0f90a7121729ae573c030  server/team_arena.py
e81f88a20f97e81da7b01c0ebb896e2933749bf07d0631d384a6c7cd6682f6f9  tio/protocol/battle_turn.py
984adaa4784f01b4e92785a68bdd81c979e829dd87c084fd2ce7ec89bac9fcd2  tio/protocol/battle_attack.py' | sha256sum -c -
test ! -e server/battle_events.py
.venv/bin/python -c 'import ast,sys; from pathlib import Path; root=Path(sys.argv[1]); [ast.parse((root/f).read_text()) for f in sys.argv[2:]]' "$stage" "${files[@]}"
if ss -Htn state established '( sport = :28512 or sport = :28513 )' | grep -q .; then
    echo 'Players are connected; update was not applied.' >&2
    exit 1
fi
saved=$(mktemp -d /root/tio-before-combat-XXXXXX)
chmod 700 "$saved"
cp -a /etc/tio-server/server.toml "$saved/server.toml"
cp -a /etc/systemd/system/tio-server.service "$saved/tio-server.service"
for file in "${files[@]}"; do
    mkdir -p "$saved/$(dirname "$file")"
    if [ -f "$file" ]; then cp -a "$file" "$saved/$file"; fi
done
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        for file in "${files[@]}"; do
            if [ -f "$saved/$file" ]; then cp -a "$saved/$file" "$file"; else rm -f -- "$file"; fi
        done
        systemctl start tio-server || true
        echo "Update failed; previous code restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$saved/reservation.sqlite3"
tar -czf "$saved/hosted-data.tar.gz" -C /var/lib/tio-server .
for file in "${files[@]}"; do install -m 0644 "$stage/$file" "$file"; done
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 2
systemctl is-active --quiet tio-server
.venv/bin/python deploy/check_connection.py --host 127.0.0.1 --port 28512
trap - EXIT
echo "COMBAT_BACKUP=$saved"
sha256sum "${files[@]}"
journalctl -u tio-server -n 8 --no-pager
