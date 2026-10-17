# Список серверов05/06 — RE-009

Обновление RE-010: record+4 address иrecord+8 port теперь CONFIRMED по выбору
и реальному mode1 connect; record byte0 передаётся как server_id в07.
См. SERVER_LOGIN.md. Ниже сохранены первоначальные оценки.

## Источники и уверенность
CONFIRMED layout из оригинального SILVER SHA256
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.
Preferred VAs: parser87d1cc, request builder87c76c, u8 reader605d68,
u16 reader605d8c, u32 writer6e1d70, CString605f1c→605e8c.
Полный ASM: evidence/server_list_original.asm. Native tests:
evidence/native_server_list_probe.json. Live raw/hooks:
evidence/server_list_live_summary.json и два исходных server_list_*_run.log.

## C2S05 request
`05 | unknown_u8_01 | unknown_u32_01:LE | trailing:CString`.
Builder пишет первый байт поля как0; наблюдались u32=806 и строка10127.
Их семантика UNKNOWN. Не считать их version/build без дополнительных xrefs.
Captured plain: `050026030000313031323700`.

## S2C06 list
`06 | count:u8 | unknown_u8_01 | entries[count] | trailing:CString`.
Header unknown byte читается и отбрасывается. Count0 поддержан прямо в parser.
Запись занимает ровно12 байт:

| Offset в записи | Формат | Native destination / вывод |
|---|---|---|
| 0 | u8 | record+0; семантика UNKNOWN |
| 1..4 | 4 octets | преобразуются в десятичные строки с точками, record+4 pointer; IPv4 STRONG |
| 5..6 | u16LE | record+8; port LIKELY, codec пока сохраняет unknown_u16_01 |
| 7..8 | u16LE | record+0a; unknown_u16_02 |
| 9..10 | u16LE | record+0c; unknown_u16_03 |
| 11 | u8 | record+0e; unknown_u8_02 |

Дополнительно record+0f получает производную от100*second_u16/(third_u16+1);
это не поле wire. Похожесть на загрузку сервера — LIKELY, не имя поля в codec.
Память record16 bytes содержит padding и указатель, её нельзя отправлять на wire.

Trailing CString читается доNUL, сохраняется в global ac48e4 и копируется в
shortstring по [ac5b7c]+124. Семантика UNKNOWN. Native reader использует255-byte
shortstring и продолжает сканирование доNUL; strict codec ограничивает строку255
байт как собственную политику. Non-ASCII encoding ещё UNKNOWN, сохраняем raw bytes.
Native guard проверяет только length-2 >= count*10, хотя читает12 bytes/entry и
строку. Строгий codec отвергает truncation/trailing data; это намеренная серверная
валидация, не воспроизведение слабых проверок клиента.

## Проверка
7 original-x86 cases: count0/1/2 × header0/255 и короткий packet, отвергаемый guard.
Исходные dispatcher/parser/u8/u16/empty CString scanner выполняются. UI, allocator,
Delphi strings и numeric conversion40742c stubbed; проверены consumption, numeric
record stores, count и вызов refresh. Address string construction в harness не
проверяется, её layout установлен disassembly. Native тесты не подтверждают UI.

Live empty plain `06000000`, encrypted frame `0600a3f4d34c` после00/02/04.
Live single record: synthetic id1, octets127.0.0.1, first u16 равен probe port,
second0, third100, last0, trailing empty. Это тестовые значения; смысл unknown
полей не объявлен доказанным. Создана одна настоящая запись, вызван refresh и parser
вернулся. Нового C2S за2 секунды наблюдения не было; это не доказательство его
отсутствия при выборе сервера. Визуальный вид UI не проверялся.

Команды:
`python tools/verify_server_list_native.py`
`python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list`
Добавить `--server-list-entry` для одной записи.
Все подключения ограничены собственным loopback endpoint. Initial codec пока
проверен только на ранних кадрах; counter-dependent изменения остаются UNKNOWN.
