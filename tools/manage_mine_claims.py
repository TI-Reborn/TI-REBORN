"""Explicit, local checkpoint ownership administration; no SSH or native bypass.

Examples (substitute an existing clan ID and the current revision from show):
  python tools/manage_mine_claims.py --db /path/state.db show
  python tools/manage_mine_claims.py --db /path/state.db set 13 --clan 7 \
    --tax-percent 10 --expected-revision 0 --actor operator --reason 'Initial claim'
  python tools/manage_mine_claims.py --db /path/state.db clear 13 \
    --expected-revision 1 --actor operator --reason 'Release checkpoint'

Run under the authorized operator's OS access. This is emulator configuration,
not a recovered native checkpoint assault command. It never creates a clan,
member, account, or funds. Mutations require no pending battle/checkpoint/outbox
and use an exact expected revision. Unconfigured checkpoints remain unowned,
with tax zero and no defender. Tax is frozen per battle; score-based tax rounds
and alliance membership are not implemented by this tool.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT)]
from tio.mine_claims import MineClaimsStore,LOCATIONS,frozen_claim


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db',required=True,type=Path,help='Existing authoritative SQLite database; no automatic database creation')
    commands=parser.add_subparsers(dest='command',required=True)
    show=commands.add_parser('show',help='Read claims without creating tables or changing data')
    show.add_argument('location',type=int,nargs='?',choices=sorted(LOCATIONS))
    for name in ('set','clear'):
        command=commands.add_parser(name)
        command.add_argument('location',type=int,choices=sorted(LOCATIONS))
        command.add_argument('--expected-revision',type=int,required=True)
        command.add_argument('--actor',required=True)
        command.add_argument('--reason',required=True)
        if name=='set':
            command.add_argument('--clan',type=int,required=True,help='Existing real clan ID')
            command.add_argument('--tax-percent',type=int,default=10,choices=range(11))
    args=parser.parse_args(argv)
    if not args.db.is_file():parser.error('Database must already exist')
    try:
        if args.command=='show':
            with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('BEGIN')
                configured=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='mine_claims'").fetchone())
                result=[frozen_claim(db,location) if configured else dict(location=location,owner_clan=None,tax_percent=0,revision=0)
                        for location in ([args.location] if args.location is not None else sorted(LOCATIONS))]
        else:
            store=MineClaimsStore(args.db)
            result=store.admin_set_claim(args.location,args.clan if args.command=='set' else None,
                tax_percent=args.tax_percent if args.command=='set' else 0,
                expected_revision=args.expected_revision,actor=args.actor,reason=args.reason)
    except (ValueError,sqlite3.Error) as error:parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
