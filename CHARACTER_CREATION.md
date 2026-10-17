# Создание с хранением: диагностический путь проверен live

CONFIRMED совместимость последовательности в нашем эксперименте:
пустой10 → original builder11(ProbeNew,0,0,0,0,0) → сохранение SQLite →
повторное открытие базы →1200→10 с сохранённой записью id1.
Клиент прочитал12, обработал ProbeNew и вернулся из10; flagac4c58=0.
Это проверенный сценарий эмулятора, а не запись обмена официального сервера.

Предыдущий trial только11→10 также обработал новую запись, но оставил
flagac4c58=1. ac5940 содержит адресac4c58; builder889cdc проверяет этот флаг
и при1 подавляет новый запрос. Setter9dc760 пишет флаг; builder ставит1,
result parser12 сбрасывает0. Поэтому один10 не завершает этот цикл полностью.
В коде12 значение0 всё ещё попадает в default с логом unknown. Не переименовывать
это в доказанный официальный success status. Live подтвердил отсутствие блокировки
и принятие записи для выбранной последовательности; внешний вид UI не проверен.

## Минимальное хранение
`tio/characters.py`: SQLite, транзакцияBEGIN IMMEDIATE, отдельный slot на account,
глобальный name_key unique, исходный request11 сохранён как BLOB. Connection
закрывается явно черезclosing, включая исключения; первая версия выявила
незакрытые handles в Windows тестах, исправлено и весь suite повторён.

Ограничения диагностической политики:1 персонаж/account;ASCII имя3–16,
первая буква,далее буквы/цифры;case-insensitive uniqueness. Это наши ограничения,
не восстановленные полностью правила сервера. Только u16=0/options0000;
прочие profile варианты вызывают NotImplementedError без записи в базу.
Возвращаемый10 использует ранее проверенный частичный human profile/type1.
Остальные неизвестные игровые поля не получают выдуманных названий.

Store выдаёт ошибки4 invalid,3 duplicate,2 account diagnostic limit. В текущем
loopback positive probe используется только чистая база в новом evidence run;
это не самостоятельный многопользовательский сервер/полноценная аутентификация.
Account probe_user синтетический. Перезапуск store после commit проверен;
повторный сетевой login с тем же аккаунтом ещё не проверен.

## Воспроизведение
```powershell
python tools/probe_item_fixture.py --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --shared-config --empty-characters --create-success-probe
```
Flag create-success-probe обозначает диагностический сценарий выше.
NativeFunction вызывает оригинальный builder напрямую; полноценная форма создания
не используется. Shared config доставляется по сети. База остаётся в каталоге
конкретного evidence run, путь записан в summary; temporary items.xml удалён.

59 unit tests PASS: повторное открытие,account isolation,duplicate/limit rejection,
unsupported options и отсутствие записи при отказе. Live три новых trials:
character_create_positive_trial.log (list only),character_create_persisted_run.log
(persist,list,flag1),character_create_ack_trial.log (persist,1200,list,flag0).
Итог: character_create_persistence_summary.json. Process ti.exe завершён.

Следующий шаг: выбор сохранённого персонажа через штатный callback/C2S builder,
затем восстановить18. Полный профиль, UI submit и reconnect остаются ограничениями.

---
# Создание персонажа: запрос и отказ подтверждены

CONFIRMED C2S11 builder889cdc: name raw CString, unknown_u16 LE,
четыре option bytes. ABI EAX=Delphi name, EDX=u16, stack+4/+8/+c/+10
соответствуют последнему/третьему/второму/первому option. ECX не используется.
Builder подавлен, если byte[[ac5940]]!=0. UI caller8a3062 передаёт u16=0,
первый option из выбранного control+278, остальные0. Семантика options UNKNOWN.
Имя UI берётся из control+58 после предшествующей обработки текста.

CONFIRMED S2C12 parser88a79c читает один u8:
1→cw06 общий отказ;2→cw07 лимит персонажей (english/russian.lng),
3→cw08 имя занято;4→cw09 недопустимое имя.
German translation cw07 противоречит English/Russian, поэтому локализации
не следует считать серверной спецификацией.0 и прочие попадают в default,
который вызывает8a2868(1) и логирует Char create result unknown. 0x0x.
Это НЕ доказательство success. Ни выделения персонажа, ни чтения новой записи
в12 нет. Возможно, успех приходит обновлённым10; это пока UNKNOWN.

Реализация: tio/protocol/character_create.py сохраняет неизвестные поля,
строго проверяет длину/хвост/ranges.255-byte name — policy codec, не UI limit.
UI localization указывает3–16,но полная серверная validation не восстановлена.

Live repeat: после пустого10 вызван оригинальный builder через маленький
Delphi ABI trampoline в собственном процессе, synthetic name1/u16=0/options0.
C2S plaintext113100000000000000, S2C1204; parser entered status4 и вернулся.
Эмулятор пока диагностически отвечает4 для этого точного запроса. Это не
production endpoint создания и не сохранённый новый персонаж.
First run FAILED из-за освобождения JS Memory.alloc buffer, адрес которого
был встроен в trampoline. Closure теперь удерживает name/code allocations;
повтор PASS. Не скрывать первый результат (character_create_run.log).

57 unit tests PASS.6 original-x86 result cases PASS (0,1,2,3,4,255), UI,
localization/logging stubbed. Request wire проверен настоящим socket exchange.
Evidence: character_create_original.asm,native_character_create_result.json,
character_create_repeat_run.log,character_create_summary.json.

Повтор:
```powershell
python tools/capture_loaded_orange.py --fix-user32 --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --empty-characters --create-probe
```
Следующий шаг: восстановить положительный путь (обновлённый10 или иной ответ),
смысл первого option и UI callback; только затем реализовать сохранение нового
персонажа. Существующий Probe в предыдущих экспериментах был synthetic list entry.
