#!/bin/bash
set -euo pipefail
cd /opt/tio-emulator
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/root/tio-backups/appearance-step-$stamp
install -d -m 0700 "$backup"
if [ -n "$(ss -Htn state established '( sport = :28512 or sport = :28513 )')" ]; then
    echo 'Active game clients: postpone update'; exit 1
fi
tar --exclude=.venv --exclude=.venv-web --exclude=__pycache__ -czf "$backup/code.tar.gz" -C /opt/tio-emulator .
tar -czf "$backup/config.tar.gz" /etc/tio-server /etc/systemd/system/tio-server.service /etc/systemd/system/tio-registration.service
cp /var/www/tio-client/updates/manifest.json "$backup/manifest.json"
systemctl stop tio-registration tio-server
trap 'systemctl start tio-server tio-registration' EXIT
python3 deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$backup/reservation.sqlite3"
before=$(sha256sum /var/lib/tio-server/reservation.sqlite3 | cut -d' ' -f1)
tar -xzf /root/tio-appearance-step.tar.gz -C /opt/tio-emulator --no-same-owner
if ! runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check; then
    tar -xzf "$backup/code.tar.gz" -C /opt/tio-emulator --no-same-owner
    echo "Preflight failed: previous code restored; backup $backup"; exit 1
fi
after=$(sha256sum /var/lib/tio-server/reservation.sqlite3 | cut -d' ' -f1)
test "$before" = "$after"
echo 'd14f9b31d66398df5309bceb0dc1e452bb33108c001a21584967b8bd16875dc7  /root/silver-onboarding.dll' | sha256sum -c -
install -m 0644 /root/silver-onboarding.dll /var/www/tio-client/updates/blobs/d14f9b31d66398df5309bceb0dc1e452bb33108c001a21584967b8bd16875dc7
install -m 0644 /root/manifest-appearance-step.json /var/www/tio-client/updates/manifest.json.next
mv /var/www/tio-client/updates/manifest.json.next /var/www/tio-client/updates/manifest.json
systemctl start tio-server tio-registration
systemctl is-active tio-server tio-registration
echo "BACKUP=$backup"
echo 'Existing database unchanged by installation and preflight'
