# Самостоятельная регистрация на VPS

Адрес: https://185.184.42.88/register/ . Домен не требуется.
Кнопка клиента использует `g_reglink` в `base/config.cfg`.
Новый аккаунт и персонаж создаются одной транзакцией через server.accounts,
в существующей базе /var/lib/tio-server/reservation.sqlite3. Изменение паролей,
удаление аккаунтов и административные операции через сайт отсутствуют.
Существующие аккаунты не изменяются. Резервное копирование уже включает данные.

Сайт работает отдельной службой, игровой сервер не нужно останавливать.
Flask/Waitress устанавливаются в отдельное окружение .venv-web. Waitress слушает
только 127.0.0.1:8080, снаружи nginx принимает HTTPS на TCP443. TCP80 нужен для
сертификата и перенаправления. UDP и внешний TCP8080 открывать не нужно.
Форма требует HTTPS, CSRF-токен и совпадающий Origin; ограничение — 5 попыток
с IP в час и 100 глобально в час. Лимиты сбрасываются при рестарте сайта.
Пароли не попадают в URL, журналы или клиентские файлы.

## 1. Передача

Windows PowerShell:

```powershell
scp C:\TIO-emulator\data\tio-registration.tar.gz root@185.184.42.88:/root/
```

## 2. Подготовка в SSH

На VPS предполагается уже работающий multi_account=true и созданный аккаунт.
Не продолжайте после ошибки. Файлы игровых модулей этот архив не заменяет.

```bash
(
set -e
systemctl start tio-backup.service
tar -xzf /root/tio-registration.tar.gz -C /opt/tio-emulator --no-same-owner
apt update
apt install -y nginx python3-venv
python3 -m venv /opt/tio-emulator/.venv-web
/opt/tio-emulator/.venv-web/bin/pip install -r /opt/tio-emulator/registration/requirements.txt
python3 -m venv /opt/tio-certbot
/opt/tio-certbot/bin/pip install 'certbot>=5.4,<6'
test -e /etc/tio-server/web-secret || python3 -c 'import secrets; from pathlib import Path; Path("/etc/tio-server/web-secret").write_text(secrets.token_hex(32))'
chown root:tio /etc/tio-server/web-secret
chmod 0640 /etc/tio-server/web-secret
install -d -m 0755 /var/www/tio-acme
cat > /etc/nginx/sites-available/tio-registration <<'EOF'
server {
    listen 80;
    server_name 185.184.42.88;
    location /.well-known/acme-challenge/ { root /var/www/tio-acme; }
    location / { return 503; }
}
EOF
ln -sfn /etc/nginx/sites-available/tio-registration /etc/nginx/sites-enabled/tio-registration
nginx -t
systemctl enable --now nginx
systemctl reload nginx
ufw allow 80/tcp
ufw allow 443/tcp
)
```

## 3. Сертификат (отдельная интерактивная команда)

Certbot спросит email и согласие с условиями центра сертификации. Ответьте в
терминале. Не добавляйте --staging к этой команде: для сайта нужен доверенный
сертификат. При ошибке проверки порта80 сайт пока не включайте.

```bash
/opt/tio-certbot/bin/certbot certonly --webroot --webroot-path /var/www/tio-acme --preferred-profile shortlived --ip-address 185.184.42.88 --cert-name 185.184.42.88
```

## 4. Включение HTTPS и сайта

```bash
(
set -e
test -s /etc/letsencrypt/live/185.184.42.88/fullchain.pem
install -m 0644 /opt/tio-emulator/deploy/tio-registration.nginx /etc/nginx/sites-available/tio-registration
install -m 0644 /opt/tio-emulator/deploy/tio-registration.service /etc/systemd/system/
install -m 0644 /opt/tio-emulator/deploy/tio-cert-renew.service /etc/systemd/system/
install -m 0644 /opt/tio-emulator/deploy/tio-cert-renew.timer /etc/systemd/system/
nginx -t
systemctl daemon-reload
systemctl enable --now tio-registration
systemctl enable --now tio-cert-renew.timer
systemctl reload nginx
systemctl status tio-registration --no-pager
systemctl list-timers tio-cert-renew.timer --no-pager
)
```

Проверьте страницу браузером без предупреждения о сертификате. Создайте отдельный
тестовый аккаунт и войдите им в игру. Также выполните проверку обновления:

```bash
/opt/tio-certbot/bin/certbot renew --dry-run
journalctl -u tio-registration -n 30 --no-pager
```

Сертификат IP действует 6 дней, поэтому timer должен оставаться включённым.
Внешних уведомлений о сбое обновления пока нет; проверяйте journalctl и срок
сертификата. Если сменится IP, надо перевыпустить сертификат, изменить origin
службы, nginx и ссылку клиента.

## 5. Кнопка клиента

Только после проверки HTTPS: закройте игру. Сохраните копию base/config.cfg.
Замените строку g_reglink на:

```text
g_reglink https://185.184.42.88/register/?lang=
```

Это сохраняет прежний формат ссылки с параметром языка. Проверьте «Регистрация»
→ «Да» в оригинальном клиенте. В исполняемые файлы изменений нет.
Старый архив друга надо обновить либо дать ему исправленный config.cfg без
сохранённых паролей. До появления сайта ссылку в рабочем клиенте не меняем.

Отключение сайта: `systemctl disable --now tio-registration` — игровой сервер
и сохранения продолжают работать. Учётные записи, созданные через сайт, остаются.

Источники:
https://letsencrypt.org/2026/03/11/shorter-certs-certbot
https://flask.palletsprojects.com/en/stable/web-security/
https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html

Проверено локально: форма, создание аккаунта и проверка пароля игровым модулем,
конфликты имён, CSRF, ограничение запросов и размера. Выпуск сертификата, nginx,
systemd и реальный переход кнопкой требуют проверки на VPS.
