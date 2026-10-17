"""Read the authoritative territory schedule, claims and event receipts."""
import argparse
import json
from tio.territories import TerritoriesStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--config')
    parser.add_argument('--town',type=int)
    args=parser.parse_args()
    store=TerritoriesStore(args.database,args.config)
    towns=(args.town,) if args.town else tuple(store.locations)
    rows=[]
    for town in towns:
        state=store.info(town)
        event=state['event'] or dict(id=None,phase='DISABLED',starts=None,phase_ends=None)
        rows.append(dict(id=town,name=state['name'],enabled=state['enabled'],levels=state['levels'],
            claim=state['claim'],phase=event['phase'],starts_utc=event['starts'],phase_ends_utc=event['phase_ends'],
            groups=store.groups(town) if state['enabled'] else (),ranking=store.ranking(event['id']) if state['enabled'] else ()))
    print(json.dumps(rows,ensure_ascii=False,default=lambda v:v.decode('cp1251') if isinstance(v,bytes) else str(v)))


if __name__=='__main__':main()
