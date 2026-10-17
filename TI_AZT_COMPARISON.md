# Comparative mechanic map

VA ниже относятся к silver.dll соответствующего клиента. «Anchor» означает
найденную строку/RTTI, **не** автоматически доказанную функцию или механику.
Точная общая строка CONFIRMED; gameplay relation без code path — LIKELY/UNKNOWN.
Полные offset-bearing записи: [TI strings](evidence/TI.silver.dll.strings.json),
[AZT strings](evidence/AZT.silver.dll.strings.json),
[genealogy](evidence/string_genealogy.json).

| Mechanic | TI evidence / packet-function | AZT evidence / packet-function | Structural similarity | Confidence | How this helps TI RE / next validation |
|---|---|---|---|---|---|
| Login | 04 → 0x87d00c, RECV_LSLoginResult | same log at 0xce6f24, dispatch table | matching dispatcher role | CONFIRMED mappings | recover TI 03 writer completely, including optional fields |
| Server list | 06 → 0x87d1cc | same log at 0xce6f58 | same named consumer | CONFIRMED name, UNKNOWN records | compare record readers after TI transport works |
| Authentication | 02 → 0x87ce60; status/u32 read | 02 → 0xce5608; status/u32 read | same branch/read/store pattern | CONFIRMED local layout; STRONG ancestry | TI native probe already verifies this fragment |
| Character roster | TGUISoldierLists @0x8431e3; net3_Character @0xab4eb0 | TGUISoldierLists @0xc49017; AZT repo roster | GUI/unit anchors | LIKELY relation, UNKNOWN TI packet | find TI post-login selection request and ID consumer |
| Equipment | no matching Equipment packet-name anchor in current pass | equipment improvement RTTI; AZT repo | TI counterpart unresolved | UNKNOWN | follow TI soldier/inventory object callsites, not keyword alone |
| Ammunition | TANetItemTypes_AMMUNITION @0x608076 | PTANetSoldierAmmunitionInfo @0x4fd392; repo C8:10→C8:0F | item category vs separate response, not same entity yet | CONFIRMED anchors; UNKNOWN TI analog | inspect TI soldier-selection sequence for distinct ammo request |
| Inventory | TANetInventoryUpdateElement raw anchor @0x612d8a | TANetInventoryUpdateElement @0x4f3452 | type-name match candidate | STRONG family naming, UNKNOWN layout | derive TI ID/instance/template serialization |
| Battle creation | TANetBattlePlayerStatsResult @0x606a5e is result anchor, not creation | same type @0x4f191e | battle vocabulary only | UNKNOWN creation packet | locate TI join/start callbacks after world bootstrap |
| Turn order | RECV_SMTurnNow_Delayed @0x9636d8 | RECV_TrueskillPlayerTurnNow @0xd92600 (also exists TI) | turn-related callbacks, semantics may differ | LIKELY | trace actor ID/AP fields and request ordering |
| Movement | RECV_Move @0x7219b8 | RECV_Move @0xbc4b29 | exact log name | CONFIRMED string; UNKNOWN packet | resolve TI xref, producer and position/AP reader |
| Attack | TANetBattleAttacked nested RTTI @0x62106d | TANetBattleAttackedItemInfo @0x4ff321 | battle attack type family | STRONG naming | compare serialization order, not opcode |
| Damage | fdamage RTTI anchor @0x62112a | fdamage @0x4ff3c0 | field spelling only | LIKELY | establish owner type, width, HP update side effect |
| Death | death @0x8b2a49 | Death @0x732b44 | vocabulary only | UNKNOWN packet | connect death animation/UI to attack result consumer |
| Loot/container | Container @0x68a980; identical ti_box cursor | Container @0x738ea0; matching cursor | generic name plus asset | UNKNOWN gameplay structure | prove discovery and transfer packets |
| Doors | CanOpenDoors @0xa8153e | CanOpenDoors @0xe933a2 | exact property name | CONFIRMED string, UNKNOWN authority | find AP validation and server confirmation |
| Visibility | generic Visibility @0x44257d may be framework RTTI | visibilityRange @0xdd372f | no established semantic match | UNKNOWN | exclude UI/framework symbols; locate battle LOS consumer |
| Repair | repair @0xa74a78 | repair @0xde6698 | same text anchor | LIKELY mechanics, UNKNOWN wire | trace item-instance request/result |
| Upgrade | UpgradeTB @0x9722cb | LeUpgrade01 @0xb6ec2c | UI naming only | LIKELY | trace upgrade button through sender, result and destruction |
| Clan/alliance | alliance @0x6e7e52; TANetWarehouseType_CLAN | alliance @0xe72c43; same warehouse enum naming | common entity vocabulary | STRONG naming, UNKNOWN schema | defer until vertical MVP works |

AZT repository evidence is a reference only:
`C:\azt-emulator\PROTOCOL.md:194` documents C8:0F ammunition fields;
`:229` describes its writer. No C8 IDs or guessed soldier model were copied into TI.
