> **2026-09-12: непустой10 прошёл live после сетевой загрузки B9.** Старый NULL catalog fault устранён штатным loader; обработан Probe и подтверждён возврат CharSelectInfo. 54 unit tests PASS. Полный каталог/UI/world entry ещё не проверены. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). Нижние записи FAILED относятся к предыдущим запускам.

# Список персонажей — RE-013

## Последний результат: формат записи10 и найденная зависимость

CONFIRMED: полный layout непустой записи восстановлен;47 unit tests и3 native
record/catalog cases прошли. Live parser прочитал поля, но завершение10 не прошло:
при обновлении модели найден NULL в таблице [[ac637c]], fault a78b1c/address116.
Подробности — CHARACTER_RECORD.md. Следующий блокер — инициализация этой таблицы.
Непустой список и вход в мир пока не считаются успешно обработанными.

## История предыдущих этапов

## Результат
CONFIRMED: после auth0D оригинальный клиент принимает S2C10 с пустым списком,
вызывает RECV_CharSelectInfo889eac, обновление выбора8a2868 с аргументом1,
устанавливает флаг по[ac5814] в1 и возвращается. Это начало работы с выбором
персонажа, а не загрузка игрового мира. Визуальный вид экрана не проверялся.

## Dispatcher и условие допуска
SILVER_NET3_PacketHandler9f5548 сначала проверяет auth и два ранних dispatcher.
Далее условие: byte по[ac5834]==0 ИЛИ low byte четвёртого аргумента export!=0.
Если условие истинно, цепочка доходит до88b33c (call9f5651), где opcode10
отображается на889eac. Иначе вызывается9faf74 через другую ветку. Назначение
флага UNKNOWN; нельзя считать его автоматически login/world state.
Все4 сочетания flag0/1 × override0/1 проверены на оригинальном x86. Прочие
subdispatchers и конечный parser в этой проверке stubbed. В живом запуске
flag0/override0, packet прошёл без вмешательства в gate.

## Минимальный доказанный формат
`10 | count:u16LE | records[count]`.
Для count0 точный packet `100000`, без хвостовых полей. По889f25 читаетсяu16,
после очистки списка8894cc нулевойcount переходит к88a3c3; после этого полей wire
не читается. Exact empty encoder/decoder реализованы вcharacter_select.py.
Codec намеренно не принимает nonempty list, trailing bytes или truncation.

В game cipher sequence после0B и0D пустой10 имеет wire `050065f957` при прежнем
seed0001020304050607. Ключ S2C продолжает текущее состояние, не сбрасывается.
Два live runs обработали empty10; повторныйrun без ошибок instrumentation.
Нового C2S за2 секунды наблюдения не было.

## Непустая запись — ещё не реализована
Начало записи по889f46: u8, CString, u8, u32, u8, u8. Затем parser создаёт/находит
объект персонажа, вызывает вложенныйreader6d01f8 по88a0c1 и читает дополнительные
поля/структуры. Полный layout не восстановлен; перечисленный префикс не является
готовой записью. Нельзя дополнять остальную запись нулями без анализа readers.
Семантика большинства полей UNKNOWN. Character id/name выглядят вероятными,
но пока не используются как доказанные имена в codec.

Дополнительные confirmed mappings из88b33c:
12 → CharCreateResult88a79c;14 → CharDeleteResult88aa60;
18 → CharSelectResult88a4cc;1A → MyCharInfo88ac80;1C → CharInfo88b100.
Это mappings, не доказанная обязательная последовательность сервера.

## Проверки и доказательства
43 unit tests прошли (2 новых: exact empty layout/rejections и cipher continuity).
6 native cases:2 empty parser paths по результатуUI lookup и4 комбинацииgate.
В parser tests original dispatcher/u16/branches/flag stores выполняются;
UI, lifecycle иrecord initialization/finalization stubbed. Live hooks дополнительно
подтверждают выполнение реальной функции обновления ивозврат обработчика.

Evidence: character_select_original.asm, native_character_select_probe.json,
character_select_live_summary.json, empty_characters_run.log,
empty_characters_repeat.log. Все адреса привязаны к SHA исходного SILVER вASM.

Первыйrun сообщил ошибку Frida при обращении к отсутствующемуapphelp.dll, но
клиент загрузилORANGE иобработал10. Guard исправлен: если slot ужеuser32,
память не меняется; patch возможен только при известномapphelp slot иprologue.
Неизвестныйslot оставляется без изменения сdiagnostic event. Повторныйrun
подтвердил user32_slot_already_correct иполный обмен без Frida errors.

Reproduce:
`python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --empty-characters`

## Следующий шаг
Восстановить полную записьCharSelectInfo10, включая6d01f8, проверить одну запись
на native parser и затем live. После этого исследовать выбор персонажа/18.
World entry, порядок остальныхinitialization packets ипоздниеtransport изменения
по object+1ab всёещё не подтверждены. Original server packet ordering не captured:
проверен локально сконструированный exchange после0D.
