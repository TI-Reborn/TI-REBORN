#!/usr/bin/env bash
set -Eeuo pipefail
stage=/root/tio-liveness-20260924
cd /opt/tio-emulator
# This targeted update was tested against these exact hosted files.
echo '9dc8e97c2a60ffa0a64c8864caffbf90c2701eb2a35350a6b9ccd47017d00336  server/multi.py' | sha256sum -c -
echo '436a76251d0c5033b58b7f385fea36916d02b69315db424c0a3e290c58f48127  tools/loopback_exchange.py' | sha256sum -c -
if [ -n "$(ss -Htn state established '( sport = :28512 or sport = :28513 )')" ]; then
    echo 'Players are connected; finish their sessions before updating.' >&2
    exit 1
fi
systemctl is-active --quiet tio-server
saved=$(mktemp -d /root/tio-before-liveness-XXXXXX)
chmod 700 "$saved"
cp -a server/multi.py "$saved/multi.py"
cp -a tools/loopback_exchange.py "$saved/loopback_exchange.py"
cp -a /etc/tio-server/server.toml "$saved/server.toml"
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        cp -a "$saved/multi.py" server/multi.py
        cp -a "$saved/loopback_exchange.py" tools/loopback_exchange.py
        systemctl start tio-server || true
        echo "Update failed; previous code restored. Backup: $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$saved/reservation.sqlite3"
chmod 600 "$saved/reservation.sqlite3"
install -m 0644 "$stage/server/multi.py" server/multi.py
install -m 0644 "$stage/tools/loopback_exchange.py" tools/loopback_exchange.py
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 3
systemctl is-active --quiet tio-server
trap - EXIT
echo "CONNECTION LIVENESS FIX READY. Backup: $saved"
sha256sum server/multi.py tools/loopback_exchange.py
ss -ltn '( sport = :28512 or sport = :28513 )'
