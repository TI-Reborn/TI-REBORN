> 2026-09-12: добавлены каталоги города: 61→62 рынок найма, 69→74 магазин, B102→B103 список услуг. Форматы проверены original readers и live. Данные пока частичные/тестовые, транзакции ещё не реализованы. См.[CITY_SERVICES.md](CITY_SERVICES.md).

> 2026-09-12: скриншоты пользователя подтвердили видимый Reservation и открытие городских окон. Запуск без таймера: `python tools/run_reservation.py`; `--seconds N` включает диагностическое закрытие через N секунд. Данные наёмников и premium ещё не восстановлены. Актуальная проверка — COMPLETION_AUDIT.md; нижние старые статусы являются историей.

> Reservation открывается серверными командами F0/98 и F0/117: два запуска подтвердили загрузку городского фона. 65 тестов проходят. Визуальная проверка и городской сервисный обмен ещё не завершены. См. [RESERVATION.md](RESERVATION.md).

> Диагностическое создание с SQLite и последовательностью1200→10 проверено live;gateac4c58 сброшен,59 unit tests PASS. Полные игровые правила/официальная success семантика не восстановлены. См.[CHARACTER_CREATION.md](CHARACTER_CREATION.md).

> Создание: C2S11 и отказ S2C1204 проверены live;57 unit +6 native cases PASS. Успешное создание/persistence ещё не реализованы. См.[CHARACTER_CREATION.md](CHARACTER_CREATION.md).

> **2026-09-12: непустой10 прошёл live после сетевой загрузки B9.** Старый NULL catalog fault устранён штатным loader; обработан Probe и подтверждён возврат CharSelectInfo. 54 unit tests PASS. Полный каталог/UI/world entry ещё не проверены. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). Нижние записи FAILED относятся к предыдущим запускам.

> B9/03 wire layout и original reader/copy проверены: 52 unit + 3 native cases PASS. Распаковка/XML loading ещё не проверены. Подробности: [SHARED_CONFIG.md](SHARED_CONFIG.md).

> Новый результат: shared-config B9/01 manifest восстановлен; зависимость items.xml найдена. См. [SHARED_CONFIG.md](SHARED_CONFIG.md). 50 unit + 2 native manifest cases PASS; live непустой10 по-прежнему FAILED.

# Reverse-engineering findings

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


## RE-007 — initial framing, XOR and actual loopback exchange (2026-09-12)

- Subsystem: original ORANGE transport. Binary: unpacked snapshot from guarded
  loader; exact file identity in evidence/manifest.json.
- Function/address: unpacked offsets 0x1cd0 writer, 0x1da0 stream reader,
  0x2680 encrypt, 0x2710 decrypt, 0x2250 dispatcher, 0x2290 challenge consumer.
- Observed behavior: u16_le length includes header; cipher enabled on initial
  mode0 connection; S2C challenge 00 produces native C2S reply01 over real TCP.
- Evidence: TRANSPORT.md, initial_loopback_encrypted.log and
  initial_loopback_codec.log, timestamped loopback.json, native_transport_probe.json.
- Interpretation: initial transport fragment is confirmed independently of AZT.
  Flags and opaque tail meanings UNKNOWN. Tail differs across two runs.
- Confidence: CONFIRMED first framing/XOR/fields/state-key updates; no claim
  of complete application login or UI connect behavior.
- Related packets: ORANGE 00/01; completion02 code branch only, not sent yet.
- Test: 21 unit tests; 8 original x86 cipher cases with sequential state updates,
  no stubbed callees in cipher; new codec exercised against original live transport.
- Experiment failures retained: initial_loopback_run.log invalid Frida ABI
  (corrected to mscdecl); initial_loopback_run2.log plaintext challenge caused
  no valid reply; encrypted attempts then succeeded. Neither failure is hidden.
- Side effects: ephemeral localhost listener, explicit original-export invocation,
  loader compatibility pointer fix in owned process, ordinary client log writes.
  No credentials, no remote connect permitted, no binary/config changes.
- Open questions: transport02 completion callback, application auth initiation,
  counter-dependent transforms after 5/6 application sends, game mode09/0B.
- Next experiment: completion02 on existing stream with maintained cipher state;
  inspect original callback, recover next producer before server response.

## RE-006 — wrong module slot; successful unpacking (2026-09-12)

- Subsystem: protected ORANGE loader. Binary orange.dll SHA
  `5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589`.
- Function/address: packed RVA 0xbc80 resolver; 0x6b5c name hash; table
  RVA 0x4977, module slot +0x9c = 0x4a13.
- Observed behavior: CRC32 0x89606806 (GetCursorPos) looked up in apphelp.dll,
  returns null. Replacing that single pointer with actual user32.dll base
  resolves the API and makes LoadLibraryW succeed in three owned processes.
- Evidence: resolver_run.log (control); user32_fix_run.log,
  user32_fix_run2.log, user32_fix_guarded.log; ORANGE_LOADER.md and snapshots.
- Interpretation: wrong module is a sufficient cause of observed failure.
  Packer module-order assumption LIKELY; origin of wrong entry UNKNOWN.
- Confidence: CONFIRMED lookup, identity, mismatch, successful local recovery.
- Related packets: none new; no login check or packet field altered.
- Side effects: process memory only; client writes its startup log. No disk
  binary/config patch. Created client processes terminated.
- Unpacking: module snapshot 65536 bytes; 11 E9 exports lead to a separate
  28672-byte allocation with transport code. Both saved, not rebuilt loadable PEs.
- Tests: 4 new evidence/hash/export tests, total 15 passing; guarded third
  runtime probe checks exact client SHA and pre-write module/instruction values.
- Open questions: transport framing/cipher/handshake, permanent compatibility
  solution, root of incorrect enumeration. Intentional SEH faults remain.
- Next experiment: derive framing from original unpacked code and capture first
  loopback exchange. Evidence hashes: recursive evidence/manifest.json.

## RE-001 — workspace and client identity

- ID: RE-001; Date: 2026-09-11; Subsystem: infrastructure.
- Binary: TI tree and reference AZT tree; Function/address: N/A.
- Observed behavior: C:\TIO-emulator initially empty; no existing protocol/source/
  tests/traces to continue. Client-source extension search returned no matches.
- Evidence: FILE_INVENTORY.md; evidence/ti_files.csv, azt_files.csv, PE JSONs.
- Interpretation: start at transport/login infrastructure; binary/resource RE required.
- Confidence: CONFIRMED inventory; absence scoped to searched extensions/directories.
- Related packets: none.
- Open questions: source archives elsewhere are not ruled out.
- Next experiment: inspect original consumer and transport initialization.

## RE-002 — application login dispatcher

- ID: RE-002; Date: 2026-09-11; Subsystem: login.
- Binary: TI silver.dll (SHA in GAMEPLAY_VERSION.md).
- Function/address: export 0x9f5548 → 0x87daa4, jump table 0x87dac4.
- Observed behavior: named callbacks 00/01/02/04/06/08/0B/0D; names include
  EventConnectResult, EventDisconnected, LSAuthResult, LSLoginResult,
  LSServerList, LSServerLoginResult, AuthReply1, AuthReply2.
- Evidence: evidence/TI.login_dispatch_table.json, TI.silver.dll.0087dafc.asm,
  packet_name_anchors.json, disassembly_provenance.json.
- Interpretation: dispatch 00/01 are local events; not proven wire packets.
- Confidence: CONFIRMED names and dispatch; UNKNOWN complete wire framing.
- Related packets: PACKET_REGISTRY.md.
- Open questions: complete send layouts and handoff state.
- Next experiment: restore transport then capture initial request sequence.

## RE-003 — first auth response and arithmetic

- ID: RE-003; Date: 2026-09-11; Subsystem: application auth.
- Binary: TI silver.dll; Function/address: 0x87ce60, 0x87c5e4.
- Observed behavior: read status u8; if 0, read u32_le, save at 0xacf3ec, call
  normal login-builder (or alternate branch). Nonzero selects error UI path.
- Evidence: original-byte disassembly + evidence/native_auth_probe.json.
- Interpretation: u32 is LIKELY challenge/token; public codec retains
  `unknown_u32_01`. Formula at 0x87c5e4 is
  `(((u32 ^ 4) * 8 * 0xe8) mod 2^32) ^ 0x375830`.
- Confidence: CONFIRMED layout, arithmetic, store and local branch;
  LIKELY token semantics; UNKNOWN end-to-end server auth.
- Related packets: 02, outgoing builder candidates 03/0A.
- Open questions: security meaning, transport wrapping, complete credentials
  representation and optional fields.
- Next experiment: verify actual C2S bytes following a framed 02 response.

Function review (requested 11 questions):

1. Caller: 0x87daa4, case 2 via 0x87db41; top-level 0x9f5548.
2. Callees: readers 0x605d68/0x605db8, log 0x6061b0, config lookup 0x688338,
   normal builder 0x87c604, alternate builder 0x87c8fc, UI/error helpers.
3. Reads: pointer-to-buffer cursor, mode flags 0xac48e8 and indirection
   0xac59a8, local account structure reached via 0xac5788.
4. Writes: cursor, global 0xacf3ec, alternate flag 0xac48e8.
5. Strings: RECV_LSAuthResult at dispatcher; success/failure log text and UI keys
   in adjacent string records (original addresses preserved).
6. Network read/write: reads application buffer; delegates subsequent send to
   builder, no direct socket call.
7. Opcode: case 02 in caller; body reads after opcode.
8. Switch: caller has 14-entry table; body branches on status and mode flags.
9. Length checks: none around the two primitive reads; length parameter is not
   used to bound this normal path. Strict codec validation is our policy.
10. State: success stores field and calls login-builder; failure does not;
    no proof of complete authenticated server session.
11. Entity: local authentication context; not yet a profile/character/entity ID.

Validation limits: Unicorn executes original dispatcher, parser and arithmetic;
UI, logs, string lookup/cleanup and login-builder calls are stubbed. 9 cases
check 5 successful values, 3 nonzero statuses, 1 unknown opcode. Five arithmetic
values independently match native x86. Unit tests cover all 255 nonzero statuses,
endian, ranges, truncation and suffix policy. No socket/client-login test passed
or was represented as passed.

## RE-004 — original ORANGE loader blocker

- ID: RE-004; Date: 2026-09-11; Subsystem: transport loader.
- Binary: ti.exe + packed orange.dll; Function/address: ti 0x718fb8,
  LoadLibraryW call 0x718fef; packed orange entry preferred 0x10004000.
- Observed behavior: instrumented startup returns null from LoadLibraryW with
  lastError 1114. Runtime target 0x78651c remains null. Late-attach control also
  finds no orange module and null target. Standalone 32-bit LoadLibrary helper
  exits code 1 without producing a full mapped image.
- Evidence: capture_exceptions.log, capture_late.log; tools/capture_loaded_orange.py;
  orange.partial.bin + orange.partial.json (local partial image); exact file
  hashes in evidence/manifest.json. The partial image was captured during failed
  initialization in the owned instrumented process, not obtained by static unpacking.
- Interpretation: blocked before connection, not malformed server response.
  Packed initializer/OS compatibility is LIKELY; exact cause UNKNOWN.
- Confidence: CONFIRMED observed load result, null pointer and partial exceptions;
  no claim that Frida is the root cause or that late-run error was directly read.
- Related packets: no C2S/S2C packet captured.
- Open questions: exception-driven unpacker includes intentional faults; final
  invalid indirect execution might follow failed API resolution, but this is
  only a hypothesis. Partial image is still packed and must not be used as DLL.
- Next experiment: trace last failing resolver/indirect call or use an older
  Windows test environment to obtain a working unpacked **TI** transport.

Each probe creates and terminates its own client process. `connect` is intercepted
before resume in normal probes; late attach does not provide this pre-start
interception. No login credentials submitted. Client updates its normal log on
launch. No client binaries/config files patched; existing log was automatically
replaced by client startup. No emulator listener exists yet.

## RE-005 — shared code/assets; TANet already in TI

- ID: RE-005; Date: 2026-09-11; Subsystem: comparative RE.
- Binary: TI/AZT trees, silver.dll and gold.dll.
- Function/address: TI 0x87daa4/0x87ce60 vs AZT 0xce6d14/0xce5608.
- Observed behavior: 524 same paths, 445 identical SHA files; 1871 common
  filtered strings; identical gold.dll; related dispatch and status/u32 readers.
  TI already contains TANet type names alongside NET3 names.
- Evidence: TI_AZT_COMMON_ANCESTRY.md and linked CSV/JSON/ASM/XML diffs.
- Interpretation: shared lineage STRONG; simplistic later introduction of all
  TANet naming in AZT is unsupported by this TI build.
- Confidence: CONFIRMED concrete matches; UNKNOWN historical direction/full
  protocol compatibility.
- Related packets: auth 02 independently recovered; no AZT-only opcode ported.
- Open questions: vtable/class layout and serialization homology beyond auth.
- Next experiment: after transport, trace TI roster/ammunition request sequence.

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
