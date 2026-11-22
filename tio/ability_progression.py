"""Authoritative native90 forgetting and native console skill decreases.

The manual specifies decreasing5/1000; forgetting cost/removal scope are
explicit policy. Every mutation is city-only at the session routing boundary
and uses one transaction for wallet, base profile and learned-state revision.
"""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path

from .ability_learning import AbilityLearning
from .db_transaction import transaction
from .protocol.abilities import (encode_abilities,decode_abilities,encode_skill_tree,
                                decode_ability_request)
from .protocol.asset_count import encode_asset_count
from .protocol.binary import Reader
from .protocol.pet_info import decode_pet_info,encode_pet_info
from .wallets import WalletStore


@lru_cache(maxsize=1)
def policy():
    value=json.loads((Path(__file__).resolve().parents[1]/'config/roster_progression.json').read_text(encoding='utf-8'))
    if (value.get('schema')!=1 or value.get('skill_decrease')!=5 or value.get('skill_decrease_credits')!=1000
            or value.get('forgetting_mode')!='all_ranks' or value.get('minimum_saved_skill')!=0):
        raise ValueError('Unsupported roster progression policy')
    if type(value.get('forgetting_credits_per_rank')) is not int or not 1<=value['forgetting_credits_per_rank']<=0xffffffff//255:
        raise ValueError('Invalid forgetting price policy')
    if (value.get('base_roster_capacity')!=7 or value.get('extra_starter_mercenaries')!=2
            or value.get('starter_resources')!=[1,2]
            or value.get('hire_credits')!={'1':500,'2':500,'3':2500,'4':2500,'5':2500,'6':3500}):
        raise ValueError('Invalid documented recruitment policy')
    expansion = value.get('roster_expansion')
    if not isinstance(expansion, list) or not 1 <= len(expansion) <= 255 or any(
            not isinstance(tier, list) or len(tier) != 2
            or type(tier[0]) is not int or tier[0] != bonus
            or type(tier[1]) is not int or not 1 <= tier[1] <= 0xffffffff
            for bonus, tier in enumerate(expansion, 1)):
        raise ValueError('Invalid roster expansion policy')
    return value


class AbilityProgression(AbilityLearning):
    def __init__(self,path,catalog,learning_policy):
        super().__init__(path,catalog,learning_policy)
        self.forget_offers={}

    @staticmethod
    def forgetting_price(rank):return rank*policy()['forgetting_credits_per_rank']

    def _lists(self,db,account,owner):
        revision,learned,available=super()._lists(db,account,owner)
        learned=tuple(replace(e,unknown_u32=self.forgetting_price(e.level)) for e in learned)
        return revision,learned,available

    def _tree(self,db,account,owner,learned):
        packet=super()._tree(db,account,owner,learned)
        current={e.ability_id:e.level for e in learned}
        r=Reader(packet);r.u8();identity=r.u32();rows=[]
        for _ in range(r.u16()):
            ability,rank,known,required,learn,forget=r.u32(),r.u8(),r.u8(),r.u8(),r.u32(),r.u32()
            rows.append((ability,rank,known,required,learn,self.forgetting_price(current[ability]) if known else 0))
        r.finish();return encode_skill_tree(identity,rows)

    def _quote(self,account,owner,revision,learned,available):
        self.offers[(account,owner)]=(revision,{e.ability_id:e for e in available})
        self.forget_offers[(account,owner)]=(revision,{e.ability_id:e for e in learned})

    def tree(self,account,owner):
        with transaction(self.path) as db:
            revision,learned,available=self._lists(db,account,owner)
            packet=self._tree(db,account,owner,learned)
        self._quote(account,owner,revision,learned,available)
        return packet

    def lists(self,account,owner,*,offer=True):
        with transaction(self.path) as db:
            revision,learned,available=self._lists(db,account,owner)
            replies=(encode_abilities(owner,learned),encode_abilities(owner,available,for_learning=True))
        if offer:self._quote(account,owner,revision,learned,available)
        return replies

    def learn(self,account,owner,ability):
        # Existing learning policy and atomic write remain the source of truth.
        replies=super().learn(account,owner,ability)
        identity,learned,_=decode_abilities(replies[0])
        learned=tuple(replace(e,unknown_u32=self.forgetting_price(e.level)) for e in learned)
        revision=self.offers[(account,owner)][0]
        self.forget_offers[(account,owner)]=(revision,{e.ability_id:e for e in learned})
        return (encode_abilities(identity,learned),*replies[1:])

    def forget(self,account,owner,ability):
        quote=self.forget_offers.get((account,owner))
        if quote is None or ability not in quote[1]:raise ValueError('Обновите список перков перед забыванием')
        expected,offers=quote;selected=offers[ability]
        with transaction(self.path) as db:
            revision,learned,available=self._lists(db,account,owner)
            if revision!=expected or selected not in learned:raise ValueError('Предложение забывания устарело')
            if ability not in self._allowed(db,account,owner):raise ValueError('Недоступный перк')
            remaining=tuple(e for e in learned if e.ability_id!=ability)
            packet=encode_abilities(owner,remaining)
            if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',
                          (selected.unknown_u32,account,selected.unknown_u32)).rowcount!=1:
                raise ValueError('Недостаточно кредитов для забывания перка')
            if db.execute('UPDATE ability_states SET revision=?,packet=? WHERE account=? AND pet_id=? AND revision=?',
                          (revision+1,packet,account,owner,revision)).rowcount!=1:
                raise ValueError('Предложение забывания устарело')
            # Current HP can include a learned health bonus. Losing that bonus
            # clamps HP to the new maximum and never heals or revives a fighter.
            human,base=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
            from .passive_stats import project_saved_pet
            projected=decode_pet_info(project_saved_pet(db,account,owner,base,bool(human)),human_equipment=bool(human))
            saved=decode_pet_info(base,human_equipment=bool(human))
            health=min(saved.fields['0x8c4ab1'],projected.fields['0x8c4a07'])
            if health!=saved.fields['0x8c4ab1']:
                base=encode_pet_info(replace(saved,fields={**saved.fields,'0x8c4ab1':health}))
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(base,account,owner))
            _,remaining,available=self._lists(db,account,owner)
            replies=(encode_abilities(owner,remaining),self._tree(db,account,owner,remaining),
                     encode_asset_count(WalletStore(self.path).ensure(account)),
                     project_saved_pet(db,account,owner,base,bool(human)))
        self._quote(account,owner,revision+1,remaining,available)
        return replies

    def handle(self,account,packet):
        if packet[:2]==b'\xc8\x12':
            r=Reader(packet);r.u8();r.u8();owner=r.u32();r.finish()
            return (self.lists(account,owner)[0],)
        if packet[:1] not in (b'\xa9',):
            owner,ability,opcode=decode_ability_request(packet)
            if opcode==0x90:return self.forget(account,owner,ability)
        return super().handle(account,packet)


def decrease(path,account,packet,*,allowed=True):
    from .protocol.proficiency_decrease import decode_proficiency_decrease,SKILLS
    from .weapon_proficiency import ProficiencyRules,SAVED,BASE,HUMAN_SKILLS,number,bits
    request=decode_proficiency_decrease(packet)
    if not allowed:raise ValueError('Снижение навыков доступно в городе вне очереди и боя')
    limits=policy();index=SKILLS[request.skill]
    with transaction(path) as db:
        matches=[]
        for identity,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(account,)):
            pet=decode_pet_info(raw,human_equipment=bool(human))
            if pet.fields['0x8c4489'].decode('cp1251').casefold()==request.mercenary_name.casefold():
                matches.append((identity,bool(human),raw))
        if len(matches)!=1:raise ValueError('Имя бойца не найдено или неоднозначно')
        identity,human,raw=matches[0]
        if index not in (HUMAN_SKILLS if human else (0,)):raise ValueError('Недоступный навык этого бойца')
        pet=decode_pet_info(ProficiencyRules().normalize(raw,human),human_equipment=human)
        value=number(pet.fields[SAVED[index]])
        if value<limits['skill_decrease']+limits['minimum_saved_skill']:
            raise ValueError('Навык нельзя уменьшить ещё на5')
        fields={**pet.fields,SAVED[index]:bits(value-limits['skill_decrease']),BASE[index]:bits(value-limits['skill_decrease'])}
        changed=encode_pet_info(replace(pet,fields=fields))
        if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',
                      (limits['skill_decrease_credits'],account,limits['skill_decrease_credits'])).rowcount!=1:
            raise ValueError('Недостаточно кредитов для снижения навыка')
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(changed,account,identity))
        from .passive_stats import project_saved_pet
        replies=(project_saved_pet(db,account,identity,changed,human),encode_asset_count(WalletStore(path).ensure(account)))
    return replies
