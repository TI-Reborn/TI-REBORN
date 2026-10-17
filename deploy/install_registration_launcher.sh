#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/tio-emulator
archive=/root/tio-registration-launcher-fix.tar.gz
site=/etc/nginx/sites-available/tio-launcher
test -f "$archive" || { echo "Missing $archive" >&2; exit 1; }
printf '%s  %s\n' 1fc58957079e67cf05eaa70b0a4ae59d3a3e634bc7eae6f9eb05f86205f307f4 "$archive" | sha256sum --check -
test -f "$site" || { echo "Missing $site" >&2; exit 1; }
runuser -u tio -- .venv/bin/python - <<'PY'
from server.config import ServerConfig
from server.accounts import Accounts
c=ServerConfig.load('/etc/tio-server/server.toml')
assert c.multi_account, 'Enable multi_account in the game server before registration'
Accounts(c.database).check()
print('Multiplayer database and existing accounts verified')
PY
stage=$(mktemp -d /root/tio-registration-stage-XXXXXX)
python3 - "$archive" "$stage" <<'PY'
import sys,tarfile
with tarfile.open(sys.argv[1]) as f:f.extractall(sys.argv[2],filter='data')
PY
python3 - "$stage" <<'PY'
from pathlib import Path
import hashlib,sys
p=Path(sys.argv[1])
assert hashlib.sha256((p/'downloads/TIO-Launcher.exe').read_bytes()).hexdigest()==(p/'launcher-sha256.txt').read_text().strip()
print('Launcher 0.1.1 checksum verified')
PY
saved=$(mktemp -d /root/tio-before-registration-XXXXXX)
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "$saved/reservation.sqlite3"
cp -a "$site" "$saved/site"
if [ -d registration ]; then cp -a registration "$saved/registration"; fi
unit=/etc/systemd/system/tio-registration.service
snippet=/etc/nginx/snippets/tio-registration.conf
if [ -f "$unit" ]; then cp -a "$unit" "$saved/unit"; fi
if [ -f "$snippet" ]; then cp -a "$snippet" "$saved/snippet"; fi
was_active=0
if systemctl is-active --quiet tio-registration; then was_active=1; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        systemctl stop tio-registration || true
        cp -a "$saved/site" "$site"
        if [ -d "$saved/registration" ]; then cp -a "$saved/registration/." registration/; fi
        if [ -f "$saved/unit" ]; then cp -a "$saved/unit" "$unit"; else rm -f "$unit"; fi
        if [ -f "$saved/snippet" ]; then cp -a "$saved/snippet" "$snippet"; else rm -f "$snippet"; fi
        systemctl daemon-reload
        if [ "$was_active" -eq 1 ]; then systemctl start tio-registration || true; fi
        nginx -t && systemctl reload nginx || true
        echo "Registration setup failed. Previous config: $saved. Game service unchanged." >&2
    fi
    exit "$result"
}
trap rollback EXIT
install -d -m 0755 registration
cp -a "$stage/registration/." registration/
python3 -m venv .venv-web
.venv-web/bin/pip install -r registration/requirements.txt
if [ ! -e /etc/tio-server/web-secret ]; then
    (umask 077; .venv/bin/python -c 'import secrets; from pathlib import Path; Path("/etc/tio-server/web-secret").write_text(secrets.token_hex(32))')
fi
chown root:tio /etc/tio-server/web-secret
chmod 0640 /etc/tio-server/web-secret
install -m 0644 "$stage/deploy/tio-registration.service" "$unit"
cat > "$snippet" <<'EOF'
location = /register { return 301 /register/; }
location /register/ {
    client_max_body_size 4k;
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host 185.184.42.88;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
}
location /static/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host 185.184.42.88;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
}
EOF
python3 - "$site" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
line='    include /etc/nginx/snippets/tio-registration.conf;\n'
if line.strip() not in s:
    marker='    include /etc/nginx/snippets/tio-updates.conf;'
    if s.count(marker)!=1:raise SystemExit('Unexpected HTTPS site configuration')
    s=s.replace(marker,line+marker)
    p.write_text(s)
PY
nginx -t
systemctl daemon-reload
systemctl enable tio-registration
systemctl restart tio-registration
systemctl reload nginx
ready=0
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --show-error --max-time 15 https://185.184.42.88/register/ -o /dev/null; then ready=1; break; fi
    sleep 2
done
test "$ready" -eq 1
systemctl is-active --quiet tio-registration
install -d -m 0755 /var/www/tio-client/downloads
if [ -f /var/www/tio-client/downloads/TIO-Launcher.exe ]; then
    cp -a /var/www/tio-client/downloads/TIO-Launcher.exe "$saved/TIO-Launcher.exe"
fi
install -m 0644 "$stage/downloads/TIO-Launcher.exe" /var/www/tio-client/downloads/TIO-Launcher.exe.new
mv /var/www/tio-client/downloads/TIO-Launcher.exe.new /var/www/tio-client/downloads/TIO-Launcher.exe
trap - EXIT
echo "REGISTRATION READY: https://185.184.42.88/register/"
echo "LAUNCHER 0.1.1 READY: https://185.184.42.88/downloads/TIO-Launcher.exe?v=0.1.1"
echo "Backup: $saved. Existing accounts and game service preserved."
