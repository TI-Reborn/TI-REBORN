"""Original checkpoint menu requests, role selection, scene entry and quotes."""
import json,struct
from pathlib import Path
from .protocol import mining as wire
from .protocol.asset_count import encode_asset_count
from .wallets import WalletStore
from .crystal_market import CrystalMarket,POLICY
from .locations import MINE_LOCATIONS


class MiningService:
    def __init__(self,path,arena,locations):
        self.path,self.arena,self.locations=path,arena,locations
        self.market=CrystalMarket(path)

    def quote(self):
        rate,history=self.market.quote_history()
        return (wire.price(rate),wire.price_history(history))

    def handle(self,account,character,name,packet):
        if len(packet)<2 or packet[0]!=0xb0:return None
        sub=packet[1]
        if sub in (0x21,0x24) and len(packet)==2:
            return None,self.quote() if sub==0x21 else (b'\xb0\x25\0',)
        if sub==0x1d:
            if len(packet)!=6:raise ValueError('Invalid crystal sale packet')
            self.market.sell(account,struct.unpack_from('<i',packet,2)[0])
            assets=self.market.project(account,WalletStore(self.path).ensure(account))
            return None,(encode_asset_count(assets),*self.quote())
        if sub==0x15:
            actor,x,y,amount=wire.decode_pickup(packet)
            room=next((r for r in self.arena.rooms.snapshot() if character in r.members),None)
            turn=None if room is None else self.arena._turns.get(room.room_id)
            if turn is None or turn[0]!=character or self.arena._clock()>=turn[2] or actor not in turn[1]:raise ValueError('Active owned turn required')
            field=self.arena._fields[room.room_id]
            if not hasattr(field,'mining'):raise ValueError('Not in a mine')
            return None,field.mining.pickup(character,actor,x,y,amount)
        # The rating screen requests all three role pages even outside a mine.
        # This public read must not run checkpoint admission or change gameplay.
        if sub==0x28:
            if len(packet)!=3:raise ValueError('Invalid mining rating request')
            return None,(b'\xb0\x29'+packet[2:3]+b'\0\0',)
        if sub not in (0x14,0x19,0x1c,0x2c):return None
        town=self.locations.current(account)
        if town not in MINE_LOCATIONS:raise ValueError('Travel to a mine checkpoint first')
        if sub in (0x1c,0x2c) and len(packet)==2:
            return None,(wire.player_state(),b'\xb0\x26'+struct.pack('<II',5,5),b'\xb0\x27'+struct.pack('<II',0,0),b'\xb0\x2b'+struct.pack('<I',3600))
        if sub==0x19 and len(packet)==2:return None,(b'\xb0\x1b'+struct.pack('<I',character),)
        if sub!=0x14 or len(packet)!=3:raise ValueError('Invalid checkpoint request')
        role=packet[2]
        if role==3:raise ValueError('Defense requires membership of the checkpoint owner clan')
        if role not in (1,2):raise ValueError('Invalid mining role')
        if any(character in r.members for r in self.arena.rooms.snapshot()):raise ValueError('Already in battle')
        from .owned_pets import OwnedPetStore
        from .matchmaking import SurvivalQueue
        from .mining import band
        ticket=SurvivalQueue().join(character,OwnedPetStore(self.path).list(account))
        if band(ticket.levels)!=tuple(POLICY['bands'][MINE_LOCATIONS[town]['band']]):raise ValueError('Squad does not match this mine level range')
        from .abilities import AbilityCatalog,AbilityLevel
        from tools.mining_scene import prepare_mining
        source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        prepared=prepare_mining(self.path,account,ticket,catalog,role=role)
        prepared.field.return_town=town
        room,replies=self.arena.start_survival(character,name,prepared)
        return (room,prepared),replies


from server.battle_journal import private_service
MiningService.handle=private_service(MiningService.handle)
