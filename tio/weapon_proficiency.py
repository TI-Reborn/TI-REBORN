"""Native damage factor, with explicitly provisional configurable training rules."""
from dataclasses import replace
import json
import math
from pathlib import Path
import struct
from .protocol.pet_info import decode_pet_info, encode_pet_info

NAMES=('Melee','Light','Heavy','Distance','Automatic','Throwing','Medical','Engineering')
SAVED=('0x8c4879','0x8c48a1','0x8c48c9','0x8c48f1','0x8c4919','0x8c4941','0x8c4969','0x8c4991')
BASE=('0x8c488d','0x8c48b5','0x8c48dd','0x8c4905','0x8c492d','0x8c4955','0x8c497d','0x8c49a5')
CAPS=('0x8c49b9','0x8c49cd','0x8c49e1')
HUMAN_SKILLS=(0,1,2,3,4,5,7)
BATTLE_SAVED=('0x8c54cc','0x8c54f6','0x8c5520','0x8c554a','0x8c5574','0x8c559e','0x8c55c8','0x8c55f2')
BATTLE_BASE=('0x8c54e1','0x8c550b','0x8c5535','0x8c555f','0x8c5589','0x8c55b3','0x8c55dd','0x8c5607')

def battle_fields(packet,human):
    f=decode_pet_info(packet,human_equipment=human).fields
    return {k:f[v] for k,v in zip((*BATTLE_SAVED,*BATTLE_BASE,'0x8c561c','0x8c5631','0x8c5646'),(*SAVED,*BASE,*CAPS))}

def number(bits):
    value=struct.unpack('<f',struct.pack('<I',bits))[0]
    if not math.isfinite(value) or value<0:raise ValueError('Invalid weapon proficiency')
    return value

def bits(value):
    return struct.unpack('<I',struct.pack('<f',value))[0]

class ProficiencyRules:
    def __init__(self,path=None):
        self.config=json.loads(Path(path or Path(__file__).resolve().parents[1]/'config/weapon_proficiency.json').read_text())
        c=self.config
        for k in ('maximum','initial','level_one_cap','cap_per_level','human_level_one_total','total_per_level','hit_gain_per_ap','miss_multiplier'):
            if not isinstance(c[k],(int,float)) or not math.isfinite(c[k]) or c[k]<=0:raise ValueError('Invalid proficiency policy')
        if c['maximum']!=200 or not c['initial']<=c['level_one_cap']<=200 or c['miss_multiplier']>=1:
            raise ValueError('Invalid proficiency limits')
        if c['human_level_one_total']<=7*c['initial']:raise ValueError('No initial training headroom')

    def caps(self,level,human):
        level=max(1,int(level));c=self.config
        single=min(200,c['level_one_cap']+(level-1)*c['cap_per_level'])
        total=min(1400,c['human_level_one_total']+(level-1)*c['total_per_level']) if human else single
        return int(single),int(total)

    def normalize(self,packet,human):
        pet=decode_pet_info(packet,human_equipment=human);f=dict(pet.fields)
        values=[number(f[k]) for k in SAVED]
        # Only the known all-10 / zero-cap diagnostic profile is initialized.
        # Existing non-diagnostic progress is retained, including fractional values.
        legacy=all(v==10 for v in values) and all(f[k]==0 for k in CAPS)
        for i in range(8):
            value=self.config['initial'] if legacy and i in (HUMAN_SKILLS if human else (0,)) else 0 if legacy else values[i]
            f[SAVED[i]]=bits(min(200,value))
            f[BASE[i]]=f[SAVED[i]]
        cap,total=self.caps(f['0x8c4aef'],human)
        f.update(dict(zip(CAPS,(cap,total,cap))))
        return encode_pet_info(replace(pet,fields=f))

    def value(self,packet,human,weapon_type):
        if weapon_type not in NAMES:raise ValueError('Unknown weapon proficiency category')
        f=decode_pet_info(packet,human_equipment=human).fields
        index=NAMES.index(weapon_type)
        if not human and index!=0:raise ValueError('Dogs train melee only')
        return min(number(f[SAVED[index]]),self.caps(f['0x8c4aef'],human)[0])

    def train(self,packet,human,weapon_type,ap,hit,*,multiplier=1):
        if not math.isfinite(ap) or ap<=0:raise ValueError('Invalid training AP')
        pet=decode_pet_info(packet,human_equipment=human);f=dict(pet.fields)
        index=NAMES.index(weapon_type)
        if index not in (HUMAN_SKILLS if human else (0,)):raise ValueError('Unsupported trained skill')
        current=number(f[SAVED[index]])
        cap,total=self.caps(f['0x8c4aef'],human)
        used=sum(number(f[SAVED[i]]) for i in (HUMAN_SKILLS if human else (0,)))
        c=self.config
        gain=ap*c['hit_gain_per_ap']*c['initial']/max(c['initial'],current)*(1 if hit else c['miss_multiplier'])
        if multiplier not in (1,1.5):raise ValueError('Invalid premium skill multiplier')
        gain*=multiplier
        gain=max(0,min(gain,cap-current,total-used,200-current))
        f[SAVED[index]]=bits(current+gain);f[BASE[index]]=f[SAVED[index]]
        return encode_pet_info(replace(pet,fields=f))

def damage_endpoint(raw,skill):
    """Native positive integer conversion truncates the scaled endpoint."""
    if raw<0 or not math.isfinite(skill) or not 0<=skill<=200:raise ValueError('Invalid damage proficiency')
    return int(int(raw)*(67+skill)/120)

def skill_signature(packet,human):
    f=decode_pet_info(packet,human_equipment=human).fields
    return tuple(f[k] for k in (*SAVED,*BASE,*CAPS,'0x8c4aef'))
