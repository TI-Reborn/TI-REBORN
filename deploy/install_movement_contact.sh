#!/usr/bin/env bash
set -euo pipefail
cd /opt/tio-emulator
test -s /root/tio-movement-contact.tar.gz
stage=$(mktemp -d /root/tio-movement-contact-XXXXXX)
tar -xzf /root/tio-movement-contact.tar.gz -C "$stage" --no-same-owner
files=(tio/battle_state.py)
.venv/bin/python -c 'import ast,sys; from pathlib import Path; p=Path(sys.argv[1]); [ast.parse((p/f).read_text()) for f in sys.argv[2:]]' "$stage" "${files[@]}"
runuser -u tio -- .venv/bin/python deploy/scheduled_backup.py --source /var/lib/tio-server/reservation.sqlite3 --directory /var/backups/tio-server --tag pre-update
saved=$(mktemp -d /root/tio-before-movement-contact-XXXXXX)
for file in "${files[@]}"; do
    mkdir -p "$saved/$(dirname "$file")"
    if [ -f "$file" ]; then cp -a "$file" "$saved/$file"; fi
done
was_active=0
if systemctl is-active --quiet tio-server; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-server || true
        for file in "${files[@]}"; do
            if [ -f "$saved/$file" ]; then cp -a "$saved/$file" "$file"; else rm -f -- "$file"; fi
        done
        if [ "$was_active" -eq 1 ]; then systemctl start tio-server || true; fi
        echo "Installation failed; previous code restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
systemctl stop tio-server
for file in "${files[@]}"; do install -m 0644 "$stage/$file" "$file"; done
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
systemctl start tio-server
sleep 2
systemctl is-active --quiet tio-server
trap - EXIT
echo "Movement contact stop installed. Previous code: $saved"
journalctl -u tio-server -n 8 --no-pager
