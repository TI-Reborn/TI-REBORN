"""Reproducible client inventory and TI/AZT resource/string comparison."""
import collections
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import pefile

ROOT = Path(__file__).resolve().parents[1]
TI = Path(r'C:\Program Files (x86)\TIOnline')
AZT = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Affected Zone Tactics')
EVIDENCE = ROOT / 'evidence'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def strings(p):
    pe = pefile.PE(str(p))
    raw = p.read_bytes()
    result = []
    for pattern, enc in [(rb'[\x20-\x7e]{5,}', 'ascii'), (rb'(?:[\x20-\x7e]\x00){5,}', 'utf-16le')]:
        for m in re.finditer(pattern, raw):
            try:
                va = pe.OPTIONAL_HEADER.ImageBase + pe.get_rva_from_offset(m.start())
            except (pefile.PEFormatError, TypeError):
                va = None
            result.append({'string': m.group().decode(enc), 'offset': m.start(), 'va': hex(va) if va else None, 'encoding': enc})
    return pe, result


def pe_info(p, label):
    pe, extracted = strings(p)
    (EVIDENCE / f'{label}.{p.name}.strings.json').write_text(json.dumps(extracted, indent=2), encoding='utf-8')
    info = {
        'path': str(p), 'size': p.stat().st_size, 'sha256': sha(p),
        'preferred_base': hex(pe.OPTIONAL_HEADER.ImageBase),
        'pe_timestamp_raw': pe.FILE_HEADER.TimeDateStamp,
        'pe_timestamp_utc': datetime.datetime.fromtimestamp(pe.FILE_HEADER.TimeDateStamp, datetime.timezone.utc).isoformat(),
        'sections': [{'name': s.Name.decode(errors='replace').strip('\0'), 'entropy': s.get_entropy(), 'raw_size': s.SizeOfRawData} for s in pe.sections],
        'imports': [{'dll': d.dll.decode(errors='replace'), 'symbols': [{'name': i.name.decode(errors='replace') if i.name else None, 'ordinal': i.ordinal, 'iat_va': hex(i.address)} for i in d.imports]} for d in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])],
        'exports': [{'name': e.name.decode(errors='replace') if e.name else None, 'ordinal': e.ordinal, 'va': hex(pe.OPTIONAL_HEADER.ImageBase+e.address)} for e in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', [])],
        'rtti_candidates': [s for s in extracted if re.search(r'ActRec|Intf|^T[A-Z]|\.\?AV', s['string'])],
        'resource_references': [s for s in extracted if re.search(r'\.(xml|cfg|txt)\b', s['string'], re.I)],
    }
    (EVIDENCE / f'{label}.{p.name}.pe.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    return info, extracted


def xml_shape(path):
    counts = collections.Counter()
    try:
        root = ET.parse(path).getroot()
        def walk(e, parent):
            here = parent + '/' + e.tag
            counts[here + ' [' + ','.join(sorted(e.attrib)) + ']'] += 1
            for c in e:
                walk(c, here)
        walk(root, '')
        return dict(sorted(counts.items()))
    except (ET.ParseError, ValueError) as exc:
        return {'parse_error': str(exc)}


def main():
    EVIDENCE.mkdir(exist_ok=True)
    ti = {p.relative_to(TI).as_posix().lower(): p for p in TI.rglob('*') if p.is_file()}
    azt = {p.relative_to(AZT).as_posix().lower(): p for p in AZT.rglob('*') if p.is_file()}
    rows = [{'path': str(p.relative_to(TI)), 'size': p.stat().st_size, 'sha256': sha(p)} for p in ti.values()]
    with (EVIDENCE / 'ti_files.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['path', 'size', 'sha256'])
        w.writeheader(); w.writerows(rows)
    with (EVIDENCE / 'azt_files.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['path', 'size'])
        w.writerows((str(p.relative_to(AZT)), p.stat().st_size) for p in azt.values())
    print('Inventory:', len(ti), 'TI files;', len(azt), 'AZT files', flush=True)
    infos = []
    all_strings = {'TI': collections.defaultdict(list), 'AZT': collections.defaultdict(list)}
    for label, directory, names in [('TI', TI, [p.name for p in TI.iterdir() if p.suffix.lower() in ('.exe', '.dll')]), ('AZT', AZT, ['client.exe','silver.dll','orange.dll','gold.dll'])]:
        for name in names:
            info, extracted = pe_info(directory/name, label)
            if label == 'TI': infos.append(info)
            for s in extracted:
                if re.search(r'Login|Server|Auth|Soldier|Character|Inventory|Ammunition|Equipment|Battle|Turn|Move|Attack|Damage|Death|Heal|Cover|Box|Container|Rucksack|Door|Repair|Upgrade|Clan|Alliance|SEND_|RECV_|NET|\.xml', s['string'], re.I):
                    all_strings[label][s['string']].append({'binary': name, 'va': s['va'], 'offset': s['offset'], 'encoding': s['encoding']})
    common = []
    hashes = {r['path'].replace('\\','/').lower(): r['sha256'] for r in rows}
    for path in sorted(ti.keys() & azt.keys()):
        other = sha(azt[path])
        common.append({'relative_path': path, 'ti_sha256': hashes[path], 'azt_sha256': other, 'identical': hashes[path] == other})
    (EVIDENCE/'common_files.json').write_text(json.dumps(common, indent=2), encoding='utf-8')
    genealogy = [{'string': s, 'TI': all_strings['TI'][s], 'AZT': all_strings['AZT'][s], 'confidence': 'CONFIRMED exact string match; semantics UNKNOWN'} for s in sorted(all_strings['TI'].keys() & all_strings['AZT'].keys())]
    (EVIDENCE/'string_genealogy.json').write_text(json.dumps(genealogy, indent=2), encoding='utf-8')
    shapes = {}
    for name in ['battlelog.xml','serverlist.cfg','cover_factors.xml','collisions.xml','ground.xml','denver.xml','mo.xml']:
        shapes[name] = {}
        for label, files in [('TI', ti),('AZT',azt)]:
            shapes[name][label] = [{'path': k, 'sha256': sha(p), 'structure': xml_shape(p) if p.suffix == '.xml' else 'config; see raw file'} for k,p in files.items() if p.name.lower() == name]
    (EVIDENCE/'resource_structures.json').write_text(json.dumps(shapes, indent=2), encoding='utf-8')
    lines = ['# Client file inventory', '', f'TI root: `{TI}`. AZT root: `{AZT}`.', '', f'Complete TI tree: **{len(rows)} files**, every size and SHA-256 in [ti_files.csv](evidence/ti_files.csv). AZT tree: **{len(azt)} files** in [azt_files.csv](evidence/azt_files.csv).', '', 'PE timestamps are header claims, not independently established release dates. Preferred VAs require relocation at runtime.', '', '| File | Bytes | SHA-256 | PE timestamp UTC |', '|---|---:|---|---|']
    for i in infos:
        name = Path(i['path']).name
        lines.append(f"| [{name} metadata](evidence/TI.{name}.pe.json) | {i['size']} | `{i['sha256']}` | {i['pe_timestamp_utc']} |")
    lines += ['', 'Each linked PE JSON includes imports, exports, sections, RTTI candidates and XML/config string references. Adjacent `.strings.json` includes ASCII and ASCII-range UTF-16LE strings with file offsets and preferred VAs; not a complete multilingual string decoder.', '', 'Roles: ti.exe = executable/UI host (CONFIRMED module loading); silver.dll = game/application parser (CONFIRMED export and dispatcher); orange.dll = transport callback implementation (STRONG, requires runtime inspection); gold.dll = small packet hook (CONFIRMED export, broader role UNKNOWN); ode.dll = physics candidate (LIKELY); d3dx9_26.dll = D3D helper (STRONG imports); updater/launchers = names only (LIKELY).', '', 'Source-file search for .pas/.dpr/.c/.cpp/.h/.cs/.py/.pdb/.map returned no files. These client directories contain binaries/resources; source code is not yet available.']
    (ROOT/'FILE_INVENTORY.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Shared paths:', len(common), 'identical:', sum(r['identical'] for r in common), 'shared strings:', len(genealogy), flush=True)


if __name__ == '__main__':
    main()
