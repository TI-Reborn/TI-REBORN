"""Trusted local operator interface for an explicit online Prison sentence.

This command requires an existing SQLite database and a public character name.
It has no default database, authentication input, network access, automatic
penalties or game-client opcode. The production sentence helper owns all rules.
Output contains only public character name, remaining seconds, replay and status.
"""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from tio.character_identity import owner_for_name
from tio.db_transaction import transaction
from tio import world_completion as world

PUBLIC_NAME = re.compile(r'[A-Za-z][A-Za-z0-9]{2,15}\Z')
OPERATION = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
MAX_SECONDS = 31536000


class ModerationError(ValueError):
    """A static public status; raw SQL/owner/session details never reach CLI."""
    def __init__(self,status,character=None):
        self.status=status;self.character=character
        super().__init__(status)


class OperatorParser(argparse.ArgumentParser):
    def error(self,message):
        # argparse normally echoes malformed arguments (including operation
        # identifiers). Emit the same bounded public response as other errors.
        raise ModerationError('invalid_request')


def checked_database(database):
    try:
        path=Path(database).expanduser().resolve(strict=True)
        if not path.is_file():raise OSError('Not a file')
        with path.open('rb') as source:
            if source.read(16)!=b'SQLite format 3\0':raise OSError('Not an SQLite database')
        return path
    except (OSError,TypeError,ValueError):
        raise ModerationError('database_unavailable') from None


def moderate(database,character,seconds,operation):
    """Resolve a public name and sentence its save owner in one transaction."""
    if (not isinstance(character,str) or PUBLIC_NAME.fullmatch(character) is None
            or type(seconds) is not int or not 1<=seconds<=MAX_SECONDS
            or not isinstance(operation,str) or OPERATION.fullmatch(operation) is None):
        raise ModerationError('invalid_request')
    path=checked_database(database);public=None
    try:
        with transaction(path) as db:
            owner=owner_for_name(db,character)
            if owner is None:raise ModerationError('character_not_found')
            row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()
            if row is None:raise ModerationError('character_not_found')
            public=bytes(row[0]).decode('ascii')
            if PUBLIC_NAME.fullmatch(public) is None:raise ModerationError('database_unavailable')
            replay=bool(world.exists(db,'world_prison_operations') and db.execute(
                'SELECT 1 FROM world_prison_operations WHERE identity=?',(operation,)).fetchone())
            state=world.sentence(db,owner,seconds,operation)
            result=dict(character=public,remaining=state['remaining'],replay=replay,
                status='replayed' if replay else 'sentenced')
        # Publish a success only after the enclosing CLI transaction commits.
        return result
    except ModerationError:raise
    except (sqlite3.Error,OSError,UnicodeError,TypeError):
        raise ModerationError('database_unavailable',public) from None
    except ValueError as error:
        messages={'Conflicting prison sentence retry':'conflicting_operation',
            'Finish or recover the authoritative battle before sentencing':'battle_pending',
            'Prison sentence limit exceeded':'sentence_limit',
            'Unknown prisoner character':'character_not_found',
            'Invalid online prison sentence':'invalid_request'}
        raise ModerationError(messages.get(str(error),'operation_rejected'),public) from None


def main(argv=None):
    parser=OperatorParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--database',required=True,help='Existing local SQLite path; no default')
    parser.add_argument('--character',required=True,help='Public character name, not account login')
    parser.add_argument('--seconds',required=True,help='Online seconds1..31536000')
    parser.add_argument('--operation',required=True,help='Durable unique request key; reuse for retry')
    try:
        args=parser.parse_args(argv)
        if re.fullmatch(r'[0-9]{1,8}',args.seconds) is None:
            raise ModerationError('invalid_request')
        result=moderate(args.database,args.character,int(args.seconds),args.operation)
        code=0
    except ModerationError as error:
        result=dict(character=error.character,remaining=None,replay=False,status=error.status)
        code=2
    except Exception:
        # The command boundary also suppresses unexpected internal exception
        # messages/tracebacks, which can contain private owner/session values.
        result=dict(character=None,remaining=None,replay=False,status='operation_rejected')
        code=2
    print(json.dumps(result,ensure_ascii=True,separators=(',',':')))
    return code


if __name__=='__main__':raise SystemExit(main())
