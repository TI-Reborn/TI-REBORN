"""Offline translations for built-in messages, selected per receiving session.

Player chat, names, clan names and saves never pass through this translator.
Packets retain canonical Russian text until their recipient's cipher sends them.
"""
import json
from functools import lru_cache
from pathlib import Path
import re

@lru_cache(maxsize=1)
def raw_catalog():
    return json.loads((Path(__file__).resolve().parents[1]/'config/english_translations.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def catalog():
    return {k:v for k,v in raw_catalog().items() if isinstance(v,str)}

@lru_cache(maxsize=1)
def templates():
    result=[]
    for source,target in catalog().items():
        tokens=list(re.finditer(r'\{[^{}]+\}|%s|%d',source))
        if not tokens:continue
        parts=[];last=0
        for token in tokens:
            parts.extend((re.escape(source[last:token.start()]),'(.*?)'));last=token.end()
        parts.append(re.escape(source[last:]))
        result.append((re.compile(''.join(parts),re.S),target,tokens,raw_catalog().get('__template_fields__',{}).get(source,[])))
    return sorted(result,key=lambda x:len(x[0].pattern),reverse=True)

def english(text):
    if not re.search('[А-Яа-яЁё]',text):return text
    if text in catalog():return catalog()[text]
    if text.startswith('[Контракты] '):return '[Contracts] '+english(text[len('[Контракты] '):])
    if text.startswith('Банк: '):return 'Bank: '+english(text[len('Банк: '):])
    for pattern,target,tokens,fields in templates():
        match=pattern.fullmatch(text)
        if match:
            # Captured strings are opaque: a Cyrillic player name stays intact.
            pieces=[];last=0
            translated_tokens=list(re.finditer(r'\{[^{}]+\}|%s|%d',target))
            if len(translated_tokens)!=len(tokens):continue
            for i,token in enumerate(translated_tokens):
                value=match.group(i+1)
                pieces.extend((target[last:token.start()],english(value) if i in fields else value));last=token.end()
            pieces.append(target[last:]);return ''.join(pieces)
    return text

class LocalizedPacket(bytes):
    def __new__(cls,raw,render):
        instance=super().__new__(cls,raw);instance.render=render;return instance

def for_language(packet,language):
    if language=='english' and isinstance(packet,LocalizedPacket):return packet.render()
    return packet
