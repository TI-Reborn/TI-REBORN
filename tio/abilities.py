"""Source-backed legacy ability definitions; absent parameters stay unknown.

This catalog does not grant skills, infer learning prices or apply combat effects.
The legacy CFG is distinct from the current client's skills.xml format.
"""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class AbilityLevel:
    ability_id: int
    level: int | None
    fields: dict[str, str]

    @property
    def name(self):
        return self.fields['name']

    def number(self, key):
        value=self.fields.get(key)
        return None if value is None else int(value)


class AbilityCatalog:
    def __init__(self, records):
        self.records=tuple(records)
        self.by_key={}
        for record in self.records:
            key=(record.ability_id,record.level)
            if key in self.by_key:raise ValueError('Duplicate ability level')
            if record.ability_id<0 or (record.level is not None and record.level<1):
                raise ValueError('Invalid ability ID or level')
            levels=record.number('levels')
            if levels is not None and record.level is not None and record.level>levels:
                raise ValueError('Ability level exceeds declared maximum')
            self.by_key[key]=record

    @classmethod
    def from_cfg(cls,path):
        text=Path(path).read_text(encoding='cp1251')
        records=[]
        for match in re.finditer(r'Perk\s+(\d+):[^\r\n]*\s*\{([^}]*)\}',text):
            fields={}
            for line in match[2].splitlines():
                if '=' not in line:continue
                key,value=line.strip().split('=',1)
                if key in fields:raise ValueError('Duplicate ability field')
                fields[key]=value
            if int(fields['id'])!=int(match[1]):raise ValueError('Ability header ID mismatch')
            records.append(AbilityLevel(int(fields['id']),int(fields['level']) if 'level' in fields else None,fields))
        if not records:raise ValueError('No ability records')
        return cls(records)

    def get(self,ability_id,level):
        # A record without a level is not silently copied to every declared level.
        return self.by_key[(ability_id,level)]
