using System.Runtime.InteropServices;
using System.Text.Json;

namespace TioLauncher;

// ti.exe is SHA-pinned by GameStarter. Only the end of the native YourTurn
// event is extended, before normal input resumes. Manual selection is unchanged.
static class NativeBattleTurn
{
    internal sealed record Relocation(int Offset, uint Target);
    internal sealed record Adapter(string Code, Relocation[] Relocations);
    internal static readonly Adapter Plan = Load();
    static Adapter Load()
    {
        using var stream = typeof(NativeBattleTurn).Assembly.GetManifestResourceStream("TioLauncher.native-battle-turn.json")!;
        return JsonSerializer.Deserialize<Adapter>(stream, Updater.Json)!;
    }
    internal static byte[] Build(uint allocation)
    {
        byte[] code = Convert.FromHexString(Plan.Code);
        foreach (var relocation in Plan.Relocations)
            BitConverter.GetBytes(unchecked((int)(relocation.Target - allocation - (uint)relocation.Offset - 4)))
                .CopyTo(code, relocation.Offset);
        return code;
    }
    [DllImport("kernel32", SetLastError = true)]
    static extern IntPtr VirtualAllocEx(IntPtr process, IntPtr address, nuint size, uint allocation, uint protection);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool WriteProcessMemory(IntPtr process, IntPtr address, byte[] data, nuint size, out nuint count);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool VirtualProtectEx(IntPtr process, IntPtr address, nuint size, uint protection, out uint previous);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool FlushInstructionCache(IntPtr process, IntPtr address, nuint size);

    internal static void Apply(IntPtr process, uint module)
    {
        if (module != 0x400000) throw new InvalidDataException("Unsupported native game image base.");
        IntPtr memory = VirtualAllocEx(process, IntPtr.Zero, 4096, 0x3000, 0x04);
        if (memory == IntPtr.Zero || memory.ToInt64() > uint.MaxValue)
            throw new IOException("Cannot allocate native turn adapter.");
        uint allocation = checked((uint)memory.ToInt64()); byte[] code = Build(allocation);
        if (!WriteProcessMemory(process, memory, code, (nuint)code.Length, out var count) || count != (nuint)code.Length ||
            !VirtualProtectEx(process, memory, 4096, 0x20, out _) || !FlushInstructionCache(process, memory, (nuint)code.Length))
            throw new IOException("Cannot initialize native turn adapter.");
        byte[] jump = NativeDoorGrid.Jump(0x71da3d, allocation)[..5];
        NativeTlsRoute.GuardedPatch(process, 0x71da3d, Convert.FromHexString("e9c60f0000"), jump);
    }
}
