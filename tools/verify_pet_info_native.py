"""Verify encoded PetInfo66 across new/existing slots and eight body profiles."""
from trace_pet_info_native import trace,ROOT
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
import json


def main():
    results=[]
    for human in (False,True):
        for appearance in (False,True):
            for owner in (False,True):
                baseline=trace(human=human,appearance=appearance,owner_fields=owner)
                pet=decode_pet_info(b'\x66'+bytes.fromhex(baseline['body_hex']),human_equipment=human)
                pet.fields['0x8c4489']=b'OwnedRecruit'
                wire=encode_pet_info(pet)
                actual=trace(body=wire[1:],human=human,new_slot=True)
                assert actual['consumed']==len(wire)-1
                assert actual['body_hex']==wire[1:].hex()
                results.append({'human':human,'appearance':appearance,'owner':owner,
                                'body_bytes':actual['consumed'],'packet_hex':wire.hex()})
    (ROOT/'evidence/pet_info_codec_native.json').write_text(json.dumps({'method':__doc__,
       'limitations':'UI/runtime/string/model stubs, resource lookup branch selected explicitly; not live actor verification',
       'cases':results},indent=2)+'\n')
    print('PetInfo codec:8 original-reader profiles PASS')
if __name__=='__main__':main()
