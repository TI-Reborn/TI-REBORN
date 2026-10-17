#!/usr/bin/env bash
set -euo pipefail
cd /opt/tio-emulator
test -s /root/tio-weapon-slots.tar.gz
stage=$(mktemp -d /root/tio-weapon-slots-XXXXXX)
tar -xzf /root/tio-weapon-slots.tar.gz -C "$stage" --no-same-owner
.venv/bin/python -c 'import ast,sys; from pathlib import Path; p=Path(sys.argv[1]); [ast.parse((p/f).read_text()) for f in ("tio/equipment.py","tools/loopback_exchange.py")]' "$stage"
runuser -u tio -- .venv/bin/python deploy/scheduled_backup.py --source /var/lib/tio-server/reservation.sqlite3 --directory /var/backups/tio-server --tag pre-update
saved=$(mktemp -d /root/tio-before-weapon-slots-XXXXXX)
cp -a tio/equipment.py "$saved/equipment.py"
cp -a tools/loopback_exchange.py "$saved/loopback_exchange.py"
was_active=0
if systemctl is-active --quiet tio-server; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        cp -a "$saved/equipment.py" /opt/tio-emulator/tio/equipment.py
        cp -a "$saved/loopback_exchange.py" /opt/tio-emulator/tools/loopback_exchange.py
        if [ "$was_active" -eq 1 ]; then systemctl start tio-server || true; fi
        echo "Installation failed; previous code restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
install -m 0644 "$stage/tio/equipment.py" tio/equipment.py
install -m 0644 "$stage/tools/loopback_exchange.py" tools/loopback_exchange.py
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 2
systemctl is-active --quiet tio-server
trap - EXIT
echo "Weapon slots fix installed. Previous code: $saved"
journalctl -u tio-server -n 8 --no-pager
