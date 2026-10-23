"""Execute original zones XML loader, B9 receiver and TownInfo consumers.

The explicit candidate XML supplies isolated DOM/property lookup. Original
9ea894 control flow, indexing, enum branches and metadata stores execute in
the exact published phase6 DLL; every visited instruction matches the stock
DLL. Allocation, strings, logging, filesystem and assault-window creation are
isolated. B9/03 parsing/copy, B9 zones reload dispatch, C82D float readers and
the actual tooltip label/float loads run. No native XML tokenizer, filesystem
write, on-screen GUI or hosted game-client acceptance is asserted.
"""
from verify_auth_native import *
from verify_mine_help_catalog_native import wide, return_pop
from unicorn.x86_const import UC_X86_REG_EFLAGS, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI
from collections import deque
from dataclasses import replace
import argparse
import xml.etree.ElementTree as ET
import zlib

from tio.protocol.town_info import diagnostic_town_info, encode_town_info
from tio.protocol.shared_config import SharedConfigData, encode_shared_config_data
from tools.prepare_world_completion_catalog import rows, values, FOLDER

CLIENT = ROOT/'reports/gameplay-completion/stage6-economy/client/candidate/silver.dll'
CLIENT_SHA = '7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
CLIENT_BYTES = 7761408
ORIGINAL = pefile.PE(data=BINARY.read_bytes()).get_memory_mapped_image()


def candidate():
    raw = CLIENT.read_bytes()
    assert len(raw)==CLIENT_BYTES and hashlib.sha256(raw).hexdigest()==CLIENT_SHA
    u = emulator(); u.mem_map(0xc17000,0x10000); u.mem_map(DATA+0x10000,0x50000)
    u.mem_write(0x400000,pefile.PE(data=raw).get_memory_mapped_image())
    visited = set()
    def parity(uc,address,size,user):
        offset = address-0x400000
        assert 0<=offset and offset+size<=len(ORIGINAL),hex(address)
        assert bytes(uc.mem_read(address,size))==ORIGINAL[offset:offset+size],hex(address)
        visited.add(address)
    u.hook_add(UC_HOOK_CODE,parity)
    return u,visited


def run(u,start,end=STOP,count=100000):
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.emu_start(start,end,count=count)
    assert u.reg_read(UC_X86_REG_EIP)==end,hex(u.reg_read(UC_X86_REG_EIP))


def xml_loader(xml):
    expected = rows(xml,22)
    u,visited = candidate(); cursor=DATA+0x100; lists={}; attributes={}; lookups=[]; errors=[]; isolated=set()
    trace=deque(maxlen=32); reloads=[]
    def allocate(size):
        nonlocal cursor
        address=cursor;cursor+=(size+15)&~15
        if cursor>=DATA+0x30000:raise ValueError('Bounded XML allocation exceeded')
        return address
    def string(text):
        if not text:return 0
        raw=text.encode('utf-16-le');base=allocate(len(raw)+14)
        u.mem_write(base,struct.pack('<HHii',1200,2,-1,len(text))+raw+b'\0\0');return base+12
    def node(tag,children=(),attrs=None,properties=None):
        obj=allocate(0x30);collection=allocate(0x10)
        put32(u,obj+0x18,string(tag));put32(u,obj+0x20,collection);put32(u,collection+8,len(children))
        lists[collection]=tuple(children);attributes[obj]=(attrs or {},properties or {})
        return obj
    children=[node('town',attrs=n.attrib,properties=values(n)) for n in expected.values()]
    root=node('towns',children=children)
    path_pointer=allocate(4);put32(u,path_pointer,string('bounded-world-candidate'));put32(u,0xac5c80,path_pointer)
    put32(u,0xac63bc,0xb749e4)
    def hook(uc,address,size,user):
        trace.append(hex(address));eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        ecx=uc.reg_read(UC_X86_REG_ECX);sp=uc.reg_read(UC_X86_REG_ESP)
        if address==0x9ea894:reloads.append('zones_loader_0x9ea894');return
        if address==0x40c244:
            put32(uc,eax,string('bounded-world-candidate/zones.xml'));return_pop(uc)
            uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+edx*4)
        elif address==0x424f2c:uc.reg_write(UC_X86_REG_EAX,1);return_pop(uc)
        elif address==0x68049c:uc.reg_write(UC_X86_REG_EAX,root);return_pop(uc,4)
        elif address==0x67f7d4:return_pop(uc)
        elif address==0x68266c:uc.reg_write(UC_X86_REG_EAX,lists[eax][edx]);return_pop(uc)
        elif address==0x680a48:uc.reg_write(UC_X86_REG_EAX,1);return_pop(uc)
        elif address in (0x680770,0x6807d0,0x680974,0x680860):
            key=wide(uc,edx);attr,properties=attributes[eax];source=attr if address==0x680770 else properties
            lookups.append(dict(helper=hex(address),key=key,configured=key in source))
            if address==0x680770:put32(uc,ecx,string(source.get(key,'')));return_pop(uc)
            elif address==0x6807d0:put32(uc,get32(uc,sp+4),string(source.get(key,wide(uc,ecx))));return_pop(uc,4)
            else:
                value=source.get(key,ecx if address==0x680974 else ecx&255)
                if address==0x680860:value=int(str(value).lower() in ('true','1'))
                else:value=int(value)
                uc.reg_write(UC_X86_REG_EAX,value&0xffffffff);return_pop(uc)
        elif address==0x40d5a4:
            count=get32(uc,sp+4);old=get32(uc,eax);base=allocate(8+count*4);target=base+8
            put32(uc,base,1);put32(uc,base+4,count)
            if old:uc.mem_write(target,bytes(uc.mem_read(old,4*min(count,get32(uc,old-4)))))
            put32(uc,eax,target);return_pop(uc)
        elif address==0x4092ac:
            record=allocate(0x400);put32(uc,record,eax);uc.reg_write(UC_X86_REG_EAX,record);return_pop(uc)
        elif address==0x406a50:uc.reg_write(UC_X86_REG_EAX,allocate(eax));return_pop(uc)
        elif address==0x9ec678:uc.reg_write(UC_X86_REG_EAX,allocate(0x100));return_pop(uc)
        elif address==0x40c06c:
            raw=wide(uc,edx).encode('cp1251')[:ecx];uc.mem_write(eax,bytes((len(raw),))+raw);return_pop(uc)
        elif address==0x4237d0:put32(uc,edx,string(wide(uc,eax).lower()));return_pop(uc)
        elif address==0x40c354:
            flags=uc.reg_read(UC_X86_REG_EFLAGS);equal=wide(uc,eax)==wide(uc,edx)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags|0x40) if equal else (flags&~0x40));return_pop(uc)
        elif address==0x423920:uc.reg_write(UC_X86_REG_EAX,0 if wide(uc,eax)==wide(uc,edx) else 1);return_pop(uc)
        elif address in (0x40d6c8,0x40b0fc,0x40b12c,0x40b09c,0x4092dc,0x9eb75c):
            if address==0x40d6c8:put32(uc,eax,0)
            return_pop(uc)
        elif address in (0x40b88c,0x40b934,0x40c028):put32(uc,eax,0);return_pop(uc)
        elif address==0x4f2158:
            severity=get32(uc,sp+4)
            if severity:errors.append(severity)
            return_pop(uc,12)
        else:return
        isolated.add(hex(address))
    u.hook_add(UC_HOOK_CODE,hook)
    # Execute the actual B9 shared-config reload selector, which compares
    # "zones" and calls the original XML loader. Other catalogue branches skip.
    u.reg_write(UC_X86_REG_EAX,string('zones'))
    try:run(u,0x9d1f68,count=250000)
    except Exception as exc:raise RuntimeError('Native zones loader trace '+','.join(trace)) from exc
    table=get32(u,0xb749e4)
    assert table and get32(u,table-4)==22 and not errors,errors
    assert reloads==['zones_loader_0x9ea894'],reloads
    cases=[]
    def short(record,offset):
        n=u.mem_read(record+offset,1)[0];return bytes(u.mem_read(record+offset+1,n)).decode('cp1251')
    for identity,expected_node in expected.items():
        record=get32(u,table+(identity-1)*4);properties=values(expected_node)
        native=dict(id=get32(u,record+8),name=short(record,0xd),background=short(record,0x10d),
            enabled=u.mem_read(record+4,1)[0],kind=u.mem_read(record+0xc,1)[0],
            bounds=list(struct.unpack('<iiii',u.mem_read(record+0x210,16))),
            levels=list(u.mem_read(record+0x248,2)),drop=u.mem_read(record+0x24d,1)[0],
            equipment=u.mem_read(record+0x24e,1)[0],arena=u.mem_read(record+0x237,1)[0],
            max_upgrade=u.mem_read(record+0x24c,1)[0],training=u.mem_read(record+0x23e,1)[0],
            rank_bonus=u.mem_read(record+0x23d,1)[0],assault_map=short(record,0x257),
            assault_v4=u.mem_read(record+0x255,1)[0])
        # Name strings are stored at record+0xd, starting with length byte.
        assert native['id']==identity and native['name']==expected_node.get('name'),native
        assert native['background']==properties['background'] and native['enabled']==int(properties['enabled']),native
        assert native['kind']=={'town':0,'base':1,'base4':1,'checkpoint':2,'shootingrange':3}.get(properties.get('type','town'),0),native
        assert native['assault_v4']==int(properties.get('type','town')=='base4'),native
        assert native['levels']==[int(properties['minlevel']),int(properties['maxlevel'])],native
        assert native['drop']==int(properties.get('drop','false')=='true'),native
        assert native['equipment']==int(properties.get('dragin','false')=='true'),native
        assert native['arena']==int(properties.get('arena','true')=='true'),native
        assert native['max_upgrade']==int(properties.get('dragInMaxEnhance','255')),native
        assert native['training']==int(properties.get('IsTraining','false')=='true'),native
        assert native['rank_bonus']==int(properties.get('rankBonus','0')),native
        assert native['assault_map']==properties.get('assaultMap',''),native
        configured_bounds=[int(properties[k]) for k in ('x1','y1','x2','y2')]
        configured_size=int(properties.get('size','0'))
        computed_bounds=[round((configured_bounds[0]+configured_bounds[2]-configured_size)/2),
            round((configured_bounds[1]+configured_bounds[3]-configured_size)/2),
            round((configured_bounds[0]+configured_bounds[2]+configured_size)/2),
            round((configured_bounds[1]+configured_bounds[3]+configured_size)/2)] if configured_size>0 else configured_bounds
        assert native['bounds']==computed_bounds,(native,computed_bounds)
        cases.append(dict(**native,passed=True))
    return u,table,cases,visited,dict(loader='0x9ea894',reload_dispatch='0x9d1f68',
        configured_properties=sorted({x['key'] for x in lookups if x['configured']}),isolated=sorted(isolated))


def towns(u,table,xml):
    obj=DATA+0x34000;packet_start=DATA+0x35000;current=DATA+0x33000
    put32(u,0xac5d58,current)
    def hook(uc,address,size,user):
        if address==0x40b0fc:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    cases=[]
    for identity,node in rows(xml,22).items():
        index=identity-1;record=get32(u,table+index*4);put32(u,current,identity)
        run(u,0x7d2ea4,0x7d2eb7);assert u.reg_read(UC_X86_REG_EAX)==record and get32(u,record+8)==identity
        levels=tuple(int(values(node)[key]) for key in ('minlevel','maxlevel'))
        for enabled in (0,1):
            info=replace(diagnostic_town_info(),town_id=identity,unknown_bytes=(*levels,0,0),final_bool=enabled)
            body=encode_town_info(info)[2:];u.mem_write(packet_start,body);put32(u,0xacd0e8,packet_start)
            u.reg_write(UC_X86_REG_EAX,obj);run(u,0x64a3fc)
            assert get32(u,0xacd0e8)-packet_start==len(body)
            u.reg_write(UC_X86_REG_EDI,obj);u.reg_write(UC_X86_REG_EBX,index);run(u,0x7cfb41,0x7cfb59)
            assert u.mem_read(record+4,1)[0]==enabled
            u.reg_write(UC_X86_REG_EDI,index);run(u,0x9e8ed6,0x9e8eef if enabled else 0x9e969b)
            cases.append(dict(town=identity,enabled=enabled,native_id_lookup=True,map_gate_passed=bool(enabled),passed=True))
    return cases


def float_mapping(u,table):
    obj=DATA+0x34000;packet=DATA+0x35000;sentinels=(1.25,2.5,3.75)
    bits=tuple(struct.unpack('<I',struct.pack('<f',f))[0] for f in sentinels)
    info=replace(diagnostic_town_info(),unknown_float_bits=bits,final_bool=1)
    body=encode_town_info(info)[2:];u.mem_write(packet,body);put32(u,0xacd0e8,packet)
    u.reg_write(UC_X86_REG_EAX,obj);run(u,0x64a3fc)
    assert tuple(get32(u,obj+offset) for offset in (0x18,0x20,0x28))==bits
    u.reg_write(UC_X86_REG_EDI,obj);u.reg_write(UC_X86_REG_ESI,2);run(u,0x7cedf5,0x7cee3d)
    record=get32(u,table+8)
    assert tuple(get32(u,record+offset) for offset in (0x228,0x22c,0x230))==bits
    labels=[];formatted=[]
    def extended(raw):
        mantissa,exponent=struct.unpack('<QH',raw)
        return (-1 if exponent&0x8000 else 1)*(mantissa/2**63)*2**((exponent&0x7fff)-16383)
    def hook(uc,address,size,user):
        if address==0x6675e0:
            labels.append(wide(uc,uc.reg_read(UC_X86_REG_EAX)));put32(uc,uc.reg_read(UC_X86_REG_EDX),0);return_pop(uc)
        elif address==0x42751c:
            sp=uc.reg_read(UC_X86_REG_ESP);formatted.append(extended(bytes(uc.mem_read(sp+4,10))))
            put32(uc,uc.reg_read(UC_X86_REG_ECX),0);return_pop(uc,12)
    u.hook_add(UC_HOOK_CODE,hook);tooltip=DATA+0x36000;put32(u,tooltip+0xc,2)
    for start,end in ((0x9e815c,0x9e819e),(0x9e81cb,0x9e820d),(0x9e823a,0x9e827c)):
        u.reg_write(UC_X86_REG_EBX,tooltip);u.reg_write(UC_X86_REG_EBP,STACK+0x9000);run(u,start,end)
    assert labels==['m159','m219','m397'] and formatted==list(sentinels),(labels,formatted)
    language=(BINARY.parent/'base/english.lng').read_text(encoding='latin-1')
    descriptions={line.split('=',1)[0]:line.split('=',1)[1] for line in language.splitlines() if '=' in line}
    assert [descriptions[k] for k in labels]==['Influence rate: %s','Experience rate: %s','Profit rate: %s']
    return dict(passed=True,order=['influence','experience','profit'],sentinel_values=list(sentinels),
        packet_decoder_offsets=['0x18','0x20','0x28'],town_offsets=['0x228','0x22c','0x230'],
        actual_tooltip_labels=dict(zip(labels,[descriptions[k] for k in labels])),
        original_tooltip_consumer='0x9e8128',experience_xml_key='expirienceMultiplier',
        language_sha256=hashlib.sha256((BINARY.parent/'base/english.lng').read_bytes()).hexdigest())


def shared_config(xml):
    compressed=zlib.compress(xml);packet=encode_shared_config_data(SharedConfigData(b'zones',len(xml),compressed))
    u,visited=candidate();u.reg_write(UC_X86_REG_ESP,STACK+0xf000);put32(u,STACK+0xf000,STOP);u.mem_write(DATA,packet)
    names=[];result={}
    def hook(uc,address,size,user):
        if address==0x9cfa38:return_from_stub(uc)
        elif address==0x605f1c:
            a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX);start=get32(uc,a);end=start
            while uc.mem_read(end,1)!=b'\0':end+=1
            names.append(bytes(uc.mem_read(start,end-start)));put32(uc,a,end+1);put32(uc,d,0);return_from_stub(uc)
        elif address==0x9d04fb:
            bp=uc.reg_read(UC_X86_REG_EBP);copied=bytes(uc.mem_read(bp-0xc365,len(compressed)))
            assert copied==compressed and zlib.decompress(copied)==xml
            result.update(consumed=get32(uc,bp-12)-DATA,decompressed_size=uc.reg_read(UC_X86_REG_ESI),
                compressed_size=uc.reg_read(UC_X86_REG_EBX));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,0xb9);u.reg_write(UC_X86_REG_EDX,DATA+1)
    u.emu_start(0x9d070c,STOP,count=200000)
    assert names==[b'zones'] and result==dict(consumed=len(packet),decompressed_size=len(xml),compressed_size=len(compressed))
    return dict(passed=True,name='zones',**result,packet_sha256=hashlib.sha256(packet).hexdigest(),
        original_instruction_parity_count=len(visited),native_receiver='0x9d070c/0x9d0408',
        limitation='Stopped at0x9d04fb before filesystem/stream inflate; supplied XML DOM is separately verified through native reload loader.')


def verify(xml_path,output):
    xml=Path(xml_path).read_bytes();u,table,loaded,visited,loader=xml_loader(xml)
    visibility=towns(u,table,xml);floats=float_mapping(u,table);shared=shared_config(xml)
    result=dict(passed=True,status='PASS',method=__doc__,candidate_xml_sha256=hashlib.sha256(xml).hexdigest(),
        candidate_dll_sha256=CLIENT_SHA,original_sha256=EXPECTED_SHA,loader=loader,loader_cases=loaded,
        town_cases=visibility,float_mapping=floats,shared_config=shared,
        original_instruction_parity_count=len(visited),installed_client_changed=False,database_opened=False,
        limitations=['XML DOM/RTL/allocation/file/UI helpers isolated; native tokenizer not executed',
            'No actual Windows GUI or hosted game-client validation'])
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=verify(args.xml,args.output)
    print('Explicit candidate XML: original22townloader +44visibility +B9zones +Influence/Experience/Profit floats PASS')
