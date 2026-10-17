# Initial TI ORANGE transport — 2026-09-12

## Последний результат: mode1 handshake, 2026-09-12

CONFIRMED: второйsocket принял clear09, клиент ответилencrypted0A; encrypted0B00
перевёл state2→3, вызвалAuthReply1 иполученapplication0C.
37 unit tests,15 native mode1 cases и8 прежнихnative cipher cases прошли.
Подробности/исправленное сопоставлениеполей — MODE1_HANDSHAKE.md.
Следующийblocker — application0C/0D; игровойвход ещёне завершён.

## История предыдущих этапов

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


## Scope and proof

CONFIRMED for the **initial login transport exchange** in this TI orange build.
Code is from original unpacked region in
`evidence/loader-user32-fix/unpacked-0xc9b0000.bin` (base 0xc9b0000).
Addresses below are offsets in that allocation, not PE RVAs in packed orange.
No AZT opcode/algorithm was imported.

Loopback probe starts original ti.exe, fixes its loader in process memory, then
calls original ORANGE export AaaAa with `(127.0.0.1, ephemeral_port, null, 0)`.
This bypasses the **UI connect action only**, not the original socket/thread,
frame parser, cipher or reply builder. No credentials were submitted.
It proves original-client transport behavior, not a full UI login.

## Framing

`u16_le total_length` + transformed payload. Length includes its 2-byte prefix.
Writer 0x1cd0 adds 2, stores u16 at 0x1d0f, sends buffer at 0x1d59.
Receiver 0x1da0 buffers incomplete input, reads word at 0x1e5b, compares available
bytes, dispatches payload after skipping 2 and walks concatenated frames.

Local checked codec accepts 1..65533 payload bytes and rejects lengths <3.
Original receiver first requires at least 3 available bytes, then tests declared
length against 2. Empty-frame behavior is therefore **not** copied blindly;
our stricter minimum is explicit validation policy. No 64K live packet tested.

IMPORTANT: writer increments send byte count when object +0x1ab >6; receiver
changes bytes/length when that counter >5. Those late transformations remain
UNKNOWN. `Initial*` classes are **not advertised for unrestricted world traffic**.

## Directional XOR and key evolution

Initial key in both native states: `50 25 9f 9a 11 91 3a 09`.
Connect initializer 0x1a90 writes it to object +0x0a/+0x12 and enables transform.
No key byte is applied to the two-byte length header.

For S2C, native decrypt 0x2710 uses `plain[i] = cipher[i] XOR key[i % 8]
XOR previous_cipher`; previous_cipher starts at zero **per frame**.
Our S2C encoder is its inverse.

For C2S, native encrypt 0x2680 uses `cipher[i] = plain[i] XOR key[7-i % 8]
XOR previous_cipher`; previous_cipher likewise resets per frame.
Our C2S decoder is its inverse. Keys themselves persist across frames.

After S2C payload of length n:
`v = (big_endian(key[0:4]) + n) mod 2^32`;
new first four bytes are `(v>>16, v>>8, v, v>>24) & 255`.
After C2S payload:
`v = (big_endian(key[0],key[2],key[1],key[3]) + n) mod 2^32`;
new first four bytes are little-endian v. Remaining bytes unchanged.

These unusual permutations were independently tested against **original x86**,
four sequential calls per direction, without stubbing functions in those routines.
Results: `evidence/native_transport_probe.json`.

## First challenge/reply

Transport dispatcher 0x2250 has branches for 00,02,09,0B.
This layer is distinct from silver application opcode 02.

S2C 00 payload (11 bytes):

```text
u8  command = 00
u8  unknown_u8_01
u32 unknown_u32_01
u8  unknown_u8_02
u32 unknown_u32_02
```

Case 00 (0x2290) runs in native state word +0x1e ==0. Both u8 fields are read
but their role is not established. Probe values are explicit experimental values,
not claimed production defaults.

C2S 01 payload (16 bytes, full frame 18):

```text
u8 command = 01
u32 transformed_u32_01
u32 transformed_u32_02
u32 unknown_u32_03
byte[3] unknown_bytes
```

Let `x = ((unknown_u32_02 XOR 0x158099e1) << 2) mod 2^32`.
First transformed field = x; second = `(x >> 2) XOR unknown_u32_01`.
Builder writes 13 meaningful bytes but submits 16; trailing three are opaque
and differ between two live runs. Do not require them to be zero or identical.
The third u32 is written after an OS call; semantic mapping still pending.

Golden evidence from `initial_loopback_encrypted.log`:

```text
S2C raw:   0d005075925e7bf8c2ca759da9
S2C plain: 0000785634120001efcdab
C2S raw:   120008b2f8dcbfb8bd94b1b522f408acc785
C2S plain: 0180db35f99820792c3e06c7663b4e12
```

Second successful exchange with production codec: `initial_loopback_codec.log`;
same transformed fields, opaque tail differs. Complete JSON records are in
timestamped loader artifact directories as `loopback.json`.

## Remaining blocker

S2C transport 02 completion branch at 0x2381: reads status and another u8,
on success reads u32 and sets state word +0x1e to1. It builds a six-byte queued
callback at 0x1f70; **not yet sent/tested in live probe**. Recover its full state
and callback semantics before sending it and then handling application auth.
09/0B mode and counter-dependent traffic modifications remain UNKNOWN.

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
