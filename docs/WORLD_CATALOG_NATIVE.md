# Этап 8: подтверждённый каталог и TownInfo

Сборщик `tools/prepare_world_completion_catalog.py` читает только фактические
исходники из `reports/gameplay-completion/stage8-world/source` и
`client/source`, а правила — из `config/world_completion.json`. Он пишет
`runtime/evidence/zones_diagnostic.xml`, `client/candidate/zones.xml` и
`catalog.json`. Локальный `evidence/zones_diagnostic.xml` с незавершёнными
контрактами и `config/world_completion_zones.xml` не используются.

У двух исходных каталогов различаются старые уровни/флаги городов. В каждом
сохраняются собственные строки 1–17 побайтно, кроме согласованных 4/7/10.
Добавляются только 18–22, клонируя родные записи town/base. ID и порядок
строго 1–22: родной lookup `0x7d2ea4` использует `table[id-1]`. Геометрия
новых локаций и перенос базы7 — явно заданная политика эмулятора, а не
исторические координаты. Новые прямоугольники проверены на пересечение.

Подтверждённые ключи оригинального XML-загрузчика `0x9ea894`:

| XML | Поле родного объекта города | Назначение |
|---|---|---|
| `drop` | `+0x24d` | Флаг drop |
| `dragin` | `+0x24e` | Вход со своей экипировкой |
| `dragInMaxEnhance` | `+0x24c` | Максимальное улучшение |
| `arena` | `+0x237` | Арена |
| `IsTraining` | `+0x23e` | Учебная база |
| `rankBonus` | `+0x23d` | Бонус звания |
| `minlevel` / `maxlevel` | `+0x248` / `+0x249` | Уровни |

Ключ `equip` загрузчик не читает. В новом каталоге используется `dragin`.
Ключи `capture`/`prison_only` являются серверными правилами; клиентскому XML
не приписывается их поддержка.

Порядок float-полей C8/2D доказан исполнением оригинального reader,
getter, записи модели и трёх потребителей tooltip:

| Позиция в пакете | Декодированный объект | Город | Нативная подпись |
|---|---|---|---|
| 1 | `+0x18` | `+0x228` | `m159`: Influence rate |
| 2 | `+0x20` | `+0x22c` | `m219`: Experience rate |
| 3 | `+0x28` | `+0x230` | `m397`: Profit rate |

Значит `TownInfoBase.unknown_float_bits` имеет порядок
`(influence, experience, profit)`. Порядок трёх bool —
`(drop, dragin, quitzone)`. Оригинальный XML дополнительно содержит
`expirienceMultiplier` — именно с таким написанием — для второго float.

`tools/verify_world_catalog_native.py` принимает явный `--xml` и `--output`.
Проверены 22 записи полного оригинального загрузчика, 44 состояния enabled
и lookup, B9/03 parsing/copy с точным сжатым XML, selector B9 reload `zones`
и float-sentinel1.25/2.5/3.75, доходящие до родных tooltip-подписей.
Используется точный опубликованный DLL .4; каждый исполненный байт инструкции
сравнивается с оригиналом. XML DOM, строки, allocation, filesystem, logging
и создание окна штурма изолированы. Родной XML tokenizer, полный inflate/
filesystem путь и пиксели Windows GUI не проверены. На VPS ничего не менялось.

Публикация .5 описана в `WORLD_CLIENT_RELEASE.md`. Для неё нужны отдельные
серверные validation/deployment/hosted-world с точным `world_client_release`
из подготовленного `client/release.json`.
