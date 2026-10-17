> 2026-09-12: скриншоты пользователя подтвердили видимый Reservation и открытие городских окон. Запуск без таймера: `python tools/run_reservation.py`; `--seconds N` включает диагностическое закрытие через N секунд. Данные наёмников и premium ещё не восстановлены. Актуальная проверка — COMPLETION_AUDIT.md; нижние старые статусы являются историей.

> Обновление: пользователь подтвердил глобальную карту. Проверка Reservation и её ограничения — в RESERVATION.md.

# Вход в город — история восстановления

CONFIRMED live: создание/persistence→штатный callback8a3108(slot0,null)
→C2S1701000000→S2C1800+дваu32→C2S19→S2C1A.18 и1A вернулись.
17 writer889dbc: u32id + CString только при non-null optional parameter;
обычный callback в probe передаёт null. Selected id/name сохраняются callback,
вызван именно штатный selection callback, а не только serializer.

18: statusu8;если0,дваdiscardedu32LE,clear state и builder19. Failure короче.
1A: u32id,CStringname,u16unknown,u32Xraw,u32Yraw,u32unknown. Coordinates в
клиенте трактуются signed для fild/position; codec сохраняет raw bits.
Пакет также передаётся host callback68a8fc до silver parser.
Данные diagnostic: id1/ProbeNew,u16=3,XY=(-153,-317),tail0. u16 ещё UNKNOWN,
НЕ объявлен town id только на основании совпадения.61 unit tests PASS.

## Городские ресурсы
Live после1A впервые найден town_count0 у[[ac63bc]]. B9 namezones в9d20e1
ведёт Towns_XMLLoad9ea894;файл base/shared config/zones.xml,не towns.xml.
Добавлен fixture первых3 towns из оригинального TI towns.cfg с sourceSHA:
evidence/zones_diagnostic.xml и zones_diagnostic_provenance.json.
Ключиid/name — attributes;enabled,background,x1,y1,x2,y2,size,minlevel,
maxlevel,drop — child key/val. Numeric CFG type не копировался:default town
подтверждён loader literal. Gaps в id не оставлены (table индексid-1).
B9 delivery items затемzones прошла;mychar hook показываетtown_count3.
Fixture cleanup сохраняет ранее существующие файлы (отказ до probe),удаляет
только точные bytes fixture или егоcompressed form. XML после runs отсутствуют.

## TownInfo: исправление и подтверждение C8/2D
CONFIRMED: serializer64a650 пишет C8 2D. Значение60=0x3C из[[ac5b3c]]
используется в диагностике7d089c и НЕ является доказательством wire opcode.
Прежнее утверждение о сетевом3C отозвано.

Decoder64a3fc: u16 town_id,u16 unknown,4u8,3bool,3float32,3u16,
7 optional presence bytes с условными payload,final bool. Без optional
payload тело37bytes. Codec town_info.py реализует только этот вариант;
unknown float bits сохраняются, present optional ветви отклоняются.
verify_town_native.py исполнил оригинальный декодер и проверил расход37bytes.

Два live probe подтвердили C8/2D→7d089c→64a2bc→7cec78 и возврат всех трёх.
Повторный probe с кодеком прочёл town id3, поля+248=[1,3,0,0],
float bits+22c=0x3f800000. Это подтверждает изменение городской записи,
но не визуальный вход. После пакета за2s новых C2S не наблюдалось.
Доказательства: town_c82d_probe.log,town_c82d_codec_probe.log,
native_town_decoder.json,town_consumer_original.asm.63 unit tests PASS.

Следующий барьер: найти событие перехода к городскому интерфейсу и причины
отсутствия видимого окна. TownInfo сам по себе пока доказывает обновление данных.

## Видимый запуск
Навык computer-use подключён. sky.list_apps/list_windows не показал окнаTI
даже во время45s inspect-window. Изменён опциональный --visible-launch:
Popen(CREATE_SUSPENDED=4) + instrumentation + NtResumeProcess своего process.
Добавлен явный STARTF_USESHOWWINDOW/SW_SHOWNORMAL. Протокол работает;
повторная визуальная проверка после этой правки ещё требуется.
Первыйvisible run ошибся отсутствующимsubprocess.CREATE_SUSPENDED,исправлен
на documentedflag4. К probe поумолчанию новыйспособнеприменяется.

## Evidence и воспроизведение
character_selection_run.log:17/18/19;mychar_info_run.log:1A,emptytowns;
zones_mychar_run.log:zones+1A,town_count3;world_bootstrap_original.asm.
visible_city_probe_repeat.log:protocol OK,no window found withsky.
```powershell
python tools/probe_item_fixture.py --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --shared-config --empty-characters --create-success-probe --select-probe --mychar-probe --town-probe
```
--inspect-window держит observation45s;--visible-launch optional new launch mode.
No ti.exe remains. Отсутствие окна и town transition не решены,goal active.

## F0 command98: текущий город установлен (новый live результат)
CONFIRMED: dispatcher7d4af0 принимаетF0 и вызывает7d0980 через68a850.
Тело: u32 command,u32 argument_count; для каждого аргументаu32 type,
далее type1..4=u32 с преобразованием в строку, type0=CString.
Проверен только command98,один type1 аргумент3:
`f062000000010000000100000003000000`.

Switch7d1d98: byte map7d1db4, table7d1fbf; command98→index53→7d2e78.
Этот обработчик преобразует первый аргумент в integer и записывает[[ac5d58]]
(aliasac4cac),затем вызывает93fa7c,a00bbc,a088e0,775be4.
Live enter_town_command_probe.log подтвердил возврат и current_town3.
Клиент автоматически отправил5003; builder7ceb48 подтверждает opcode50+u8town.
Ответ на этот запрос пока не восстановлен.1C/88b100 — только log+return,
его не следует считать недостающим полным профилем.

Observation loop исправлен: не завершает соединение при первом C2S;
сохраняет его до deadline (45s сinspect-window). Повторный held probe также
установил current_town3,но sky не обнаружил окна во время открытого соединения.

## Диагностика окна (новый цикл)
--trace-windows записывает вызовы CreateWindowEx/ShowWindow, checkpoints и
стек потоков. Служебное ti окно создаётся с0x0размерами, отдельная форма
320x240 без заголовка передаётсяShowWindow. Нельзя утверждать, что ShowWindow
не вызывается. App.ShowMainForm=1; основной поток выполняет frame idle6f956c,
снимок поймал SleepEx6f95fb,а не зависание загрузчика.
STARTUPINFO и временный r_fullscreen0 не дали targetable window вsky.
probe_windowed.py восстанавливает исходныйconfig.cfg вfinally.
startup_state_probe.log содержит rawmode76dab4=1 (первоначальное имяloading
в записи не доказывает семантику). loadedflag76df14=1,ready76dbb0=1,
clock167138046,deadline0. Семантика mode требует дальнейшего анализа.
Доказательства: window_startup_trace.log,window_thread_trace.log,
startup_gate_probe.log,startup_state_probe.log,windowed_city_probe.log.
