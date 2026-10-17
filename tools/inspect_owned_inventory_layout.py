"""One bounded read-only category-layout diagnostic for the exact owned QA PID.

No hooks, remote calls, control handlers, writes, process launch, or network.
"""
from pathlib import Path
import ctypes
import datetime as dt
import hashlib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.inspect_native_tls_route import api, modules, stamp, require

PID = 28708
CREATED = '2026-10-09T17:37:37.336622+00:00'
SILVER_SHA = 'af023ada9cc049cfc384b73bb11511629bdf43e683e42bae20c1d04d70bfbe87'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
OWNED = ROOT/'reports/arena-surroundings-implementation/client-qa/game-a'


def main():
    marker = json.loads((OWNED/'.tio-owned-qa').read_text())
    require(marker.get('creator') == 'tools/prepare_hosted_graphical_qa.py'
            and Path(marker['root']).resolve() == OWNED.resolve(), 'Exact owned marker differs')
    for name, sha in (('ti.exe', TI_SHA), ('silver.dll', SILVER_SHA)):
        require(hashlib.sha256((OWNED/name).read_bytes()).hexdigest() == sha, 'Owned file hash differs: '+name)
    k = api()
    process = k.OpenProcess(0x1010, False, PID)
    require(process, 'The exact owned PID is unavailable')
    try:
        epoch = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
        delta = dt.datetime.fromisoformat(CREATED)-epoch
        expected_stamp = (delta.days*86400+delta.seconds)*10_000_000+delta.microseconds*10
        observed_stamp = stamp(k, process)
        # Win32_Process CreationDate supplied by the owned harness has microsecond
        # precision; FILETIME additionally contains the final 100-ns digit.
        require(observed_stamp//10 == expected_stamp//10, 'Owned PID creation time differs')
        loaded = modules(k, PID)
        require(loaded['ti.exe']['path'] == (OWNED/'ti.exe').resolve()
                and loaded['silver.dll']['path'] == (OWNED/'silver.dll').resolve(), 'Owned loaded paths differ')
        base, image_size = loaded['silver.dll']['base'], loaded['silver.dll']['image_size']
        reads = []
        def read(address, size):
            require(0x10000 <= address <= 0x7fffffff and 0 < size <= 1024, 'Pointer/size outside bounded read policy')
            buf, count = ctypes.create_string_buffer(size), ctypes.c_size_t()
            require(k.ReadProcessMemory(process, address, buf, size, ctypes.byref(count))
                    and count.value == size, 'Bounded GUI read failed')
            reads.append((address, size))
            require(sum(n for _, n in reads) <= 40000, 'Bounded GUI byte budget exceeded')
            return buf.raw
        def u32(address): return struct.unpack('<I', read(address, 4))[0]
        def managed(pointer):
            if not pointer: return ''
            n = u32(pointer-4)
            if n > 160: return '<length outside name bound>'
            return read(pointer, max(2, n*2)).decode('utf-16le').rstrip('\0')
        visited = set()
        def control(pointer, depth):
            require(pointer not in visited and len(visited) < 96, 'Cyclic/oversized child graph')
            visited.add(pointer)
            data = read(pointer, 0x78)
            vmt = struct.unpack_from('<I', data)[0]
            require(base <= vmt < base+image_size, 'Control VMT outside exact Silver module')
            nameptr = u32(vmt-0x38)
            classname_length = read(nameptr, 1)[0]
            require(classname_length <= 120, 'Invalid native classname length')
            classname = read(nameptr+1, max(1, classname_length)).decode('ascii', errors='replace')
            row = dict(object=hex(pointer), vmt=hex(vmt-base+0x400000), classname=classname,
                name=managed(struct.unpack_from('<I', data, 0x68)[0]),
                parent=hex(struct.unpack_from('<I', data, 0x4c)[0]),
                visible=data[0x49], enabled=data[0x4a],
                x=struct.unpack_from('<i',data,0x30)[0], y=struct.unpack_from('<i',data,0x34)[0],
                width=struct.unpack_from('<i',data,0x38)[0], height=struct.unpack_from('<i',data,0x3c)[0])
            children = struct.unpack_from('<I', data, 0x2c)[0]
            if depth and children:
                array, count = u32(children+4), u32(children+8)
                require(count <= 80 and (not count or array), 'Oversized native child list')
                if count:
                    refs = struct.unpack('<'+'I'*count, read(array, count*4))
                    row['children'] = [control(p,depth-1) for p in refs if p]
            return row
        right = u32(base+0xad10a4-0x400000)
        require(right and u32(right) == base+0xa2bf58-0x400000, 'Native right table-panel VMT differs')
        tree = control(right,2)
        require(stamp(k,process) == observed_stamp, 'Owned PID metadata changed during diagnostic')
        report = dict(schema='owned-inventory-layout/v1', read_only=True, process_rights='0x1010',
            pid=PID, creation_utc=CREATED, creation_filetime=observed_stamp, silver_sha256=SILVER_SHA,
            silver_base=hex(base), bytes_read=sum(n for _, n in reads), reads=len(reads), tree=tree)
        path=ROOT/'reports/ui-modernization/graphical/owned-right-tab-28708.json'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(report=str(path), controls=len(visited), bytes_read=report['bytes_read'])))
    finally:
        k.CloseHandle(process)


if __name__ == '__main__': main()
