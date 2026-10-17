# Client file inventory

TI root: `C:\Program Files (x86)\TIOnline`. AZT root: `C:\Program Files (x86)\Steam\steamapps\common\Affected Zone Tactics`.

Complete TI tree: **4556 files**, every size and SHA-256 in [ti_files.csv](evidence/ti_files.csv). AZT tree: **9463 files** in [azt_files.csv](evidence/azt_files.csv).

PE timestamps are header claims, not independently established release dates. Preferred VAs require relocation at runtime.

| File | Bytes | SHA-256 | PE timestamp UTC |
|---|---:|---|---|
| [d3dx9_26.dll metadata](evidence/TI.d3dx9_26.dll.pe.json) | 2297552 | `8ea96fe01c3c86a36fcb3795ae03eb12034003e335ef475571efaeda17c5bc78` | 2005-05-26T22:17:37+00:00 |
| [gold.dll metadata](evidence/TI.gold.dll.pe.json) | 40960 | `e06cdf99ba5dac9e433290ebe9fc426da72b2ba2f27c82f82130532b0214c079` | 2012-05-21T10:48:48+00:00 |
| [ode.dll metadata](evidence/TI.ode.dll.pe.json) | 446464 | `fdba0e4b4fbeb1e6cf33ab96c9f7080235e73d9d9b1afeb2205f31eb67ee66e3` | 2004-05-18T22:52:47+00:00 |
| [orange.dll metadata](evidence/TI.orange.dll.pe.json) | 126464 | `5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589` | 2009-01-19T14:13:01+00:00 |
| [silver.dll metadata](evidence/TI.silver.dll.pe.json) | 7732224 | `a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11` | 2017-03-20T16:47:52+00:00 |
| [ti.exe metadata](evidence/TI.ti.exe.pe.json) | 3935232 | `e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c` | 2017-03-07T15:49:10+00:00 |
| [Total Influence.exe metadata](evidence/TI.Total Influence.exe.pe.json) | 16384 | `b34c1f39669d0fbe33de99365313088471bcacf6012cf093ff24f73b110b6498` | 2010-06-26T19:08:32+00:00 |
| [totinf_mini.exe metadata](evidence/TI.totinf_mini.exe.pe.json) | 461824 | `4e84e5c409ac20c2df468d77f0c631f9e39dd666f94877345c7948129f6a48b5` | 2012-05-03T10:40:49+00:00 |
| [uninstall.exe metadata](evidence/TI.uninstall.exe.pe.json) | 49853 | `39e22d8323382f93320aa137a1c9918c9ecc93ad109acdb521669d7c21ce8ba7` | 2013-07-14T20:09:51+00:00 |
| [updater.exe metadata](evidence/TI.updater.exe.pe.json) | 4521472 | `91f6a332fec30b20019693930dcc80728988c0d086cc0ffe8a85e518df1af8c2` | 2017-01-18T06:45:44+00:00 |

Each linked PE JSON includes imports, exports, sections, RTTI candidates and XML/config string references. Adjacent `.strings.json` includes ASCII and ASCII-range UTF-16LE strings with file offsets and preferred VAs; not a complete multilingual string decoder.

Roles: ti.exe = executable/UI host (CONFIRMED module loading); silver.dll = game/application parser (CONFIRMED export and dispatcher); orange.dll = transport callback implementation (STRONG, requires runtime inspection); gold.dll = small packet hook (CONFIRMED export, broader role UNKNOWN); ode.dll = physics candidate (LIKELY); d3dx9_26.dll = D3D helper (STRONG imports); updater/launchers = names only (LIKELY).

Source-file search for .pas/.dpr/.c/.cpp/.h/.cs/.py/.pdb/.map returned no files. These client directories contain binaries/resources; source code is not yet available.
