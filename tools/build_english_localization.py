"""Build an offline English resource pack from the inspected hosted client.

Existing original English translations take priority. The optional --translate
step sends only built-in game text to Google's public translation endpoint;
runtime clients never contact a translation service. Placeholder identities are
checked before any translated resource is emitted.
"""
from pathlib import Path
import argparse, ast, concurrent.futures, json, re, time
import urllib.parse, urllib.request
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/english-localization'
ASSETS = ROOT / 'assets/english-localization'
CYR = re.compile('[А-Яа-яЁё]')
TOKENS = re.compile(r'%%|%(?:\d+\$)?[-+0#]*\d*(?:\.\d+)?[sdiufgxX]|@[A-Za-z0-9_]+@|\{[^{}]+\}|\\[nr]')
CS_LEX = re.compile(r'//[^\r\n]*|/\*.*?\*/|@"(?:[^"]|"")*"|\$?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'',re.S)

def language(raw, encoding):
    return dict(line.split('=', 1) for line in raw.decode(encoding).splitlines() if '=' in line)

def python_templates(tree):
    result={}
    def form(node):
        values=[]
        def part(n):
            if isinstance(n,ast.Constant) and isinstance(n.value,str):return n.value
            if isinstance(n,ast.JoinedStr):return ''.join(part(v.value) if isinstance(v,ast.FormattedValue) else part(v) for v in n.values)
            if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Add):return part(n.left)+part(n.right)
            index=len(values);values.append(ast.unparse(n));return '{'+str(index)+'}'
        text=part(node)
        # Only known server-owned status dictionaries can translate interpolated
        # values. Names and user text remain opaque even if they match UI words.
        flags=[i for i,value in enumerate(values) if value.startswith(('labels[','PARTY_STATES[','CONTRACT_STATES['))]
        return text,flags
    for node in ast.walk(tree):
        if isinstance(node,ast.JoinedStr) or isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
            text,flags=form(node)
            if CYR.search(text):result[text]=flags
    return result

def source_templates():
    result=set()
    for folder in ('tio','server'):
        paths=list((ROOT/folder).rglob('*.py'))
        if (REPORT/'server-baseline'/folder).exists():paths+=list((REPORT/'server-baseline'/folder).rglob('*.py'))
        if folder=='server': paths.append(ROOT/'tools/loopback_exchange.py')
        for p in paths:
            tree=ast.parse(p.read_text(encoding='utf-8-sig'))
            result.update(python_templates(tree))
            fragments=set()
            for n in ast.walk(tree):
                if isinstance(n, ast.JoinedStr):
                    text='';i=0
                    for v in n.values:
                        if isinstance(v,ast.Constant):text+=v.value;fragments.add(id(v))
                        else:text+='{'+str(i)+'}';i+=1
                    if CYR.search(text):result.add(text)
            docstrings={id(n.body[0].value) for n in ast.walk(tree) if isinstance(n,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n,ast.Constant) and isinstance(n.value,str) and id(n) not in fragments|docstrings and CYR.search(n.value):result.add(n.value)
    def collect(x):
        if isinstance(x,str) and CYR.search(x):result.add(x)
        elif isinstance(x,dict):
            for v in x.values():collect(v)
        elif isinstance(x,list):
            for v in x:collect(v)
    for p in (ROOT/'config').glob('*.json'):collect(json.loads(p.read_text(encoding='utf-8-sig')))
    # Translation of launcher messages includes interpolation templates.
    for p in (ROOT/'launcher').glob('*.cs'):
        for literal in CS_LEX.finditer(p.read_text(encoding='utf-8-sig')):
            value=literal.group()
            if not value.startswith(('"','$"','@"')):continue
            s=value[2:-1] if value.startswith(('$"','@"')) else value[1:-1]
            if CYR.search(s):
                try:result.add(json.loads('"'+s+'"'))
                except ValueError:pass
    return {value for value in result if '[A-Za-zА-Я' not in value}

def template_fields():
    result={}
    for root in (ROOT,REPORT/'server-baseline'):
        for folder in ('server','tio'):
            for p in (root/folder).rglob('*.py'):
                for text,flags in python_templates(ast.parse(p.read_text(encoding='utf-8-sig'))).items():
                    if flags:result[text]=flags
    return result

def required_text():
    base=REPORT/'baseline/base'
    ru=language((base/'russian.lng').read_bytes(),'cp1251')
    en=language((base/'english.lng').read_bytes(),'latin1')
    needed={v for k,v in ru.items() if (k not in en or not en[k].strip()) and CYR.search(v)}
    needed.update(source_templates())
    needed.update(v for k,v in ru.items() if k in en and TOKENS.findall(v)!=TOKENS.findall(en[k]) and CYR.search(v))
    for name in ('rules.txt','help.txt'):
        raw=(base/name).read_text(encoding='cp1251')
        needed.update(line for line in raw.splitlines() if CYR.search(line))
    for name in ('battlelog.xml','quest/00000.xml','quest/tut_1000.xml'):
        root=ET.fromstring((base/name).read_bytes())
        for node in root.iter():
            needed.update(v for v in node.attrib.values() if CYR.search(v))
            if node.text and CYR.search(node.text):needed.add(node.text)
    return needed

def translate_batch(values):
    protected=[];tokens=[]
    for i,value in enumerate(values):
        captured=[]
        def mask(m):
            captured.append(m.group());return 'ZXPH'+str(len(captured)-1)+'ZX'
        text=TOKENS.sub(mask,value)
        # Game terminology, rather than financial credit/loan translations.
        text=re.sub(r'кредит(?:ов|ами|ам|ы|а|у|е)?\b','credits',text,flags=re.I)
        text=re.sub(r'на[её]мник(?:ов|ами|ам|и|а|у|е)?\b','mercenary',text,flags=re.I)
        text=re.sub(r'\bОД\b','AP',text)
        protected.append(f'ZXROW{i}ZX: '+text.replace('\n',' ZXNEWLINEZX '));tokens.append(captured)
    query='\n'.join(protected)
    url='https://translate.googleapis.com/translate_a/single?'+urllib.parse.urlencode(dict(client='gtx',sl='ru',tl='en',dt='t',q=query))
    for attempt in range(2):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            data=json.loads(urllib.request.urlopen(request,timeout=35).read())
            output=''.join(x[0] or '' for x in data[0]);parts=re.split(r'ZXROW\s*(\d+)\s*ZX\s*:\s*',output,flags=re.I)
            found={int(parts[i]):parts[i+1].strip() for i in range(1,len(parts),2)}
            if set(found)!=set(range(len(values))):raise ValueError('Batch row markers changed')
            result={}
            for i,value in enumerate(values):
                translated=found[i].replace('ZXNEWLINEZX','\n')
                for j,t in enumerate(tokens[i]):
                    marker='ZXPH'+str(j)+'ZX'
                    if translated.count(marker)!=1:raise ValueError('Translation changed placeholder')
                    translated=translated.replace(marker,t)
                if CYR.search(translated) or TOKENS.findall(translated)!=TOKENS.findall(value):raise ValueError('Translation residue or placeholder mismatch: '+repr(value)+' => '+repr(translated))
                translated=translated.replace('freak miner','miner')
                result[value]=translated
            return result
        except Exception:
            if attempt==1:
                if len(values)>1:
                    middle=len(values)//2;return translate_batch(values[:middle])|translate_batch(values[middle:])
                raise
            time.sleep(1+attempt)

def translate_missing():
    ASSETS.mkdir(parents=True,exist_ok=True);cache=ASSETS/'translations.json'
    translations=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    pending=sorted(required_text()-translations.keys());batches=[];current=[];size=0
    for value in pending:
        if current and (size+len(value)>2600 or len(current)>=22):batches.append(current);current=[];size=0
        current.append(value);size+=len(value)
    if current:batches.append(current)
    print('Translating',len(pending),'built-in strings in',len(batches),'batches',flush=True)
    errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(translate_batch,b):b for b in batches}
        for i,future in enumerate(concurrent.futures.as_completed(futures)):
            try:translations.update(future.result())
            except Exception as error:errors.append(str(error));print(str(error),flush=True)
            cache.write_text(json.dumps(translations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('Cached batch',i+1,'/',len(batches),flush=True)
    if errors: (REPORT/'translation-errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')

def build():
    translations=json.loads((ASSETS/'translations.json').read_text(encoding='utf-8'))
    import unicodedata
    def native_text(value):
        value=value.replace('\u200b','').replace('≥','>=').replace('≤','<=')
        result=[]
        for char in value:
            try:char.encode('cp1251');result.append(char)
            except UnicodeEncodeError:result.append(unicodedata.normalize('NFKD',char).encode('ascii','ignore').decode())
        return ''.join(result)
    translations={k:native_text(v) for k,v in translations.items()}
    missing=required_text()-translations.keys()
    if missing:raise ValueError(f'{len(missing)} untranslated source strings')
    base=REPORT/'baseline/base';ru=language((base/'russian.lng').read_bytes(),'cp1251');en=language((base/'english.lng').read_bytes(),'latin1')
    final={k: en[k] if k in en and en[k].strip() else translations.get(v,v) for k,v in ru.items()}
    final.update({k:v for k,v in en.items() if k not in final})
    # Later native additions use these exact localized keys.
    final.update({'m99N':'Loading','m950':'Mercenary','m1028':'Miner','an60':'Recruit','lg03':'Bronze League','lg02':'Silver League','lg01':'Gold League','lg00':'Platinum League'})
    for k,v in final.items():
        if CYR.search(v):raise ValueError('Cyrillic in '+k)
        if k in ru and TOKENS.findall(v)!=TOKENS.findall(ru[k]):
            # Original English has a few incompatible old placeholders.
            if CYR.search(ru[k]) and ru[k] in translations:v=final[k]=translations[ru[k]]
            else:raise ValueError('Placeholder mismatch '+k)
    runtime=ASSETS/'runtime/base';runtime.mkdir(parents=True,exist_ok=True)
    import unicodedata
    for k,v in final.items():
        v=v.replace('\x81',' ').replace('\x96','-').replace('\x97','-').replace('\x92',"'").replace('\xa0',' ')
        try:v.encode('cp1251')
        except UnicodeEncodeError:v=unicodedata.normalize('NFKD',v).encode('ascii','ignore').decode()
        final[k]=v
    (runtime/'english.lng').write_bytes(('[language]\r\n'+'\r\n'.join(k+'='+v for k,v in final.items())+'\r\n').encode('cp1251',errors='strict'))
    # Preserve the XML structure/attributes. Existing rus tags are the native
    # schema; the per-language launcher overlay selects the entire resource.
    for name in ('battlelog.xml','quest/00000.xml','quest/tut_1000.xml'):
        encoding='utf-8-sig' if (base/name).read_bytes().startswith(b'\xef\xbb\xbf') else 'cp1251'
        text=(base/name).read_text(encoding=encoding)
        text=re.sub(r'<!--.*?-->','',text,flags=re.S)
        def attrs(m):
            quote,value=m.group(1),m.group(2)
            if not CYR.search(value):return m.group()
            decoded=value.replace('&quot;','"').replace('&amp;','&').replace('&lt;','<').replace('&gt;','>')
            new=translations[decoded].replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;')
            return quote+new+quote
        text=re.sub(r'([\"])([^\"]*)\1',attrs,text)
        def content(m):
            value=m.group(1)
            return '>'+translations.get(value,value)+'<'
        text=re.sub(r'>([^<>]+)<',content,text)
        target=runtime/name;target.parent.mkdir(parents=True,exist_ok=True);raw=text.encode(encoding);ET.fromstring(raw);target.write_bytes(raw)
    builtins=source_templates()
    server_text={k:v for k,v in translations.items() if k in builtins}
    server_text['__template_fields__']=template_fields()
    (ROOT/'config/english_translations.json').write_text(json.dumps(server_text,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ('rules.txt','help.txt'):
        text=(base/name).read_text(encoding='cp1251')
        (runtime/name).write_bytes(('\r\n'.join(translations.get(line,line) for line in text.splitlines())+'\r\n').encode('cp1251'))
    # The updater installs both overlays. The launcher selects one immediately
    # before startup, after integrity verification of the canonical resources.
    for locale in ('ru','en'):
        for name in ('battlelog.xml','quest/00000.xml','quest/tut_1000.xml','rules.txt','help.txt'):
            target=runtime/'locales'/locale/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((base/name if locale=='ru' else runtime/name).read_bytes())
    launcher_sources=builtins
    (ROOT/'launcher/Assets/english.json').write_text(json.dumps({k:v for k,v in translations.items() if k in launcher_sources},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Built',len(final),'language keys; missing originals filled:',len(ru.keys()-en.keys()))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--translate',action='store_true');p.add_argument('--build',action='store_true');a=p.parse_args()
    if a.translate:translate_missing()
    if a.build:build()
