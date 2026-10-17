# Арена: список комнат

CONFIRMED: dispatcher86021c проверяет opcodeBA, читает subcommandu8;
таблица860252[2]=860282 вызывает85fcc8 (RECV_ArenaRoomList).
BA/02 содержит signed i16 count, затем count записей85fa88.

| Порядок | Тип | Место в структуре / значение |
|---|---|---|
| 1 | u32 | +00, идентификатор (семантика требует дальнейшей проверки) |
| 2 | u32 | прочитан и отброшен, unknown_u32_02 |
| 3 | u8 | +10, участвует в фильтре по globalac55a4 |
| 4 | u8 | +1e |
| 5 | u32 | прочитан и отброшен, unknown_u32_03 |
| 6 | u8 | +1d |
| 7 | u8 | +1c |
| 8 | CString | +14, сравнивается при обновлении существующей записи |
| 9 | u32 | +04; дополнительно передаётся68a094 |
| 10–13 | четыре u8 | +1a,+1b,+18,+20 |

Подтверждение: tools/verify_arena_room_native.py, evidence/arena_room_native.json,
evidence/arena_room_reader.asm. Numeric readers исполняются из silver.dll;
allocation, managed strings и UI изолированы. Пустой пакет проходит dispatcher
до возврата; непустой проверен до фильтрации/вставки в список, не до отображения.
Это не доказательство готовой Арены. Ответ пока не подключён: запрос списка,
семантика остальных полей и жизненный цикл комнаты требуют восстановления.

GUI3_PDA_ArenaClick85a0f2 вызывает93fe70 (выбор отряда), альтернативная ветка
85a0f9 вызывает873ad0 (список). Следующий шаг: обработчик подтверждения93fe70
и исходящий запрос списка, затем серверный lifecycle комнат.

Проверка компьютером: city_ui_roster_live.log, finite90s завершён. Sky вернул
процессti.exe isRunning=true, но windows=[]; клики не выполнялись, UI не проверен.

## Исходящие запросы и первый серверный ответ

CONFIRMED: tools/verify_arena_requests_native.py выполняет шесть builders с настоящими
675bf8/673464/6e1d70 writers (transport и очистка UI изолированы), все6 PASS.

| Builder | C2S | Подтверждённая форма |
|---|---|---|
|85f890|BA01|без полей; перед отправкой очищает список комнат|
|85f954|BA03|u8(EAX),u8(EDX), семантика UNKNOWN|
|85f99c|BA04|u32(EAX), берётся из первого поля выбранной записи8737e5|
|85f9d4|BA05|u32(EAX),u8(EDX), семантика UNKNOWN|
|85fa18|BA07|u8(EAX), семантика UNKNOWN|
|85fa50|BA09|u8(EAX), семантика UNKNOWN|

Доказательство evidence/arena_requests_native.json включает sentinel значения и hash binary.
В city_service_reply подключён BA01→BA020000: пока комнат нет, список пуст.
Остальные операции не подтверждаются фиктивным успехом.106 unittest PASS.
BA03 нельзя пока называть доказанным созданием комнаты: необходимо прочитать UI
callers87512f/875589/8756bd, источникac48a0 и87969c.
Следующий шаг: семантика этих параметров и выбранной записи, затем lifecycle комнаты.

## Категория и число бойцов BA03

CONFIRMED: UI callback875118 вызывает87969c, затем85f954.
87969c обходит31слот ac618c и считает ненулевые указатели с state+5ff1!=0.
Это НЕ доказательство выбора конкретных бойцов: IDs вBA03 отсутствуют.
Первый параметр — категорияac48a0. Указательac55a4 указывает наac48a0;
поэтому поле+10 комнаты сравнивается именно с этой категорией.
Названия категорий и смысл самой операцииBA03 пока UNKNOWN.

Native tools/verify_arena_roster_count_native.py исполнил весь875118 callback,
настоящий counter и packet writers:0бойцов, смешанные состояния,31бойца PASS.
Доказательство evidence/arena_roster_count_native.json.

Добавлен tio/protocol/arena.py: полные recordsBA02 с сохранением неизвестных
полей. Router использует encoder пустого списка. Тесты используют независимо
сформированный пакет, прочитанный оригинальным parser, и все его усечения.
108unittest PASS. Непустые комнаты пока сервером не создаются.
Следующее: идентифицировать UIназвания категорий и обработку ответа наBA03;
BA0B member list8600d0 хранитroomID вac6184 и восемьслотов участниковac62a4.

## Участники BA0B

CONFIRMED:86021c subcommand11→8600d0; header u32roomID,u8unknown,i16count.
До8участников, запись85fe74: u32characterID,CStringname,u32unknown114,
u8unknown109,u8flag110,i16petcount. До3бойцов:3u8,5u32,CString,2u32.
Третий petu32 клиент уменьшает на1; исходное wireзначение codec сохраняет.
Ненулевые флаги нормализуются клиентом; wireзначения не теряются.

CONFIRMED: собственный characterID сравнивается с[ac5a98]. При наличии остаются
roomID[ac6184] и in_room[ac6370]=1; при отсутствии roomID=FFFFFFFF,in_room=0.
Участники занимают0x1c0byte записи, данные бойцов stride0x28.

Native tools/verify_arena_members_native.py исполняет dispatcher и consumer ДО
ВОЗВРАТА (строки/chat/UI изолированы). Проверены ownID присутствует/отсутствует,
0/3бойца, полный cursor, размещение чисел. evidence/arena_members_native.json.
Codec encode/decode_member_list добавлен, ошибки/усечения/лимиты покрыты;
110unittest PASS. В liveUI пакет ещё не отправлялся, серверный lifecycle не подключён.
Следующее: связать BA03/04/05 со спискомBA0B и идентифицировать поля бойцов,
затем реализовать вход/выход/создание без фиктивного успеха.

## Выход / исключение BA05

CONFIRMED:872430 при текущей комнатеac489c!=FFFFFFFF отправляет собственный
characterID[ac5a98] иflag0; вне комнаты не отправляет пакет.
87a0c0 формирует подтверждениеms06 изrussian.lng («Действительно исключить
игрока "%s" из битвы?»), сохраняетtargetIDac48a4. Callback87a0ac отправляет
BA05 targetID,flag1. Следовательно u32 — IDперсонажа, НЕ IDкомнаты.
Native callbacks целиком: no-room→no packet;room42/self11→ba050b00000000;
kick target22→ba051600000001. Всего9native builder/callbackcases PASS.

Добавлен strict ArenaRemoveRequest codec (неизвестныеflag2..255 отклоняются).
111unittest PASS. Не подключён к серверным мутациям, пока отсутствует lifecycle
и проверка полномочий владельца комнаты. Нельзя разрешать исключение по одному
присланномуtargetID. Evidence:arena_requests_native.json,arena_remove_localization.json.
Следующее: BA04 выбранная запись и BA03; для полноценной комнаты определить
операцию создания, владельца и состав, затем подключить вход/выход/исключение.

## Важное уточнение: кнопка «Создать»

CONFIRMED: labelmn53=Создать вrussian.lng. Constructor875ff4 загружаетmn53,
87602b привязывает object+38. Interface table874cc8 offset38→vtable874bf8,
invoke thunk874969→87537c→8737f4. Этот путь открываетwindow_servercreate и
скрываетwindow_serverlist. ПрямогоBA03 в нём нет. Native callback chain проверен
с изолированными windowhelpers, evidence/arena_create_ui_binding.json.

Предыдущий план «BA03 создание» был гипотезой, не доказанным соответствием.
Следующий шаг должен идти черезwindow_servercreate, его кнопку подтверждения
и структуру настроек[ac6008].85e488 обновляет настройки;85d4c0 список доступного.
Также подтверждена категория4:gm04=Стенка на стенку, constructor8764a4,
interfaceoffset24→8748ab→8755bc записываетac48a0=4. gm00=Выживание,
gm01=Командный (остальные привязки ещё не проверены).

BA04 остаётся запросом по первойu32 выбранной записи из второй таблицы;
его название пока не доказано. Кнопка mn18=Вход первой таблицы вызывает873794
→a089f0 (другой путь). Нельзя смешивать эти две таблицы.

## Подтверждение создания боя C8/2B

CONFIRMED:constructor85f2a6 labelmn53→85f2c5 callback85d658.
Он читает GUIнастройки, вызываетa0a6f4→6468b4; wireopcode C8/2B.
Original a0a6f4/setters/serializer/numeric writers исполнялись без замены:
только629764/629938 packetbegin/end изолированы.2cases PASS.
Evidence:arena_create_request_native.json, tools/verify_arena_create_request_native.py.

20bytes: C82B,u32mode,u8map_size,u8players_count,u8unknown01,u32unknown01,
u8soldiers_count01,u8soldiers_count02,u8level_range_index,u32unknown02.
GUIcaller подставляет unknownbyte=2, unknownu32_01=20*track_soldiers_count+20,
both soldierbytes=track_soldiers_count, levelindex=track_levels_range-1.
Последнееu32 читается из textcontrolacf068, назначение ещёUNKNOWN.
Mode изsettings[ac6008]+19; map_size изtrack_map_size; playercount изtrack_players_count.
Codec сохраняет разные soldiercounts и неизвестные числа без доменных догадок.
112unittest PASS. Серверное создание не подключено до подтверждения ответа.
Следующее: ответ и stateструктура a0a83c (читаетsettingsac6008), поля последнегоu32,
связь общего списка боёв с ранее найденнойBAветкой.

## BattleSettings

CONFIRMED entry a0a834 (не a0a83c: это серединаprologue). Dispatcher a0b234
прикоманде6C регистрирует a0a834 через68a850. ИмяRECV_BattleSettings.
68a850 передаёт работу внешнему callback[ac60e0]; transport wrapper здесь
не проверен, поэтому новыйcodec кодирует BODY, не конструирует полный пакет6C.

Body: u32,u8,u8mode,u16,u8,CStringowner,5u8,u32,u8flag.
При mode16 дополнительно4u8flags,2u16. Значения неизвестных полей сохраняются.
Consumer сравнивает ownername с собственным именем, выставляяac63b4.
Режимы6,7,10 нормализуютсяв0; режим21 включает дополнительный state;mode16
читает extension. Codec сохраняет исходное modeзначение.

tools/verify_battle_settings_native.py исполняет настоящие numeric readers до
последнего поля в ветках0/16/21;managedstrings/variants/UI изолированы.
Cursor и nativefieldoffsets подтверждены, evidence/battle_settings_native.json.
113unittest PASS. Follow-up a0ac58→81d588 ещё не проверен; BattleSettings нельзя
пока объявить полным ответом успешного создания. Далее externalwrapper68a850,
переход81d588 и handshake создания/входа.

## Промежуточный callback в ti.exe

Live arena_callback_live.log: [silver ac60e0]→ti.exe71cc6c (rva31cc6c),
адрес и256bytes сохраненыarena_callback_target.json. Конечный запуск3s завершён.
71cc6c передаёт opcode,payload,length,reader в6f6984; тот копирует тело без
изменения, сохраняет readerpointer и добавляет запись в очередь.
Original ti.exe callback/copy проверены доqueue insertion; allocation/listinsert
изолированы. Evidence:arena_callback_queue_native.json. Исполнение очереди ещё
не проверено; это не liveBattleSettings. Followup81d588 обновляетwindow_battleroom.
Следующее: обработчик очереди/живой6C на отдельной диагностической сессии,
полный state BattleRoom и ответ создания; валюту/основную БД не изменять.

## Live6C принят

CONFIRMED:run_reservation.py --seconds6 --probe-battle-settings --database
evidence/battle-settings-trial.sqlite3. Послеinventory30 отправлен6C с локальным
диагностическим BODY. Originala0a834 enter→return,mode0,field40=1,ownerflag1.
Это проверяет queuedexecution и полноценный возврат consumer/followup вживом
клиенте. Не является созданием комнаты: её состояние сервером не фиксировалось.
Evidence:battle_settings_live.log/summary. Процесс завершён по таймеру.
Стартовые10000/10000 иinventory1001/301 приняты; основнаяБД не использовалась.

Новый probe требует отдельнуюБД и собственный отряд, несовместим с mutationprobes.
114unittest PASS. Хук тольконаблюдает обработчик; сервер посылает настоящийпакет.
Следующее: основной BattleMemberList и команда открытияwindow_battleroom,
не путать сBA0B. Соседниеopcode26/28/27/71 означают listdel/listclear/memberdel/arranged.

## Основной список участников25

CONFIRMED: serializer64e720 пишетopcode25; delayedreceivera0ce08→a0b5dc
→typeddecoder64e628→64e6b4. Это ДРУГОЙ формат, чем BA0B.
Header:u8unknown,u8flag,u32count. Member: u32id,CStringname,u32unknown,
4u8unknown,2u8flags,u32count_group1,group1records,u32count_group2,group2records.
Native размерmember0x134, group1stride0x28(reader64c2e0),group2stride0x13c(reader64cb6c).
Не считать группы бойцами/инвентарём без доказательства.

Original64e6b4/64d880 numericreader принял0/1/2members с обеими группами пустыми,
cursorточный,строки/offsets верны. Allocation/stringconversion изолированы.
Evidence:battle_member_list_native.json;tools/verify_battle_member_list_native.py.
UIconsumer и непустые вложения ещё не проверены; productioncodec не подключён.
Следующее:64c2e0/64cb6c группы и callbacka0b5dc interface для переходаBattleRoom.

## Полные вложения25

CONFIRMED group1(reader64c2e0):u8,u32,u8,5u32 (26bytes).
Первое и второе по wireпорядкуu32 сохраняются вnativebyte+2/+6; codec не обрезает.
Group2(reader64cb6c):CString,u8,2u16,6u32,u32childcount,u16children[];
первые2u32 сохраняютсявbytes. Leaf64c980 читаетu16.
Назначения полей покаUNKNOWN. Нативныеgroup1/group2 strides0x28/0x13c подтверждены.

Original64e6b4+вложенныеreaders прошли0/1/2members, по2записи каждойгруппы и
по2childwords, cursor и sentineloffsets PASS. Динамическое выделение/strings
изолированы. tools/verify_battle_member_nested_native.py,
evidence/battle_member_nested_native.json. Полныйcodec вprotocol/battle_members.py.
116unittest PASS: независимые nativefixtures, всеусечения, лишниеbytes, impossiblecount.
Следующее: consumerclosurea0b5dc и семантика групп, затем live25 вместе с6C.
Полный wirecodec ещё не означает функционирующую комнату или бой.

## Consumer списка25: выбор места
CONFIRMED: closure a0b5d0 -> a0a29c. Таблица [ac62a4] содержит 8 записей stride0x1c0, occupied+0, characterID+4. Существующий ID обновляется, новый занимает первое свободное место; заполненная таблица пропускает новый ID. mode12 принудительно задаёт settings+18=1. Native verifier: tools/verify_battle_member_consumer_native.py (4 случая); преобразование a09b78 и UI изолированы. Полная живая комната ещё не подтверждена.

## Полное преобразование a09b78
CONFIRMED original execution through return: modes6/7 выбирают group2, mode0 group1, mode21 пропускает обе. Не более трёх вложений на участника (member+120,stride28). Совпадение characterID с [ac5a98] устанавливает member+111=1, member+10f копируется в [ac5498]. Расширен verify_battle_member_nested_native.py: original reader создаёт четыре записи каждой группы, conversion проверяет три результирующих записи в modes0/6/7 и пропуск в21. Managed copy/strings/events/UI изолированы. Семантика числовых полей UNKNOWN; live25 ещё не выполнен.

## Live25+6C
--probe-battle-members (отдельная база обязательна) посылает6C затем25 с ID/именем текущего диагностического персонажа и пустыми вложениями. Наблюдение a0a29c read-only: enter -> return, slot0/id1/own1. settings returned owner1. evidence/battle_members_live_summary.json; процесс exit0. Открытие окна и штатная кнопка создания пока не проверены.

## Переход после25
CONFIRMED a0a3df: flag0 вызывает66754c, результат1 вызывает7d0be8; mode12 предварительно устанавливает flag1. Native verifier8cases подтверждает четыре сочетания перехода. LIVE flag0: 7d0be8 context_count3 ->81d37c enabled1 ->return ->a0a29c return. 81d37c вызывает подготовку/позиционирование window_battleroom и info. Визуальный результат и штатное создание ещё не проверены. См.evidence/battle_transition_live_summary.json.

## Имена настроек6C по оригинальному UI
CONFIRMED через table81f2fd (подписи) + table81de7b (значения), russian.lng: tags0..7 = creator+24,mode+19,map_size+20,players_count+1,soldiers_count+1c,turn_seconds+14,exit_zone+28,stake+2c. Exit label использует2-value. verify_battle_settings_labels.py проверяет8bindings и pinnedSHA. В BattleSettings добавлены свойства; неизвестные поля не переименованы. Диапазоны и соответствие C8/2B ещё требуют проверки.

## Full create confirmation85d658
verify_arena_create_form_native.py исполняет полный callback, typedbuilder и numericserializer с UI fixtures. Два набора PASS: map,players,фиксированное2,20*soldiers+20,soldiers дважды,levels-1,последнийu32. Последнийu32 CONFIRMED stake: editacf068 имеет расположенную над ним label85f884=m617=Ставка. Добавлено свойство ArenaCreateRequest.stake. Назначение20*soldiers+20 ещё не доказано напрямую.

## Server waiting-room model
tio/arena_rooms.py содержит create/join/leave без wire-интеграции. ВнутренниеID монотонны в процессе; snapshotsimmutable; lock защищает вместимость/единственное membership. Дублирующий create идемпотентен. Локальная политика: выход владельца закрывает комнату, ставки отклоняются до settlement. Это не заявление о восстановлении оригинальных правил. 4 новых теста,120totalPASS. По1f найдены сравнения с member+10f при стрелках; назначение ещё UNKNOWN.

## Create network integration
ArenaService подключён к loopback C8/2B: выбранная identity, room registry,6C затем25(flag0). 122tests PASS; новый live end-to-end пока не выполнен. Временный compatibility profile: unknown40=1 (не ID),1f=2,levels0/0,exit0,time20*soldiers+20. Поддержаны0/1/4/8 и1..3soldiers; ставки/бой/боевой отряд не реализованы. Ошибки394, serialization-before-mutation. Disconnect послеjoinпотока освобождает комнату.

## Live server create
--probe-arena-create на отдельной базе: native a0a6f4 ->C8/2B ->ArenaService room_created ->6C/25 ->81d37c return ->a0a29c return(slot0/id1/own1). Exit0. evidence/arena_create_live_summary.json. Прямых диагностических ответов settings/members в этом режиме нет. 123tests PASS. UIclick/visible window, бойцы и бой остаются непроверенными.

## Original RTTI soldierInfo
61c229 TANetBattleMemberList.TANetBattlePlayerInfo.TANetBattlePlayerSoldierInfo: fields level,equipStatus,injureStatus,npcId,avatarId,rank,militaryRank,pointsToNextRank. Getter pointers64c64c..64c8dc совпали с оригинальным consumer,8 offsetsPASS. ВАЖНО: group1 НЕ содержитpetID; +124=npcId,+128=avatarId,+120=level. Group2 assault содержитname,level,maxHp,pDefence,equipStatus,npcId,avatarId,rank,militaryRank,pointsToNextRank и weaponItemId[] (RTTI61c6..61ce). Memberprefix61d0b0: memberObjectId,memberName,crestId,avgLevel,level,color,team,ready,online. Alias свойства добавлены; server online исправлен1. Связь с owned66 ещё не завершена.

## UnitStatus renderer
RTTI a0cec2 TUnitStatus; DrawEquipStatus pointera0fc6c. Native18casesPASS: equip1..4 sprites4..7; other4; injury>0 colorffff7777 elseffffffff. Это не доказывает enum names. Owned66 model другая структура: level+5ffc (reader8c4aef),name+5ff4; не копировать с+5ff0 как UnitStatus. Сопоставление экипировки/травм/рангов ещё UNKNOWN, roster не подключён.

## Saved roster to room
room_soldiers проецирует66 level8c4aef/NPC8c446f вgroup1. Толькоhuman1/2; state0 пропускается, первыеIDдоlimit (локальная политика). Equip1/injury0/avatar0/ranks0 ВРЕМЕННЫЕ. Live native create: room_open_return, member soldier level1,npc1,equip1,avatar0;exit0. evidence/arena_roster_live_summary.json. 124testsPASS. Не считать полноценным восстановлением статусов/выбора состава/боя.

## Main-room ready/leave
81db34 non-owner ->81dae8 ownID lookup ready inversion ->a08a80 ->2C01/00. Original numeric writers PASS. Server set_ready returns25 flag1 preserving roster/online;125tests. Owner branch usesa08ab0 (start, not ready). Leave labelmn65 callback81db8c ->a08a20(EAX0) ->2A01; alternateEAX1 ->2A00 semanticsUNKNOWN. Leave reply not recovered; not BA05. Live ready pending.

## Live ready and leave response route
Native81dae8 ->2C01 ->25ready1 ->81dae8 ->2C00 ->25ready0 PASS; rosterunchanged,exit0; evidence/arena_ready_live_summary.json. --probe-arena-ready isolated. Static F0 command24: selector7d1db4[24]=23 ->7d1fbf[23]=7d2661 ->7d4a88 clears flags/8members ->7d0c84 closewindow. Полный F0/24 live и параметры ещё не проверены. 125tests.

## Live leave integration
2A01 ->ArenaService.leave ->F0/24 zeroargs подключён. Native81db8c live вызов послеreadyon/off: server rooms0; client7d4a88 return occupied0/owner0;exit0. evidence/arena_leave_live_summary.json.126tests PASS, повторныйleave иre-create проверены. 2A00 unsupported, multiclient notifications/actualUI/startbattle ещё не реализованы.

## End-of-load marker41 and ground dependencies
CONFIRMED ti.exe7182c0 compares opcode35 then subtracts0C ->41; calls718138, which sets[76deb4]=3 without reading body. Original dispatcher41 +completion717de0 native cases: state2/pending0 ->4 and36; state2/pending1 ->3/no-send. encode_battle_load_end returns41. Not a live battle yet.

7175ac uses ground.xml (string717ba4); supplies procedural decorative brushes. Read-only audit evidence/battle_ground_resources.json: ground IDs0..4 have all brush files, mines5 missing32/32, junk6 missing21/27. Presence only, not renderer verification; ground.xml is not original server map layout. Next isolated live sequence35/3B/41 with proper scene values, observe36 and resource faults.

## Scene ground and loading acknowledgement
ti.exe717e1c (string BattleGround recv.7180e4) consumes35. Original3rectangles write layers into grid[x][y*14+8/+0], size+4/+5, firstbyte==1 at+6. Object entries name/u8/u8 are passed to6cd690 then queued6f67c8(1001). End calls7175ac resource loader (not yet emulated). Zero dimensions UNSAFE: byte loop underflows, TEST clearsCF beforeJB, enters evenwidth0 (native confirmed). Codec rejectszero dimensions and names>255 (69d844 converts to shortstring limit255); previous silver0x0 fixture is not valid complete-client evidence.

ti.exe717de0: global[76deb4]state3 AND queue6f5734()==0 ->state4,[76e214]=1,726844,7186b4(AL36). Original builder emits one byte36 to both transport endpoints71944c/718e68. Native4gate casesPASS, pending count/scene finalizer/transport endpoints isolated. S2C37 dispatched962546 ->95e050 readsu32 ID, scans8 occupied members andsets+111=1 onlymatching. Native4lookup casesPASS. This +111 flag is context-dependent, not universallyown. No server battle lifecycle route yet;133tests. Next resource load7175ac/state3/live launch.

## BattleSoldierAdd3B
Dispatch8c7edc:3B->8c7f72->queued8c5044,42->8c6994,43->8c71e0 (latter two unrecovered). Read phase3B ends8c5aab before scene/event actions. Header3*u32 (soldierID,ownerID,resource passed to a853cc),CStringname,u8level,u32(+602c),3*u8(+6030,+602a,+6029),u8x/u8y,appearance6d01f8. Remaining equipment-class dependent values captured by numeric read callsites in battle_soldier.py.

Original branch coverage: human/nonhuman equipment (lookup isolated), appearance0/1/2, four timed states at5898/5918/5998/59e8 requireexact1, flag5831 extra2*u32+float32 ifnonzero. Native8structural and6marker cases PASS;131tests. OwnerID2->own0 andID1->own1;level5 andposition31/47 stored original model+5ffc/+603c/+6040. String allocation and model/resource methods stubbed; no live actor, rendering or scene completion claim. Do not send zero structural fixtures as playable actors.

## Start and BattleGround format
CONFIRMED native a08ab0 writes2E; AL255 omits optional byte, AL0/1/2 writes that byte. Owner callback81db34 supplies255 except mode16, where ac481c2->1,3->2,other->0. Strict decoder requires room mode to distinguish forms; no server battle-start handler yet.

CONFIRMED static dispatcher96244c opcode35 ->96256b ->95dd78. Body: u8unknown,u8width,u8height, width*height bytes, u16count, count*(CString,u8,u8), width*height bytes. Reader consumes first layer and entries without storing them here; second layer written column[x][y*8]. Unknown byte/layer/entry semantics remain UNKNOWN; packet may have other consumers. Reader first deletes nonempty models in31-slot owned table, so sending this alone is unsafe for an incomplete scene sequence.

Native evidence/battle_ground_native.json:4cases, including rectangular2x3/3x2 grids and0/2/1 named entries; original numeric readers/loops/gridwrites execute through return. Allocation/resource setup/string allocation/cleanup isolated, owned table empty. Codec round-trip and malformed-input checks pass;129tests total. No live scene or UI claim. Next: remaining scene initialization and BattleSoldierAdd ref8c7f76; RECV_BattleStart RTTI method724eb0 is an event listener, not an established wire opcode.

## Live empty scene
--probe-battle-scene separateDB: after6C/25 sends35 empty8x8(no objects/actors),41. Resources2->ground2->loadend3->finalize4, server36. Live12seconds exit0. evidence/battle_scene_live_summary.json.134tests. Not playable battle/UI evidence. Next valid3B and Start integration.

## Live diagnostic actor
--probe-battle-actor implies isolated scene probe.35 ->3B ->41: silver8c5044 returned id1/owner1/level1/HP100of100/position2,2; finalize4 andC2S36.12seconds exit0, no script errors.135tests. Field projection tools/battle_actor_fixture.py copies common model offsets from saved66, identity/name/resource and appearance; equipment absent, other battle fields temporaryzero. Same destination not full semantic proof. Visual ti.exe actor and combat not verified. See battle_actor_live_summary.json.

## Equipment slot dispatch
Original3B numeric readers ->98f978 execute11masks and12 destination records. Managed copy isolated; marker IDs301..311 not resource/render evidence. Slot0x10 copies todf0/1080. See battle_equipment_native.json and HUMAN_EQUIPMENT_FIELDS.136tests. ItemList.location_raw relation unknown; do not automatically equip inventory items.

## Выживание — физический UI 2026-09-13
BA030003 captured on Survival after selecting three actors. category0 confirmed for Survival.
BA0B own member, ready1, selected soldierInfo rows removes Loading and shows waiting for opponent; no create-room UI. BA05 ownID/flag0 -> empty BA0B returns selector.
BA0701 physically captured from Ready. BA08 body room:u32,char:u32,ready:u8;85fe00 checks current room and occupied matching member then writes boolean110. Native4 cases PASS.
Service starts queue immediately with ready1; readiness0 pauses matching,1 resumes. Waiting does not yet start a scene/bot.
