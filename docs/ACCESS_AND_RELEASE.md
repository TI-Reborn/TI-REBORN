# Доступ и выпуск

Целевой репозиторий: `Junduge/TI-REBORN`, только **Private**.
Владелец: Junduge. Предполагаемый collaborator: ilyaplot, без права администратора.
Снимок кода не предоставляет SSH, базу игроков, production-секреты или право выпуска.
Человек с чтением репозитория может скачать весь его код; ограничить чтение отдельных
папок внутри одного репозитория нельзя. Отзыв доступа не удалит уже скачанную копию.

## Обязательные настройки до приглашения

В GitHub Settings → Branches / Rulesets для `main`:

- Require a pull request before merging.
- Require approvals: 1; Require review from Code Owners (`@Junduge`).
- Dismiss stale approvals when new commits are pushed.
- Require conversation resolution.
- После первого успешного CI: Require status checks → `server-checks`.
- Запретить force push и удаление ветки. Не давать ilyaplot bypass/admin.
- Для наиболее строгого режима применить правила и к администратору.

В личном репозитории GitHub collaborator имеет read/write, отдельного read-only нет.
Защита закрытых личных репозиториев требует GitHub Pro; для организации — подходящего
плана, например Team. Если тариф не поддерживает правила, НЕ приглашать разработчика
с неограниченной записью под видом «только PR»: согласовать Pro/организацию или отдельный
репозиторий для предложений. Покупка тарифа не входит в эту подготовку.

Источники GitHub (проверены 17.10.2026):
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

## Выпуск — владелец

GitHub Actions запускает только проверки на временном runner. Production-секретов и
SSH-ключей в репозитории/CI нет. Код из PR не получает доступ к живому серверу.

Перед игровым выпуском владелец проверяет фактическое состояние хостинга, сохраняет
согласованную резервную копию базы и предыдущие код/конфигурацию. Локальная база никогда
не заменяет hosted-базу. После обновления: preflight, состояние службы, журналы, проверка
несколькими аккаунтами и отдельно настоящими игровыми клиентами, очистка своих QA-фикстур.
Старые команды в `DEPLOY_HETZNER.md` и `deploy/BACKUPS.md` — исходные runbook-материалы,
их нельзя выполнять слепо: перед выпуском требуется сверить реальную конфигурацию.

Подготовка репозитория не меняла хостинг и не подтверждает совпадение локального кода
с удалённым. Если потребуется точная production-ветка, сначала провести read-only
сверку хешей с хостингом силами владельца, без копирования базы и секретов.
