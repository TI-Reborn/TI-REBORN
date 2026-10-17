#!/usr/bin/env bash
# Bootstrap the confirmed empty HTTP/HTTPS host without touching the game service.
set -Eeuo pipefail
trap 'echo "Setup stopped at line $LINENO. Send the error output; the game service was not changed." >&2' ERR
test "$(id -u)" -eq 0
test -f /root/install_launcher_updates.sh
archive=/root/tio-launcher-hosting-20260923.tar.gz
printf '%s  %s\n' ab44866b087e4be6cead9c9f5301f540ec1ac91603ec34af9500a6d35f96c1fd "$archive" | sha256sum --check -
site=/etc/nginx/sites-available/tio-launcher
if [ -e "$site" ] && ! grep -q '^# TIO launcher HTTPS bootstrap$' "$site"; then
    echo "An unmanaged tio-launcher site exists. Refusing to replace it." >&2
    exit 1
fi
apt-get update
apt-get install -y nginx python3-venv ca-certificates curl
python3 -m venv /opt/tio-certbot
/opt/tio-certbot/bin/pip install 'certbot>=5.4,<6'
install -d -m 0755 /var/www/tio-acme /etc/nginx/snippets
if [ ! -f "$site" ]; then
    cat > "$site" <<'EOF'
# TIO launcher HTTPS bootstrap
server {
    listen 80;
    server_name 185.184.42.88;
    location /.well-known/acme-challenge/ { root /var/www/tio-acme; }
    location / { return 503; }
}
EOF
fi
if [ ! -e /etc/nginx/sites-enabled/tio-launcher ]; then
    ln -s "$site" /etc/nginx/sites-enabled/tio-launcher
fi
nginx -t
systemctl enable --now nginx
systemctl reload nginx
if command -v ufw >/dev/null; then
    ufw allow 80/tcp
    ufw allow 443/tcp
fi
echo "Requesting HTTPS certificate. Certbot may ask for email and agreement to Let's Encrypt terms."
echo "If validation times out, allow inbound TCP 80 and 443 in the hosting provider firewall."
/opt/tio-certbot/bin/certbot certonly --webroot --webroot-path /var/www/tio-acme --preferred-profile shortlived --ip-address 185.184.42.88 --cert-name 185.184.42.88 --keep-until-expiring
test -s /etc/letsencrypt/live/185.184.42.88/fullchain.pem
saved=$(mktemp -d /root/tio-https-before-XXXXXX)
cp -a "$site" "$saved/site"
if [ ! -e /etc/nginx/snippets/tio-updates.conf ]; then
    printf '# Managed by install_launcher_updates.sh\n' > /etc/nginx/snippets/tio-updates.conf
fi
cat > "$site" <<'EOF'
# TIO launcher HTTPS bootstrap
server {
    listen 80;
    server_name 185.184.42.88;
    location /.well-known/acme-challenge/ { root /var/www/tio-acme; }
    location / { return 301 https://185.184.42.88$request_uri; }
}
server {
    listen 443 ssl;
    server_name 185.184.42.88;
    ssl_certificate /etc/letsencrypt/live/185.184.42.88/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/185.184.42.88/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    include /etc/nginx/snippets/tio-updates.conf;
    location = / { return 302 /downloads/TIO-Launcher.exe; }
    location / { return 404; }
}
EOF
if ! nginx -t; then
    cp -a "$saved/site" "$site"
    echo "Previous nginx site restored to disk." >&2
    exit 1
fi
systemctl reload nginx
cat > /etc/systemd/system/tio-cert-renew.service <<'EOF'
[Unit]
Description=Renew TIO HTTPS certificate
[Service]
Type=oneshot
ExecStart=/opt/tio-certbot/bin/certbot renew --quiet --deploy-hook "/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx"
EOF
cat > /etc/systemd/system/tio-cert-renew.timer <<'EOF'
[Unit]
Description=Check TIO HTTPS renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now tio-cert-renew.timer
TIO_NGINX_SITE="$site" bash /root/install_launcher_updates.sh
systemctl list-timers tio-cert-renew.timer --no-pager
echo "HTTPS AND LAUNCHER READY: https://185.184.42.88/downloads/TIO-Launcher.exe"
