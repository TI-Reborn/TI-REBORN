# TI ↔ AZT common ancestry

## File tree и ресурсы

Сканированы 4556 TI и 9463 AZT файлов. Найдено 524 общих относительных пути,
из них **445 побайтно идентичны по SHA-256**. Полные hashes:
[common_files.json](evidence/common_files.json). Это включает общие сторонние
библиотеки и не означает 445 доказательств собственного игрового кода студии.

| Resource | Результат | Интерпретация / confidence |
|---|---|---|
| gold.dll | SHA одинаков: `e06cdf99ba5dac9e433290ebe9fc426da72b2ba2f27c82f82130532b0214c079` | CONFIRMED идентичный hook binary; не доказывает одинаковый основной протокол |
| base/cursors/ti_aim.ani, ti_aim2.cur, ti_box.ani | одинаковые SHA | CONFIRMED shared assets |
| base/battlelog.xml | разные SHA; общий root list, AZT имеет action_event | CONFIRMED структурные сходства/изменения |
| base/ground.xml | TI: 7 ground, 164 brush; AZT: 3 ground, 56 brush | CONFIRMED common element/attribute schema, content differs |
| base/assault/denver.xml, mo.xml | пути совпадают, SHA разные; общий Map/ArrowColor/ArrowsAttack | CONFIRMED shared schema; gameplay identity не доказана |
| base/serverlist.cfg | разные SHA, text diff сохранён | CONFIRMED configuration difference; AZT install уже использовался локальным эмулятором |
| cover_factors.xml, collisions.xml | найдены в AZT, отсутствуют под этими именами в TI | CONFIRMED filename absence, не отсутствие механики |

Сохранены [структуры](evidence/resource_structures.json),
[разница структур](evidence/resource_structure_diff.json), canonical XML diffs
`evidence/*.xml.diff` и `serverlist.cfg.diff`. XML diff сохраняет значения,
нормализует порядок атрибутов; cfg для просмотра декодирован CP1251, что ничего
не доказывает о wire encoding.

## Strings genealogy

[string_genealogy.json](evidence/string_genealogy.json) содержит **1871** общую
строку среди отфильтрованных network/game/resource anchors: TI/AZT binary,
preferred VA, file offset, encoding и confidence. ASCII/UTF-16 extractor может
захватывать соседние printable bytes Delphi RTTI; строки являются anchors.

| TI string | AZT string | TI silver VA | AZT silver VA | Relation | Confidence |
|---|---|---|---|---|---|
| RECV_LSAuthResult | RECV_LSAuthResult | 0x87dc5c | 0xce6ef4 | same handler log name | CONFIRMED |
| RECV_LSLoginResult | RECV_LSLoginResult | 0x87dc8c | 0xce6f24 | same handler log name | CONFIRMED |
| RECV_LSServerList | RECV_LSServerList | 0x87dcc0 | 0xce6f58 | same handler log name | CONFIRMED |
| RECV_LSServerLoginResult | RECV_LSServerLoginResult | 0x87dcf0 | 0xce6f88 | same handler log name | CONFIRMED |
| RECV_AuthReply1 | RECV_AuthReply1 | 0x87dd30 | 0xce6fc8 | same auth callback name | CONFIRMED |
| RECV_AuthReply2 | RECV_AuthReply2 | 0x87dd5c | 0xce6ff4 | same auth callback name | CONFIRMED |

## Function genealogy

TI dispatcher `0x87daa4` и AZT dispatcher `0xce6d14` имеют независимо прочитанные
14-entry tables (`TI:0x87dac4`, `AZT:0xce6d3c`). В обоих индекс 2 ведёт к
LSAuthResult, 4 — LoginResult, 6 — ServerList, 8 — ServerLoginResult, B/D —
AuthReply1/2. Таблицы сохранены отдельно; совпадения не переносились из AZT в TI.

TI `0x87ce60` читает u8, проверяет ноль, затем читает u32 и сохраняет его в global.
AZT `0xce5608` имеет ту же последовательность (calls `0x4f04f0`, `0x4f05fc`, store
`0xf654c0`), но добавляет объект/closure setup и отличается дальнейшими ветвями.
TI parser подтверждён независимо. Это **STRONG** evidence общей линии реализации
login consumer; тождественность полных packet layouts остаётся UNKNOWN.

## Проверка гипотезы NET/NET3 → TANet

Простая схема «TIO имела только NET3, TANet появился лишь в AZT» не поддерживается
этим build: уже в **TI silver.dll** есть `TANetItemTypes_AMMUNITION` (`0x608076`),
`TANetInventoryUpdateElement` (raw RTTI anchor `0x612d8a`),
`TANetBattlePlayerStatsResult` (`0x606a5e`) наряду с NET3 dispatcher/unit names.
**CONFIRMED: TANet и NET3 naming сосуществуют в данном TI build.**

Направление эволюции, история веток, serializer/vtable родство всех систем и
полный session lifecycle — UNKNOWN. Следующий полезный function comparison:
после восстановления TI transport сопоставить примитивы framing и lifecycle
по инструкциям, затем TI inventory/ammunition readers. Совпадение имён не
разрешает использовать AZT opcodes для TI.
