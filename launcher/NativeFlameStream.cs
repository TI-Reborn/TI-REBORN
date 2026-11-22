using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

// Finite server-authoritative flame visuals. Bind only after the existing
// throwable/recon adapters, on the exact immutable published Silver image.
static class NativeFlameStream
{
    internal sealed record Relocation(int Offset,uint Target);
    internal sealed record Hook(uint Rva,string Before,uint Entry);
    internal sealed record Adapter(string Sha256,string Code,Relocation[] Relocations,
        int Size,int SilverPointer,Hook[] Hooks);
    internal static readonly Adapter Plan=Load();
    static Adapter Load()
    {
        using var stream=typeof(NativeFlameStream).Assembly.GetManifestResourceStream("TioLauncher.native-flame-stream.json")!;
        var plan=JsonSerializer.Deserialize<Adapter>(stream,Updater.Json)!;
        if(plan.Size!=0xc000 || plan.SilverPointer!=0x7000 || plan.Code.Length!=0x2000 || plan.Hooks.Length!=4)
            throw new InvalidDataException("Unsupported flame adapter layout.");
        return plan;
    }
    internal static byte[] Build(uint allocation,uint silver)
    {
        var code=Convert.FromHexString(Plan.Code);
        foreach(var r in Plan.Relocations)
            BitConverter.GetBytes(unchecked(silver+r.Target-allocation-(uint)r.Offset-4)).CopyTo(code,r.Offset);
        return code;
    }
    [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr process,IntPtr address,nuint size,uint allocation,uint protection);
    [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] data,nuint size,out nuint count);
    [DllImport("kernel32",SetLastError=true)] static extern bool VirtualProtectEx(IntPtr process,IntPtr address,nuint size,uint protection,out uint previous);
    [DllImport("kernel32",SetLastError=true)] static extern bool FlushInstructionCache(IntPtr process,IntPtr address,nuint size);
    internal static bool Apply(IntPtr process,uint silver,string image)
    {
        using var file=File.OpenRead(image);
        if(!SilverRegions.Matches(File.ReadAllBytes(image),"flame"))return false;
        var memory=VirtualAllocEx(process,IntPtr.Zero,(nuint)Plan.Size,0x3000,0x04);
        if(memory==IntPtr.Zero || memory.ToInt64()>uint.MaxValue)throw new IOException("Cannot allocate flame stream adapter.");
        uint allocation=checked((uint)memory.ToInt64());var code=Build(allocation,silver);
        if(!WriteProcessMemory(process,memory,code,(nuint)code.Length,out var count) || count!=(nuint)code.Length ||
           !WriteProcessMemory(process,memory+Plan.SilverPointer,BitConverter.GetBytes(silver),4,out count) || count!=4 ||
           !VirtualProtectEx(process,memory,0x6000,0x20,out _) || !FlushInstructionCache(process,memory,(nuint)code.Length))
            throw new IOException("Cannot initialize flame stream adapter.");
        foreach(var hook in Plan.Hooks)
        {
            var before=Convert.FromHexString(hook.Before);
            // Existing extension JMP displacements do not change with ASLR.
            var after=Enumerable.Repeat((byte)0x90,before.Length).ToArray();
            NativeDoorGrid.Jump(silver+hook.Rva,allocation+hook.Entry)[..5].CopyTo(after,0);
            NativeTlsRoute.GuardedPatch(process,silver+hook.Rva,before,after);
        }
        return true;
    }
}
