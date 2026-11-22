"""Manage game administrators from the server console and authorize native jail commands."""
import argparse
from contextlib import closing
from hashlib import sha256
import logging
from pathlib import Path
import re
import sqlite3
import time

from .accounts import identity
from .config import ServerConfig
from tio.character_identity import auth_account, owner_for_name, owners
from tio.db_transaction import transaction
from tio.player_admin import active_sanction, is_admin, lift_sanction, list_admins, record_sanction, set_admin
from tio.world_completion import exists, sentence

LOG = logging.getLogger('tio.server')
JAIL_ARGUMENTS = re.compile(r'([A-Za-z][A-Za-z0-9]{2,15}) ([1-9][0-9]{0,3}) ([A-Za-z0-9_.-]{1,64})')
TARGET = re.compile(r'[A-Za-z][A-Za-z0-9]{2,15}')
MINUTES = re.compile(r'[1-9][0-9]{0,3}')
COMMANDS = frozenset(('//jail', '//ban', '//banchat'))


def role(path: Path, actor: str) -> bool:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        return is_admin(db, actor)


def require_chat(path: Path, actor: str) -> None:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if active_sanction(db, actor, 'mute', now=int(time.time())):
            raise ValueError('Чат заблокирован модератором.')


def _minutes(value: str, limit: int) -> int:
    if not MINUTES.fullmatch(value) or int(value) > limit:
        raise ValueError(f'Укажите срок от 1 до {limit} минут.')
    return int(value) * 60


def _arguments(command: str, text: str) -> tuple[str, int | None, str]:
    if command == '//jail':
        legacy = JAIL_ARGUMENTS.fullmatch(' '.join(text.split()))
        if legacy is not None and int(legacy[2]) <= 3600:
            return legacy[1], int(legacy[2]), legacy[3]
    parts = text.split(maxsplit=1 if command == '//ban' else 2)
    if (len(parts) != (2 if command == '//ban' else 3) or not TARGET.fullmatch(parts[0])
            or not 1 <= len(parts[-1]) <= 120):
        raise ValueError('Укажите имя персонажа, срок (для чата и Prison) и причину.')
    if command == '//ban':
        return parts[0], None, parts[1]
    if command == '//banchat':
        return parts[0], _minutes(parts[1], 1440), parts[2]
    if parts[1].startswith('m'):
        seconds = _minutes(parts[1][1:], 60)
        fingerprint = sha256(repr((parts[0].lower(), seconds, parts[2])).encode()).hexdigest()
        return parts[0], seconds, 'native:'+fingerprint
    raise ValueError('Формат: //jail ИМЯ СЕКУНДЫ ID_РЕШЕНИЯ. Срок от 1 до 3600 онлайн-секунд.')


def moderate(path: Path, actor: str | None, command: str, arguments: str) -> tuple[str, str | None]:
    """Apply moderation for an authenticated grant and return any login to disconnect."""
    denial = 'Команда доступна только игровым администраторам.'
    if actor is None or not role(path, actor):
        raise ValueError(denial)
    character, duration, reason = _arguments(command, arguments)
    with transaction(path) as db:
        if not is_admin(db, actor):
            raise ValueError(denial)
        owner = owner_for_name(db, character)
        if owner is None:
            raise ValueError('Персонаж не найден.')
        login = auth_account(path, owner, connection=db)
        if is_admin(db, login):
            raise ValueError('Игрового администратора может наказать только оператор сервера.')
        if command == '//jail':
            assert duration is not None
            result = sentence(db, owner, duration, f'player-admin:{actor}:{reason}')
            notice = f'Prison: {character}, осталось {result["remaining"]} онлайн-сек.'
        elif command == '//ban':
            # A blocked account cannot reconnect to finish or recover another slot's battle.
            for saved in owners(path, login):
                if any(exists(db, table) and db.execute(
                    f'SELECT 1 FROM {table} WHERE account=?', (saved,)
                ).fetchone() for table in ('battle_checkpoint_members', 'battle_settlement_jobs')):
                    raise ValueError('Дождитесь завершения боя и расчётов игрока.')
            record_sanction(db, login, 'ban', reason, None)
            notice = f'Доступ игрока {character} заблокирован.'
        else:
            assert duration is not None
            record_sanction(db, login, 'mute', reason, int(time.time()) + duration)
            notice = f'Чат игрока {character} заблокирован.'
    LOG.info('player_admin_%s actor=%s character=%s seconds=%s', command[2:], actor, character, duration)
    return notice, login if command == '//ban' else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--config', type=Path, required=True, help='Path to the active server.toml')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List game administrator logins')
    commands.add_parser('grant', help='Grant administrator status').add_argument('login', type=identity)
    commands.add_parser('revoke', help='Revoke administrator status').add_argument('login', type=identity)
    commands.add_parser('unban', help='Restore game access').add_argument('login', type=identity)
    commands.add_parser('unmute', help='Restore chat access').add_argument('login', type=identity)
    args = parser.parse_args(argv)
    try:
        config = ServerConfig.load(args.config)
        if not config.multi_account:
            raise ValueError('Player administrators require multi_account')
        database = config.database.as_uri()
        if args.command == 'list':
            with closing(sqlite3.connect(database + '?mode=ro', uri=True)) as db:
                for login in list_admins(db):
                    print(login)
            return 0
        with closing(sqlite3.connect(database + '?mode=rw', uri=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if args.command in ('grant', 'revoke'):
                changed = set_admin(db, args.login, enabled=args.command == 'grant')
            else:
                changed = lift_sanction(db, args.login, args.command[2:])
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print('Updated.' if changed else 'Already up to date.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
