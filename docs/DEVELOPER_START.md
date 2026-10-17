# Начало работы

## Окружение

Клонируйте закрытый `Junduge/TI-REBORN` после принятия приглашения. Требуется Python 3.11+,
рекомендуемая версия CI — 3.12. Команды выполняются из корня репозитория.

```powershell
git clone https://github.com/Junduge/TI-REBORN.git
cd TI-REBORN
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m server --check
python tools/check_handoff.py
python tools/run_server_checks.py
```

На Linux: `python3 -m venv .venv`, затем `source .venv/bin/activate`.
Для ядра `pip install` не нужен. `pyproject.toml` исторически упаковывает только `tio`;
wheel не является самостоятельным сервером с каталогами. Работайте из checkout.
Flask-регистрация отдельно: `python -m pip install -r registration/requirements.txt`.
RE-инструменты могут требовать Windows, установленного клиента и research extras;
они не нужны для обычной серверной разработки.

## Локальная среда с независимыми аккаунтами

```powershell
Copy-Item config/development.example.toml config/development.local.toml
python -m server.accounts create deva --character DevAlpha --config config/development.local.toml
python -m server.accounts create devb --character DevBeta --config config/development.local.toml
python -m server --config config/development.local.toml --check
python -m server --config config/development.local.toml
```

Пароли вводятся интерактивно, 12–64 ASCII-символа. База создаётся в `data/development/`,
который исключён из Git. Порты 28512/28513 привязаны только к loopback.
Не подставляйте адрес хостинга и не копируйте его базу. Сначала создайте аккаунты:
проверка multi-account намеренно отклоняет пустую базу.

Эта среда предназначена для разработки и TCP-тестов. Приёмка игрового изменения требует
двух реальных аккаунтов и согласованной проверки на хостинге с настоящими клиентами.
Исходники сервера не включают игровой клиент. Подключение клиента согласуется с владельцем;
смотрите исторические `CLIENT_CONNECTION.md` и `GAME_TLS_PLAN.md`.

## Первая задача

1. Создать ветку `feature/<краткое-название>`.
2. Найти затрагиваемый сервис в карте архитектуры и его тесты `test_<тема>*.py`.
3. Зафиксировать воспроизводимый пример и ожидаемое поведение нескольких аккаунтов.
4. Внести небольшой патч. Изменение wire-format согласовать отдельно.
5. Выполнить базовые и тематические тесты; приложить результат в PR.
6. Запросить review у Junduge. Деплой выполняет владелец после review и резервной копии.
