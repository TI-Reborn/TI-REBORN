# Gameplay version scope

| Component | Identity / source | Confidence |
|---|---|---|
| ti.exe | PE timestamp `2017-03-07T15:49:10Z`, SHA `e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c` | CONFIRMED header/file |
| silver.dll | PE timestamp `2017-03-20T16:47:52Z`, SHA `a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11` | CONFIRMED header/file |
| launch log before experiments | `version 16`, recorded on 2026-08-29 | CONFIRMED log text; meaning of 16 UNKNOWN |
| Commercial release / balance epoch | timestamp is not an independently verified release date | UNKNOWN |

Every address in these docs belongs to the above binaries, not another TIO
release. Runtime silver.dll was relocated (for example `0x0cc20000`); resolve
`runtime_base + preferred_va - 0x400000`, do not invoke preferred addresses live.

Mechanic: action-point limits and action costs.
Value: UNKNOWN for this build.
Source/version: user-provided historical values are search anchors only.
Client evidence: no AP-cost consumer/constants validated in this cycle.
Confidence: UNKNOWN; no AP/loot/upgrade/location balance constants implemented.

Mechanic: textual encoding.
Value: UNKNOWN on wire; UTF-16LE ASCII-range logging strings confirmed in silver.
Source/version: current silver.dll string extraction.
Client evidence: `RECV_LSAuthResult` is UTF-16LE at 0x87dc5c; host imports
`MultiByteToWideChar`/`WideCharToMultiByte`, but call-site codepages not traced.
Confidence: CONFIRMED internal string representation; neither UTF-8 nor CP1251
has been established for packet names/chat. No network string codec added.
