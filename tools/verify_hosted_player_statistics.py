"""Shared PvP and profile fields over the public encrypted TCP transport.

Fresh QA accounts only; never alter existing players. No graphical clients.
"""
from verify_hosted_rewards import reward_run,ROOT
from tio.protocol.binary import Reader
from pathlib import Path
import json,shlex,subprocess,sys,time


def decode(packet):
    r=Reader(packet)
    def ansi():
        data=bytearray()
        while (v:=r.u8()):data.append(v)
        return bytes(data).decode('cp1251')
    def wide():
        data=bytearray()
        while (v:=r.read(2))!=b'\0\0':data.extend(v)
        return data.decode('utf-16-le')
    assert (r.u8(),r.u8())==(0xa7,0)
    identity=r.u32();name=ansi();level=r.u8();r.u32()
    ansi();r.u32();ansi();r.u32();battle=r.u8();r.u8()
    keys=('mute','online_hours','rating','wins','losses','kills','deaths','damage_dealt','damage_received','squad_icon','squad_rank')
    values=dict(zip(keys,(r.u32() for _ in keys)))
    for k in ('rating','squad_rank'):
        if values[k]>=0x80000000:values[k]-=0x100000000
    about,contact,website=wide(),wide(),wide();soldiers=[]
    for _ in range(r.u8()):
        nick=ansi();lvl=r.u8();r.u32();xp=r.u32();r.u32();rank=r.u32();r.u32();r.u32()
        soldiers.append(dict(name=nick,level=lvl,xp=xp,rank=rank))
    r.u8();r.u32();r.u32();r.u32();r.u8();online=r.u8()
    skill=r.u32();league=r.u32();place=int.from_bytes(r.read(8),'little');streak=int.from_bytes(r.read(8),'little');r.u8();r.finish()
    return dict(name=name,level=level,battle=battle,online=online,skill=skill,league=league,place=place,streak=streak,
                soldiers=soldiers,about=about,contact=contact,website=website,**values)


def profiles(peers,names,summaries,result,case):
    result['profiles']=[]
    for index,peer in enumerate(peers):
        time.sleep(.6);peer.send(b'\x68\0'+names[index].encode()+b'\0')
        profile=decode(peer.until(b'\xa7\0',max_packets=2048));result['profiles'].append(profile)
        summary=summaries[index]
        assert (profile['wins'],profile['losses'])==((1,0) if index==0 else (0,1)),profile
        assert tuple(profile[k] for k in ('kills','deaths','damage_dealt','damage_received'))==summary[1:5],(profile,summary)
        assert profile['rating']==(1 if index==0 else -1),profile
        assert (profile['skill'],profile['league'],profile['place'],profile['streak'])==(0,3,0,0),profile
        assert len(profile['soldiers'])==1 and profile['soldiers'][0]['xp']>0 and profile['soldiers'][0]['rank']>=1,profile
        time.sleep(.6);peer.send(b'\x68\0'+names[1-index].encode()+b'\0')
        other=decode(peer.until(b'\xa7\0',max_packets=2048))
        assert other['name']==names[1-index] and other['wins']==index and other['losses']==1-index,other
    result['checks'].append('Own/cross-account native profile: totals equal authoritative battle result, XP/rank roster, bronze index3; Reservation does not award TrueSkill')


if __name__=='__main__':
    host=sys.argv[1]
    result=reward_run(host,profile_check=profiles)
    (ROOT/'reports/player-statistics/hosted-verification.json').write_text(json.dumps(result,indent=2)+'\n')
