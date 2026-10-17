# Проверка смены хода — 22 сентября 2026

Проблема настоящих клиентов пока не воспроизведена. Нельзя считать её исправленной.
Новый TCP-тест создаёт два отдельных лобби «Стенки», объединяет двух людей
и шесть ботов, выполняет три круга пропуска (actor=0 и реальный ID бойца),
проверяет ответ 39 и следующий 38, затем истечение времени первого игрока
и передачу второму. Проверка проходит. Отдельные native-проверки подтверждают
построитель 3A и обработчик 38 оригинального клиента с UI-заглушками.

Добавлена только диагностика в server/team_arena.py: team_turn_started,
team_turn_skipped, team_turn_expired и opcode в team_request_rejected.
Правила и порядок ходов не менялись. Запись started означает постановку
пакета в очередь, а не подтверждение отображения на экране клиента.

Для диагностики завершить текущий бой и выйти обоим игрокам.
Windows PowerShell:

```powershell
scp C:\TIO-emulator\server\team_arena.py root@185.184.42.88:/root/team_arena-diagnostics.py
ssh root@185.184.42.88
```

Затем на VPS:

```bash
(
set -e
test -f /root/team_arena-diagnostics.py
test ! -e /root/team_arena-before-diagnostics.py
cp -p /opt/tio-emulator/server/team_arena.py /root/team_arena-before-diagnostics.py
/opt/tio-emulator/.venv/bin/python -m py_compile /root/team_arena-diagnostics.py
systemctl stop tio-server
install -m 0644 /root/team_arena-diagnostics.py /opt/tio-emulator/server/team_arena.py
systemctl start tio-server
sleep 2
systemctl is-active tio-server
)
```

Повторить бой и пропуск. Сохранить вывод:

```bash
journalctl -u tio-server --since '10 minutes ago' --no-pager
```

Также нужны фактические наблюдения обоих игроков: чья надпись «Ваш ход»,
можно ли двигать своего бойца, какое число ОД до и после пропуска.
Это отделит отсутствие запроса от отказа сервера или проблемы отображения.

Откат только диагностического изменения:

```bash
systemctl stop tio-server
install -m 0644 /root/team_arena-before-diagnostics.py /opt/tio-emulator/server/team_arena.py
systemctl start tio-server
```
