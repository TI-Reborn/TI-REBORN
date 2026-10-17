# Каталог локаций клиента: этап 8

`tools/publish_world_completion_client.py` готовит релиз `2026.10.08.5` из
фактически опубликованного `2026.10.08.4`. Меняется только запись
`base/shared config/zones.xml`: исправляются ID 4, 7, 10 и добавляются ID 18–22.
DLL, новости, остальные файлы, seed-флаги и порядок записей сохраняются.
Нулевые клиентские файлы допустимы.

Подготовка выполняет только чтение HTTPS. Она сравнивает свежий манифест с
`client/source/observation.json`, сохраняет **точные исходные байты** в
`client/previous-manifest.json` и получает исходный XML по его immutable SHA.
Она повторно строит XML из принятой политики и требует native-проверку
оригинального клиента: 22 записи загрузчика, 44 проверки доступности,
успешную конфигурацию B9 и порядок коэффициентов
`influence`, `experience`, `profit`.

```powershell
python -m unittest tests.test_publish_world_completion_client -v
python -m tools.publish_world_completion_client prepare --version 2026.10.08.5
```

Подготовка сохраняет `client/release.json`, `client/manifest.json`,
`client/previous-manifest.json`, `client/prepare-https.json` только в
`reports/gameplay-completion/stage8-world`. Существующие исходники, кандидат,
native-проверка и завершённая подготовка не перезаписываются. Если подготовка
прервалась между записями, сохраните частичные доказательства перед новым
запуском. Поле `world_client_release` из `client/release.json` связывает четыре
SHA256: `policy_sha256`, `runtime_sha256`, `candidate_sha256`,
`native_proof_sha256`.

Публикация допускается после серверного развёртывания и проверки хостинга.
Три документа — `validation.json`, `deployment.json`, `hosted-world.json` —
должны содержать `passed: true` и точный объект `world_client_release`.
`deployment.json` дополнительно содержит фактически развёрнутые файлы в
`runtime_files` либо `hashes` формата имя → SHA256. Обязательны
`config/world_completion.json` и `evidence/zones_diagnostic.xml`; добавьте все
изменённые серверные файлы этапа 8, чтобы публикация проверила их на VPS.
Неизвестная структура отчёта вызывает отказ, а не обход проверки.

```powershell
python -m tools.publish_world_completion_client publish --version 2026.10.08.5
python -m tools.publish_world_completion_client verify --version 2026.10.08.5
```

Перед записью публикация сравнивает свежие SSH и HTTPS манифесты, исходный
XML, все опубликованные blobs и фактические серверные хеши. Закрытая резервная
копия `/root/tio-before-world-client-*` содержит старый/новый манифесты, XML,
оба launcher-файла, код и конфигурацию. Затем новый XML помещается в immutable
blob, а манифест заменяется атомарно. Общая блокировка
`.tio-gameplay-client.lock` предотвращает параллельные игровые публикации.

Операция имеет постоянный UUID из `release.json`. Завершённый результат
сохраняется в закрытый журнал `/root/tio-world-client-<UUID>.json`. Повторный
`publish` той же операции восстанавливает подтверждённый результат без
второго backup. При ошибке после commit старый манифест возвращается, только
если текущий манифест всё ещё принадлежит этой операции. Более поздний чужой
манифест сохраняется; неиспользованный immutable blob остаётся для диагностики.
Результат и HTTPS-проверка сохраняются в `client/publication.json` и
`client/https-verification.json`.

Изолированные тесты исполняют тот же удалённый stdlib-код во временных
каталогах, с подменёнными service/lock и без сети. Скрипт не открывает БД,
не читает и не загружает сохранения, не меняет launcher-файлы и не
перезапускает службу. HTTPS/native и автоматические проверки отдельно от
проверки двумя настоящими графическими клиентами; `graphical_acceptance_complete`
остаётся `false` в отчёте проверки HTTPS.
