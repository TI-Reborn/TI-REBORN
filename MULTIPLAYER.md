# Этап 1: независимые аккаунты и одновременные сессии

Режим включается явно: `multi_account = true`. По умолчанию остаётся прежний
однопользовательский режим. Форматы игровых пакетов и executable клиента не меняются.

Реализованы отдельные пароли (PBKDF2-SHA256 с индивидуальной солью), сохранения
по имени аккаунта, один активный вход на аккаунт и параллельные сессии.
Существующий `probe_user` сохраняет персонажа, отряд, деньги и прогресс.
Новая таблица `accounts` добавляется в ту же SQLite-базу; старые записи не переносятся.
Пароль по умолчанию в новом режиме НЕ действует: сначала назначьте собственный.
Автоматические резервные копии включают и новую таблицу.

Добавлен экспериментальный общий бой для командной Арены: см. TEAM_LOBBIES.md.
«Выживание» также использует общую очередь реальных игроков: см. SURVIVAL_MULTIPLAYER.md. Лимит соединений — 16, нагрузочная ёмкость VPS не измерена.
Существующий транспорт клиента не является TLS. Пока допускайте только доверенные
IP тестировщиков и используйте отдельные игровые пароли.

## Порты

* TCP 28512 (`game_port`) — начальный вход.
* TCP 28513 (`session_port`) — игровая сессия в новом режиме.
* UDP не используется.

Оба handshake начинаются ответом сервера, поэтому для параллельных подключений
используются два listener. Клиент получает второй порт из существующего списка
серверов. Маршрутизация проверяет два значения handshake, срок действия, IP
и однократность использования; два клиента за одним NAT не смешиваются.

## Обновление действующего VPS

Закройте игру. В Windows PowerShell загрузите подготовленный архив:

```powershell
scp C:\TIO-emulator\data\tio-multi-stage1.tar.gz root@185.184.42.88:/root/
```

Далее в SSH под root. Блок сохраняет данные и предыдущий код, затем останавливает
игровую службу и устанавливает код. База из локального компьютера НЕ загружается.

```bash
(
set -e
test ! -e /root/tio-before-multi.tar.gz
test ! -e /root/tio-before-multi.toml
runuser -u tio -- /opt/tio-emulator/.venv/bin/python /opt/tio-emulator/deploy/scheduled_backup.py --source /var/lib/tio-server/reservation.sqlite3 --directory /var/backups/tio-server --tag pre-update
cp -p /etc/tio-server/server.toml /root/tio-before-multi.toml
tar --exclude=.venv --exclude=__pycache__ -czf /root/tio-before-multi.tar.gz -C /opt/tio-emulator .
systemctl stop tio-server
tar -xzf /root/tio-multi-stage1.tar.gz -C /opt/tio-emulator --no-same-owner
)
```

Создайте пароль для существующего аккаунта, без `--character`, чтобы сохранить
его персонажа. Ввод пароля скрыт, повторяется дважды. Пароль: 12–64 печатных
ASCII-символа без пробелов. Пароль не передавать аргументом командной строки.

```bash
cd /opt/tio-emulator
runuser -u tio -- .venv/bin/python -m server.accounts create probe_user --config /etc/tio-server/server.toml
```

Если аккаунт уже был создан, используйте `reset-password` вместо `create`.
Создайте второго тестировщика (логин `player_two`, персонаж `PlayerTwo`):

```bash
runuser -u tio -- .venv/bin/python -m server.accounts create player_two --character PlayerTwo --config /etc/tio-server/server.toml
```

Новый аккаунт получает существующий стартовый профиль эмулятора при первом входе.
Имена персонажей уникальны; логин — 3–32 строчных ASCII-буквы/цифры/подчёркивания.
Персонаж — 3–16 ASCII-букв/цифр, первый символ буква.

Включите режим и разрешите второй порт текущему IP. Если любая команда выдаёт
ошибку, не переходите к следующему блоку — сохраните текст ошибки.

```bash
(
set -e
cat > /etc/tio-server/server.toml <<'EOF'
bind_address = "0.0.0.0"
advertised_address = "185.184.42.88"
game_port = 28512
session_port = 28513
multi_account = true
data_directory = "/var/lib/tio-server"
log_level = "INFO"
EOF
chown root:tio /etc/tio-server/server.toml
chmod 0640 /etc/tio-server/server.toml
cd /opt/tio-emulator
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
TIO_CLIENT_IP="${SSH_CONNECTION%% *}"
test -n "$TIO_CLIENT_IP"
ufw allow from "$TIO_CLIENT_IP" to any port 28512 proto tcp
ufw allow from "$TIO_CLIENT_IP" to any port 28513 proto tcp
systemctl start tio-server
systemctl status tio-server --no-pager -l
ss -ltnp 'sport = :28512 or sport = :28513'
journalctl -u tio-server -n 25 --no-pager
)
```

Для друга с другого подключения добавьте его внешний IPv4 для ОБОИХ портов:

```bash
read -rp 'Tester public IPv4: ' TIO_TESTER_IP
ufw allow from "$TIO_TESTER_IP" to any port 28512 proto tcp
ufw allow from "$TIO_TESTER_IP" to any port 28513 proto tcp
```

Клиент по-прежнему использует `orange_addr 185.184.42.88` и `orange_port 28512`
в `base/autoexec.cfg` (подробнее CLIENT_CONNECTION.md). Входите назначенными
логинами и паролями. Вручную менять клиентский порт на 28513 не нужно.

## Проверка на VPS

Локальные TCP-тесты проверяют два одновременных клиента с одним IP, обратный порядок
игровых подключений, неверный пароль, повторный вход и повтор handshake, изоляцию
инвентаря/баланса, перезапуск и остановку с незавершённым подключением.
Новый режим ещё требует проверки двумя оригинальными клиентами на Ubuntu:

1. Войти одновременно как `probe_user` и `player_two`.
2. Проверить разные имена, баланс и отряды. Выполнить покупку только одним.
3. Выйти, выполнить `systemctl restart tio-server`, войти снова и проверить данные.
4. Проверить `journalctl -u tio-server -n 50 --no-pager` и выполнить
   `systemctl start tio-backup.service`.

## Возврат к предыдущему коду

При проблеме остановите оба клиента. Возврат кода и конфигурации сохраняет
актуальную SQLite-базу (включая новые аккаунты); база из backup не подменяется:

```bash
(
set -e
systemctl stop tio-server
tar -xzf /root/tio-before-multi.tar.gz -C /opt/tio-emulator --no-same-owner
cp -p /root/tio-before-multi.toml /etc/tio-server/server.toml
systemctl start tio-server
systemctl status tio-server --no-pager -l
)
```

После возврата действует прежний диагностический вход и один аккаунт; дополнительные
строки базы остаются сохранены. Новые Python-файлы могут остаться на диске,
старый runtime их не вызывает. Полное восстановление данных — отдельная операция,
см. [DEPLOY.md](DEPLOY.md); не выполнять её для обычного отката кода.
