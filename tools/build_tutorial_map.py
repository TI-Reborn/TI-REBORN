"""Import the installed original tutorial map; no shared catalogue mutation."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.import_arena_fragments import BASE,read_fragment


def main():
    source=BASE/'maps/tutorial.s';fragment=read_fragment(source)
    if fragment['sha256']!='3e74ba79f9033442a1b343ed6918cd70a3d8f91ddae360114c1e1293078f83de':raise ValueError('Unexpected original tutorial map')
    out=ROOT/'config/tutorial_map.json'
    out.write_text(json.dumps(dict(source='Installed original maps/tutorial.s TI SET v2; native model-door extraction',fragment=fragment),indent=2)+'\n',encoding='utf-8')
    quest=BASE/'quest/tut_1000.xml'
    (ROOT/'evidence/tutorial_original_sources.json').write_text(json.dumps(dict(
        map_sha256=fragment['sha256'],quest_sha256=hashlib.sha256(quest.read_bytes()).hexdigest(),
        width=fragment['width'],height=fragment['height'],models=len(fragment['models']),
        native_doors=fragment['doors'],boxes=fragment['containers'],
        policy='Original scenery; short four-observed-action lesson, temporary Beretta, stationary target and deployment are explicit emulator policy',
        limitation='Original ack XML/source instructions inspected; original automatic intro network trigger/dialogue ABI not recovered'),indent=2)+'\n',encoding='utf-8')
    print('Original tutorial map imported:48x48/27models/1box/3native doors')


if __name__=='__main__':main()
