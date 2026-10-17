# Выбор сервера07/08 — RE-010

CONFIRMED: оригинальная функция выбора71e998 вызвана после обработки06.
Client selection index [acdda0]+280 был0; probe явно выбирает0. Из actual record
получены id=byte0, address=pointer+4, port=u16+8. Caller71ea57 передаёт их в
builder87c7b4 как EAX,EDX,ECX; stack argument — string из[ac5818]. Это подтверждает
address иport прежнего списка06. Остальные поля06 не переименованы.

## Wire layouts
C2S `07 | server_id:u8 | unknown_bytes_01[8]` — ровно10 plain bytes.
Builder сохраняет host/port/optional string локально, не пишет их в07.
Восемь байт берутся из памяти по[ac5958], writer7f9dc0 переносит дваu32LE.
Назначение этих байт UNKNOWN. Наблюдалось `070118a28a0735000000`.

S2C `08 | status:u8`. Status0 вызывает606080(host,port,optional_string,mode1),
используя сохранённые builder значения. Ненулевой status идёт в error UI; точные
значения ошибок UNKNOWN. Строгий codec отвергает лишние байты/обрезанные payload.

## Прямые доказательства
`evidence/server_login_original.asm` — исходный SILVER, SHA сохранён в заголовке.
`evidence/native_server_login_probe.json`: original dispatcher08/parser,
status0/1/255; проверены consumed1 и exact connect args host/port/optional/mode1.
UI/string helpers/connect callback stubbed; исходные readers/ветвления выполняются.
`evidence/server_login_live_summary.json` + `server_login_run.log`: real07,
успешный08, silver connect hook mode1, реальный второй TCP accept на loopback.

Список указал собственный127.0.0.1:57192. C2S07 encrypted frame
`0c000e35bc0fea7262d4dde7`; S2C08 frame `04005f78`. Golden зависит от всей
предыдущей cipher sequence, включая динамический port в06; не фиксированный wire
шаблон для любого подключения. На втором соединении за2s bytes не пришли.

## Ограничения эксперимента
Выбор вызван через original function в onLeave parser06, не кнопкой UI.
Индекс выбран синтетически; record и builder/сокеты оригинальные. Frida не доставил
вложенный hook builder07 и его send-counter при этом NativeFunction call;
успех подтверждён фактическим07, handler08, connect hook и вторым socket accept.
Native function выбора может сохранять обычные client preferences. Файлы клиента
инструментами не патчились; loader compatibility pointer исправлен только в памяти.

Наблюдавшийся object+1ab равен0 на recv и0/1 на ненестированных send.
Это не доказательство его поведения позже и не основание называть его счётчиком
пакетов. Ветки >5/>6 остаются не восстановлены. Initial codec не распространять
на mode1 до анализа. Отсутствие bytes за2s не доказывает конкретный handshake.

Reproduce:
`python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list --server-list-entry --server-login`
33 unit tests и3 native08 cases прошли. Игровой handshake иworld login не выполнены.
