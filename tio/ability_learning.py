"""Atomic learning with explicit price policies and derived passive stats.

Miner effects use documented sources; rank gates and prices include explicit
user overrides. Battle effects are configured from saved ranks on scene entry.
"""

from .db_transaction import connect
import json,sqlite3
from contextlib import closing
from .abilities import AbilityCatalog,AbilityLevel
from .ability_state import AbilityStateStore
from .wallets import WalletStore
from .protocol.abilities import AbilityEntry,encode_abilities,decode_ability_request,encode_skill_tree
from .protocol.asset_count import AssetCount,encode_asset_count
from .protocol.pet_info import decode_pet_info
from .protocol.binary import Reader


class AbilityLearning:
    def __init__(self,path,catalog,policy):
        self.path=path;self.catalog=catalog;self.policy=policy
        self.price=policy['price_credits_per_level']
        if type(self.price) is not int or not 0<self.price<=0xffffffff:raise ValueError('Invalid learning price')
        for key in ('human_skills','dog_skills','miner_skills'):
            ids=policy.get(key,())
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate learning rule')
            for ability in ids:
                rows=[r for r in catalog.records if r.ability_id==ability]
                maximum=catalog.get(ability,1).number('levels')
                if sorted(r.level for r in rows)!=list(range(1,maximum+1)) or any(r.number('value') is None for r in rows):
                    raise ValueError('Incomplete learning definition')
        self.state=AbilityStateStore(path,catalog);WalletStore(path)
        self.offers={}

    @classmethod
    def from_workspace(cls,path,root):
        data=json.loads((root/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in data['records'])
        from .miner_abilities import catalog_for_play
        from .dog_abilities import catalog_for_play as dog_catalog
        return cls(path,dog_catalog(catalog_for_play(catalog)),json.loads((root/'config/ability_learning.json').read_text()))

    def _allowed(self,db,account,owner):
        self.state._owned(db,account,owner)
        human,packet=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        resource=decode_pet_info(packet,human_equipment=bool(human)).fields['0x8c446f']
        if human and resource in (1,2):return self.policy['human_skills']
        if not human and resource in (3,4,5):return self.policy['dog_skills']
        if human and resource==6:return self.policy.get('miner_skills',())
        return ()

    @staticmethod
    def required_level(ability,rank,*,dog=False):
        from .miner_abilities import MINER_SKILLS,required_level
        from .dog_abilities import required_level as dog_level
        if dog or ability in (12,14,15,16,18,19,23,26):return dog_level(ability,rank)
        # Original manual p46: human critical ranks3/4 require levels4/7;
        # melee mastery ranks1/2 require levels3/5. Other human gates are rank.
        if ability in (4,10):return {4:(1,2,4,7),10:(3,5)}[ability][rank-1]
        return required_level(ability,rank) if ability in MINER_SKILLS else rank

    def learning_price(self,ability,rank,learned):
        from .miner_abilities import MINER_SKILLS,learning_price
        if ability in MINER_SKILLS:
            return learning_price(ability,rank,learned)
        return self.price

    def _lists(self,db,account,owner):
        allowed=self._allowed(db,account,owner)
        revision,learned=self.state._read(db,account,owner)
        current={e.ability_id:e.level for e in learned};available=[]
        human,packet=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        actor_level=decode_pet_info(packet,human_equipment=bool(human)).fields['0x8c4aef']
        for ability in allowed:
            level=current.get(ability,0)+1
            if (ability,level) in self.catalog.by_key and self.required_level(ability,level,dog=not human)<=actor_level:
                available.append(AbilityEntry(ability,level,self.learning_price(ability,level,learned)))
        return revision,learned,tuple(available)

    def _tree(self,db,account,owner,learned):
        current={e.ability_id:e.level for e in learned};entries=[]
        allowed=self._allowed(db,account,owner)
        dog=not db.execute('SELECT human FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()[0]
        for ability in allowed:
            # The original AA window has one cell per (ability, actor level),
            # not per rank. Equal requirements would draw/hit-test overlapping
            # icons; its unstable sort can put rank3 above the learnable rank1.
            # Within each cell show the first unlearned rank, or the last learned
            # rank if that cell is complete. Distinct level rows stay visible.
            cells={}
            for level in range(1,self.catalog.get(ability,1).number('levels')+1):
                cells.setdefault(self.required_level(ability,level,dog=dog),[]).append(level)
            for required,ranks in cells.items():
                level=next((r for r in ranks if r>current.get(ability,0)),ranks[-1])
                entries.append((ability,level,level<=current.get(ability,0),required,self.learning_price(ability,level,learned),0))
        return encode_skill_tree(owner,entries)

    def tree(self,account,owner):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN')
            revision,learned,available=self._lists(db,account,owner)
            tree=self._tree(db,account,owner,learned)
        self.offers[(account,owner)]=(revision,{e.ability_id:e for e in available})
        return tree

    def lists(self,account,owner,*,offer=True):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN')
            revision,learned,available=self._lists(db,account,owner)
        if offer:self.offers[(account,owner)]=(revision,{e.ability_id:e for e in available})
        return (encode_abilities(owner,learned),encode_abilities(owner,available,for_learning=True))

    def learn(self,account,owner,ability):
        quote=self.offers.get((account,owner))
        if quote is None or ability not in quote[1]:raise ValueError('Refresh ability list before learning')
        expected,offers=quote;selected=offers[ability]
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            revision,learned,available=self._lists(db,account,owner)
            if revision!=expected or selected not in available:raise ValueError('Stale ability offer')
            wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            if wallet is None or wallet[0]<selected.unknown_u32:raise ValueError('Insufficient learning credits')
            row=self.catalog.get(ability,selected.level)
            active=int(row.fields.get('Active',row.fields.get('active','0')))
            # 80 tail is the forgetting price. Feature disabled; expose zero.
            learned=tuple(e for e in learned if e.ability_id!=ability)+(AbilityEntry(ability,selected.level,0,active),)
            packet=encode_abilities(owner,learned)
            db.execute('UPDATE wallets SET credits=credits-? WHERE account=?',(selected.unknown_u32,account))
            db.execute('INSERT INTO ability_states VALUES (?,?,?,?) ON CONFLICT(account,pet_id) DO UPDATE SET revision=excluded.revision,packet=excluded.packet',
                       (account,owner,revision+1,packet))
            _,_,available=self._lists(db,account,owner)
            replies=(packet,self._tree(db,account,owner,learned),encode_asset_count(AssetCount(wallet[0]-selected.unknown_u32,wallet[1])))
            if ability in (1,2,6,15,16,20,21,24):
                from .passive_stats import project_saved_pet
                human,base=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
                replies+=(project_saved_pet(db,account,owner,base,bool(human)),)
        # AA above refreshes the open native window without another A9 request.
        # Keep its prices/ranks and the next server offer on the same revision.
        # Native 8F has no rank/nonce: each subsequent request buys the currently
        # offered rank; ownership, level, funds and revision are rechecked.
        self.offers[(account,owner)]=(revision+1,{e.ability_id:e for e in available})
        return replies

    def handle(self,account,packet):
        if packet[:1]==b'\xa9':
            r=Reader(packet);r.u8();owner=r.u32();r.finish()
            return (self.tree(account,owner),)
        if packet[:2]==b'\xc8\x12':
            r=Reader(packet);r.u8();r.u8();owner=r.u32();r.finish()
            return (encode_abilities(owner,self.state.read(account,owner)[1]),)
        owner,ability,opcode=decode_ability_request(packet)
        if opcode!=0x8f:raise ValueError('Ability forgetting is not enabled')
        return self.learn(account,owner,ability)
