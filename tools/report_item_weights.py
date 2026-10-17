"""Write an auditable list of every current item's original unit mass."""
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.weight import item_weights


def main():
    catalog=item_weights()
    rows=[]
    for node in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot():
        identity=int(node.get('id'))
        explicit=node.find("value[@key='weight']") is not None
        rows.append(dict(id=identity,name=node.get('name'),unit_weight=catalog[identity][0],
                         contained_item=catalog[identity][1],explicit_weight=explicit))
    report=dict(source='Original base/items.cfg via evidence/items_diagnostic.xml',
                total=len(rows),explicit=sum(r['explicit_weight'] for r in rows),items=rows)
    (ROOT/'evidence/item_weights.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Item weights: {report['total']} templates, {report['explicit']} explicit masses")


if __name__=='__main__':main()
