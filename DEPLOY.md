# Развёртывание на хостинге

## Хостинг

- Провайдер: **is\*hosting**, VPS #461544 (панель: https://my.ishosting.com/en/vps/461544/management).
- Сервер: Ubuntu 24.04 x86-64, `root@185.184.42.88`, домен `ti-reborn.com`.
- Код: `/opt/tio-emulator`; конфигурация: `/etc/tio-server/server.toml`; данные: `/var/lib/tio-server`.
- Основная служба: `tio-server`.
- SSH-доступ по ключу администратора. Подключение не предполагать: перед работой проверить его.

> Файл раньше назывался `DEPLOY_HETZNER.md`. Hetzner рассматривался до выбора
> хостинга и не используется; действующий сервер работает на is\*hosting.

## Текущее состояние и порядок обновлений

> Действующий сервер: root@185.184.42.88 (is*hosting), /opt/tio-emulator, tio-server.
> Он многопользовательский; начальные ограничения ниже исторические.
> Команды первичной установки и загрузки локальной БД ниже предназначены только
> для нового пустого VPS. На действующий хостинг локальные сохранения загружать
> запрещено: резервировать удалённую БД/код/config, обновлять только код и каталоги.
> Клановое scoped-обновление: tools/prepare_clans_deploy.py,
> tools/verify_clans_remote.py, tools/deploy_clans_remote.py; CLANS.md.
> Перед ним рейтинговое scoped-обновление: tools/prepare_ranked_deploy.py,
> tools/verify_ranked_remote.py, tools/deploy_ranked_remote.py; RANKED_BATTLES.md.
> Перед ним: tools/deploy_battle_recovery_remote.py; BATTLE_RECOVERY_STAGE3.md.
> Перед ним: tools/deploy_admission_capacity_remote.py; ADMISSION_CAPACITY_STAGE2.md.
> Перед ним: tools/deploy_battle_safety_remote.py; BATTLE_SAFETY_STAGE1.md.
> Игровой TLS установлен; launcher 0.1.3 опубликован и проверен полной HTTPS-загрузкой.
> Схема, сертификаты и статус: GAME_TLS_PLAN.md. Прямые 28512/28513 остаются на время перехода.

### Причина отключения при выпуске обновления

Поддержка окна `Server update` включена в клиент `2026.11.19.1`.
Лаунчер `0.1.51` поддерживает английский режим этого клиента. Исходники
поставки находятся в `work/update-disconnect-20261119/launcher`.

`tools/deploy_game_operations_remote.py` при обновлении посылает основному
процессу `tio-server` сигнал `SIGUSR1` и ждёт штатной остановки перед заменой
кода. Подключённые игровые сессии получают `Server update` в штатном окне
отключения клиента с поддержкой этого кода. Первая установка использует обычную
остановку, пока работающий процесс ещё не обрабатывает `SIGUSR1`.

Для ручного выпуска после установки поддержки используйте
`systemctl kill --kill-whom=main --signal=SIGUSR1 tio-server`. Дождитесь
`ActiveState=inactive` и `Result=success`, затем установите обновление и
выполните `systemctl start tio-server`. Обычная остановка через `SIGTERM`
и внезапная потеря связи не помечаются как обновление.

### Диагностика обрыва игрового TLS

Лаунчер 0.1.54 передаёт случайный `trace_id` в TLS-префиксе отдельно для входа
и игры. Найдите строку `tls_relay_end` в
`%LOCALAPPDATA%\TioLauncher\tls-relay-<PID>.log` и тот же `trace_id` в
`journalctl -u tio-server --utc -o short-iso-precise`. Мост записывает первый
EOF или ошибку с указанием операции (`native_read`, `vps_read` и другие).
VPS записывает первый EOF, ошибку или своё закрытие сокета. При поиске обрыва
в игре используйте `kind=game`: закрытие канала `kind=login` при входе штатное.
При расхождении часов сопоставляйте направление операций, записанных под одним
`trace_id`, и учитывайте погрешность при сравнении времени.
Общая метка появляется после TLS-рукопожатия и приёма префикса сервером.

## Игровой TLS — установленная поставка 7 октября 2026

Новые login/session listeners используют TCP 29512/29513 и тот же общий backend.
Launcher 0.1.3 подключается TCP к `185.184.42.88`, проверяя сертификат для `ti-reborn.com` на обоих входах,
и направляет собственный native-клиент через отдельные loopback-порты. Старый
launcher не обновляет свой EXE; игрок закрывает игру/launcher и [заменяет 0.1.2 опубликованным 0.1.3](https://ti-reborn.com/downloads/TIO-Launcher.exe).
Переход на plaintext при ошибке защищённого соединения отсутствует.

Scoped tooling: `tools/prepare_game_tls_deploy.py`,
`tools/deploy_game_tls_remote.py`, `tools/verify_game_tls_hosted.py`.
Перед поставкой сверяются фактические hashes кода/config/launcher/manifest,
проверяются игровые соединения, durable checkpoints и отложенные расчёты.
Создаётся backup настоящей hosted SQLite и прежних код/config/systemd/launcher.
Клиентский EXE опубликован отдельным `--publish-launcher` после проверок backend и native-клиентов.
При откате сохраняется **текущая удалённая БД**; резервная SQLite автоматически
не восстанавливается, локальные player data не загружаются.

Сертификат домена копируется renewal hook в неизменяемые поколения
`/etc/tio-server/tls/versions/`, с `root:tio` 0750/0640; symlink `current`
заменяется атомарно. `systemctl reload tio-server` отправляет SIGHUP и обновляет
контекст только новых соединений после проверки пары. Текущие игровые сокеты
продолжаются, повреждённая пара не заменяет рабочий контекст. Hook обслуживает
только lineage `ti-reborn.com`. Полная конфигурация и проверки — [GAME_TLS_PLAN.md](GAME_TLS_PLAN.md).

Backup действующей поставки: `/root/tio-before-game-tls-jzzbxmdu`.
При обновлении кода сохранены 62 таблицы и 177 игровых аккаунтов. Публичный
launcher имеет 118679712 байт и SHA256
`8a34ea68124eebfb6ded5f2c9d8c96dee85befb9eb99b5efb57d5dea708b4d52`;
client manifest `2026.10.07.4` не изменён. Отдельный metadata helper создал
свежий полный PostgreSQL dump 0600 и обновил одну строку `DownloadVersion/main`;
3 web-аккаунта сохранены, запись аккаунтов не выполнялась. Его откат возвращает
только четыре поля metadata после проверки текущей строки, без восстановления всей БД.

Два настоящих клиента за одним public IP подтвердили вход, покупку, загрузку
общего боя, движение, чат и reconnect. Бой подготовлен обычными BA03 TLS protocol
clients; создание через native UI button не проверено. Renewal hook с тем же
валидным сертификатом сменил immutable generation/context без перезапуска и
разрыва двух native-соединений. Другой сертификат проверен в изолированных тестах.
Все четыре службы активны, integrity БД `ok`, checkpoints/settlement jobs — 0.
Доказательства: [acceptance.json](reports/game-tls/acceptance.json),
[publication.json](reports/game-tls/publication.json),
[hosted-health-final.json](reports/game-tls/hosted-health-final.json).

Прямые игровые порты 28512/28513 и их firewall rules остаются на время перехода.
Два физических клиента с разными public IP ещё не проверены. Автоматический
TCP-прогон и действия настоящего native UI перечислены отдельно в итоговом отчёте.

## Свободное место перед обновлениями

Перед резервированием и загрузкой новой поставки проверьте `df -h /` и
`df -i /`. После размещения временных файлов, резервных копий и новой поставки
должно оставаться не менее **4 ГиБ доступных обычным службам**. Считайте запас
по `os.statvfs('/').f_bavail * os.statvfs('/').f_frsize`: резерв ext4 для root
недоступен игровому пользователю `tio`. Если запаса не хватает, сначала
освободите место или расширьте диск; не начинайте публикацию.

23 октября 2026 заполнение диска вызвало `SQLITE_FULL` и перезапуск игры.
Одинаковые статические файлы только в старых `/root/tio-before-*` объединены
жёсткими ссылками после SHA256-проверки. Освобождено 5,32 ГиБ; все пути и
содержимое сохранены. Эти архивные файлы следует считать неизменяемыми:
заменять атомарно, не перезаписывать на месте. Живые публикации, базы и
конфигурация в объединении не участвовали. Исходные временные метки и журнал
операции сохранены в `/root/tio-disk-maintenance-20261023-i78mgs2h`.
Повторное обслуживание требует нового обследования и свежего плана; старый
план повторно применять нельзя. Не удаляйте игровые данные и резервные копии
ради освобождения места без проверенного сохранения их содержимого.

## Журнал клиентских публикаций

### Клиентское обновление «Экран», 2026-10-09

Для этого изменения используется отдельная публикация `silver.dll`. Полная
сборка из старой установленной игры через `launcher/build_release.py` здесь
не подходит: она может заменить более свежие опубликованные игровые ресурсы.
Точная исходная версия — `2026.10.09.10`, исходный SHA256 DLL —
`bd0ce7a29d4cfdb4689330da8086052c287146fe7a383ed50710493a7ba0b0ac`.

Результат опубликован как `2026.10.09.11`: `silver.dll`, 7 787 008 байт,
SHA256 `7a58e792614a179cfef1920e7f2d3b1775bc573ef0c39c8dc00eef3ccf23a8a8`.
Остальные 6329 записей манифеста и лаунчер 0.1.4 сохранены.

`deploy/client_screen_resolution_ui.py` добавляет современные пункты в штатное
окно настроек. `deploy/client_screen_settings.py` соединяет штатную кнопку
«Применить» со сменой размера окна, VSync, циклом восстановления Direct3D и
изменением размеров интерфейса. Основная и дополнительная экранные текстуры,
а также depth buffer, пересоздаются под фактический размер окна. Существующие
вкладки чата пересчитываются без удаления сообщений; сохраняются свёрнутое
состояние, вкладки и введённый текст. Пересчитываются привязки jackpot/PDA,
верхнего меню и координаты девяти боевых слотов. Ошибка Reset или создания
ресурсов возвращает прежние cvars и размеры; повторное применение неизменённых
параметров пропускает Reset. В полноэкранных LCD-режимах исходный
клиент использует разрешение рабочего стола, поэтому выбор отдельных разрешений
в них отключён. Настройки хранятся на стороне клиента и не изменяют серверные
аккаунты или протокол игры.

Порядок проверки и публикации:

1. Сверить действующий HTTPS-манифест и исходную DLL с точными SHA256.
2. Последовательно собрать кандидата двумя указанными чистыми transformers.
3. Выполнить `tools/verify_client_screen_settings_native.py`. Внешние вызовы
   UI/Direct3D в этой проверке заглушены; инструкции штатного изменения размеров
   Silver и геометрии интерфейса исполняются. Результат не заменяет запуск игры.
4. Проверить штатное окно «Экран» через отдельные `.tio-owned-qa` клиенты на
   хостинге. `tools/verify_screen_settings_graphical.py` наблюдает реальные
   HRESULT, размеры backbuffer, промежуточных экранных поверхностей и depth,
   Present и соединения тестовых аккаунтов. Отдельная native-проверка чата —
   `tools/verify_chat_layout_native.py`.
5. Передать точные SHA256/размер кандидата в
   `tools/publish_screen_settings_remote.py --inspect`. Затем `--apply`
   создаёт online-backup SQLite, архив предыдущего серверного кода/config,
   копию старого манифеста и DLL. Публикуется immutable blob, после него —
   атомарно манифест с единственной изменённой записью `silver.dll`.
6. Сверить HTTPS-загрузку, целостность SQLite, сохранение аккаунтов, контрольные
   суммы кода/config/лаунчера и PID служб. При неопределённом ответе операции
   сначала использовать `--verify-only`, а не повторную публикацию.

Перезапуск служб не требуется. Настройки и сохранённый вход игроков в пакет
не входят. Первый запуск нового кода требует обычного обновления через лаунчер;
последующие изменения «Экрана» применяются в текущем сеансе.

Публикация завершена 2026-10-09 в 16:09:55 UTC. Резервная копия хостинга:
`/root/tio-before-screen-settings-3wj1bivo` — online-копия SQLite с 202 аккаунтами,
предыдущий серверный код/config, манифест и DLL. Целостность базы `ok`, 202 аккаунта
сохранены, PID и число перезапусков всех четырёх служб не изменились. Локальные
данные игроков на хостинг не загружались.

Доказательства: `reports/screen-settings/client/publication-7a58e792.json` и
`publication-7a58e792-https.json`; SHA256 HTTPS-манифеста
`b05f5ff717480e540dde4c13d152e2169861cc29d86801ee4ee591da8f079e6f`.
Автоматические проверки кандидата: 304 случая в `hotapply-native-proof.json`
и 168 в `chat-native-proof.json`, все прошли. Настоящий интерфейс проверен
через два клиента с отдельными аккаунтами на хостинге: переход в Full HD,
полный экран QHD, смена VSync, рабочий стол и возврат в окно. Все пять Reset
вернули HRESULT 0 на потоке рендера вне BeginScene. Повторное «Применить» без
изменений не вызвало Reset; шесть TCP-соединений с исходными CreationTime
сохранились. Отчёт: `reports/screen-settings/graphical/final-ui-pass.json`.
Агрегат настоящих клиентских проверок и очистка тестовых процессов:
`reports/screen-settings/graphical/final-graphical-proof.json`.
Проверка в настоящем бою не выполнялась; боевые привязки проверены отдельно
исполнением native-геометрии.

Независимая повторная проверка 16:11:15 UTC:
`reports/screen-settings/client/postpublication-independent-7a58e792.json`.
Отдельная HTTPS-загрузка совпала с полным ожидаемым манифестом и DLL;
read-only SSH подтвердил прежние службы/code/config/launcher, целостность
резервной копии и наличие каждого из 202 login-идентификаторов backup в живой БД.


### Клиентское обновление UI и портрета, 2026-10-09

Опубликована версия `2026.10.09.12`: только `silver.dll`, 7 823 872 байт,
SHA256 `87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d`.
Остальные 6329 записей манифеста, launcher 0.1.4 и закреплённый `ti.exe`
(`e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c`) сохранены.
Payload и hooks применения настроек «Экран» из .11 сохранены побайтово.

Добавлены масштабы UI 100/125/150/200%; выше 100% выбор ограничен минимальным
логическим размером 800×768. Физическое разрешение и координаты мира сохраняются.
Размеры и прокрутка существующего инвентаря/PDA пересчитываются при применении.
Портрет строится в native target 512×512; ПКМ открывает увеличенный просмотр
со штатными поворотом бойца и закрытием. `ti.exe` на диске сохранён побайтово;
клиентские runtime hooks используются для UI-render/input.

Публикация выполнена 2026-10-09T18:50:02.998213+00:00 через `tools/publish_ui_modernization_remote.py`.
Backup `/root/tio-before-ui-modernization-p2lw7815` содержит online SQLite, прежний код/config, манифест и DLL.
Независимая SSH/HTTPS-проверка подтвердила SQLite `ok`, сохранность
202 аккаунтов и прежних launcher/code/config/PID всех четырёх служб.
Службы не перезапускались, локальные player data на сервер не загружались.
Доказательства: `reports/ui-modernization/client/publication-87645b94.json`,
`reports/ui-modernization/client/publication-87645b94-https.json`,
`reports/ui-modernization/client/postpublication-independent-87645b94.json`;
полный HTTPS-манифест SHA256 `77c984e9346f1208c84ee739ca18ebebdd45fcdc970cd4de50f618627191738d`.

Автоматические проверки: 534 core-случая, 98 controls, 189 portrait;
отдельно 256 native и 212 product-helper проверок инвентаря. Доказательства:
`reports/ui-modernization/core-099-proof-provenance.json`, `reports/ui-modernization/controls-native-proof.json`,
`reports/ui-modernization/portrait-native-proof.json`, `reports/ui-modernization/inventory-scrollbar-native-proof.json`.
Они исполняют native инструкции в подготовленных fixture и частично заменяют
внешние API заглушками; настоящие клиенты проверены отдельно.

Настоящий city GUI на двух hosted-аккаунтах: portrait GetDesc 512×512,
поворот мышью/стрелкой и закрытие, QHD 2560×1440 с VSync1, один Reset S_OK
на потоке рендера вне BeginScene; четыре PID и шесть TCP-соединений с прежними
CreationTime сохранены. Scale-only применение не вызывает Reset; native выход
сохранил `ui_scale 150`, перезапуск с точными сохранёнными bytes подтвердил scale150.
Отчёт: `reports/ui-modernization/graphical/city-and-persistence-87645b94.json`.
Authenticated вход после persistence-перезапуска не проверялся. Проверка login UI,
трансформации источника OBS и exclusive Direct3D fullscreen не заявляется:
штатный LCD-fullscreen использует окно размером с монитор.

Настоящий бой с двумя owned hosted-аккаунтами без ботов:
84 проверки в `reports/ui-modernization/graphical/battle-native-validation-87645b94.json`: движение бойца 35,24/AP15→33,25/AP13 при масштабе150; штатное MENU→Settings→Screen, Apply100 вместе с mode/VSync вызвал один Reset S_OK вне BeginScene, возврат100→150 изменил только scale и не вызвал нового Reset; все шесть TCP-соединений сохранились.
Выход/cleanup: native процессы завершены по guarded QA cleanup, затем выполнен штатный public-протокольный forfeit только двух owned аккаунтов; checkpoint и pending settlements очищены. GUI Leave через Sky не проверялся.
Первый refresh после Reset кратковременно был чёрным; последующие снимки и
GetDesc подтвердили нормальную отрисовку полного кадра. Все возможные боевые
оверлеи не проверялись.
Preservation использует отдельный backup текущего QA epoch, сохраняя archival
ownership fixture; все 89 таблиц чужих аккаунтов сравниваются по полным строкам.
Общий SC-каталог допускает только точный replay штатного таймера в БД в памяти,
без исключений для player operations; индивидуальный caller таймера не инструментирован.
Доказательства: `reports/ui-modernization/graphical/battle/stock-catalogue-clock-proof.json`,
`reports/ui-modernization/client/independent-qa-preservation-review-87645b94.json` и `reports/ui-modernization/graphical/battle/qsa1496217-reservation-cleanup.json`, `reports/ui-modernization/graphical/battle/final-cleanup-audit.json`.


### HD-иконки А и шрифт В, 2026-10-09

По выбору пользователя опубликована версия `2026.10.09.13`: бронзовые иконки
варианта А и Roboto Condensed варианта В. Заменены девять ролей шрифта и
пятнадцать основных ресурсов кнопок. Для каждого подготовлены отдельные
атласы 100/125/150/200%; клиент выбирает плотность при применении масштаба.
У иконок сохранены штатные четыре состояния, размеры и обработчики кнопок;
у шрифтов сохранены логические advances, высота строки и правила переноса.
Неподключённые изображения предметов, навыков и декоративных рамок используют
прежние ресурсы. Лицензия Roboto Condensed OFL включена в обновление.

Пакет `reports/ui-hd-assets/client/package.json`, SHA256
`2a98b1a14ee4f294a0d6efad45dd0ef36e93e8cde89b78309b461f0fd32f1bf6`,
содержит 98 файлов: Silver, 36 атласов шрифта, 60 атласов иконок и лицензию.
`silver.dll`: 7 950 848 байт, SHA256
`3c99c9dd46a087564406b664f5895d7b0457f3dde95d4868353241f3330c4800`.
Сохранены 6329 прежних записей; добавлены 97 ресурсов, всего 6427 записей.
Манифест SHA256 `3d8d33ed91552117a1747952a15e1fb2167d1edc50d1e8f96573911f960d8a79`.
`ti.exe`, launcher и 45 056 байт payload настроек/масштаба/портрета .11/.12
сохранены побайтово, как и 16 проверенных участков native authentication.

Публикация `tools/publish_ui_hd_assets_remote.py` выполнена
2026-10-09T20:44:43.959274+00:00. Backup
`/root/tio-before-ui-hd-assets-khfz3y0s` содержит online SQLite, прежний
код/config, манифест и Silver. Независимый read-only SSH/HTTPS postchecker
подтвердил полный манифест и все 98 файлов, SQLite `ok`, сохранность
202 аккаунтов и credentials, прежних code/config и PID четырёх служб.
Службы не перезапускались; БД публикацией не изменялась; локальные player data
на сервер не загружались. Доказательства:
`reports/ui-hd-assets/deployment/publication-2a98b1a1.json`,
`reports/ui-hd-assets/deployment/publication-2a98b1a1-https.json`,
`reports/ui-hd-assets/deployment/postpublication-independent-2a98b1a1.json`.

Автоматические проверки: 969 native font cases, 560 native icon cases,
72 независимые проверки настоящего TI Unicode filename scanner. Проверены
четыре плотности, UV/состояния/геометрия, отсутствие alias в basename cache,
два ASLR base и fallback. Внешние decoder/OS API в native fixture частично
заменены заглушками. Доказательства: `reports/ui-hd-assets/native-fonts/native-unicode-loader-proof.json`,
`reports/ui-hd-integration/icons-native-final-proof.json`,
`reports/ui-hd-assets/native-fonts/font-loader-independent-proof.json`.

Отдельно проверены настоящие клиенты на двух owned hosted-аккаунтах в городе:
36 атласов шрифта и 60 различных managed GPU textures иконок, 0 ошибок;
масштабы 100/125/150 применяются сразу. Один VSync Reset вернул S_OK вне
BeginScene на потоке рендера; кадры и HD-текст продолжили отрисовку с прежними
cache identities. Четыре PID/CreationTime и шесть TCP-соединений сохранились.
Оба QA-клиента завершены, независимые seed config восстановлены.
Доказательства: `reports/ui-hd-assets/graphical/final-evidence-reviewed-3c99.json`,
`reports/ui-hd-assets/graphical/visual-review-final-3c99.json`,
`reports/ui-hd-assets/graphical/cleanup-final-3c99.json`.
Реальный GUI 200%, повтор боя, новые текстуры брони, настройка трансформации
OBS и exclusive fullscreen в этом обновлении не проверялись.
Первую установку .13 выполнить через лаунчер при закрытом клиенте; дальнейшее
изменение масштаба через «Экран» не требует перезапуска игры.

## Историческая первичная установка нового пустого VPS (Ubuntu 24.04 x86-64)

Только для нового пустого сервера. Действующий хостинг так не обновлять.

**Готовность PARTIAL.** Ниже полностью определён запуск существующего backend
как Linux-службы. Это один диагностический аккаунт, не многопользовательский
сервер. Полный вход оригинального клиента через публичный IP ещё требует
проверки/доработки: сначала прочитайте CLIENT_CONNECTION.md. VPS не устраняет
зависимость прежнего входа от Windows hooks. Launcher и протокол не переписаны.

### 1. Подготовить файлы на Windows

Завершите бой, выйдите в город, закройте клиент и локальный сервер. Создайте
согласованную резервную копию существующего сохранения. Исходная БД не меняется.
Имена результатов должны быть свободны: команды не перезаписывают старые копии.

```powershell
cd C:\TIO-emulator
python deploy/package_server.py tio-server.tar.gz
python deploy/backup.py data/reservation.sqlite3 reservation-upload.sqlite3
$VpsIp = Read-Host 'VPS public IPv4'
scp tio-server.tar.gz reservation-upload.sqlite3 "root@${VpsIp}:/root/"
ssh "root@$VpsIp"
```

Предварительно создайте VPS **Ubuntu 24.04, x86-64** (у is\*hosting или другого
провайдера) с public IPv4 и вашим SSH-ключом. Укажите именно его IPv4. Архив содержит только серверные
исходники, конфигурацию и нужные данные каталога/карт. DLL/EXE и весь evidence
загружать не нужно. Лицензия на используемые игровые ресурсы остаётся вашей.

### 2. Чистый VPS — выполнять в SSH от root

```bash
apt update
apt upgrade -y
apt install -y python3 python3-venv sqlite3 ufw ca-certificates
python3 --version
uname -m
useradd --system --user-group --home-dir /var/lib/tio-server --shell /usr/sbin/nologin tio
install -d -o root -g root -m 0755 /opt/tio-emulator
install -d -o root -g tio -m 0750 /etc/tio-server
install -d -o tio -g tio -m 0750 /var/lib/tio-server
tar -xzf /root/tio-server.tar.gz -C /opt/tio-emulator --no-same-owner
cd /opt/tio-emulator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ожидается Python 3.12 и x86_64. В requirements нет сторонних runtime-зависимостей.
Установка `pip install -e .[research]` здесь не нужна. Запуск идёт из исходного
дерева; существующий pyproject не используется как production wheel.

Если Ubuntu требует reboot после upgrade, перезагрузите VPS и снова подключитесь
по SSH перед продолжением. Переменные из предыдущей SSH-сессии не сохраняются.

### 3. Перенести сохранение и задать параметры

```bash
test ! -e /var/lib/tio-server/reservation.sqlite3
# Если предыдущая команда неуспешна, ОСТАНОВИТЬСЯ: там уже есть сохранение.
python3 - <<'PY'
from pathlib import Path
import shutil
source = Path('/root/reservation-upload.sqlite3')
target = Path('/var/lib/tio-server/reservation.sqlite3')
with source.open('rb') as src, target.open('xb') as dst:
    shutil.copyfileobj(src, dst)
PY
chown tio:tio /var/lib/tio-server/reservation.sqlite3
chmod 0640 /var/lib/tio-server/reservation.sqlite3
sqlite3 /var/lib/tio-server/reservation.sqlite3 'PRAGMA integrity_check;'
read -rp 'VPS public IPv4: ' PUBLIC_IPV4
cat > /etc/tio-server/server.toml <<EOF
bind_address = "0.0.0.0"
advertised_address = "$PUBLIC_IPV4"
game_port = 28512
data_directory = "/var/lib/tio-server"
log_level = "INFO"
EOF
chown root:tio /etc/tio-server/server.toml
chmod 0640 /etc/tio-server/server.toml
cd /opt/tio-emulator
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml --check
```

Ожидается `ok` от SQLite и `Preflight OK`. Для нового пустого мира пропустите
ТОЛЬКО копирование/chown/chmod/check файла БД; сервер создаст БД в data_directory.
Но создание персонажа сохраняет диагностические ограничения, см. CLIENT_CONNECTION.

**PERSISTENT DATA LOCATION:** `/var/lib/tio-server/reservation.sqlite3`.
Сохраняйте весь `/var/lib/tio-server`, включая возможные SQLite sidecar-файлы.
Аккаунт probe_user, персонажи, инвентарь, прогресс и экономика используют эту БД.
Код обновляется отдельно, в `/opt/tio-emulator`. Боевые комнаты живут в памяти;
остановка во время боя применяет существующие правила выхода/поражения.

### 4. Firewall — до запуска

Укажите внешний IPv4 вашего игрового компьютера. Пароль диагностического
аккаунта известен из исходников: нельзя открывать этот этап всему Интернету.

```bash
read -rp 'Your client public IPv4: ' CLIENT_IPV4
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow from "$CLIENT_IPV4" to any port 28512 proto tcp
ufw --force enable
ufw status numbered
```

Во внешнем firewall провайдера (в панели хостинга), если он используется, разрешите те же TCP 22 и TCP 28512
с нужных IP. UDP не нужен. Подробности и источники: deploy/FIREWALL.md.
Не закрывайте текущую SSH-сессию до проверки нового SSH-подключения.

### 5. systemd и запуск

```bash
install -m 0644 /opt/tio-emulator/deploy/tio-server.service /etc/systemd/system/tio-server.service
systemd-analyze verify /etc/systemd/system/tio-server.service
systemctl daemon-reload
systemctl enable --now tio-server
systemctl status tio-server --no-pager
journalctl -u tio-server -n 50 --no-pager
ss -ltnp 'sport = :28512'
```

Ожидается `0.0.0.0:28512`, служба active/running, процесс от tio.
**SERVER START COMMAND** (для ручной диагностики вместо systemd, не одновременно):

```bash
cd /opt/tio-emulator
runuser -u tio -- .venv/bin/python -m server --config /etc/tio-server/server.toml
```

Одна команда запускает оба этапа TIO на одном TCP-порту. Никаких дополнительных
скриптов или клиентского процесса на VPS не требуется. SIGINT/SIGTERM запрашивают
остановку, закрывают сетевые операции и дожидаются текущей работы и settlement.

Команды управления:

```bash
systemctl start tio-server
systemctl stop tio-server
systemctl restart tio-server
systemctl status tio-server
journalctl -u tio-server -f
```

Последняя команда следит за журналом; Ctrl+C прекращает просмотр, а не сервер.
Служба включена после reboot; аварийный выход перезапускается через 5 секунд.

### 6. Проверка с Windows и проверка рестарта

С Windows, без активной игры:

```powershell
cd C:\TIO-emulator
$VpsIp = Read-Host 'VPS public IPv4'
Test-NetConnection $VpsIp -Port 28512
python deploy/check_connection.py --host $VpsIp --port 28512
```

Вторая команда должна вывести `TIO transport challenge OK`. Probe закрывает
соединение до login, поэтому одна запись о раннем отключении в журнале ожидаема.
Настройка оригинального клиента и честная граница этой проверки — CLIENT_CONNECTION.md.

На VPS, когда клиент отключён и бой завершён:

```bash
systemctl stop tio-server
sqlite3 /var/lib/tio-server/reservation.sqlite3 'PRAGMA integrity_check;'
sqlite3 /var/lib/tio-server/reservation.sqlite3 '.dump' > /root/tio-before-restart.sql
systemctl start tio-server
systemctl stop tio-server
sqlite3 /var/lib/tio-server/reservation.sqlite3 '.dump' > /root/tio-after-restart.sql
diff -u /root/tio-before-restart.sql /root/tio-after-restart.sql
systemctl start tio-server
```

На первом запуске старой БД возможны существующие инициализации таблиц. Сравнение
выше проводится ПОСЛЕ первого запуска. При неизменной базе без входа клиента diff
должен быть пустым. Вход запускает обычный учёт офлайн-времени/аренды/восстановления.

### 7. Backup и обновление кода

Перед обновлением: выйти в город, отключить клиент, остановить службу.

```bash
systemctl stop tio-server
install -d -m 0700 /root/tio-backups
cd /opt/tio-emulator
.venv/bin/python deploy/backup.py /var/lib/tio-server/reservation.sqlite3 "/root/tio-backups/reservation-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
```

Скопируйте backup также с VPS на свой компьютер. Новый архив собирается той же
командой packager под НОВЫМ именем и загружается через scp. Распакуйте его в
`/opt/tio-emulator`, выполните `pip install -r requirements.txt`, `--check`, затем
`systemctl start tio-server`. Архив не содержит data_directory или конфигурацию
`/etc/tio-server`, поэтому не заменяет их. Не копируйте локальный data/ поверх
VPS и не используйте удаление каталогов при обновлении.

Для восстановления backup остановите службу, сохраните текущую БД отдельной
копией, убедитесь, что нет активных SQLite writers/sidecars, затем восстановите
выбранную БД с владельцем tio:tio и правами 0640. Не восстанавливайте файл поверх
работающего сервера. Эта задача не выполняет миграцию живых данных.

### Что осталось проверить на Ubuntu

Локально нет установленного Linux/WSL. Проверить systemd unit, Unix permissions,
SIGTERM/systemctl stop, повторный старт, reboot и внешний IPv4 по шагам выше.
Главный функциональный блокер отдельно: полный stock-client login → city через
VPS не доказан и может требовать восстановления bootstrap, а не Linux-исправлений.
