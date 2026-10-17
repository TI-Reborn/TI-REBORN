#!/usr/bin/env bash
set -euo pipefail
cd /opt/tio-emulator
test -s /root/equipment-tank.py
.venv/bin/python -c 'import ast; from pathlib import Path; ast.parse(Path("/root/equipment-tank.py").read_text())'
runuser -u tio -- .venv/bin/python deploy/scheduled_backup.py --source /var/lib/tio-server/reservation.sqlite3 --directory /var/backups/tio-server --tag pre-update
saved=$(mktemp -d /root/tio-before-tank-XXXXXX)
cp -a tio/equipment.py "$saved/equipment.py"
was_active=0
if systemctl is-active --quiet tio-server; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        cp -a "$saved/equipment.py" /opt/tio-emulator/tio/equipment.py
        if [ "$was_active" -eq 1 ]; then systemctl start tio-server || true; fi
        echo "Installation failed; previous equipment.py restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
install -m 0644 /root/equipment-tank.py tio/equipment.py
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 2
systemctl is-active --quiet tio-server
trap - EXIT
echo "Tank Armor fix installed. Previous code: $saved/equipment.py"
journalctl -u tio-server -n 8 --no-pager
