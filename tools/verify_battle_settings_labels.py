"""Verify original room-info label/field bindings against the pinned client.

Static branch-table and instruction checks; no UI execution or create mapping.
"""
from verify_auth_native import *

if __name__ == '__main__':
    u = emulator()  # verifies binary hash
    labels = (0x81f31d,0x81f344,0x81f36b,0x81f392,0x81f3b9,0x81f3dd,0x81f401,0x81f425)
    values = (0x81de9b,0x81ded0,0x81df2b,0x81df6b,0x81dfab,0x81dfeb,0x81e02b,0x81e08c)
    keys = ('mn55','mn44','mn93','mn08','mn94','mn61','m216','m618')
    offsets = (0x24,0x19,0x20,0x01,0x1c,0x14,0x28,0x2c)
    meanings = ('owner_name','mode','map_size','players_count','soldiers_count','turn_seconds','exit_zone','stake')
    patterns = ('8b5224','0fb64019','0fb64020','0fb64001','0fb6401c','0fb74014','0fb64028','8b402c')
    language = Path(r'C:\Program Files (x86)\TIOnline\base\russian.lng').read_text(encoding='cp1251')
    translations = dict(line.split('=',1) for line in language.splitlines() if '=' in line)
    records = []
    for i, (label, value, key, offset, meaning, pattern) in enumerate(zip(labels,values,keys,offsets,meanings,patterns)):
        assert get32(u,0x81f2fd+i*4) == label
        assert get32(u,0x81de7b+i*4) == value
        string_va = 0x81f710+i*0x18
        assert bytes(u.mem_read(label,16)).find(b'\xb8'+struct.pack('<I',string_va)) >= 0
        assert bytes(u.mem_read(string_va,len(key)*2+2)).decode('utf-16le').rstrip('\0') == key
        assert bytes.fromhex(pattern) in bytes(u.mem_read(value,40))
        records.append({'tag':i,'label_key':key,'label':translations[key],
                        'settings_offset':hex(offset),'meaning':meaning})
    (ROOT/'evidence/battle_settings_labels.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'bindings':records},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('BattleSettings: 8 original room-info label/field bindings PASS')
