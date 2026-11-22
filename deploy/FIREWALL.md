# Сеть TIO

Для опционального `multi_account = true` дополнительно требуется TCP 28513
(`session_port`), а TCP 28512 используется для входа. Оба порта разрешаются
для IP тестировщиков. В обычном режиме TCP 28513 не слушается. См. MULTIPLAYER.md.

| PORT | TCP/UDP | PURPOSE |
|---|---|---|
| 22 | TCP | SSH администратора, стандартный порт чистого Ubuntu VPS |
| 28512 | TCP | Вход TIO и второе игровое подключение на тот же listener |

UDP сервером не используется: UDP-порты не открывать. 80/443 также не нужны.
28512 — новый постоянный порт standalone-сервера, выбранный по существующему
`base/autoexec.cfg` клиента. Старый LoopbackExchange использовал порт 0
(случайный порт ОС), а не фиксированный 28512. Источник: SERVER_AUDIT.md.
При изменении game_port синхронно изменить firewall и клиент.

У сервера в режиме по умолчанию известный диагностический аккаунт и нет изоляции нескольких
клиентов. Поэтому на этом этапе разрешить игровой порт ТОЛЬКО с публичного
IPv4 своего компьютера, не с 0.0.0.0/0. Это конкретное ограничение существующей
аутентификации. bind_address=0.0.0.0 этому не противоречит.

На VPS (CLIENT_IPV4 — внешний адрес компьютера, не 192.168.x.x):

```bash
read -rp 'Your client public IPv4: ' CLIENT_IPV4
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow from "$CLIENT_IPV4" to any port 28512 proto tcp
ufw --force enable
ufw status numbered
```

Сначала разрешается SSH. Текущую SSH-сессию оставить открытой и проверить новую.
Если используется Hetzner Cloud Firewall, привязать его к VPS и добавить inbound
TCP 22 (IP администратора) и TCP 28512 (IP клиента). Не добавлять исходящих
ограничений для этого рецепта. Если IP компьютера изменился, обновить оба firewall.

Проверка на сервере: `ss -ltnp 'sport = :28512'`.
Проверка с Windows: `Test-NetConnection PUBLIC_IPV4 -Port 28512`.
Проверка протокола: `python deploy/check_connection.py --host PUBLIC_IPV4`.
Последняя проверка занимает login-подключение; выполнять без активной игры.

Источники: [Ubuntu UFW](https://ubuntu.com/server/docs/how-to/security/firewalls/),
[Hetzner Cloud Firewall](https://docs.hetzner.com/cloud/firewalls/overview/).
