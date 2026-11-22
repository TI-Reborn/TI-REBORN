# Игровые администраторы

Назначение действует на игровой логин и все его слоты. Оператор с SSH-доступом
запускает команды от имени пользователя службы. Изменения вступают в силу
для уже подключённых игроков. Повторная выдача или отзыв роли безопасны.

```sh
cd /opt/tio-emulator
sudo -u tio .venv/bin/python -m server.player_admin --config /etc/tio-server/server.toml list
sudo -u tio .venv/bin/python -m server.player_admin --config /etc/tio-server/server.toml grant GAME_LOGIN
sudo -u tio .venv/bin/python -m server.player_admin --config /etc/tio-server/server.toml revoke GAME_LOGIN
sudo -u tio .venv/bin/python -m server.player_admin --config /etc/tio-server/server.toml unban GAME_LOGIN
sudo -u tio .venv/bin/python -m server.player_admin --config /etc/tio-server/server.toml unmute GAME_LOGIN
```

В лаунчере 0.1.52 и новее администратор нажимает правой кнопкой на имя
персонажа в списке чата города и выбирает **Ban Chat**, **Jail** или
**Ban Account**. Окно запрашивает причину и для временных мер срок в минутах.
Роль проверяется при отправке каждого действия. При повторном открытии
контекстного меню после отзыва роли эти пункты исчезают. Подтверждение
появляется у исполнителя поверх игрового экрана, ошибки видны в чате.

- `//banchat CharacterName 15 Причина` отключает чат на 1–1440 минут
  по часам сервера. Ограничение действует на все слоты и каналы игрового
  чата. Повтор с той же причиной не продлевает ограничение.
- `//ban CharacterName Причина` отключает игрока и запрещает вход
  этому аккаунту до `unban`. Если за одним из слотов закреплён бой или
  незавершённый расчёт, сервер отклоняет действие.
- `//jail CharacterName 60 case-123` назначает 1–3600 онлайн-секунд
  существующего [режима Prison](PRISON_MODERATION.md) указанному
  персонажу. Такая же команда с прежним идентификатором не добавляет срок.
  Штатное окно передаёт минуты с маркером `m`, например `m15`.

Игровые администраторы не могут применять эти меры к другим назначенным
админам. Сервер журналирует действие, исполнителя и цель.

## Клиент и референсы

- REA/Rizin подтвердил три пункта в `popup_userlist` и одно родное окно
  `window_admin_ban`. Меню обновляет видимость в `0xa04ee2`, обработчик
  окна формирует команды в `0x9fff3e`–`0x9ffff2`. Лаунчер меняет эти
  участки в памяти процесса после проверки опубликованного образа.
  Сервер передаёт видимость отдельно для каждого аутентифицированного
  аккаунта. REA Evidence
  `ev_41950a224eee3370d699f5c7ee7837befbfe9744343dc61ab36535f86c190f6d`
  и `ev_8cbd74c5a835f245f7342665db3b2a16c497f234c3734b8c824ca616cfa5baa8`.
  Исходники выпуска 0.1.52 находятся в `work/player-moderation-20261119/launcher`,
  план изменений проверяется кодом `deploy/client_player_moderation.py`.
- Обработчик входящего чата `0x9fed8c` считывает и отбрасывает первые четыре
  байта после opcode. Этот участок не даёт надёжного признака администратора
  в интерфейсе. REA Evidence
  `ev_db4aee71109b81aaa8adcd9b82e534ec67112562eaa4a5ebea8e8b190b124e0a`
  и `ev_179589fd10fc0ba376d092f8a85bae93c9ac5014374613b5f44ee1cc675ef688`.
- У AzerothCore оператор назначает уровень GM игровому аккаунту через консоль.
  В Luanti право выдавать и отзывать привилегии само является отдельным
  полномочием. [AzerothCore GM Commands](https://www.azerothcore.org/wiki/gm-commands),
  [Luanti Privileges](https://docs.luanti.org/for-players/privileges/).
