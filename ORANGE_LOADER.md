# ORANGE loader recovery — 2026-09-12

## Confirmed cause and recovery

Packed orange.dll keeps a module table at RVA 0x4977. Entry +0x98 holds kernel32;
entry +0x9c incorrectly holds apphelp in the observed process. Resolver RVA
0xbc80 searches the latter for hash 0x89606806 and returns null. Independent
CRC32 scan of PE exports identifies **GetCursorPos**, exported by user32.dll.

Hash helper RVA 0x6b5c initializes 0xffffffff, uses table at 0x6bcb and complements
the result. CRC32 checks: GetCursorPos=89606806, CreateFileA=553b5c78,
DeleteCriticalSection=a3589103. Resolver control trace also resolves the latter
two correctly from kernel32, including an ntdll forwarder.

Changing one pointer at module RVA 0x4a13 to loaded user32 base fixes GetCursorPos
resolution and DLL initialization. Three successful runs recorded in
`user32_fix_run.log`, `user32_fix_run2.log`, `user32_fix_guarded.log`.
This establishes the mismatch and sufficient remedy in this environment.
How the packer chose apphelp is UNKNOWN; dependence on module order is LIKELY.

## Reproduce

```powershell
python tools/capture_loaded_orange.py --fix-user32
python -m unittest discover -s tests -v
```

Probe verifies SHA of ti.exe and orange.dll, starts its own process, intercepts
connect, locates packed base at a known SEH event, checks expected apphelp slot
and resolver prologue, then corrects the slot at the RVA 0xf8be event. It dumps
memory and terminates its process. Binary/config files are not patched; the
client updates its normal startup log. This is a research probe, not a launcher.
New probes write unique timestamp directories. Expected intentional unpacker
exceptions are passed on to the original handlers.

## Recovered original transport code

Mapped orange size: 0x10000. Eleven exports at RVAs 0x1180..0x11b2 are E9 stubs
into a separate allocation of size 0x7000. A module-only dump misses this code.

Second-run region: `evidence/loader-user32-fix/unpacked-0xc9b0000.bin`,
base 0x0c9b0000. Guarded third-run artifacts:
`evidence/loader-user32-fix-20260911T212202403120Z/`, region base 0x0c200000.
Use metadata JSON, never assume runtime addresses across runs. These snapshots
include resolved pointers and are not reconstructed loadable PEs.

| Export | RVA in unpacked region | Observed fragment |
|---|---:|---|
| AAaAA | 0x16a0 | checks globals, object byte +0x12e, enters 0x1a70 |
| AAaAa | 0x1640 | virtual cleanup and clears globals |
| AAaaa | 0x15d0 | returns region+0x5064 |
| AaaAa | 0x1670 | semantic analysis pending |
| aAAAa | 0x1780 | delegates to 0x1bc0 |
| aAaAa | 0x16e0 | semantic analysis pending |
| aAaaA | 0x1720 | semantic analysis pending |
| aaAaA | 0x1620 | compares u16 argument with 0xd431, enables initialization |
| aaAaa | 0x15e0 | allocates/constructs transport object when enabled |
| aaaAa | 0x1750 | semantic analysis pending |
| aaaaa | 0x16d0 | returns region+0x5058 |

No wire opcode or framing is inferred from these export names.

## Validation and limits

15 tests pass: 11 existing plus 4 new tests for hashes, failing control lookup,
two recovery recordings, and all 11 stub destinations within the saved allocation.
The third guarded live run separately succeeds. Evidence tests are checks on
recorded observations, not proof that every Windows build will work.
No network login/handshake has yet been completed. Next: NEXT_TASK.md.
