# Application 0C/0D — RE-012

## Подтверждённый результат
CONFIRMED: оригинальный клиент отправил 0C, принял 0D 00, выполнил AuthReply2
и записал «Client auth to gameserver successful, nothing to do...». Обработчик
вернулся. За 2 секунды наблюдения новых C2S bytes не было. Это завершение данной
auth-последовательности; загрузка игрового мира ещё не подтверждена.

## Форматы
C2S: `0c | unknown_string_01:CString | server_list_trailing_bytes:CString`.
Первый источник — строка по [ac5818]; второй — ac48e4, установленный trailing
CString ответа списка06. Builder: SILVER87d671..87d698, два вызова674aac.
Наблюдаемый plain: `0c302e32313a36330000` (raw first0.21:63, second empty).
Назначение первой строки UNKNOWN. Название второго поля указывает происхождение,
не предполагаемый смысл. Код сохраняет bytes, не навязывает текстовую кодировку.
Ограничение CString255 соответствует builder; embedded NUL запрещён кодеком.

S2C: `0d | status:u8`. Parser87d8a4 читает один byte через605d68.
Status0 вызывает logger6061b0 со строкой87d974 и возвращается. Ненулевой status
идёт в error UI. Семантика отдельных кодов ошибок UNKNOWN. Никакого следующего
packet builder в success-ветке нет. Кодек строго отвергает лишние bytes.

Cipher: второй S2C encrypted frame game-соединения, после0B, использует тот же
объект направления. При seed0001020304050607 plain0d00 → wire04002653.
Нельзя сбрасывать ключ между0B и0D. Login-соединение имеет отдельное состояние.

## Проверки
41 unit tests прошли, из них4 новых: live request, CString boundaries/truncation,
все256 статусов, live encrypted0D с сохранением ключа.3 original-x86 tests прошли:
status0/1/255, consumed1, success log address и error UI branch. В native harness
logging/UI/string helpers stubbed; исходные dispatcher/parser/readers выполняются.
Живой запуск дополнительно подтвердил фактический logger text и возврат parser.

Evidence: auth2_original.asm (SHA и preferred VAs), native_auth2_probe.json,
auth2_live_summary.json, полный auth2_run.log.
Reproduce:
`python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result`

## Следующий блокер
Нужно установить, какое серверное сообщение запускает игровую инициализацию.
Входная цепочка SILVER_NET3_PacketHandler9f5548 сначала проверяет auth dispatcher
87daa4, затем6d4c08 (opcode9E), затем9ff7c4 (opcode22, RECV_CreatureSay), далее
использует gate по [ac5834] и аргументу export+14 перед остальными dispatchers.
Порядок dispatchers не доказывает порядок сообщений в сессии. Opcode22 не следует
посылать как bootstrap только потому, что он расположен рано в цепочке.
Нужно исследовать gate, receivers состояния персонажа/локации и их зависимости.

Успешный0D сам не инициирует загрузку мира. Отсутствие данных за2s не исключает
поздние события. Object+1ab и ветки >5/>6 остаются ограничением transport codec.
UI ввод/выбор в probe синтетический, сервер проверяет тестовый обмен, полноценная
аутентификация реальных аккаунтов и world server не реализованы.
