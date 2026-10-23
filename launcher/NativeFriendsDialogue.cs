using System.Runtime.InteropServices;

namespace TioLauncher;

// Guarded by the Silver hash in NativeDoorGrid.BindRecon. Reset the shared
// Yes/No dialog before attaching its captured friend-name callback.
static class NativeFriendsDialogue
{
    [DllImport("kernel32",SetLastError=true)]
    static extern IntPtr VirtualAllocEx(IntPtr process,IntPtr address,nuint size,uint allocation,uint protection);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] data,nuint size,out nuint count);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool VirtualProtectEx(IntPtr process,IntPtr address,nuint size,uint protection,out uint previous);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool FlushInstructionCache(IntPtr process,IntPtr address,nuint size);
    static byte[] Branch(byte opcode,uint source,uint target) =>
        new[]{opcode}.Concat(BitConverter.GetBytes(unchecked((int)(target-source-5)))).ToArray();
    internal static byte[] Build(uint allocation,uint silver)
    {
        var code=new List<byte>(Convert.FromHexString("50525131c031d231c9"));
        code.AddRange(Branch(0xe8,allocation+(uint)code.Count,silver+0x288798));
        code.AddRange(Convert.FromHexString("595a58"));
        code.AddRange(Branch(0xe9,allocation+(uint)code.Count,silver+0x654f40));
        return code.ToArray();
    }
    internal static void Apply(IntPtr process,uint silver)
    {
        var memory=VirtualAllocEx(process,IntPtr.Zero,4096,0x3000,0x04);
        if(memory==IntPtr.Zero || memory.ToInt64()>uint.MaxValue) throw new IOException("Cannot allocate friends dialog adapter.");
        uint allocation=checked((uint)memory.ToInt64());var code=Build(allocation,silver);
        if(!WriteProcessMemory(process,memory,code,(nuint)code.Length,out var count) || count!=(nuint)code.Length ||
            !VirtualProtectEx(process,memory,4096,0x20,out _) || !FlushInstructionCache(process,memory,(nuint)code.Length))
            throw new IOException("Cannot initialize friends dialog adapter.");
        foreach(uint rva in new uint[]{0x604451,0x6047ed})
            NativeTlsRoute.GuardedPatch(process,silver+rva,Branch(0xe8,silver+rva,silver+0x654f40),Branch(0xe8,silver+rva,allocation));
        // Incoming invitations also offer only Yes and No.
        NativeTlsRoute.GuardedPatch(process,silver+0x3f49f9,new byte[]{0xb9}.Concat(BitConverter.GetBytes(silver+0x3f4928)).ToArray(),Convert.FromHexString("31c9909090"));
    }
}
