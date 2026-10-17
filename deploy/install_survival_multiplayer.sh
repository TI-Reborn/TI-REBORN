#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/tio-emulator
archive=/root/tio-survival-multiplayer-20260923.tar.gz
expected=be67dc5475311067d54a8a1b462912c1cf781f9941b86fd725c90c1fccd21557
printf '%s  %s\n' "$expected" "$archive" | sha256sum --check -
# Confirm existing multiplayer accounts before interrupting the server.
runuser -u tio -- .venv/bin/python -c 'from server.accounts import Accounts; Accounts("/var/lib/tio-server/reservation.sqlite3").check()'
stage=$(mktemp -d /root/tio-survival-stage-XXXXXX)
saved=$(mktemp -d /root/tio-before-survival-XXXXXX)
tar -xzf "$archive" -C "$stage" --no-same-owner
.venv/bin/python -m compileall -q "$stage/server" "$stage/tio" "$stage/tools"
cp -a /etc/tio-server/server.toml "$saved/server.toml"
tar --exclude=.venv --exclude=__pycache__ -czf "$saved/code.tar.gz" -C /opt/tio-emulator .
was_active=0
if systemctl is-active --quiet tio-server; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        tar -xzf "$saved/code.tar.gz" -C /opt/tio-emulator --no-same-owner
        cp -a "$saved/server.toml" /etc/tio-server/server.toml
        if [ "$was_active" -eq 1 ]; then systemctl start tio-server || true; fi
        echo "Update failed; previous code/config restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$saved/reservation.sqlite3"
tar -xzf "$archive" -C /opt/tio-emulator --no-same-owner
.venv/bin/python - <<'PY'
from pathlib import Path
import re, tomllib
p=Path('/etc/tio-server/server.toml')
s=p.read_text()
for key,value in (('multi_account','true'),('session_port','28513')):
    if key=='session_port' and key in tomllib.loads(s):
        continue
    pattern=rf'(?m)^\s*{key}\s*=.*$'
    if re.search(pattern,s):s=re.sub(pattern,f'{key} = {value}',s)
    else:s+=f'\n{key} = {value}\n'
p.write_text(s)
PY
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 3
systemctl is-active --quiet tio-server
trap - EXIT
printf '\nUpdate successful. Backup: %s\n' "$saved"
systemctl status tio-server --no-pager -l
ss -ltnp 'sport = :28512 or sport = :28513'
journalctl -u tio-server -n 15 --no-pager
