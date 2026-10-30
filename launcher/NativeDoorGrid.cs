using System.Runtime.InteropServices;
using System.Text.Json;
using System.Security.Cryptography;

namespace TioLauncher;

// The immutable ti.exe is SHA-pinned by GameStarter. Apply while the main
// thread is stopped at CREATE_PROCESS, before any native scene can run.
static class NativeDoorGrid
{
    internal sealed record Relocation(int Offset,uint Target);
    internal sealed record Adapter(string Code,int FogEntry,int DoorEntry,Relocation[] Relocations);
    internal static readonly Adapter Plan=Load();
    static Adapter Load()
    {
        using var stream=typeof(NativeDoorGrid).Assembly.GetManifestResourceStream("TioLauncher.native-door-grid.json")!;
        return JsonSerializer.Deserialize<Adapter>(stream,Updater.Json)!;
    }
    internal static byte[] Build(uint allocation)
    {
        byte[] code=Convert.FromHexString(Plan.Code);
        foreach(var relocation in Plan.Relocations)
            BitConverter.GetBytes(unchecked((int)(relocation.Target-allocation-(uint)relocation.Offset-4)))
                .CopyTo(code,relocation.Offset);
        return code;
    }
    internal static byte[] Jump(uint source,uint target)
    {
        byte[] result=[0xe9,0,0,0,0,0x90];
        BitConverter.GetBytes(unchecked((int)(target-source-5))).CopyTo(result,1);
        return result;
    }
    internal static byte[] ReconMarkerJump(uint silver) => Jump(silver+0x87920c,silver+0x87922c);
    [DllImport("kernel32",SetLastError=true)]
    static extern IntPtr VirtualAllocEx(IntPtr process,IntPtr address,nuint size,uint allocation,uint protection);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] data,nuint size,out nuint count);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool VirtualProtectEx(IntPtr process,IntPtr address,nuint size,uint protection,out uint previous);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool FlushInstructionCache(IntPtr process,IntPtr address,nuint size);

    internal static uint Apply(IntPtr process,uint module)
    {
        // This executable and the existing route both use its fixed base.
        if(module!=0x400000) throw new InvalidDataException("Unsupported native game image base.");
        IntPtr memory=VirtualAllocEx(process,IntPtr.Zero,4096,0x3000,0x04);
        if(memory==IntPtr.Zero || memory.ToInt64()>uint.MaxValue)
            throw new IOException("Cannot allocate native door adapter.");
        uint allocation=checked((uint)memory.ToInt64());byte[] code=Build(allocation);
        if(!WriteProcessMemory(process,memory,code,(nuint)code.Length,out var count) || count!=(nuint)code.Length ||
            !VirtualProtectEx(process,memory,4096,0x20,out _) || !FlushInstructionCache(process,memory,(nuint)code.Length))
            throw new IOException("Cannot initialize native door adapter.");
        NativeTlsRoute.GuardedPatch(process,0x6e40a4,Convert.FromHexString("558bec83c4d0"),
            Jump(0x6e40a4,allocation+(uint)Plan.FogEntry));
        NativeTlsRoute.GuardedPatch(process,0x72dc90,Convert.FromHexString("558bec83c4e0"),
            Jump(0x72dc90,allocation+(uint)Plan.DoorEntry));
        return allocation;
    }

    // F7 snapshots already contain only the recipient's authoritative visible
    // cells. Bind the exact known reader; older Silver releases keep their
    // existing behavior until the client updater supplies the current image.
    internal static bool BindRecon(IntPtr process,uint allocation,uint silver,string image)
    {
        using var file=File.OpenRead(image);
        if(NativePasswordLimit.CompatibilityHash(File.ReadAllBytes(image))!="717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625") return false;
        byte[] pointers=new byte[8];
        BitConverter.GetBytes(checked(silver+0x818bf8)).CopyTo(pointers,0);
        BitConverter.GetBytes(checked(silver+0x818c00)).CopyTo(pointers,4);
        NativeTlsRoute.GuardedPatch(process,allocation+0xf00,new byte[8],pointers);
        uint tail=checked(silver+0x8798a7);
        byte[] hook=new byte[8];Array.Fill(hook,(byte)0x90);
        Jump(tail,allocation+0x800).CopyTo(hook,0);
        NativeTlsRoute.GuardedPatch(process,tail,Convert.FromHexString("c744241c01000000"),hook);
        // Recon changes native fog only. Skip the legacy beige marker draw;
        // smoke, fire, flare and light keep their normal renderer branches.
        NativeTlsRoute.GuardedPatch(process,silver+0x87920c,Convert.FromHexString("8b042483e808"),
            ReconMarkerJump(silver));
        NativeThrowableEffects.Apply(process,silver,image);
        NativeFriendsDialogue.Apply(process,silver);
        NativeFlameStream.Apply(process,silver,image);
        NativeRainWeather.Apply(process,silver,image);
        NativeGroundLoot.Apply(process,silver);
        NativeContractsUi.Install(process,silver,image);
        return true;
    }
}
