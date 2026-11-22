# Native mine quit confirmation

The server allowed `admin` to quit with a carried drill containing 500 crystals,
but the client sent no quit request. Read-only inspection of the running client
found mining flag `1`, active battle `1`, alternate exit flag `0`, send block `0`.

The menu callback `9C1EFC` registers confirmation callback `9C1DA0`. That callback
calls `95DC30` at `9C1E00`: all living own fighters must stand at the map border.
If this fails, ordinary battle mode silently returns without calling the `2A01`
writer `95DF90`. Server permission B216 enables the menu but does not bypass this
second client-side restriction. Earlier packet-level tests missed this callback.

`deploy/client_mine_menu_exit.py` changes that call to a position-independent
helper in unused executable padding at RVA `821540`. In mining state (B20A,
global indirection `AC6590`) it permits sending the request; otherwise it runs
the original predicate. Server drill, crystal threshold, raider and five-round
rules remain authoritative. Only 28 bytes differ from release `2026.11.17.2`.

Verification:

- The regression probe on the old hosted DLL returns no packet from the mine
  interior. The candidate sends exactly one `2A01`.
- `python tools/verify_mine_menu_native.py PATH_TO_DLL` executes the real
  confirmation callback and numeric writers: mine interior/border, non-mine
  interior/border and native send blocking, at preferred and relocated bases.
  UI closing, string cleanup and transport flush are explicit stubs.
- Server rules: `python -m unittest discover -s tests -p test_gameplay_feedback_20261117.py -v`.
- The publisher requires all launcher native adapter regions to match, backs up
  hosted SQLite/code/config/client state and atomically changes only silver.dll.
  It does not restart the server or alter an active battle.

Publication: `python tools/publish_mine_menu_exit_20261117.py inspect`, then
`publish`, then `verify`. Private reports and binary fixtures are in
`reports/mine-menu-client-20261117/`. Release `2026.11.17.3` requires restarting
the game through the launcher to load the new DLL. Real graphical confirmation
after that restart is a separate validation step; native emulation does not
claim it happened. No player battle was ended by the verification probe.
