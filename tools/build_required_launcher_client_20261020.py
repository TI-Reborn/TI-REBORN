"""Replace native application icons and add a fail-closed pre-CRT entry gate."""
import ctypes,hashlib,json,struct
from ctypes import wintypes
from pathlib import Path
import pefile
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/launcher-required-20261020';OUT=ROOT/'reports/launcher-required-20261020'
SOURCE='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'

def sha(b):return hashlib.sha256(b).hexdigest()
def align(n,a):return (n+a-1)//a*a

def icons(path,ico):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    begin=kernel.BeginUpdateResourceW;begin.argtypes=[wintypes.LPCWSTR,wintypes.BOOL];begin.restype=wintypes.HANDLE
    update=kernel.UpdateResourceW;update.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD];update.restype=wintypes.BOOL
    end=kernel.EndUpdateResourceW;end.argtypes=[wintypes.HANDLE,wintypes.BOOL];end.restype=wintypes.BOOL
    pe=pefile.PE(str(path));groups=[]
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id==14:
            for name in entry.directory.entries:
                for lang in name.directory.entries:groups.append((str(name.name) if name.name else name.id,lang.id))
    pe.close();assert groups
    zero,kind,count=struct.unpack_from('<HHH',ico);assert (zero,kind)==(0,1)
    group=bytearray(struct.pack('<HHH',0,1,count));blobs=[]
    for index in range(count):
        w,h,c,r,planes,bits,size,offset=struct.unpack_from('<BBBBHHII',ico,6+16*index)
        group+=struct.pack('<BBBBHHIH',w,h,c,r,planes,bits,size,5000+index)
        blobs.append(ico[offset:offset+size]);assert len(blobs[-1])==size
    handle=begin(str(path),False)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        for lang in sorted({lang for _,lang in groups}):
            for index,blob in enumerate(blobs):
                buf=ctypes.create_string_buffer(blob)
                if not update(handle,3,5000+index,lang,buf,len(blob)):raise ctypes.WinError(ctypes.get_last_error())
        buf=ctypes.create_string_buffer(bytes(group))
        for name,lang in groups:
            resource=ctypes.cast(ctypes.c_wchar_p(name),ctypes.c_void_p) if isinstance(name,str) else name
            if not update(handle,14,resource,lang,buf,len(group)):raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:end(handle,True);raise
    if not end(handle,False):raise ctypes.WinError(ctypes.get_last_error())
    return dict(groups=groups,images=count,ico_sha256=sha(ico))

def gate(source):
    pe=pefile.PE(data=source)
    assert pe.OPTIONAL_HEADER.ImageBase==0x400000 and pe.OPTIONAL_HEADER.AddressOfEntryPoint==0x358f6c
    section=pe.sections[-1];assert section.Name.rstrip(b'\0')==b'.rsrc'
    assert section.PointerToRawData+section.SizeOfRawData==len(source)
    rva=section.VirtualAddress+section.SizeOfRawData
    # call/pop obtains the actual image base, including rebased loads.
    code=bytearray(b'\xe8\0\0\0\0\x5b\x81\xeb'+struct.pack('<I',rva+5))
    code+=b'\x6a\x10\x8d\x83'+struct.pack('<I',rva+128)+b'\x50\x8d\x83'+struct.pack('<I',rva+192)+b'\x50\x6a\0'
    code+=b'\xff\x93'+struct.pack('<I',0x388f54)+b'\x6a\x01\xff\x93'+struct.pack('<I',0x388ddc)+b'\xcc'
    payload=bytearray(1024);payload[:len(code)]=code
    title='TIO Online\0'.encode('utf-16le');text='Запускайте игру через TIO Launcher.\nЛаунчер должен проверить и установить обновления перед входом.\0'.encode('utf-16le')
    payload[128:128+len(title)]=title;payload[192:192+len(text)]=text
    result=bytearray(source)+payload
    at=section.get_file_offset();struct.pack_into('<I',result,at+8,section.SizeOfRawData+len(payload));struct.pack_into('<I',result,at+16,section.SizeOfRawData+len(payload));struct.pack_into('<I',result,at+36,0x60000040)
    opt=pe.OPTIONAL_HEADER.get_file_offset();struct.pack_into('<I',result,opt+16,rva);struct.pack_into('<I',result,opt+56,align(rva+len(payload),pe.OPTIONAL_HEADER.SectionAlignment));struct.pack_into('<I',result,opt+64,0)
    return bytes(result),dict(guard_rva=rva,original_entry=0x358f6c,guard_prefix='e800000000',payload=payload.hex())

def main():
    source=(WORK/'ti-before.exe').read_bytes();assert sha(source)==SOURCE
    path=WORK/'ti.exe';path.write_bytes(source)
    icon=icons(path,(ROOT/'launcher/Assets/tio-launcher.ico').read_bytes())
    after_icon=path.read_bytes();raw,plan=gate(after_icon);path.write_bytes(raw)
    # All original code sections are preserved; only resource layout and the
    # explicit PE entry/header changes differ. No login or gameplay code edits.
    a=pefile.PE(data=source);b=pefile.PE(data=raw)
    for old,new in zip(a.sections[:-1],b.sections[:-1]):
        assert old.get_data()==new.get_data(),old.Name
    plan.update(before_sha256=sha(source),after_sha256=sha(raw),size=len(raw),icon=icon,original_code_sections_preserved=True)
    (OUT/'native-gate-plan.json').write_text(json.dumps(plan,indent=2))
    cs='''namespace TioLauncher;
internal static class NativeLaunchGate
{
    internal const string ImageSha256 = "%s";
    internal const uint GuardRva = 0x%x;
    internal static void Release(IntPtr process, uint imageBase, GameLaunchProfile? profile)
    {
        if (profile?.Verification is null) throw new InvalidDataException("Запускайте игру через TIO Launcher с проверкой обновлений.");
        byte[] jump = new byte[5]; jump[0] = 0xe9;
        BitConverter.GetBytes(unchecked((int)(0x358f6c - GuardRva - 5))).CopyTo(jump, 1);
        NativeTlsRoute.GuardedPatch(process, imageBase + GuardRva, Convert.FromHexString("e800000000"), jump);
    }
}
'''%(sha(raw),plan['guard_rva'])
    (ROOT/'launcher/NativeLaunchGate.cs').write_text(cs,encoding='utf-8')
    print(json.dumps({k:v for k,v in plan.items() if k!='payload'}))

if __name__=='__main__':main()
