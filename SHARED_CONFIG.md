# 2026-09-12 — live B9 доставка и непустой10 подтверждены

CONFIRMED: `B9/01 → C2S B9/02 items → B9/03 → C2S B9/04 → S2C10`
прошла на оригинальном TI. Загрузчик a7005c вызван обработчиком сети;
предварительный NativeFunction loader в этом запуске НЕ использован.
Таблица из NULL стала ненулевой, bound=2. Затем обработан id7/Probe/type1,
достигнут88a3b7 и возврат889eac, flag[ac5814]=1. Старый fault116 устранён
штатной загрузкой ресурсов. Вход в мир и внешний вид UI не проверены.

## Схема и источник
Атрибуты id/name читаются680770 из XML node+4. Properties helpers6807d0,
680860,680974 используют node+8. Parser680278..6802f2 сохраняет атрибуты
key/val дочернего элемента в словарь родителя. Fixture использует
`<items><item id="0" name=":)"><value key="empty" val="1"/>...</item>...</items>`.
680a48 требует наличия дочерних узлов; запись без них пропускается.
Полная schema (вложенные effects/attack types/все defaults) НЕ восстановлена.

`tools/build_item_fixture.py` строит две частичные диагностические записи
0 и300 из установленного TI base/items.cfg. ID300 указан в mobs.udf как
human default weapon. Перенесены только выбранные совпадающие ключи,
никаких автоматически переименованных damage/accuracy stats. Source SHA,
включённые/пропущенные поля: items_diagnostic_provenance.json. Это не полный
игровой каталог и не восстановленный баланс; источник AZT не использован.

## Проверка и воспроизведение
Первый loader-only запуск подтвердил принятие XML. Второй — ids[0,300]
и непустой10 после явного вызова loader. Третий, основной, передаёт XML по сети.
Python zlib.compress payload штатно распакован TI: сохранённый XML побайтно
равен fixture (SHA в shared_config_delivery_summary.json). Тем самым обычный
zlib wrapper подтверждён live, не только по имени TZDecompressionStream.
Manifest comparison_value=1 — диагностическое значение для отсутствующего
файла с local value0, а не утверждение о checksum algorithm.

Команда из C:\TIO-emulator:
```powershell
python tools/build_item_fixture.py
python tools/probe_item_fixture.py --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --shared-config --character-record
```
Probe отказывается перезаписывать существующий items.xml. В network mode
файл создаёт сам клиент. После закрытия собственного процесса точное совпадение
с fixture/его zlib bytes удаляется; неожиданное содержимое сохраняется.
Снимок последнего файла — items_last_probe_saved.bin. Итоговая проверка:
items.xml отсутствует, ti.exe процессов нет. Каталог shared config может остаться.

54 unit tests PASS, включая encrypted socketpair flow и отказ на неверный ответ.
Native fixtures прошлых циклов сохранены; полный loader теперь проверен live.
Существующие probe hooks для credentials/server selection и guarded ORANGE
resolver всё ещё используются. Это не подтверждение полностью ручного UI login.

Evidence: item_schema_original.asm,item_schema_key_inventory.json,
items_diagnostic.xml,items_diagnostic_provenance.json,item_fixture_run.log,
item_fixture_character_run.log,shared_config_delivery_run.log,
shared_config_delivery_summary.json. Основная live трасса содержит и обычные
исключения packed ORANGE startup; их не смешивать с поздним fault silver.

## Дальнейшая работа
Проследить штатный выбор персонажа: UI callback, builder C2S и parser S2C18.
Не присваивать запросу opcode по соседству. Ограничения полного каталога,
comparison algorithm и transport counters остаются отдельными задачами.

---
# B9/03: формат содержимого восстановлен

CONFIRMED по9d0484: B9,03,name:CString,decompressed_size:u32LE,
compressed_size:u32LE,data[compressed_size]. Оба размера читаются605da0.
605f4c копирует ровно второй размер; переданный ECX=50000 внутри helper
заменяется размером из стека. Кодек ограничивает данные50000 для соблюдения
ёмкости локального буфера клиента. Это ограничение эмулятора, не проверка клиента.

9d0578 пишет сжатые данные черезa89740 (CREATE_ALWAYS) в
`<root>shared config\<name>.xml`. Затем memory stream читает этот файл,
6878ec создаёт TZDecompressionStream (VMT52cb78,class name52cbe2), читает
первый размер распакованных байтов и записывает их другим stream обратно в тот
же файл. Constructor52d938 передаёт windowBits15 через52d970/52d138.
STRONG: стандартный zlib wrapper; непосредственная распаковка нашим payload
в оригинальном клиенте в этом цикле НЕ проверялась. Кодек сохраняет сжатые
байты непрозрачно и не объявляет произвольные байты валидным zlib.

Это целый файл в одном B9/03, без видимой сборки chunks в данной ветке.
После сохранения9d0625 вызывает9d2afc, затем9d062d вызывает reload9d1f68.
Общий размер, счётчики транспорта и пригодность большого файла в live ещё
не проверены. 0xffffffff в первом размере имеет специальную ветку687906;
её внутренний заголовок не восстановлен, автоматически не используется.

Live read-only snapshot: root=C:\Program Files (x86)\TIOnline\base\.
Лог shared_config_root_run.log. Этот запуск не отправлял B9/03 и не создавал XML.
Native verifier выполняет9d070c,9d0484,primitive readers и оригинальную
605f4c/406cf8 copy. Остановлен в9d04fb до filesystem/decompression; CString
conversion/logging stubbed. Размеры0,31,50000 прочитаны точно.52 unit tests PASS.

Следующий блокер — TI XML schema и содержимое. AZT reference содержит
синтетический compatibility catalog; в TI он не копировался и доказательством
TI содержимого не считается. Непустой10 и world entry остаются незавершёнными.
Evidence: shared_config_data_original.asm,native_shared_config_data_probe.json,
shared_config_data_summary.json,shared_config_root_run.log.

---
# Shared config и зависимость непустого списка персонажей

## CONFIRMED
Адреса — preferred VA оригинального silver.dll, SHA256
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.

Основной dispatcher вызывает 9d070c по адресу 9f5761. Он распознаёт B9:
- S2C B9/01 → 9d0408, строка RECV_SharedConfigSet.
- S2C B9/03 → 9d0484, строка RECV_SharedConfig.
- C2S B9/02 → 9d036c, CString имени конфигурации.
- C2S B9/04 → 9d03d8; дальнейшая семантика завершения не проверена.

B9/01: opcode B9, subcommand01, count:u8, затем count записей
(name:raw CString, comparison_value:u32LE). Кодек сохраняет значение без
предположения об алгоритме checksum/version. Ограничение имени 255 bytes —
политика эмулятора, не установленный лимит оригинального reader.

9d0408 создаёт записи через 9d2a78, затем вызывает 9d2ba8. Эта функция сравнивает
поле +8 с локальным значением +c; при несовпадении вызывает builder9d036c,
при равенстве — 9d1f68. 9d0484 после обработки полученных данных также вызывает
9d1f68 по адресу9d062d. Полный формат и сборка содержимого B9/03 ещё НЕ восстановлены.

9d1f68 сравнивает имя с items (literal9d2498) и вызывает a7005c.
Этот загрузчик строит путь из [[ac5c80]], `shared config`, `\items.xml`.
Проверяет существование файла, читает XML, выделяет dynamic array через40d5a4
в a701d1 с owner[ac637c]. Stride записи0x3a78. После обработанной записи
пишет boundac4e70 в a73b8b. Error literal: ReadXMLGameItemDatas: File not found.
Точный runtime prefix [[ac5c80]] пока не снят. В установленном дереве TIOnline
поиск items.xml ничего не нашёл; items.cfg не считается эквивалентом XML.

## Проверка
Новая live трасса catalog_startup_run.log: owner ненулевой, tableNULL,bound0
перед CharSelectInfo; ни одного вызова XML loader/reload dispatcher за время
наблюдения. Чтение полей прежнего Probe завершено; снова fault a78b1c/read116.
Ресурсная зависимость определена, но НЕ восстановлена. Hooks наблюдают загрузку
модуля с запуска; бинарные файлы и таблицы ресурсов не патчились.

Native verifier выполняет оригинальные9d070c/9d0408 и примитивные readers:
2 cases (empty,items+mobs), точное потребление и значения. CString conversion,
создание списка, loading и logging stubbed. Это не проверка загрузки XML/UI.
50 unit tests прошли; собственный ti.exe завершён, оставшихся ti.exe нет.

Evidence: shared_config_original.asm, native_shared_config_probe.json,
catalog_init_summary.json, catalog_startup_run.log.

## Следующий шаг
Восстановить B9/03: размеры, упаковку/сборку данных, путь сохранения; проверить
XML schema на собственном TI loader. Найти пригодный TI источник содержимого,
не подменять items.xml файлом AZT или пустым фиктивным каталогом. После штатной
инициализации повторить ту же запись10. До этого world entry не заявляется.
