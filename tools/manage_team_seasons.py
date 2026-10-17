"""Read/close team-rating seasons locally on the authoritative database.

There are no seed, reset, grant, winner or score mutation commands. An archive
operation follows the calendar and refuses to seal a season with pending games.
"""
import argparse
from contextlib import closing
import json

from tio.db_transaction import connect
from tio import team_ratings, rating_seasons


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('seasons')
    ratings=sub.add_parser('standings');ratings.add_argument('--season');ratings.add_argument('--offset',type=int,default=0);ratings.add_argument('--limit',type=int,default=20)
    sub.add_parser('archive-due')
    args=p.parse_args(argv)
    with closing(connect(args.database)) as db:
        if args.command=='archive-due':
            with db:
                db.execute('BEGIN IMMEDIATE');team_ratings.schema(db)
                result=dict(closed=rating_seasons.close_finished(db),seasons=rating_seasons.listing(db))
        elif args.command=='seasons':result=rating_seasons.listing(db)
        else:result=team_ratings.standings(db,scope=args.season,offset=args.offset,limit=args.limit)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
