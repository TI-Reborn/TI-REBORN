"""Read five known loading flags from two currently authenticated own QA clients.

Windows OpenProcess uses only VM_READ|QUERY_LIMITED_INFORMATION (0x1010).
Every PID must match the current bridge status and an exact marked QA path.
No native calls, instrumentation, UI, process launch, network or memory writes.
Import and --self-test open no process handles.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time

ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT/'reports/arena-surroundings-implementation/client-qa'
CURRENT = OWNED/'current-clients.json'
PINNED = {
    'ti.exe': 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
    'orange.dll': '5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589',
    'silver.dll': '7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1',
}
# Pointees independently read from the pinned original PE initialized data.
INDIRECT = {
    'load_state': (0x76deb4, 0x76dbb1),
    'load_overlay': (0x76e2ac, 0x76dab4),
    'graphics_alias': (0x76df14, 0x76dbb0),
    'modal': (0x76e1f0, 0x76dab8),
}
DIRECT_GRAPHICS = 0x76dbb0


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


def validate_status(status, pids):
    require(status.get('event') == 'graphical_status' and isinstance(status.get('clients'), list)
            and len(status['clients']) == 2, 'Current bridge must report exactly two own clients')
    require(len(pids) == len(set(pids)) == 2 and all(type(pid) is int and 0 < pid < 2**32 for pid in pids), 'Invalid own PID pair')
    require([c.get('pid') for c in status['clients']] == list(pids), 'Requested PIDs differ from current bridge status')
    names = []
    for index, client in enumerate(status['clients']):
        require(client.get('authenticated') is True and client.get('connected') is True and
                client.get('worldStartSent') is True and client.get('fault') is None and not client.get('runtime_errors'),
                'Current bridge has not authenticated this own native client')
        for key in ('loginStatus', 'serverLoginStatus', 'gameAuth1Status', 'gameAuth2Status', 'characterSelectStatus'):
            require(type(client.get(key)) is int and client[key] == 0, 'Native hosted authentication/character result is incomplete')
        server = client.get('selectedServer', {})
        require(server.get('host') == '185.184.42.88' and server.get('port') == 28513 and server.get('id') == 1,
                'Current native client selected another hosted server')
        character = client.get('selectedCharacter', {})
        name = character.get('name', '')
        require(re.fullmatch(r'qs[0-9a-f]{8}'+chr(97+index), name) is not None and
                character.get('id') == 1 and character.get('index') == 0 and character.get('unselectable') == 0,
                'Selected character is not the observed own fixture avatar')
        require(client.get('camera', {}).get('pid') == pids[index], 'Camera status PID differs')
        names.append(name)
    require(names[0][:-1] == names[1][:-1], 'Native clients belong to different QA fixtures')
    return names


def static_guard(index):
    root = (OWNED/('game-'+chr(97+index))).resolve()
    require(root.parent == OWNED.resolve(), 'QA root escaped its dedicated folder')
    marker = json.loads((root/'.tio-owned-qa').read_text(encoding='utf-8'))
    require(marker.get('schema') == 1 and marker.get('creator') == 'tools/prepare_hosted_graphical_qa.py'
            and canonical(marker.get('root', '')) == canonical(root), 'Dedicated QA marker differs')
    hashes = {}
    for name, expected in PINNED.items():
        observed = hashlib.sha256((root/name).read_bytes()).hexdigest()
        require(observed == expected, 'Pinned QA binary differs: '+name)
        hashes[name] = observed
    import pefile
    pe = pefile.PE(str(root/'ti.exe'))
    try:
        require(pe.OPTIONAL_HEADER.ImageBase == 0x400000 and pe.OPTIONAL_HEADER.DllCharacteristics & 0x40 == 0,
                'Unsupported relocated native executable')
        for address, expected in INDIRECT.values():
            require(int.from_bytes(pe.get_data(address-0x400000, 4), 'little') == expected, 'Native initialized pointer differs')
    finally:
        pe.close()
    return root, hashes


class ReadOnlyProcess:
    def __init__(self, pid, expected_executable):
        require(os.name == 'nt', 'This readonly Win32 helper requires Windows')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        self.api.OpenProcess.restype = ctypes.c_void_p
        self.api.QueryFullProcessImageNameW.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32))
        self.api.QueryFullProcessImageNameW.restype = ctypes.c_int
        self.api.ReadProcessMemory.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
        self.api.ReadProcessMemory.restype = ctypes.c_int
        self.api.CloseHandle.argtypes = (ctypes.c_void_p,)
        self.api.CloseHandle.restype = ctypes.c_int
        self.handle = self.api.OpenProcess(0x1010, 0, pid)
        require(self.handle, 'Cannot open the observed own native PID with readonly rights')
        try:
            buffer, length = ctypes.create_unicode_buffer(32768), ctypes.c_uint32(32768)
            require(self.api.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(length)), 'Cannot query own executable path')
            self.image = buffer.value
            require(canonical(self.image) == canonical(expected_executable), 'Current PID no longer belongs to the exact own QA client')
        except BaseException:
            self.close()
            raise

    def read(self, address, size):
        allowed = {address:4 for address, _ in INDIRECT.values()}
        allowed.update({address:1 for _, address in INDIRECT.values()})
        allowed[DIRECT_GRAPHICS] = 1
        require(allowed.get(address) == size, 'Read outside the fixed five native loading flags was refused')
        buffer, count = ctypes.create_string_buffer(size), ctypes.c_size_t()
        require(self.api.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(count))
                and count.value == size, 'Cannot read the fixed native loading flag')
        return buffer.raw

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def sample(reader):
    fields, pointers = {}, {}
    fields['graphics_enabled'] = reader.read(DIRECT_GRAPHICS, 1)[0]
    for name, (address, expected) in INDIRECT.items():
        pointer = struct.unpack('<I', reader.read(address, 4))[0]
        require(pointer == expected, 'Current native loading pointer differs: '+name)
        pointers[name] = dict(address=hex(address), pointee=hex(pointer))
        fields[name] = reader.read(pointer, 1)[0]
    require(fields['graphics_alias'] == fields['graphics_enabled'], 'Graphics pointer/direct alias changed during sampling')
    return dict(fields=fields, guarded_native_pointers=pointers, bytes_read=21,
                load_completed_graphics_enabled=fields['load_state'] == 4 and fields['load_overlay'] == 0
                    and fields['graphics_enabled'] == fields['graphics_alias'] == 1)


def inspect_owned(pids):
    raw = CURRENT.read_bytes()
    status = json.loads(raw)
    names = validate_status(status, pids)
    report = dict(schema='owned-native-load-state/v1', read_only=True, pid_source=str(CURRENT),
        bridge_status_sha256=hashlib.sha256(raw).hexdigest(), sampled_at_unix=time.time(),
        observed_bridge_at_unix=status.get('observed_at_unix'), process_rights='0x1010', clients=[])
    for index, pid in enumerate(pids):
        root, hashes = static_guard(index)
        reader = ReadOnlyProcess(pid, root/'ti.exe')
        try:
            report['clients'].append(dict(pid=pid, account=names[index], executable=reader.image,
                native_files_sha256=hashes, **sample(reader)))
        finally:
            reader.close()
    require(CURRENT.read_bytes() == raw, 'Current bridge status changed during sampling; retry with the fresh owned PIDs')
    return report


def self_test():
    class FakeReader:
        def __init__(self, drift=False):
            self.reads = []
            self.memory = {DIRECT_GRAPHICS:b'\x01', 0x76dbb1:b'\x04', 0x76dab4:b'\0', 0x76dab8:b'\0'}
            self.memory.update({address:struct.pack('<I', pointee) for address, pointee in INDIRECT.values()})
            if drift:
                self.memory[0x76deb4] = struct.pack('<I', 0x12345678)
        def read(self, address, size):
            self.reads.append((address, size))
            value = self.memory[address]
            require(len(value) == size, 'Invalid fake fixed field size')
            return value
    reader = FakeReader()
    result = sample(reader)
    require(result['load_completed_graphics_enabled'] and sum(size for _, size in reader.reads) == 21,
            'Fixed readonly loading sample failed')
    checks = 1
    reader = FakeReader(drift=True)
    try:
        sample(reader)
    except ValueError:
        require(not any(address == 0x12345678 for address, size in reader.reads), 'Drifted pointer was dereferenced')
        checks += 1
    else:
        raise AssertionError('Changed native pointer was accepted')
    status = dict(event='graphical_status', clients=[])
    for index, pid in enumerate((11196, 29280)):
        status['clients'].append(dict(pid=pid, authenticated=True, connected=True, worldStartSent=True,
            fault=None, runtime_errors=[], loginStatus=0, serverLoginStatus=0, gameAuth1Status=0, gameAuth2Status=0,
            characterSelectStatus=0, selectedServer=dict(host='185.184.42.88', port=28513, id=1),
            selectedCharacter=dict(name='qs01234567'+chr(97+index), id=1, index=0, unselectable=0), camera=dict(pid=pid)))
    validate_status(status, (11196, 29280));checks += 1
    for mutate in (
        lambda s: s['clients'][0].update(pid=77),
        lambda s: s['clients'][0].update(authenticated=False),
        lambda s: s['clients'][1]['selectedCharacter'].update(name='actual_user'),
        lambda s: s['clients'][1]['selectedServer'].update(host='127.0.0.1'),
    ):
        bad = json.loads(json.dumps(status));mutate(bad)
        try:
            validate_status(bad, (11196, 29280))
        except ValueError:
            checks += 1
        else:
            raise AssertionError('Foreign/unauthenticated native PID status was accepted')
    print(json.dumps(dict(offline_self_test='passed', checks=checks, process_handles_opened=0, server_contacted=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pids', type=int, nargs=2)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        require(args.pids is not None, 'The two explicit PIDs from current-clients.json are required')
        report = inspect_owned(args.pids)
        path = OWNED/('native-load-state-'+str(args.pids[0])+'-'+str(args.pids[1])+'-'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(report=str(path), **report)))
