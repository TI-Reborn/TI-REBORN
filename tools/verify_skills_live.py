"""Read-only verification of original client's skills metadata against XML import."""
import argparse,json,time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('pid',type=int);args=parser.parse_args()
    messages=[];session=frida.attach(args.pid)
    try:
        script=session.create_script("""
const b=Process.getModuleByName('silver.dll').base;
const p=b.add(0xac5ef0-0x400000).readPointer().readPointer();
const n=p.isNull()?0:p.sub(4).readU32();if(n>10000)throw Error('Invalid catalog length');
const rows=[];for(let i=0;i<n;i++){const r=p.add(i*0x348);rows.push({
id:r.add(8).readU32(),level:r.add(0x31e).readU8(),levels:r.add(0x31f).readU8(),
value:r.add(0x320).readS32(),active:r.add(0x326).readU8(),range:r.add(0x332).readU8(),
ap:r.add(0x327).readU8(),cooldown:r.add(0x32c).readU32()});}send(rows);
""")
        script.on('message',lambda message,data:messages.append(message));script.load();time.sleep(.2)
    finally:session.detach()
    if len(messages)!=1 or messages[0]['type']!='send':raise ValueError(messages)
    rows=messages[0]['payload'];report=json.loads((ROOT/'evidence/skills_provenance.json').read_text())
    expected={(s['id'],i+1):(s,v) for s in report['included'] for i,v in enumerate(s['values'])}
    assert len(rows)==len(expected)
    assert {(r['id'],r['level']) for r in rows}==set(expected)
    for row in rows:
        definition,value=expected[(row['id'],row['level'])];mapped=definition['mapped']
        assert row['value']==value and row['levels']==definition['levels'],row
        assert row['active']==int(mapped.get('operateType')=='OP_ACTIVE'),row
        for field,key in [('range','castRange'),('ap','apConsume'),('cooldown','reuseTurns')]:
            if key in mapped:assert row[field]==int(mapped[key]),row
    (ROOT/'evidence/skills_native_readback.json').write_text(json.dumps({
        'status':'PASS','pid':args.pid,'method':__doc__,'rows':rows,
        'limitations':'Omitted XML fields reflect client defaults, not recovered source values; learning and effects not tested.'},indent=2)+'\n')
    print(f'Original client skills catalog: {len(rows)} levels PASS')

if __name__=='__main__':main()
