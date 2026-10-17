> **2026-09-12: непустой10 прошёл live после сетевой загрузки B9.** Старый NULL catalog fault устранён штатным loader; обработан Probe и подтверждён возврат CharSelectInfo. 54 unit tests PASS. Полный каталог/UI/world entry ещё не проверены. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). Нижние записи FAILED относятся к предыдущим запускам.

# Непустая запись CharSelectInfo10 — RE-014

## Результат и граница проверки
CONFIRMED layout прочитан из SILVER889eac и вложенного6d01f8; исходный x86
успешно разобрал записи с отсутствующим и присутствующим шестибайтовым блоком.
Непустой список отправлен живому клиенту. Он прочитал все поля, создал объект
и дошёл до88a354, затем получил access violation при обновлении модели/ресурсов.
Возврат CharSelectInfo не наблюдался. Успешный приём непустого списка НЕ заявлен.

## Полный формат
`10 | count:u16LE | records[count]`, хвостовых полей списка не найдено.
Каждая запись, в порядке wire:

| Поле кодека | Формат | Прямое доказательство |
|---|---|---|
| record_id | u8 | сохраняется в object+28 |
| name_bytes | CString | сохраняется в object+5ff4 |
| resource_type | u8 | setter a853cc, lookup a8e4b0, object+4 |
| unknown_u32_01 | u32LE | object+6000 |
| unknown_u8_01 | u8 | object+60e8 |
| select_hint | u8 | nonzero вызывает8a33ec; смысл дальше не восстановлен |
| optional_flag | u8 | 6d01f8 проверяет nonzero |
| optional_six | 6 bytes только при nonzero flag | six u8 → word offsets6,0,2,4,8,a в object+60 |
| words | 19 × u16LE | 13 чтений до88a289, затем6 прямых word stores |
| unknown_u8_02 | u8 | object+5ffc |
| unknown_u32_02 | u32LE | object+60dc |
| boolean_byte | u8 | reader605d74 нормализует nonzero в1, object+5ff0 |

Минимум54 bytes на запись плюс длина имени, ещё6 при optional_flag!=0.
С Probe (5 ASCII bytes) запись59 bytes, полный one-record packet62 bytes.
Имя ограничено255 bytes в codec; non-ASCII encoding UNKNOWN. Строгий codec
отвергает обрезанные/лишние данные и неправильные размеры. Ограничение frame65533
— политика текущего сервера. Нет ограничений count на основании UI бездоказательств.

Из13 первыхwords значения №3 и№4 читаются/отбрасываются. Остальные передаются
setter98f978 с masks1,2,10,80,4,8,400,40000,80000,100000,200000 (hex).
Последние6 сохраняются относительно object+3b0 по48,4a,568,56a,7f8,7fa.
Игровые названия числовых полей пока UNKNOWN; codec не называет их здоровьем,
предметами или навыками только по догадке.

## Native-проверки
Два original parser cases используют непохожие числовые значения и проверяют
consumption, property values, основные stores и перестановку optional block.
Original numeric readers, ветвления и6d01f8 выполняются; UI/allocator/lifecycle,
property setters и CString conversion stubbed. Это проверка wire layout,
а не готовности моделей/ресурсов. Третий case выполняет исходный lookup a78afc
с NULL-таблицей и воспроизводит access violation поa78b1c/address116.
47 unit tests прошли, включая4 новых для full layout, двух записей, optional
flags0/1/255, границ и всех обрезаний.

## Live failure и установленная зависимость
Тестовая запись: id7, nameProbe, resource_type1, остальные известные поля0,
optional block отсутствует. Это синтетические значения, не профиль реального
персонажа. Local mobs.udf определяет id1 как Man; файл/хеш/выдержка сохранены.
Клиент дошёл до88a354 (после чтения последнего поля), затем access violation:
preferredVA a78b1c, EDI=0, адрес чтения116. Lookup a78afc читает [[ac637c]]
как начало таблицы, loop bound берёт изac4e70. При NULL table и bound0 он всё
равно делает первое чтение по116. Native regression это подтвердил.

Пока не установлено, кто должен инициализировать эту таблицу: startup path,
ресурсная загрузка или предварительное серверное сообщение. Она широко
используется в функциях предметов/моделей; точное назначение и owner UNKNOWN.
Нельзя считать проблему решённой подстановкой указателя, подавлением исключения
или случайной заменой полей пакета. Изменения ресурсов/таблицы не выполнялись.

Первыйrun завис при detach после остановки клиента внутри native кода.
Созданный probe процесс установлен по parent PID и завершён. Cleanup теперь
сначала завершает собственный spawned process, затем detach; повторныйrun
завершился штатно со стороны инструмента, сохранив failure trace.

Evidence: native_character_record_probe.json, character_record_original.asm,
character_record_live_summary.json, character_record_run.log,
character_record_trace_run.log, character_resource_reference.json.
Команда: прежняя auth2 команда плюс `--character-record` вместо `--empty-characters`.
Текущий live результат этой команды ожидаемо не является успешным завершением10.

## Следующий блокер
Восстановить owner и заполнение [[ac637c]], проверить prerequisite без патча
указателя, затем повторить тот же full-record packet. Только после завершения
CharSelectInfo переходить к выбору персонажа/18 и MyCharInfo1A.
