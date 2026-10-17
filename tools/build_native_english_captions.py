"""Prepare bounded in-memory English captions for reviewed published DLLs.

Only authored UI string buffers change. Original keyboard mappings, profanity
filters, internal scope identifiers, instructions and authentication stay intact.
"""
from pathlib import Path
import argparse,hashlib,json,struct
import pefile

ROOT=Path(__file__).resolve().parents[1]
CAPTIONS={
    'Принять':('Accept',4,None),
    'нет данных':('No data',12,None),
    'Склад:':('Depot:',12,None),
    'Экран':('Screen',12,32),
    'Не удалось изменить экран. Сохранены прежние настройки.':('Could not change display. Settings kept.',12,None),
    'Интерфейс:':('Interface:',4,None),
    'Доступный масштаб зависит от разрешения':('Available scale depends on resolution',4,None),
    'Боец: мышь — поворот, ПКМ — закрыть':('Drag to rotate; RMB to close',4,None),
    'Онлайн':('Online',12,None),
}

def plan(source):
    raw=source.read_bytes();pe=pefile.PE(data=raw);patches=[]
    for text,(translated,header,capacity) in CAPTIONS.items():
        original=text.encode('utf-16-le');new=translated.encode('utf-16-le');at=0;count=0
        while (at:=raw.find(original,at))>=0:
            count+=1;start=at-header;size=capacity or header+len(original)+2
            before=raw[start:start+size];declared=struct.unpack_from('<I',before,header-4)[0]
            if declared!=(len(text) if header==12 else len(original)):raise ValueError('Unexpected native string header')
            if header+len(new)+2>size:raise ValueError('Translation exceeds native allocation')
            after=bytearray(before);struct.pack_into('<I',after,header-4,len(translated) if header==12 else len(new))
            after[header:]= (new+b'\0\0').ljust(size-header,b'\0')
            patches.append(dict(rva=pe.get_rva_from_offset(start),expected=before.hex(),replacement=after.hex(),source=text,english=translated))
            at+=len(original)
        if count==0:raise ValueError('Published caption missing: '+text)
    return dict(sha256=hashlib.sha256(raw).hexdigest(),patches=patches)

def build(images):
    result=[plan(source) for source in images]
    if len({item['sha256'] for item in result})!=len(result):raise ValueError('Duplicate native image')
    (ROOT/'launcher/Assets/native-english.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Prepared',len(result),'SHA-pinned images:',[len(item['patches']) for item in result],'bounded captions; DLL files unchanged')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,action='append',required=True,help='Reviewed DLL; repeat for each supported release')
    build(parser.parse_args().image)
