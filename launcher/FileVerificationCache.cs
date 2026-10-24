using System.Buffers.Binary;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace TioLauncher;

// ChangeTime catches same-size edits even if LastWriteTime was restored. FileId
// catches replacements. LastAccessTime is deliberately excluded (reads change it).
internal sealed record FileStamp(ulong Volume, string Id, long Created, long Written, long Changed, long Size, uint Attributes);
internal sealed record VerifiedFile(string Sha256, FileStamp Stamp, long VerifiedUtcTicks);
internal sealed record VerificationState(int Schema, string Root, Dictionary<string, VerifiedFile> Files);

internal static class FileMetadata
{
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFileW(string name, uint access, uint sharing, IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int kind, [Out] byte[] buffer, uint size);
    static long I64(byte[] b, int p) => BinaryPrimitives.ReadInt64LittleEndian(b.AsSpan(p));
    static uint U32(byte[] b, int p) => BinaryPrimitives.ReadUInt32LittleEndian(b.AsSpan(p));
    static bool Query(SafeFileHandle h, int kind, byte[] b) => GetFileInformationByHandleEx(h,kind,b,(uint)b.Length);
    static bool Usable(FileStamp s) => s.Changed > 0 && s.Created > 0 && s.Id != new string('0',32);

    internal static FileStamp? Read(SafeFileHandle handle)
    {
        byte[] basic=new byte[40], standard=new byte[24], id=new byte[24];
        if (!Query(handle,0,basic) || !Query(handle,1,standard) || !Query(handle,18,id)) return null;
        var stamp=new FileStamp(BinaryPrimitives.ReadUInt64LittleEndian(id),Convert.ToHexStringLower(id.AsSpan(8,16)),
            I64(basic,0),I64(basic,16),I64(basic,24),I64(standard,8),U32(basic,32));
        return Usable(stamp) ? stamp : null;
    }

    // FILE_ID_EXTD_DIR_INFO: one directory query returns stamps for many files.
    // https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_id_extd_dir_info
    // Unsupported filesystems fall back to hashing, never to size/mtime alone.
    internal static Dictionary<string,FileStamp>? Directory(string path, CancellationToken token)
    {
        using var handle=CreateFileW(path,0x81,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
        if (handle.IsInvalid) return null;
        byte[] id=new byte[24];
        if (!Query(handle,18,id)) return null;
        ulong volume=BinaryPrimitives.ReadUInt64LittleEndian(id);
        byte[] buffer=new byte[65536];
        var entries=new Dictionary<string,FileStamp>(StringComparer.OrdinalIgnoreCase);
        bool first=true;
        while (true)
        {
            token.ThrowIfCancellationRequested();
            if (!Query(handle,first ? 20 : 19,buffer))
                return Marshal.GetLastWin32Error()==18 ? entries : null; // ERROR_NO_MORE_FILES
            first=false; int offset=0;
            while (true)
            {
                if (offset > buffer.Length-88) return null;
                uint next=U32(buffer,offset), length=U32(buffer,offset+60);
                if ((length&1)!=0 || length > buffer.Length-offset-88) return null;
                string name=Encoding.Unicode.GetString(buffer,offset+88,(int)length);
                var stamp=new FileStamp(volume,Convert.ToHexStringLower(buffer.AsSpan(offset+72,16)),
                    I64(buffer,offset+8),I64(buffer,offset+24),I64(buffer,offset+32),I64(buffer,offset+40),U32(buffer,offset+56));
                if (name is not ("." or ".."))
                    if (!Usable(stamp) || !entries.TryAdd(name,stamp)) return null;
                if (next==0) break;
                if (next < 88+length || next > buffer.Length-offset-88) return null;
                offset+=(int)next;
            }
        }
    }
}

internal sealed class FileVerificationCache
{
    readonly string root;
    readonly Dictionary<string,VerifiedFile> files;
    internal bool Dirty;
    internal FileVerificationCache(string root, byte[]? bytes)
    {
        this.root=root;
        try
        {
            var state=bytes==null ? null : JsonSerializer.Deserialize<VerificationState>(bytes,Updater.Json);
            files=state is {Schema:1,Files:not null} && state.Files.Count<=20000 && string.Equals(state.Root,root,StringComparison.OrdinalIgnoreCase)
                ? new(state.Files,StringComparer.OrdinalIgnoreCase) : new(StringComparer.OrdinalIgnoreCase);
        }
        catch (JsonException) { files=new(StringComparer.OrdinalIgnoreCase); }
        catch (ArgumentException) { files=new(StringComparer.OrdinalIgnoreCase); }
    }
    internal bool Matches(ReleaseFile file, FileStamp? stamp)
    {
        if (stamp==null || !files.TryGetValue(file.Path,out var known) || known==null) return false;
        long age=DateTime.UtcNow.Ticks-known.VerifiedUtcTicks;
        return age>=0 && age<=TimeSpan.FromDays(7).Ticks && known.Sha256==file.Sha256 && known.Stamp==stamp && stamp.Size==file.Size;
    }
    internal void Remember(ReleaseFile file, FileStamp? stamp)
    {
        if (stamp==null) { Forget(file.Path); return; }
        files[file.Path]=new(file.Sha256,stamp,DateTime.UtcNow.Ticks);Dirty=true;
    }
    internal void Forget(string path) { if (files.Remove(path)) Dirty=true; }
    internal byte[] Serialize(Release release)
    {
        var present=release.Files.Select(f=>f.Path).ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var path in files.Keys.Where(p=>!present.Contains(p)).ToArray()) files.Remove(path);
        return JsonSerializer.SerializeToUtf8Bytes(new VerificationState(1,root,files));
    }
}
