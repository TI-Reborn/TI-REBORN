#!/usr/bin/env bash
# Run as root after uploading tio-launcher-hosting-20260923.tar.gz.
# Only nginx/static client downloads change; the game database and service are untouched.
set -Eeuo pipefail
archive=/root/tio-launcher-hosting-20260923.tar.gz
site=${TIO_NGINX_SITE:-/etc/nginx/sites-available/tio-registration}
test -f "$site" || { echo "Missing nginx site: $site. Run bootstrap_launcher_https.sh first." >&2; exit 1; }
test -f "$archive" || { echo "Missing archive: $archive" >&2; exit 1; }
printf '%s  %s\n' ab44866b087e4be6cead9c9f5301f540ec1ac91603ec34af9500a6d35f96c1fd "$archive" | sha256sum --check -
nginx -t
stage=$(mktemp -d /root/tio-launcher-stage-XXXXXX)
python3 - "$archive" "$stage" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1]) as bundle:
    bundle.extractall(sys.argv[2], filter='data')
PY
python3 - "$stage" <<'PY'
import hashlib, json, pathlib, re, sys
root=pathlib.Path(sys.argv[1])
manifest=json.loads((root/'updates/manifest.json').read_text())
assert manifest['schema']==1 and manifest['files']
for f in manifest['files']:
    assert re.fullmatch('[0-9a-f]{64}', f['sha256'])
    data=(root/'updates/blobs'/f['sha256']).read_bytes()
    assert len(data)==f['size'] and hashlib.sha256(data).hexdigest()==f['sha256']
print('Verified release',manifest['version'],'files:',len(manifest['files']))
PY
saved=$(mktemp -d /root/tio-before-launcher-XXXXXX)
cp -a "$site" "$saved/site"
snippet=/etc/nginx/snippets/tio-updates.conf
if [ -f "$snippet" ]; then cp -a "$snippet" "$saved/snippet"; fi
rollback() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ]; then
        cp -a "$saved/site" "$site"
        if [ -f "$saved/snippet" ]; then cp -a "$saved/snippet" "$snippet"; else rm -f "$snippet"; fi
        nginx -t && systemctl reload nginx || true
        echo "Nginx configuration restored from $saved" >&2
    fi
    exit "$result"
}
trap rollback EXIT
install -d -m 0755 /var/www/tio-client/updates/blobs /var/www/tio-client/downloads
cp -n "$stage"/updates/blobs/* /var/www/tio-client/updates/blobs/
chmod 0644 /var/www/tio-client/updates/blobs/*
install -m 0644 "$stage/downloads/TIO-Launcher.exe" /var/www/tio-client/downloads/TIO-Launcher.exe.new
mv /var/www/tio-client/downloads/TIO-Launcher.exe.new /var/www/tio-client/downloads/TIO-Launcher.exe
cat > "$snippet" <<'EOF'
location = /updates/manifest.json {
    root /var/www/tio-client;
    default_type application/json;
    add_header Cache-Control "no-cache" always;
    try_files $uri =404;
}
location /updates/blobs/ {
    root /var/www/tio-client;
    default_type application/octet-stream;
    add_header Cache-Control "public, max-age=31536000, immutable";
    autoindex off;
    try_files $uri =404;
}
location /downloads/ {
    root /var/www/tio-client;
    default_type application/octet-stream;
    add_header Cache-Control "no-cache" always;
    autoindex off;
    try_files $uri =404;
}
EOF
python3 - "$site" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
line='    include /etc/nginx/snippets/tio-updates.conf;\n'
if line.strip() not in s:
    needle='    location / {\n        proxy_pass http://127.0.0.1:8080;'
    if s.count(needle)!=1:raise SystemExit('Unexpected nginx config; inspect manually before installing')
    s=s.replace(needle,line+needle)
    p.write_text(s)
PY
nginx -t
systemctl reload nginx
# Publish the manifest only after all immutable files exist.
install -m 0644 "$stage/updates/manifest.json" /var/www/tio-client/updates/manifest.json.new
mv /var/www/tio-client/updates/manifest.json.new /var/www/tio-client/updates/manifest.json
trap - EXIT
# Reload is asynchronous: an old worker can briefly serve the previous locations.
ready=0
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --show-error --max-time 20 https://185.184.42.88/updates/manifest.json -o /dev/null; then
        ready=1
        break
    fi
    sleep 2
done
test "$ready" -eq 1 || { echo "Files published, but HTTPS verification failed. Check nginx and retry the URL." >&2; exit 1; }
echo "Client updates published. Download: https://185.184.42.88/downloads/TIO-Launcher.exe"
echo "Previous nginx configuration: $saved"
