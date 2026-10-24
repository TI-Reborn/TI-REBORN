# Battle delivery under network backpressure

The supplied 158-second recording shows two `Disconnected. Reason is 0`
messages. Server timestamps place the disconnects immediately after a mutant
turn at 17:03:52 and 17:04:46 Helsinki time. Both reconnects resumed the same
authoritative battle. No server traceback or match quarantine accompanies
those events. Later turns continued after the nearby mutant died.

The journal did not retain the originating socket error or outbound packet
trace, so the exact cause of those two incidents remains unconfirmed. In
particular, this report does not establish corrupt saves, incorrect turn
ownership or an idle-watchdog expiry. Analysis of an existing backup was
read-only; no player state was changed or replayed against production.

## Confirmed delivery defect

`TeamArena.pump` uses a 0.1-second socket timeout to poll incoming commands.
`TeamArena.drain` previously inherited that timeout for `sendall` as well.
Backpressure lasting longer than 100 ms could therefore terminate a game
connection during an outgoing turn burst. A surrounding legacy handshake
timeout handler could consume that exception without an INFO/WARNING entry.

This change gives queued writes their own five-second timeout. The following
input poll still explicitly uses 0.1 seconds. Writes remain outside the shared
hub lock and inside the owning session thread. No encrypted frame is retried:
`sendall` may have transmitted a prefix before failing. Failed delivery now
logs the account, owner ID and exception type without packet or credential
contents. Reconnect retains the existing authoritative scene-recovery path.

The socket timeout bounds each write, not the duration of an entire queue
flush. The existing 2048-packet queue limit remains in force. No gameplay rules,
client opcodes, storage schema or launcher/client binaries change.

## Regression coverage

`tests/test_battle_delivery.py` exercises actual sockets and the production
encrypted-frame encoder/reader. A stress queue uses 600 inventory-sized frames
to reliably fill buffers on both Windows and Linux; it is not a reconstruction
of the player's actual packet contents or traffic volume.

- A receiver paused for 0.3 seconds receives every frame in order, without
  missing/duplicate frames or cipher-state damage. The old 0.1-second write
  budget fails this test with `TimeoutError`.
- A stalled receiver still times out, emits a delivery diagnostic and does
  not prevent another account from receiving its own packets.
- A successful write is followed by the original short input-poll timeout.
- Existing heartbeat checks retain periodic delivery and do not mark a failed
  heartbeat as sent.

These checks establish the delivery fix. Confirmation of the reported client
incident requires observing subsequent real-client turns; automated socket or
TLS checks alone do not establish graphical gameplay acceptance.
