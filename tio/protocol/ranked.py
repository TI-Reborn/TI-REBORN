"""Original C6 TrueSkill builders/readers: silver 952bfc, 953038, 953d30, 953e5c."""
import struct
from .binary import Reader,Writer,PacketError
from .arena import _name_write


def encode_gears(item_ids):
    """C6/18 RECV_TokenGearsInfo (silver 953ec8): count, template IDs.

    This is the arena's catalogue, not an inventory or a grant of items.
    An empty catalogue deliberately leaves the native city button loading.
    """
    ids=tuple(item_ids)
    if not 1<=len(ids)<=4096 or len(set(ids))!=len(ids):
        raise PacketError('Invalid arena catalogue size or duplicate template')
    w=Writer().u8(0xc6).u8(0x18).u32(len(ids))
    for identity in ids:
        if type(identity) is not int or not 1<=identity<65500:
            raise PacketError('Invalid arena gear template')
        w.u32(identity)
    return w.build()


def decode_gears(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xc6\x18':raise PacketError('Expected arena catalogue')
    count=r.u32()
    if not 1<=count<=4096:raise PacketError('Invalid arena catalogue size')
    ids=tuple(r.u32() for _ in range(count));r.finish()
    encode_gears(ids)
    return ids


def decode_join(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xc6\x21':raise PacketError('Expected TrueSkill search')
    flags=(r.u8(),r.u8());count=r.u32()
    if any(f not in (0,1) for f in flags) or not 1<=count<=4:raise PacketError('Invalid TrueSkill selection')
    pets=[]
    for _ in range(count):
        identity=r.u32();n=r.u32()
        if n>5:raise PacketError('Invalid TrueSkill equipment count')
        equipment=tuple((r.u32(),r.u32()) for _ in range(n));bonus=r.u8()
        if bonus>2 or len({slot for slot,item in equipment})!=n or any(slot not in (0,2,3,4,7) for slot,item in equipment):
            raise PacketError('Invalid TrueSkill equipment')
        pets.append((identity,equipment,bonus))
    r.finish()
    if len({i for i,e,b in pets})!=len(pets):raise PacketError('Repeated TrueSkill fighter')
    return flags,tuple(pets)


def encode_info(points,league,place,streak):
    return b'\xc6\x03'+struct.pack('<IIQQI',points,league,place,streak,0)


def encode_flags(points):
    # 953d30 forwards (x,y,last) to ColorAssaultFlag. ti.exe72db0c
    # matches model cell+4/+8, then indexes its three-color palette.
    return tuple(b'\xc6\x15'+struct.pack('<4I',x,y,0,0 if side is None else side+1)
                 for (x,y),side in zip(points.positions,points.owners))


def encode_scores(points):
    return b'\xc6\x16'+struct.pack('<I6I',2,1,points.scores[0],points.increments()[0],
                               2,points.scores[1],points.increments()[1])


def encode_turn(side,owner,actor):
    # 953884 selects the active soldier from the C6/13 owner/actor roster.
    return b'\xc6\x14'+struct.pack('<4I',0,side,owner,actor)


def encode_roster(field,names,limit=1000,*,viewer=None,character_id=None):
    w=Writer().u8(0xc6).u8(0x13).u8(1).u32(limit).u32(len(field._actors))
    for identity,a in field._actors.items():
        w.u32(field.teams[a.owner_id]).u32(character_id if a.owner_id==viewer else a.owner_id);_name_write(w,names[a.owner_id])
        from .pet_info import decode_pet_info
        name=decode_pet_info(field.combat.proficiencies[identity],human_equipment=field.combat.human[identity]).fields['0x8c4489']
        w.u32(identity);_name_write(w,name)
    return w.build()


def encode_accepted(match_id,teams,names,ratings):
    w=Writer().u8(0xc6).u8(4).u32(match_id).u8(0).u8(0)
    for team in teams:
        w.u32(len(team))
        for owner,actors in team:
            _name_write(w,names[owner]);w.data.extend(struct.pack('<Q',ratings[owner]))
            w.u32(len(actors))
            for resource,rank in actors:w.u32(resource).u32(rank)
    return w.build()
