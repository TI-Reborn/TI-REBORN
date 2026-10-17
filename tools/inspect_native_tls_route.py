"""Bounded read-only route inspection of one launcher-owned native game.

Reads only fixed TI loader state/code, the ORANGE export jump, and the
signature-validated TLS route's own allocation (code, fixed host and phase).
Never reads silver UI/account fields, stored credentials or packet buffers.
No writes, debugger attachment, GUI operation, game traffic or process control.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct


TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
ORANGE_SHA = '5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589'
SILVER_SHA = '2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359'
UNPACKED_SHA = 'a3cabaf3ba571d737ec7cc6105f96b3f11ce217398477209fcf54f7737feae47'
LAUNCHER_014_SHA = '61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
THUNK_TEMPLATE = bytes.fromhex('9c50c744240c000000008b44241883f800b8000000007405b80000000089442410589de900000000')
VARIABLES = set(range(6,10)) | set(range(18,22)) | set(range(25,29)) | set(range(36,40))
ORIGINAL_CONNECT_TEMPLATE = bytes.fromhex('a00000000084c074238b0d0000000085c974198b4424108b54240c508b44240c528b54240c5052e8')
ORIGINAL_VARIABLES = set(range(1,5)) | set(range(11,15))
LOADER_SLOTS = (('aaAaA',0x786528),('aaaaa',0x786508),('aAaAa',0x78651c),
    ('aaAaa',0x78650c),('aAaaA',0x786520),('AAaAa',0x786510),
    ('AaaAa',0x786518),('aaaAa',0x786524),('AAaAA',0x786514),('aAAAa',0x78652c))


class Module(ctypes.Structure):
    _fields_ = [('size',wintypes.DWORD),('module_id',wintypes.DWORD),('pid',wintypes.DWORD),
        ('global_usage',wintypes.DWORD),('process_usage',wintypes.DWORD),
        ('base',ctypes.POINTER(ctypes.c_byte)),('image_size',wintypes.DWORD),
        ('handle',wintypes.HMODULE),('name',wintypes.WCHAR*256),('path',wintypes.WCHAR*260)]


class Region(ctypes.Structure):
    _fields_ = [('base',ctypes.c_void_p),('allocation_base',ctypes.c_void_p),
        ('allocation_protect',wintypes.DWORD),('size',ctypes.c_size_t),
        ('state',wintypes.DWORD),('protect',wintypes.DWORD),('kind',wintypes.DWORD)]


class ProcessEntry(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
        ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
        ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),
        ('name',wintypes.WCHAR*260)]


def parent_launcher_identity(k,pid):
    k.Process32FirstW.argtypes=k.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    require(snapshot not in (None,ctypes.c_void_p(-1).value),'Process parent snapshot unavailable')
    parent=0
    try:
        row=ProcessEntry();row.size=ctypes.sizeof(row)
        require(k.Process32FirstW(snapshot,ctypes.byref(row)),'Process parent metadata unavailable')
        while True:
            if row.pid==pid:parent=row.parent;break
            if not k.Process32NextW(snapshot,ctypes.byref(row)):break
    finally:k.CloseHandle(snapshot)
    require(parent>0,'Target game parent is unavailable')
    helper=k.OpenProcess(0x1000,False,parent)
    require(helper,'Target game helper is unavailable')
    try:
        path=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(path))
        require(k.QueryFullProcessImageNameW(helper,0,path,ctypes.byref(size)),'Helper image metadata unavailable')
        return parent,hashlib.sha256(Path(path.value).read_bytes()).hexdigest()
    finally:k.CloseHandle(helper)


def api():
    k = ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD,wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Module32FirstW.argtypes = k.Module32NextW.argtypes = [wintypes.HANDLE,ctypes.POINTER(Module)]
    k.ReadProcessMemory.argtypes = [wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    k.VirtualQueryEx.argtypes = [wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(Region),ctypes.c_size_t]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    k.GetProcessTimes.argtypes = [wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.DuplicateHandle.argtypes = [wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    k.GetExitCodeThread.argtypes = [wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    k.GetProcessIdOfThread.restype = wintypes.DWORD
    k.GetThreadTimes.argtypes = k.GetProcessTimes.argtypes
    return k


def require(ok, message):
    if not ok: raise ValueError(message)


def stamp(k, process):
    created,exited,kernel,user = (wintypes.FILETIME() for _ in range(4))
    require(k.GetProcessTimes(process,*map(ctypes.byref,(created,exited,kernel,user))), 'Process creation metadata unavailable')
    return created.dwLowDateTime | created.dwHighDateTime<<32


def modules(k, pid):
    snapshot = k.CreateToolhelp32Snapshot(0x08|0x10,pid)
    require(snapshot not in (None,ctypes.c_void_p(-1).value),'Module metadata snapshot unavailable')
    result = {}
    try:
        entry = Module();entry.size=ctypes.sizeof(entry)
        require(k.Module32FirstW(snapshot,ctypes.byref(entry)),'Module metadata unavailable')
        while True:
            name=entry.name.lower()
            if name in ('ti.exe','orange.dll','silver.dll'):
                result[name]=dict(base=ctypes.cast(entry.base,ctypes.c_void_p).value,
                    image_size=entry.image_size,path=Path(entry.path).resolve())
            if not k.Module32NextW(snapshot,ctypes.byref(entry)):break
    finally:k.CloseHandle(snapshot)
    return result


def inspect(args):
    k=api();root=args.root.resolve()
    require(args.pid>0 and 1024<=args.login_port<=65535 and 1024<=args.session_port<=65535,
        'Invalid PID or expected dynamic loopback ports')
    require(args.login_port!=args.session_port,'Expected loopback ports must be distinct')
    for name,sha in (('ti.exe',TI_SHA),('orange.dll',ORANGE_SHA),('silver.dll',SILVER_SHA)):
        require(hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,'Unknown '+name+' image; inspection refused')
    process=k.OpenProcess(0x0400|0x0010,False,args.pid)  # Query metadata and read; no write/control rights.
    require(process,'Cannot open target game read-only')
    try:
        created=stamp(k,process)
        mapped=modules(k,args.pid)
        for name in ('ti.exe','orange.dll','silver.dll'):
            require(name in mapped and mapped[name]['path']==(root/name).resolve(),'Target module identity mismatch: '+name)
        require(mapped['ti.exe']['base']==0x400000,'Unknown TI module basis')
        orange=mapped['orange.dll']['base']
        reads=[]
        def read(address,size,purpose):
            require(0<address<=0xffffffff-size and size in (1,4,5,10,36,40,102,107,189,290,327),'Unexpected read bound')
            raw=(ctypes.c_ubyte*size)();count=ctypes.c_size_t()
            require(k.ReadProcessMemory(process,address,raw,size,ctypes.byref(count)) and count.value==size,
                'Read-only route check unavailable: '+purpose)
            reads.append(dict(purpose=purpose,address=hex(address),bytes=size))
            return bytes(raw)
        def region(address):
            item=Region()
            require(k.VirtualQueryEx(process,address,ctypes.byref(item),ctypes.sizeof(item))==ctypes.sizeof(item),
                'Route page metadata unavailable')
            return item
        report=dict(kind='read-only owned native TLS route metadata',pid=args.pid,
            created_utc=datetime.fromtimestamp((created-116444736000000000)/10000000,timezone.utc).isoformat(),
            module_bases={name:hex(row['base']) for name,row in mapped.items()},
            credentials_read=False,ui_fields_read=False,packet_buffers_read=False,
            memory_written=False,debugger_attached=False,network_requests=0,checks={},reads=reads)
        pointer=struct.unpack('<I',read(0x76da80,4,'TI loaded ORANGE pointer'))[0]
        report['checks']['loader_points_to_loaded_orange']=pointer==orange
        report['checks']['original_loader_store_restored']=read(0x718ff4,5,'TI loader store')==bytes.fromhex('a380da7600')
        jump=read(orange+0x118f,5,'ORANGE AaaAa export jump')
        require(jump[0]==0xe9,'ORANGE export is not the expected relative jump')
        target=(orange+0x118f+5+struct.unpack('<i',jump[1:])[0])&0xffffffff
        code=region(target)
        allocation=code.allocation_base
        report['export_target']=hex(target)
        report['checks']['route_allocation_rx']=bool(allocation and target==allocation+2048 and code.protect==0x20 and code.state==0x1000)
        require(report['checks']['route_allocation_rx'],'Export does not target the known installed TLS allocation; no allocation bytes read')
        thunk=read(target,40,'TLS route thunk instructions')
        template=bytearray(THUNK_TEMPLATE)
        if thunk[14]==0x80:
            parent,helper_sha=parent_launcher_identity(k,args.pid)
            require(helper_sha==LAUNCHER_014_SHA,'Byte-mode route requires the exact reviewed 0.1.4 helper')
            template[14]=0x80
            report['route_variant']='0.1.4-byte-mode'
            report['helper_pid']=parent
        else:report['route_variant']='0.1.3-dword-mode'
        require(all(thunk[i]==template[i] for i in range(40) if i not in VARIABLES),
            'Unknown TLS route instruction pattern; no host or phase bytes read')
        host=struct.unpack_from('<I',thunk,6)[0]
        require(host==allocation+2304,'Unknown route host pointer; no host bytes read')
        state=region(allocation+4096)
        require(state.allocation_base==allocation and state.protect==0x04 and state.state==0x1000,
            'Unknown route state page; no phase bytes read')
        login=struct.unpack_from('<I',thunk,18)[0]
        session=struct.unpack_from('<I',thunk,25)[0]
        require(1024<=login<=65535 and 1024<=session<=65535 and login!=session,'Unknown route port operands')
        report['decoded_ports']=dict(login=login,session=session)
        report['checks']['loopback_host_exact']=read(host,10,'TLS fixed loopback hostname')==b'127.0.0.1\0'
        report['checks']['login_port_matches_expected']=login==args.login_port
        report['checks']['session_port_matches_expected']=session==args.session_port
        phase=struct.unpack('<I',read(allocation+4096+12,4,'TLS bootstrap phase'))[0]
        report['phase']=phase if phase in (0,1,2,3) else 'unrecognized'
        report['checks']['bootstrap_phase_complete']=phase==3
        report['checks']['route_state_rw']=True
        # The native connect export returns silently unless both transport
        # initialization gates are set. Validate the original instruction
        # pattern and both relocated operands before reading just these fields.
        original=(target+40+struct.unpack_from('<i',thunk,36)[0])&0xffffffff
        unpacked=original-0x1670
        require(unpacked>0 and unpacked&0xfff==0 and unpacked not in (orange,allocation),
            'Unknown original ORANGE target; no transport metadata read')
        require(region(original).allocation_base==unpacked,
            'Original ORANGE allocation identity mismatch; no transport metadata read')
        native=read(original,40,'Original ORANGE AaaAa instruction fingerprint')
        require(all(native[i]==ORIGINAL_CONNECT_TEMPLATE[i] for i in range(40) if i not in ORIGINAL_VARIABLES),
            'Unknown original ORANGE connect instruction fingerprint; no transport metadata read')
        require(struct.unpack_from('<I',native,1)[0]==unpacked+0x50f5 and
            struct.unpack_from('<I',native,11)[0]==unpacked+0x50f0,
            'Original ORANGE gate relocation mismatch; no transport metadata read')
        require(region(unpacked+0x50f0).allocation_base==unpacked,
            'Original ORANGE transport metadata page identity mismatch')
        activated=read(unpacked+0x50f5,1,'ORANGE transport activation flag')!=b'\0'
        native_object=struct.unpack('<I',read(unpacked+0x50f0,4,'ORANGE transport opaque pointer presence'))[0]
        object_present=native_object!=0
        report['original_connect_target']=hex(original)
        report['transport_gate']=dict(activated=activated,object_present=object_present,
            opaque_pointer_dereferenced=False)
        report['checks']['native_transport_activated']=activated
        report['checks']['native_transport_object_present']=object_present
        # These exact native functions establish the datatype of two further
        # transport fields. Connect mode0 starts a CRT thread only while +12e
        # is zero; +24 receives that thread's handle. No string, auth, socket,
        # packet, UI or other object fields are inspected.
        if object_present:
            fixture=Path(__file__).resolve().parents[1]/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin'
            raw=fixture.read_bytes()
            require(hashlib.sha256(raw).hexdigest()==UNPACKED_SHA,'Unknown native transport reference fixture')
            for rva,size,relocations,purpose in (
                    (0x1a90,290,((61,0x3008),(276,0x3004)),'ORANGE connect mode gate fingerprint'),
                    (0x28a0,102,((76,0x2830),(86,0x3030)),'ORANGE transport thread startup fingerprint')):
                expected=bytearray(raw[rva:rva+size])
                for offset,operand in relocations:
                    require(struct.unpack_from('<I',expected,offset)[0]==0xc9b0000+operand,
                        'Unknown static ORANGE transport relocation')
                    struct.pack_into('<I',expected,offset,unpacked+operand)
                require(read(unpacked+rva,size,purpose)==expected,
                    'Unknown relocated ORANGE transport function; no object metadata read')
            require(native_object>=0x10000 and native_object&3==0 and native_object<=0xffffffff-0x12f,
                'Unknown ORANGE transport allocation; no object metadata read')
            heap=region(native_object)
            require(heap.state==0x1000 and heap.protect==0x04 and
                heap.base<=native_object and native_object+0x12f<=heap.base+heap.size,
                'Unknown ORANGE transport object region; no object metadata read')
            require(read(native_object,4,'ORANGE transport class vtable guard')==struct.pack('<I',unpacked+0x3074),
                'Unknown ORANGE transport object class; no transport fields read')
            flag=read(native_object+0x12e,1,'ORANGE transport thread started flag')[0]
            thread=struct.unpack('<I',read(native_object+0x24,4,'ORANGE transport thread handle presence'))[0]
            report['transport_gate']['opaque_pointer_dereferenced']=True
            status=dict(started_flag=flag if flag in (0,1) else 'unrecognized',
                mode0_can_start_thread=flag==0,thread_handle_present=thread!=0,
                fields_read_only=['vtable class guard','thread started flag +0x12e','thread handle +0x24'],
                socket_auth_ui_or_packet_fields_read=False,thread_control_performed=False)
            report['transport_thread']=status
            if thread:
                # Duplicate solely this already typed handle, use only OS
                # metadata queries, then close the duplicate. Never suspend,
                # inspect thread context/stack, terminate or otherwise control.
                source=k.OpenProcess(0x0040,False,args.pid)
                duplicate=wintypes.HANDLE()
                require(source,'Cannot open owned process handle duplication metadata')
                try:
                    require(stamp(k,process)==created,'Process identity changed before transport thread query')
                    require(k.DuplicateHandle(source,thread,k.GetCurrentProcess(),ctypes.byref(duplicate),0,False,2),
                        'Native transport thread handle duplication unavailable')
                    require(k.GetProcessIdOfThread(duplicate)==args.pid,
                        'Transport thread does not belong to the guarded target; no thread times read')
                    code=wintypes.DWORD()
                    require(k.GetExitCodeThread(duplicate,ctypes.byref(code)),'Native transport thread exit metadata unavailable')
                    status.update(thread_alive=code.value==259,thread_exit_code=code.value)
                    times=[wintypes.FILETIME() for _ in range(4)]
                    require(k.GetThreadTimes(duplicate,*map(ctypes.byref,times)),'Native transport thread times unavailable')
                    values=[item.dwLowDateTime | item.dwHighDateTime<<32 for item in times]
                    status.update(thread_created_utc=datetime.fromtimestamp(
                        (values[0]-116444736000000000)/10000000,timezone.utc).isoformat(),
                        thread_cpu_ms=(values[2]+values[3])/10000)
                finally:
                    if duplicate:k.CloseHandle(duplicate)
                    k.CloseHandle(source)
        # Static datatype: SILVER_RegisterOrange__ClientConnectFunction
        # 0x4f23b4 writes its sole argument into 0xacc458. The immutable global
        # 0xac5fa4 points to that function-pointer slot; 0x606080 loads it and
        # calls the registered function. These are transport bindings only.
        import pefile
        silver=mapped['silver.dll']['base']
        image=pefile.PE(str(root/'silver.dll'))
        try:
            dispatcher_rva=0x606080-0x400000
            expected=bytearray(image.get_data(dispatcher_rva,107))
            delta=silver-image.OPTIONAL_HEADER.ImageBase
            for block in image.DIRECTORY_ENTRY_BASERELOC:
                for entry in block.entries:
                    if dispatcher_rva<=entry.rva<dispatcher_rva+107:
                        require(entry.type==3 and entry.rva<=dispatcher_rva+103,
                            'Unknown native dispatcher relocation')
                        offset=entry.rva-dispatcher_rva
                        struct.pack_into('<I',expected,offset,
                            (struct.unpack_from('<I',expected,offset)[0]+delta)&0xffffffff)
            require(image.get_data(0xac5fa4-0x400000,4)==struct.pack('<I',0xacc458),
                'Unknown static transport function-pointer datatype')
            setter=next((entry for entry in image.DIRECTORY_ENTRY_EXPORT.symbols
                if entry.name==b'SILVER_RegisterOrange__ClientConnectFunction'),None)
            require(setter is not None and setter.address==0x4f23b4-0x400000 and
                image.get_data(setter.address,15)==bytes.fromhex('558bec8b4508a358c4ac005dc20400'),
                'Unknown transport binding setter; no binding metadata read')
        finally:image.close()
        require(read(silver+dispatcher_rva,107,'SILVER native transport dispatcher fingerprint')==bytes(expected),
            'Unknown relocated native transport dispatcher; no binding metadata read')
        global_pointer=struct.unpack('<I',read(silver+0xac5fa4-0x400000,4,'SILVER transport binding slot address'))[0]
        slot=silver+0xacc458-0x400000
        require(global_pointer==slot,'Unexpected transport binding slot address; no slot read')
        callee=struct.unpack('<I',read(slot,4,'SILVER transport function-pointer value'))[0]
        kind={orange+0x118f:'orange-export',target:'tls-thunk',original:'original-unpacked',
            0:'null',0x71c1b8:'ti-unicode-adapter'}.get(callee,'other')
        report['manual_transport_binding']=dict(callee=hex(callee),callee_kind=kind,
            setter_export='SILVER_RegisterOrange__ClientConnectFunction',
            native_dispatcher_fingerprint_verified=True,credential_or_ui_fields_read=False)
        report['checks']['manual_dispatch_targets_tls_route']=callee in (orange+0x118f,target)
        if callee==0x71c1b8:
            ti_image=pefile.PE(str(root/'ti.exe'))
            try:
                for address,size,purpose in ((0x71c1b8,189,'TI Unicode transport adapter fingerprint'),
                        (0x718b94,327,'TI connect dispatch fingerprint'),
                        (0x718a74,36,'TI ORANGE loader gate fingerprint')):
                    require(read(address,size,purpose)==ti_image.get_data(address-0x400000,size),
                        'Unknown native TI transport adapter; no loader count or cached connect pointer read')
                # Names/destinations are encoded in these pinned resolver calls:
                # push ebp; mov eax,slot; mov edx,UTF16-name; call 718f30.
                for index,(name,slot_address) in enumerate(LOADER_SLOTS):
                    resolver_va=0x719018+index*27
                    block=ti_image.get_data(resolver_va-0x400000,16)
                    require(block[:2]==b'\x55\xb8' and struct.unpack_from('<I',block,2)[0]==slot_address and block[6]==0xba,
                        'Unknown static ORANGE resolver slot datatype')
                    require(block[11]==0xe8 and resolver_va+16+struct.unpack_from('<i',block,12)[0]==0x718f30,
                        'Unknown static ORANGE resolver target')
                    name_address=struct.unpack_from('<I',block,7)[0]
                    require(ti_image.get_data(name_address-0x400000,12)==(name+'\0').encode('utf-16le'),
                        'Unknown static ORANGE resolver export name')
            finally:ti_image.close()
            failures=struct.unpack('<i',read(0x76da84,4,'TI missing ORANGE export count'))[0]
            cached=struct.unpack('<I',read(0x786518,4,'TI cached AaaAa connect function pointer'))[0]
            leaf={orange+0x118f:'orange-export',target:'tls-thunk',original:'original-unpacked',0:'null'}.get(cached,'other')
            report['manual_transport_binding'].update(cached_connect=hex(cached),cached_connect_kind=leaf,
                loader_export_failure_count=failures if 0<=failures<=10 else 'unrecognized')
            report['checks']['manual_loader_gate_ready']=pointer!=0 and failures<=0
            report['checks']['manual_dispatch_targets_tls_route']=cached in (orange+0x118f,target)
            if failures>0:
                missing=[]
                for name,slot_address in LOADER_SLOTS:
                    if read(slot_address,4,'TI cached export presence: '+name)==b'\0'*4:missing.append(name)
                report['manual_transport_binding']['missing_export_names']=missing
        report['checks']['process_identity_stable']=stamp(k,process)==created
        exit_code=wintypes.DWORD()
        require(k.GetExitCodeProcess(process,ctypes.byref(exit_code)),'Process exit metadata unavailable')
        report['checks']['process_alive']=exit_code.value==259
        report['passed']=all(report['checks'].values())
        return report
    finally:k.CloseHandle(process)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--login-port',type=int,required=True)
    parser.add_argument('--session-port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:report=inspect(args)
    except (OSError,ValueError) as error:
        report=dict(passed=False,pid=args.pid,error=str(error),credentials_read=False,
            memory_written=False,debugger_attached=False,network_requests=0)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','pid','error','checks','decoded_ports') if key in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
