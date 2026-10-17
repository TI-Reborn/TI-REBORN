> 2026-09-12: добавлены каталоги города: 61→62 рынок найма, 69→74 магазин, B102→B103 список услуг. Форматы проверены original readers и live. Данные пока частичные/тестовые, транзакции ещё не реализованы. См.[CITY_SERVICES.md](CITY_SERVICES.md).

> 2026-09-12: скриншоты пользователя подтвердили видимый Reservation и открытие городских окон. Запуск без таймера: `python tools/run_reservation.py`; `--seconds N` включает диагностическое закрытие через N секунд. Данные наёмников и premium ещё не восстановлены. Актуальная проверка — COMPLETION_AUDIT.md; нижние старые статусы являются историей.

> Reservation открывается серверными командами F0/98 и F0/117: два запуска подтвердили загрузку городского фона. 65 тестов проходят. Визуальная проверка и городской сервисный обмен ещё не завершены. См. [RESERVATION.md](RESERVATION.md).

> Диагностическое создание с SQLite и последовательностью1200→10 проверено live;gateac4c58 сброшен,59 unit tests PASS. Полные игровые правила/официальная success семантика не восстановлены. См.[CHARACTER_CREATION.md](CHARACTER_CREATION.md).

> Создание: C2S11 и отказ S2C1204 проверены live;57 unit +6 native cases PASS. Успешное создание/persistence ещё не реализованы. См.[CHARACTER_CREATION.md](CHARACTER_CREATION.md).

> **2026-09-12: непустой10 прошёл live после сетевой загрузки B9.** Старый NULL catalog fault устранён штатным loader; обработан Probe и подтверждён возврат CharSelectInfo. 54 unit tests PASS. Полный каталог/UI/world entry ещё не проверены. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). Нижние записи FAILED относятся к предыдущим запускам.

> B9/03 wire layout и original reader/copy проверены: 52 unit + 3 native cases PASS. Распаковка/XML loading ещё не проверены. Подробности: [SHARED_CONFIG.md](SHARED_CONFIG.md).

> Новый результат: shared-config B9/01 manifest восстановлен; зависимость items.xml найдена. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). 50 unit + 2 native manifest cases PASS; live непустой10 по-прежнему FAILED.

# Packet registry — TI build из FILE_INVENTORY

## Последний результат: формат записи10 и найденная зависимость

CONFIRMED: полный layout непустой записи восстановлен;47 unit tests и3 native
record/catalog cases прошли. Live parser прочитал поля, но завершение10 не прошло:
при обновлении модели найден NULL в таблице [[ac637c]], fault a78b1c/address116.
Подробности — CHARACTER_RECORD.md. Следующий блокер — инициализация этой таблицы.
Непустой список и вход в мир пока не считаются успешно обработанными.

## История предыдущих этапов

## Последний результат: пустой список персонажей, 2026-09-12

CONFIRMED: S2C10 `100000` после0D проходит основной gate, вызывает
RECV_CharSelectInfo и обновление выбора персонажа, устанавливает флаг завершения.
43 unit tests и6 native parser/gate cases прошли. Повторный live run без ошибок.
Подробности — CHARACTER_SELECTION.md. Следующий шаг — полная запись персонажа
в непустом10; вход в мир ещё не выполнен.

## История предыдущих этапов

## Последний результат: application 0C/0D, 2026-09-12

CONFIRMED: оригинальный клиент принял0D00, записал сообщение об успешной
аутентификации на game server и вернулся из AuthReply2. Новых C2S bytes за2s
не было; success-ветка не вызывает packet builder. 41 unit tests и3 native0D
cases прошли. Подробности — AUTH2.md. Следующий блокер: серверная инициализация
игрового состояния, не следующий запрос клиента. Вход в мир ещё не выполнен.

## История предыдущих этапов

## Последний результат: mode1 handshake, 2026-09-12

CONFIRMED: второйsocket принял clear09, клиент ответилencrypted0A; encrypted0B00
перевёл state2→3, вызвалAuthReply1 иполученapplication0C.
37 unit tests,15 native mode1 cases и8 прежнихnative cipher cases прошли.
Подробности/исправленное сопоставлениеполей — MODE1_HANDSHAKE.md.
Следующийblocker — application0C/0D; игровойвход ещёне завершён.

## История предыдущих этапов

## Последний результат:07/08 и второе соединение, 2026-09-12

CONFIRMED: original selection71e998 → C2S07 → S2C0800 → original connect mode1
к выбранному loopback host/port; сервер принял второе TCP-соединение.
33 unit tests и3 native08 cases прошли. SERVER_LOGIN.md содержит layouts,
источники иограничения. Следующий blocker — начальный handshake режима1.
Вход вworld пока не выполнен; отсутствие bytes на новом socket наблюдалось2s.

## История предыдущих этапов

## Последний результат: список серверов06, 2026-09-12

CONFIRMED: оригинальный TI принял S2C06 с пустым списком и с одной синтетической
записью. В обоих запусках вызван SILVER87d1cc, функция обновления71e594 и возврат
из parser; в непустом случае вызван add-record71fea0. Тесты:31 unit,7 original-x86
server-list cases прошли. Форматы и ограничения — SERVER_LIST.md.
Следующий blocker: выбор сервера → C2S07 → S2C08. Вход в игровой мир не выполнен.
UI выбор не автоматизирован; connect и synthetic login заданы в owned probe.

## Предыдущие результаты (история)

## Актуальный результат 2026-09-12

CONFIRMED: оригинальный TI по TCP loopback прошёл `S2C transport00 → C2S01 →
S2C transport02 → C2S application03 → S2C application0400 → C2S application05`.
Completion `02000044332211` создаёт очередь `020044332211` и native state0→1.
Transport02 сам доставляет LSAuthResult; отдельный application02 не нужен.

Connect вызван через оригинальный экспорт. В оригинальный builder поданы
синтетические ASCII credentials `probe_user / probe_password` в памяти процесса.
Socket, cipher, parser и builder выполняются оригинальным клиентом; полный UI login
и реальная серверная аутентификация не проверены. Следующий blocker — ответ06.
26 unit tests и 9 original-x86 completion cases прошли. Evidence:
`evidence/login_success_run.log`, `evidence/native_completion_probe.json`.
Counter-dependent изменения транспорта после >5/>6 остаются UNKNOWN.

## История предыдущих этапов (содержит снятые ограничения)


## Transport update 2026-09-12

The original framing-UNKNOWN statement below is historical. Initial transport
is now CONFIRMED; see TRANSPORT.md for scope, initial XOR and late-counter limits.

### ORANGE INITIAL CHALLENGE

Direction: S2C transport. Opcode: 00. Subsystem: original ORANGE login transport.
Observed length: 13 wire /11 plain bytes. Fixed in recovered branch.
State: native word at connection+0x1e ==0.
Fields: u8 command, u8 unknown_u8_01, u32_le unknown_u32_01,
u8 unknown_u8_02, u32_le unknown_u32_02.
Response: transport 01; Side effects: writes object+0x1bb and +0x1bf;
builds and sends transformed challenge values.
Evidence: unpacked 0x2290; initial_loopback_codec.log; TRANSPORT.md.
Confidence: CONFIRMED layout, transform and original-client loopback response.
Notes: original export invoked to initiate connection; not UI login verification.

### ORANGE INITIAL REPLY

Direction: C2S transport. Opcode: 01. Subsystem: ORANGE login transport.
Observed length: 18 wire /16 plain bytes. Fixed send length in branch.
State: awaiting transport completion; exact state name analytical.
Fields: command u8, transformed_u32_01, transformed_u32_02,
unknown_u32_03, unknown_bytes[3]. Response: candidate transport 02, untested.
Side effects: native send; server probe validates transformed fields only.
Evidence: 0x2309..0x2370; two successful loopback logs.
Confidence: CONFIRMED bytes and first two field relations; UNKNOWN tail/third field semantics.
Notes: opaque trailing bytes differ between runs; preserve them unchanged.

### ORANGE COMPLETION — not implemented

Direction: S2C transport candidate. Opcode: 02. Subsystem: ORANGE.
Observed wire length: UNKNOWN live. State: native +0x1e ==0.
Fields: leading status/u8, success u32 reads inspected; complete error behavior
and callback semantics pending. Response: queued local callback, not established
as wire acknowledgement. Side effects: success sets native +0x1e=1.
Evidence: unpacked 0x2381..0x241b. Confidence: CONFIRMED code branch only.
Notes: do not confuse transport 02 with application RECV_LSAuthResult (02).

---
Original application-layer registry follows.

Все адреса — preferred VA. Confidence относится отдельно к имени, dispatch и
layout. **Транспортный заголовок, шифрование и размеры wire-пакетов UNKNOWN.**
Значения ниже наблюдаются на границе `SILVER_NET3_PacketHandler`, а не в TCP capture.

## LS-AUTH-RESULT — реализован

```text
Direction: S2C application
Name: RECV_LSAuthResult
Command/opcode: 0x02
Subsystem: Login/auth
Observed length: 6 application bytes for status 0; 2 for nonzero status
  (derived from consumed bytes; no wire capture)
Variable/fixed: conditional fixed minimum; native parser does not reject suffix
State: native parser has no auth-state admission guard; server state UNKNOWN
Fields:
  +0 u8 opcode = 0x02
  +1 u8 status (0 selects success branch; other meanings UNKNOWN)
  +2 u32_le unknown_u32_01, only when status == 0
Response:
  normal branch calls login-builder 0x87c604; outgoing full wire layout UNKNOWN
  alternate branch calls 0x87c8fc
Side effects:
  success stores unknown_u32_01 at silver preferred VA 0xacf3ec
  normal branch initiates login-builder; nonzero enters error UI path
Evidence:
  table 0x87dac4[2] -> 0x87db2e -> 0x87ce60
  UTF-16 name at 0x87dc5c
  u8 read 0x605d68; u32_le read 0x605db8
  reads at 0x87ce7f, 0x87ce9b; store 0x87cea0
  evidence/TI.silver.dll.0087ce60.asm
  evidence/native_auth_probe.json
Confidence: CONFIRMED dispatch, consumed fields, branch and storage
Notes:
  token/challenge semantics LIKELY; name remains unknown_u32_01
  Python codec enforces exact length as local validation policy
  Golden 02 00 78 56 34 12 is synthetic, not a captured server response
```

## Остальные обнаруженные входные callbacks

Общие поля этих записей: `Variable/fixed: UNKNOWN`; `Observed length: UNKNOWN
wire length`; `State: UNKNOWN server admission policy`; `Confidence: CONFIRMED
mapping/name only, incomplete layout`; `Evidence: table 0x87dac4, branch
disassembly 0x87dafc, referenced UTF-16 strings`. Их serializers не реализованы.

| Direction | Opcode | Name / subsystem | Consumer | Fields established in this cycle | Response / side effect | Notes |
|---|---|---|---|---|---|---|
| Local transport event | `00` | RECV_EventConnectResult | `0x87c984` | u32 read | manipulates `0xac48e0`, opens auth UI on a branch | **Не считать S2C wire opcode** |
| Local transport event | `01` | RECV_EventDisconnected | `0x87cd9c` | u32 read | clears `0xac48e0`, error/UI branches | **Не считать C2S challenge request** |
| S2C application | `04` | RECV_LSLoginResult / login | `0x87d00c` | leading u8 status; 0 normal branch, 0x12 separate branch | status 0 calls `0x87c76c` (builder starts `05`) | remaining error-specific fields UNKNOWN; requires full review |
| S2C application | `06` | RECV_LSServerList / login | `0x87d1cc` | UNKNOWN; preserved original code | list UI details not reconstructed | no speculative count/record codec |
| S2C application | `08` | RECV_LSServerLoginResult / login | `0x87d400` | UNKNOWN; preserved original code | handoff details UNKNOWN | no endpoint/token assumptions |
| S2C application | `0B` | RECV_AuthReply1 / auth | `0x87d608` | UNKNOWN; preserved original code | builder in this body writes `0C` at `0x87d671` | pairs with `0A` is STRONG local evidence, full relation pending |
| S2C application | `0D` | RECV_AuthReply2 / auth | `0x87d8a4` | UNKNOWN; preserved original code | post-auth state UNKNOWN | pairs with `0C` not end-to-end validated |

## Обнаруженные исходящие builders (не реализованы)

`Direction: C2S application candidate; Subsystem: login/auth; Observed length:
UNKNOWN; Variable/fixed: UNKNOWN; State: caller-dependent; Fields: only operations
below inspected; Confidence: CONFIRMED builder constants, UNKNOWN full wire
layout; Side effects: calls virtual output method; Notes: do not send fabricated
remaining fields.`

| Builder | Command written | Caller / response relation | Evidence |
|---|---|---|---|
| `0x87c604` | conditional `03` or `0A`; special branch `0A` | called after successful `02` | `0x87c675`, conditional helper calls at `0x87c6d9/0x87c6e4`; detailed branching pending |
| `0x87c76c` | `05` | after successful `04`; likely request for `06` | `0x87c77d` |
| `0x87c7b4` | `07` | server-selection candidate; relation to `08` STRONG | `0x87c81a`; records address/port parameters before building |
| `0x87c8fc` | `0A` | alternate successful `02` path | `0x87c92c` |
| inside `0x87d608` | `0C` | reached from `0B` | `0x87d671` |

## Hooks и ещё не разобранные anchors

- `SILVER_NET3_PacketHandler 0x9f5548`: chains application subsystem handlers,
  advances incoming buffer pointer by one before forwarding command separately.
- `GOLD_HandlePacket 0x10001010`: compares first two bytes to global values at
  `0x10008118/0x1000811c`, writes one byte `C9` on matching branch, returns length
  1, otherwise 0. These are **hook semantics**, not a recovered login packet.
- [packet_name_anchors.json](evidence/packet_name_anchors.json) is the complete
  extracted SEND_/RECV_/handler string index for this TI silver.dll pass.
  Entries are discovery anchors, **not confirmed callable parsers**. No names
  have been silently converted to packet layouts.

Unknown inputs must retain bytes, layer and session context. JSONL support is
in `tio/protocol/trace.py`; adjacency is reconstructed by `link_packets`, leaving
the final `following_packet` null. Raw transport data has opcode null until its
framing is known.

## Достижения B5 — 2026-09-19

`B501 mode:u8/name:cp1251Z` → `B502` каталог и прогресс собственного персонажа;
`B503` — уведомление о получении. Builder `963708`, readers `9637BC/963AC8`.
58 записей из языка клиента, четыре нативных типа приза; wire/private-public
ветвление проверено Unicorn. См. `ACHIEVEMENTS.md`,
`evidence/achievements_native.json`, `tio/protocol/achievements.py`.

## RE-008 — completion и basic login: подтверждённые layouts

Адреса ORANGE относительно unpacked allocation, не packed PE: dispatcher2250,
ветка2381..241b, queue1f70. Completion: `02 | status:u8 | discarded:u8 |
value:u32le (только status0)`. Success сохраняет value в object+1c3, state conn+1e=1,
queue6 bytes02/status/value. Failure оставляет state0, queue6 bytes, но только
первые02/status подтверждены: tail4 неинициализирован, семантика UNKNOWN.
Golden completion wire после challenge: `090027b81d092b98b3`.

Basic C2S03: `03 | login:CString | password:CString | transformed_value:u32le`.
SILVER87c604; helper674aac →605cd4 →674a44 копирует converted bytes,675bf8
добавляет NUL. Bound255; non-ASCII encoding UNKNOWN, Python сохраняет raw bytes.
Alternate0A/optional suffix не реализованы. Value11223344 →37c4c830 (LE30c8c437).
S2C success04 строго `0400`; SILVER87d072 вызывает list builder87c76c.
C2S05 captured `050026030000313031323700`, поля ещё не названы.
Live доказательства — login_success_run.log; x86 — native_completion_probe.json.
Это исправляет прежнее предположение об отдельном application02 после completion.
