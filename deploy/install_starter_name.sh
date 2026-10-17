#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/tio-emulator
test -s /root/tio-starter-name.tar.gz
stage=$(mktemp -d /root/tio-starter-name-XXXXXX)
python3 - "$stage" <<'PY'
import sys,tarfile
with tarfile.open('/root/tio-starter-name.tar.gz') as archive:
    archive.extractall(sys.argv[1],filter='data')
PY
.venv/bin/python - "$stage" <<'PY'
import ast,sys
from pathlib import Path
ast.parse((Path(sys.argv[1])/'tio/owned_pets.py').read_text())
PY
saved=$(mktemp -d /root/tio-before-starter-name-XXXXXX)
cp -a tio/owned_pets.py "$saved/owned_pets.py"
was_active=0
if systemctl is-active --quiet tio-server; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        cp -a "$saved/owned_pets.py" tio/owned_pets.py
        if [ "$was_active" -eq 1 ]; then systemctl start tio-server || true; fi
        echo "Update failed; previous code restored. Backup: $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$saved/reservation.sqlite3"
install -m 0644 "$stage/tio/owned_pets.py" tio/owned_pets.py
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 3
systemctl is-active --quiet tio-server
trap - EXIT
echo "STARTER NAME FIX READY. Reconnect players to update their starter fighter names."
echo "Backup: $saved"
