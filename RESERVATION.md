> Стартовые средства:10000 кредитов и10000 золота на новый кошелёк.
> Сохраняются в data/reservation.sqlite3; повторный вход не сбрасывает баланс.

> 2026-09-12: добавлены каталоги города: 61→62 рынок найма, 69→74 магазин, B102→B103 список услуг. Форматы проверены original readers и live. Данные пока частичные/тестовые, транзакции ещё не реализованы. См.[CITY_SERVICES.md](CITY_SERVICES.md).

> 2026-09-12: скриншоты пользователя подтвердили видимый Reservation и открытие городских окон. Запуск без таймера: `python tools/run_reservation.py`; `--seconds N` включает диагностическое закрытие через N секунд. Данные наёмников и premium ещё не восстановлены. Актуальная проверка — COMPLETION_AUDIT.md; нижние старые статусы являются историей.

> Повторный вход теперь использует постоянную базу `data/reservation.sqlite3`. Путь можно задать через `--database`. Два запуска оригинального клиента подтвердили: сначала создаётся один персонаж, затем он загружается и возвращается в Reservation без повторного создания. См. `evidence/persistent_reentry_summary.json`.

> Проверка связи восстановлена: C2S70 → S2C9E без payload. Оригинальный обработчик6d4b44 подтвердил received1 и обновил elapsed. 67 тестов проходят. Для проверки дольше45s: `python tools/run_reservation.py --seconds 180` (1..3600). Видимый город подтверждён скриншотами пользователя.

# Reservation: открытие через серверные пакеты

CONFIRMED live: без --town-view-probe сервер отправил F0 command117,
оригинальный обработчик вызвал8596e0,затем render-loop загрузил
pda/loc_reserve.jpg. currenttown3/background_loaded1. Повторено отдельным
runner; evidence reservation_server_open_probe.log,reservation_runner_probe.log.

Команда117: f07500000000000000 (F0,u32command117,u32argument_count0).
Native map7d1db4[117]=27,table7d1fbf[27]=7d26e2; этаветвь вызывает
7d1350 (общая обработка параметров),затем8596e0. См.open_town_117_mapping.json
и open_town_117_branch.asm. Codec encode_open_town_view;65 unit PASS.

Повторить: `python tools/run_reservation.py`.
Runner создаёт свойлокальныйклиент/сервер,использует synthetic account и
instrumented login/character callbacks. Город выбирается и открывается
серверными пакетами98→117; прямого вызова8596e0 в runner нет.
По умолчанию сессия длится до закрытия клиента или Ctrl+C.
Параметр --seconds N включает таймер, после которого клиент закрывается.
При завершении удаляются только временные items/zones с точным совпадением fixture.
Это пока исследовательский launcher,не постоянныймногопользовательскийсервер.

После входа C2S:5003,6900,b804,b811,c501,70;повторяющиесязапросы продолжаются
при открытомсоединении. Ответы городскихсервисов ещёнеисследованы.
Видимый Reservation и открытие диалогов подтверждены пользовательскими скриншотами.

---
## История предыдущих диагностических проб

# Вход в Reservation — текущая проверка

Пользователь подтвердил загрузку глобальной карты. Цель этого этапа —
городской интерфейс Reservation, а не повторная проверка глобальной карты.

## Подтверждено оригинальным клиентом
Reservation: TI towns.cfg id3, backgroundloc_reserve; реальный файл
base/pda/loc_reserve.jpg. B9zones fixture сохраняет эту привязку.
F0 command98(type1,3) устанавливает текущийгород; codec system_message.py
сохраняет проверенныйwire: f062000000010000000100000003000000.

Текущийгород[[ac5d58]] и режим фона[[ac5e5c]]=ac4c6d разделены.
Render9de700: mode1 при overlay0 вызывает9de154; mode0 вызывает карту9ee150.
9de154 читает background из town+10d,строит pda/<background>.jpg,
вызывает4f2c50 и выставляет town+20d(background_loaded).

Original8596e0 устанавливает mode1 через9de87c,обновляет городские controls
через9e3c88,активирует UI group100 черезa3ebf4. Original8589c4 — toggle:
при уже включённом mode1 он выключаетгородскойвид. Поэтому проба8589c4
далаmode0 и была заменена конкретной функцией8596e0.

В повторной пробе mode уже был1 ДО8596e0. Нельзя утверждать, что единственной
причиной отсутствия Reservation былmode0. Существенен полный UI refresh.
После8596e0 штатный render-loop вызвал9de154,loader получил
pda/loc_reserve.jpg,вернулся; id3/background_loaded1/backgroundloc_reserve.
Evidence: reservation_enter_view_repeat.log,reservation_texture_probe.log.

## Ограничение результата
--town-view-probe вызывает оригинальную8596e0 как диагностическое действие
в instrumentedclient после F0; это НЕ самостоятельный серверный пакет и
не доказательство, что обычный UI-клик уже работает с сервером без probe.
Sky не обнаружил окно для screenshot; визуальная проверка Reservation
пока отсутствует. Глобальная карта подтверждена пользователем.

## Воспроизведение
python tools/probe_item_fixture.py --loopback --completion --login-result --server-list --server-list-entry --server-login --mode1-challenge --mode1-complete --auth2-result --shared-config --empty-characters --create-success-probe --select-probe --mychar-probe --town-probe --enter-town-probe --town-view-probe --visible-launch --inspect-window

Предыдущий барьер прямого8596e0 снят сервернойкомандой117 (см.выше).
64 unit tests PASS. Цель полноценного входа остаётся незавершённой.
