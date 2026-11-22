"""Read actual durable random hires and service tiers through original x86.

Original62/B103 readers run with existing managed allocation/UI isolation.
Original66 readers verify generated male/female/dog/miner first-level profiles.
This is numeric/wire validation, not live graphical client acceptance.
"""
from verify_auth_native import *
import random,tempfile
from tio.roster_progression import RecruitmentStore,profile,random_appearance,roster_expansion
from tio.city_catalogs import CityCatalogs
from tio.protocol.city_catalogs import encode_pet_shop,ServiceOffer,ServiceOption,encode_service_shop
from verify_city_catalogs_native import run_case
from trace_pet_info_native import trace


if __name__=='__main__':
    template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
    with tempfile.TemporaryDirectory() as directory:
        store=RecruitmentStore(Path(directory)/'probe.db',CityCatalogs(ROOT/'config/city_catalogs.json'),template,rng=random.Random(719))
        offers=store.available('alice');city=run_case('pets',encode_pet_shop(offers))
        for offer,record in zip(offers,city['records']):
            raw=bytes.fromhex(record)
            assert struct.unpack_from('<II',raw,0x100)==(offer.candidate_id,offer.resource_type)
            assert struct.unpack_from('<I',raw,0x194)[0]==offer.price_credits
            assert raw[0x108]==1 and struct.unpack_from('<I',raw,0x184)[0]==85
            if offer.optional_bytes is not None:
                assert tuple(struct.unpack_from('<H',raw,offset)[0] for offset in (0x19e,0x198,0x19a,0x19c,0x1a0,0x1a2))==tuple(offer.optional_bytes)
        tiers = roster_expansion()
        services=run_case('services',encode_service_shop((ServiceOffer(2,0,tuple(ServiceOption(index,0,cost)
                      for index,(_,cost) in enumerate(tiers,1))),)))
        records=bytes.fromhex(services['records'][1])
        assert [(records[index*24], struct.unpack_from('<I', records, index*24+16)[0])
                for index in range(len(tiers))] == [(level, cost) for level, (_, cost) in enumerate(tiers, 1)]
    profiles=[]
    for resource in (1,2,3,6):
        packet=profile(template,1,resource,b'Native Recruit',random_appearance(resource,random.Random(resource)))
        result=trace(body=packet[1:],human=resource in (1,2,6),new_slot=True)
        assert result['consumed']==len(packet)-1
        profiles.append({'resource':resource,'packet_hex':packet.hex(),'consumed':result['consumed']})
    result={'sha256':EXPECTED_SHA,'method':__doc__,'random_city_catalog':city,'service_tiers':services,'profiles':profiles}
    (ROOT/'evidence/roster_progression_native.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'Original random hire62 +{len(tiers)} service levels +4 generated profile66 cases PASS')
