#!/bin/bash
set -euo pipefail
cd /opt/tio-emulator
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/root/tio-backups/character-onboarding-$stamp
install -d -m 0700 "$backup"
if [ -n "$(ss -Htn state established '( sport = :28512 or sport = :28513 )')" ]; then
    echo 'Active game clients: postpone update'; exit 1
fi
tar --exclude=.venv --exclude=.venv-web --exclude=__pycache__ -czf "$backup/code.tar.gz" -C /opt/tio-emulator .
tar -czf "$backup/config.tar.gz" /etc/tio-server /etc/systemd/system/tio-server.service /etc/systemd/system/tio-registration.service
systemctl stop tio-registration tio-server
trap 'systemctl start tio-server tio-registration' EXIT
python3 deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$backup/reservation.sqlite3"
before=$(sha256sum /var/lib/tio-server/reservation.sqlite3 | cut -d' ' -f1)
tar -xzf /root/tio-character-onboarding.tar.gz -C /opt/tio-emulator --no-same-owner
if ! runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check; then
    tar -xzf "$backup/code.tar.gz" -C /opt/tio-emulator --no-same-owner
    echo "Preflight failed: previous code restored; backup $backup"; exit 1
fi
after=$(sha256sum /var/lib/tio-server/reservation.sqlite3 | cut -d' ' -f1)
test "$before" = "$after"
systemctl start tio-server tio-registration
systemctl is-active tio-server tio-registration
echo "BACKUP=$backup"
echo 'Existing database unchanged by installation and preflight'
