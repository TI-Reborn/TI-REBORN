# Chat paste disconnect, 2026-11-17

## Incident and cause

At 15:33:36 UTC (17:33:36 Europe/Helsinki), hosting logged `Session ended: PacketError('Invalid chat text')` for the reported player session. The submitted reproduction contains 1,031 characters and eight lines. The native client can send a truncated pasted fragment; both line controls and oversized messages hit the original chat validation.

`tools/loopback_exchange.py` decoded chat for tutorial/ability command routing before reaching `Presence.chat`, which already handles validation errors. The uncaught `PacketError` closed the session.

## Change

- `tio/protocol/chat.py` normalizes CRLF, CR, LF and tabs to spaces before text validation. The existing 200-character limit and bounded raw decoding remain. Other controls, malformed Unicode and malformed packets remain invalid.
- The early command-routing decode catches `PacketError`, sends the normal client error dialog, and continues the session. Oversized text receives an explicit 200-character-limit message. Messages are not silently truncated or split into multiple sends.
- `tests/test_chat_paste.py` includes the supplied text and two-account socket regressions for long input, short multiline input, controls and truncated frames, including successful subsequent private messaging.

## Validation and deployment

- Red tests reproduced both the line-control rejection and socket EOF for the supplied text before the fix.
- Focused local suite: 22 tests passed.
- Server preflight passed; `tools/run_server_checks.py`: 724 tests passed.
- Hosted isolated candidate: 18 tests passed. Native patch tests needing pefile and a development-only contracts configuration were checked locally, not installed into the production Python environment.
- `tools/check_handoff.py` remains absent from this workspace.
- Scoped two-file deployment completed with the existing battle/settlement guards and the authorized maintenance restart. All 175 database tables were preserved during replacement; 93 accounts remained; service active; SQLite integrity ok.
- Backup: `/root/tio-before-game-operations-chat-paste-20261117-20261117`.
- No client binaries or client manifest were changed by this fix.

Public TLS acceptance passed with two fresh excluded accounts: the exact supplied text, 201 characters and invalid controls produced a rejection without disconnection; multiline text was delivered as one line; subsequent private messages were delivered. Both fixtures were removed with unrelated rows and schema preserved. Final health: active, zero automatic restarts after deployment, integrity ok, 93 accounts and both installed hashes verified. Reports: `reports/chat-paste-20261117/`.
The QA cleanup waits for successful account reauthorization without entering a character. This proves the previous gameplay worker has released the account after hub detachment, before disposable rows are removed. A socket close alone is insufficient for that guarantee.

Actual Ctrl+V in the graphical client has not been exercised. Automated tests send the corresponding native chat packets.
