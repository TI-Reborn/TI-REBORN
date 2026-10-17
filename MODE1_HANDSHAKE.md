# Начальный обмен второго соединения — RE-011

## Доказанный переход
CONFIRMED в original code, native x86 иживом TI:
`08 success → connect mode1 → state2/cipher0 → S2C09 clear → C2S0A encrypted →
S2C0B encrypted → state3 + queued0B → SILVER AuthReply1 → C2S application0C`.
Это transport handshake, а не завершённый игровой вход.

## Инициализация
ORANGE unpacked1a90: при уже открытом предыдущем соединении иmode byte1
ветка1b44..1b9c сбрасывает ключи, закрывает прежний socket, ставит state2 иcipher0,
открывает новыйsocket. Live hooks подтвердили mode1,state2,cipher_enabled0.
Полное32-bit значение mode-аргумента имеет незначимые старшие биты; код проверяет
только low byte. Первый исследовательский hook ошибочно печатал полныйu32;
исправленныйrun читает low byte. Cold mode1 без предыдущего login не проверен.

## S2C09: cleartext challenge
`u16LE total11 | 09 | challenge_bytes[8]`.
Original branch241e проверяет payload length>8, XOR каждого из8 байт с
`ac2a77993f3a51b4`, записывает одинаковый key воба направления ивключаетcipher.
Сам09 не шифруется ине расходует состояние ключа. Server codec строго требует
ровно8 challenge bytes; trailing bytes отвергает как свою политику.
Seed `0001020304050607` → key `ac2b759a3b3f57b3`.
Golden frame `0b00090001020304050607`.

## C2S0A: encrypted reply
Plain `0a | previous_transport_u32:LE | completion_u32:LE`.
Источник первогоu32 — object+1bf: второй вычисленныйu32 ответа transport01,
записанный по22ff; источник второго — object+1c3 изcompletion02.
Это не третьеopaque поле01. Первыйlive run выявил ошибку проверки этого
сопоставления; сохранён вmode1_challenge_run.log. Ошибку исправили поASM иtrace.

Для исходногоchallenge00 иcompletion11223344:
plain `0a9820792c44332211`, wire `0b00b976692b9dacb43a98`.
Key C2S послеответа: `a32b75ac3b3f57b3`. Используется прежняя доказанная cipher
функция2680, но новыйключ; login cipher state на второйsocket не переносится.

## S2C0B: completion иapplication0C
Plain `0b | status:u8`. Вstate2 исходныйparser24eb читаетstatus иставит точные
двабайта вочередь. Status0 меняет state2→3, ненулевой оставляет2. Вдругомstate
этаветка не ставит callback. Status meanings кромеуспеха UNKNOWN.
S2C cipher начинается сderived key иотдельно отC2S: success wire `0400a78c`.
Это вызывает SILVER87d608 AuthReply1, status0 builder формируетapplication0C.

Captured C2S0C plain `0c302e32313a36330000`, wire `0c00bfd8c9c05d120f9f2c7b`.
Static builder87d671..87d698: opcode0C, CString из[ac5818], CString изac48e4
(последняя установлена trailing CString списка06). Вrun: raw first=`0.21:63`,
second empty. Смысл строк UNKNOWN; не считать их паролем/версией бездоказательства.
Отдельногоcodec0C иответа0D ещё нет.

## Проверки ивоспроизведение
37 unit tests прошли (4 новых): golden09/key, live0A/0B/0C cipher continuity,
all status bytes, invalid lengths/keys/truncation.15 original-x86 cases прошли:
3 seeds для09+native2680,8 коротких09,3 completion statuses иwrongstate.
Send1c90/queue1f70 stubbed; original dispatcher/readers/key derivation/builders/
cipher выполняются. Дополнительно8 прежнихnative cipher/state cases прошли.

Evidence: mode1_original.asm, native_mode1_probe.json, mode1_live_summary.json,
mode1_completion_run.log. Старыйfailed field-mapping run сохранён отдельно.
Command:
`python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete`

## Ограничения
UI login/выбор заменён вызовомoriginal функций сsynthetic input. После0C
эксперимент завершает owned process. World readiness не доказана.
Object+1ab иветки длины/байтов >5/>6 всёещё не восстановлены; не расширять
InitialCipher/frame codec на произвольный длительныйgame traffic.
