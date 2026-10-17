# Штатный Top100 игроков

Руководство, печатная стр.26 (`reports/chat-presence/manual.txt`, раздел рейтингов),
требует общий Top100 с сортировками по рангу, рейтингу, победам, нанесённому урону
и опыту. Исторические C2S логи уже содержат `A4 05`; новый opcode не нужен.

## Проверенный оригинальный ABI

Исходный установленный `silver.dll` SHA256:
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.

`0x7801b0` читает выбранное значение штатного combo `SortType` через
`0xa3e490`, затем вызывает builder `0x77f74c`. Builder меняет местами значения
0 и5, пишет **`A4 selector_u8`**, отправляет обычным транспортом. Меню рейтингов
вызывает этот callback (`0x9e6a1f`); переключение combo вызывает его повторно.

| Wire selector | Combo index | Сортировка |
|---|---|---|
|0|5|Рейтинг|
|1|1|Победы|
|2|2|Нанесённый урон|
|3|3|Убийства|
|4|4|Опыт|
|5|0|Ранг|
|6|6|Бронзовая лига|
|7|7|Серебряная лига|
|8|8|Золотая лига|

Штатный общий dispatcher вызывает `0x77f918` по адресу `0x9f5725`.
Этот обработчик принимает **A5**, reader `0x77f788` читает
**`selector_u8 count_u16 rows[count]`**. Selector потребляется без сохранения;
порядок списка определяет сервер. После чтения обновляет
`window_players_rating` через `0x7800dc`. Если окно закрыто, массив сохраняется
для следующего отображения. Нумерацию мест рисует исходный список; отдельного
поля place в этом пакете нет.

Порядок полей каждой строки проверен исполнением reader и RTTI
`TPlayerRaiting` (`0x77f97c`). Названия `dmg_give`, `dmg_recv`, `wins`, `loses`,
`expire`, `kills`, `deathes`, `raiting`, `militaryRank`, `militaryRankPoints`,
`trueskill` взяты из исходной DLL.

|Wire field|Native record offset|Формат|
|---|---|---|
|name|0x00|NUL-terminated bytes|
|clan_name|0x04|NUL-terminated bytes|
|clan_crest_id|0x08|u32|
|unknown_discarded_u32|—|u32, reader отбрасывает; сервер пишет0|
|alliance_crest_id|0x0c|u32|
|level|0x10|u8, native сохраняет какu32|
|damage_dealt|0x14|u32|
|damage_received|0x18|u32|
|wins|0x1c|u32|
|losses|0x20|u32|
|rating|0x30|i32|
|military_rank|0x34|i32, значок отряда|
|rank_points|0x38|i32, очки ранга отряда|
|experience|0x24|u32|
|kills|0x28|u32|
|deaths|0x2c|u32|
|trueskill|0x3c|i32|

`military_rank` здесь соответствует `PublicProfile.squad_icon`,
`rank_points` — `PublicProfile.squad_rank`. Это не ID звания бойца.
Подписи оригинального окна: `m579` ранг, `m225` победы, `m223` урон,
`m228` убийства, `ii36` опыт, `m227` рейтинг, `m1103` TrueSkill.

## Точные hooks для shared-server integration

Новый `tio.protocol.player_top100`:

* `decode_request(packet: bytes) -> int`, только точный двухбайтовый A4,
  известные selector0..8; остальные пакеты вызывают `PacketError`.
* `SORTS[selector] -> str`: rating/wins/damage/kills/experience/rank/
  bronze/silver/gold.
* `encode_world_rows(selector: int, rows: Iterable[dict]) -> bytes`:
  реальный A5, максимум100 строк, whitelist публичных полей.
* `encode_ratings(selector, rows: Iterable[PlayerRating|dict]) -> bytes`
  строгий ABI; `decode_ratings(packet) -> (selector, tuple[PlayerRating])`
  используется для проверок.

В существующем authenticated request handler (owner/auth session уже проверены):

```python
from tio.protocol.player_top100 import decode_request, SORTS, encode_world_rows
from tio.world_completion import player_top100

selector = decode_request(packet)
rows = player_top100(self.database, sort=SORTS[selector])
response = encode_world_rows(selector, rows)
# response через существующий S2C framing/send/journal-free read path
```

Этот hook должен стоять в обработке A4, а не заменять клановый82/83, профиль68/A7
или штурмовой рейтинг. `player_top100` открывает readonly DB и одну транзакцию
чтения. Все сохранённые аккаунты и реальные character aliases участвуют;
online/recent session filter отсутствует. В wire не попадают owner, login,
кошельки или внутренние ключи маршрутизации. Обработка запроса не создаёт таблиц,
не меняет rank decay, достижения, статистику или баланс.

Обновление `world_completion.players` ограничено публичными row fields и
sorts. Рейтинг получает только уже заработанный achievement bonus через
`achievement_benefits.total_rating` и ограничивается signed32. Root должен
применить такой же верхний предел `0x7fffffff` к PublicProfile для совпадения
обоих представлений. Счётчики A5 ограничиваютсяu32 при проекции и не оборачиваются.
Ранг/XP/обычный rating берутся только у текущих owned soldiers. Dismissed rows
в таблице soldier_ratings не учитываются. Результаты ставок не добавляют wins
или losses. Historical kills baseline читается тем же способом, что PublicProfile,
без повторного сложения achievement counter, если baseline уже записан.

Для selector6..8 явная политика эмулятора: читать уже существующий
`ranked_players.skill/league`, отбирать `wins+losses+draws>0`, фильтровать
bronze3/silver2/gold1 и сортировать по skill. При отсутствии ranked data
возвращается настоящий пустой A5. Формула0..400 и league hysteresis принадлежат
существующему `tio/ranked.py`; это не утверждение об исторической серверной
формуле. Равные значения всех сортировок разрешаются по casefold public name,
затем owner key, который остаётся на сервере.

Публичные clan/crest поля поддерживаются codec; текущий world projection
пока не присоединяет clan membership, поэтому по умолчанию пустое имя/нулевые
crest IDs. Это не препятствует Top100 или открытию профиля по штатному имени.

## Проверки и ограничения

`python -m unittest tests.test_player_top100 tests.test_world_completion`:
19 проверок PASS. Покрыты все manual/native sorts, earned bonus, отрицательный
ранг, signed границы, readonly DB, wager results, текущий roster, league filters,
baseline kills, отсутствие owner keys,100 строк, malformed/truncated packets.

`python tools/verify_player_top100_native.py`:9 actual native combo/builders +
13 dispatcher/reader cases PASS на pinned original. Реально выполняются
NUL-read loops `0x605e8c/0x605f1c`, scalar readers, native array field stores
и вызов refresh. Stubbed только Delphi string/allocation helpers, crest fetch,
transport и GUI lookup. Каждая выполненная инструкция внутри исходного image
сравнивается с исходными bytes; никаких DLL patches этот пакет не создаёт.

Для gate точной публикуемой DLL:

```powershell
python tools/verify_player_top100_native.py --binary <EXACT_CANDIDATE_PATH> --sha <EXACT_SHA256> --output <NEW_EVIDENCE_PATH>
```

Evidence: `evidence/player_top100_native.json`. Это автоматические ABI проверки.
Рендер живого окна, ввод реального игрового клиента и hosted S2C exchange здесь
не проверены; их выполняет root после shared request integration/deploy.
