using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;

namespace TioLauncher;

internal sealed record GameLaunchProfile(int LoginPort, int SessionPort, bool OwnedQa = false, LaunchVerification? Verification = null, string Interface = GameInterface.New);

internal static class NativeTlsRoute
{
    const uint ExportRva = 0x118f;
    [DllImport("kernel32", SetLastError = true)]
    static extern IntPtr VirtualAllocEx(IntPtr process, IntPtr address, nuint size, uint allocation, uint protection);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool VirtualProtectEx(IntPtr process, IntPtr address, nuint size, uint protection, out uint previous);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] data, nuint size, out nuint count);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool WriteProcessMemory(IntPtr process, IntPtr address, byte[] data, nuint size, out nuint count);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool FlushInstructionCache(IntPtr process, IntPtr address, nuint size);
    [StructLayout(LayoutKind.Sequential)]
    struct MemoryRegion
    {
        public IntPtr BaseAddress, AllocationBase;
        public uint AllocationProtect;
        public nuint RegionSize;
        public uint State, Protect, Type;
    }
    [DllImport("kernel32", SetLastError = true)]
    static extern nuint VirtualQueryEx(IntPtr process, IntPtr address, out MemoryRegion region, nuint length);

    internal static void ValidateImage(string path)
    {
        byte[] image = File.ReadAllBytes(path);
        int pe = BitConverter.ToInt32(image, 0x3c), optional = pe + 24;
        if (BitConverter.ToUInt32(image, pe) != 0x4550 || BitConverter.ToUInt16(image, optional) != 0x10b)
            throw new InvalidDataException(L.Text("Неподдерживаемый ORANGE PE."));
        int sections = optional + BitConverter.ToUInt16(image, pe + 20);
        int Offset(uint rva)
        {
            for (int i = 0; i < BitConverter.ToUInt16(image, pe + 6); i++)
            {
                int section = sections + i * 40;
                uint va = BitConverter.ToUInt32(image, section + 12);
                uint size = BitConverter.ToUInt32(image, section + 16);
                if (rva >= va && rva - va < size)
                    return checked((int)(BitConverter.ToUInt32(image, section + 20) + rva - va));
            }
            throw new InvalidDataException(L.Text("ORANGE RVA не принадлежит файлу."));
        }
        int exports = Offset(BitConverter.ToUInt32(image, optional + 96));
        int count = checked((int)BitConverter.ToUInt32(image, exports + 24));
        int names = Offset(BitConverter.ToUInt32(image, exports + 32));
        int ordinals = Offset(BitConverter.ToUInt32(image, exports + 36));
        int functions = Offset(BitConverter.ToUInt32(image, exports + 28));
        for (int i = 0; i < count; i++)
        {
            int name = Offset(BitConverter.ToUInt32(image, names + 4 * i));
            int end = Array.IndexOf(image, (byte)0, name);
            if (Encoding.ASCII.GetString(image, name, end - name) != "AaaAa") continue;
            uint rva = BitConverter.ToUInt32(image, functions + 4 * BitConverter.ToUInt16(image, ordinals + 2 * i));
            if (rva != ExportRva || !image.AsSpan(Offset(rva), 5).SequenceEqual(Convert.FromHexString("e9dc040000")))
                throw new InvalidDataException(L.Text("Неизвестная точка подключения ORANGE."));
            return;
        }
        throw new InvalidDataException(L.Text("Точка подключения ORANGE отсутствует."));
    }

    // AaaAa is cdecl(host, port, opaque, mode). Save flags/EAX, replace just
    // the two destination arguments, restore machine state and jump to the
    // original implementation. All GUI and reconnect callers use this export.
    internal static byte[] BuildThunk(uint address, uint host, uint target, int loginPort, int sessionPort)
    {
        _ = TlsBridge.LoginPreface(loginPort);
        _ = TlsBridge.LoginPreface(sessionPort);
        var bytes = new List<byte> { 0x9c, 0x50, 0xc7, 0x44, 0x24, 0x0c };
        bytes.AddRange(BitConverter.GetBytes(host));
        // Original Silver/TI callers push a byte mode in EAX without clearing
        // its upper 24 bits. ORANGE consumes only AL; use the same byte width.
        // CMP AL,imm8 keeps the guarded size and all operand offsets intact.
        bytes.AddRange(new byte[] { 0x8b, 0x44, 0x24, 0x18, 0x80, 0xf8, 0, 0xb8 });
        bytes.AddRange(BitConverter.GetBytes(loginPort));
        bytes.AddRange(new byte[] { 0x74, 0x05, 0xb8 });
        bytes.AddRange(BitConverter.GetBytes(sessionPort));
        bytes.AddRange(new byte[] { 0x89, 0x44, 0x24, 0x10, 0x58, 0x9d, 0xe9 });
        bytes.AddRange(BitConverter.GetBytes(unchecked(target - (address + (uint)bytes.Count + 4))));
        return bytes.ToArray();
    }

    static byte[] Read(IntPtr process, uint address, int size)
    {
        byte[] bytes = new byte[size];
        if (!ReadProcessMemory(process, new IntPtr(address), bytes, (nuint)size, out var count) || count != (nuint)size)
            throw new IOException(L.Text("Не удалось проверить защищённый маршрут игры."));
        return bytes;
    }
    static void Write(IntPtr process, uint address, byte[] bytes)
    {
        if (!WriteProcessMemory(process, new IntPtr(address), bytes, (nuint)bytes.Length, out var count) || count != (nuint)bytes.Length)
            throw new IOException(L.Text("Не удалось установить защищённый маршрут игры."));
    }
    internal static uint RemoteExport(IntPtr process, ProcessModule[] modules, string moduleName, string exportName, int depth = 0)
    {
        if (depth > 4) throw new InvalidDataException(L.Text("Слишком длинный системный переход API."));
        var module = modules.Single(m => m.BaseAddress.ToInt64() > 0 && m.BaseAddress.ToInt64() <= uint.MaxValue && m.ModuleName.Equals(moduleName, StringComparison.OrdinalIgnoreCase));
        uint basis = checked((uint)module.BaseAddress.ToInt64());
        uint pe = basis + BitConverter.ToUInt32(Read(process, basis + 0x3c, 4));
        if (BitConverter.ToUInt32(Read(process, pe, 4)) != 0x4550 || BitConverter.ToUInt16(Read(process, pe + 24, 2)) != 0x10b)
            throw new InvalidDataException(L.Text("Неизвестный системный модуль x86."));
        byte[] directory = Read(process, pe + 24 + 96, 8);
        uint exportRva = BitConverter.ToUInt32(directory), exportSize = BitConverter.ToUInt32(directory, 4);
        byte[] exports = Read(process, basis + exportRva, 40);
        uint count = BitConverter.ToUInt32(exports, 24);
        if (count > 100000) throw new InvalidDataException(L.Text("Неподдерживаемый системный каталог API."));
        uint names = basis + BitConverter.ToUInt32(exports, 32), ordinals = basis + BitConverter.ToUInt32(exports, 36), functions = basis + BitConverter.ToUInt32(exports, 28);
        string StringAt(uint address)
        {
            var bytes = new List<byte>();
            for (uint i = 0; i < 256; i++)
            {
                byte value = Read(process, address + i, 1)[0];
                if (value == 0) return Encoding.ASCII.GetString(bytes.ToArray());
                bytes.Add(value);
            }
            throw new InvalidDataException(L.Text("Слишком длинное имя системного API."));
        }
        for (uint i = 0; i < count; i++)
        {
            uint nameRva = BitConverter.ToUInt32(Read(process, names + 4 * i, 4));
            if (StringAt(basis + nameRva) != exportName) continue;
            ushort ordinal = BitConverter.ToUInt16(Read(process, ordinals + 2 * i, 2));
            uint rva = BitConverter.ToUInt32(Read(process, functions + 4u * ordinal, 4));
            if (rva >= exportRva && rva - exportRva < exportSize)
            {
                string forward = StringAt(basis + rva);
                int dot = forward.IndexOf('.');
                if (dot < 1) throw new InvalidDataException(L.Text("Неизвестный системный переход API."));
                return RemoteExport(process, modules, forward[..dot] + ".dll", forward[(dot + 1)..], depth + 1);
            }
            return basis + rva;
        }
        throw new InvalidDataException(L.Text("Системный API отсутствует: ") + exportName);
    }

    internal sealed record InProcessPlan(uint Allocation, uint OrangeBase, int ThunkLength)
    {
        internal uint Thunk => Allocation + 2048;
        internal uint PhaseAddress => Allocation + 4096 + 12;
        internal uint Phase(IntPtr process) => BitConverter.ToUInt32(Read(process, PhaseAddress, 4));
        internal void Verify(IntPtr process)
        {
            uint export = OrangeBase + ExportRva;
            byte[] jump = Read(process, export, 5);
            if (Phase(process) != 3 || jump[0] != 0xe9 || unchecked(export + 5 + BitConverter.ToUInt32(jump, 1)) != Thunk ||
                !Read(process, 0x718ff4, 5).SequenceEqual(Convert.FromHexString("a380da7600")) ||
                VirtualQueryEx(process, new IntPtr(export), out var entry, (nuint)Marshal.SizeOf<MemoryRegion>()) == 0 || entry.Protect != 0x20 ||
                VirtualQueryEx(process, new IntPtr(Allocation), out var code, (nuint)Marshal.SizeOf<MemoryRegion>()) == 0 ||
                code.AllocationBase.ToInt64() != Allocation || code.Protect != 0x20 ||
                VirtualQueryEx(process, new IntPtr(Allocation + 4096), out var state, (nuint)Marshal.SizeOf<MemoryRegion>()) == 0 || state.Protect != 0x04)
                throw new IOException(L.Text("Защищённый маршрут игры не подтвердил установку."));
        }
    }

    internal sealed class X86Code(uint address)
    {
        internal readonly List<byte> Bytes = new();
        readonly Dictionary<string, int> labels = new();
        readonly List<(int Offset, string Label)> branches = new();
        internal void Emit(params byte[] bytes) => Bytes.AddRange(bytes);
        internal void U32(uint value) => Bytes.AddRange(BitConverter.GetBytes(value));
        internal void Label(string name) => labels.Add(name, Bytes.Count);
        internal void Branch(byte condition, string label) { Emit(0x0f, condition); branches.Add((Bytes.Count, label)); U32(0); }
        internal void Call(uint function) { Emit(0xb8); U32(function); Emit(0xff, 0xd0, 0x85, 0xc0); Branch(0x84, "fail"); }
        internal void Goto(string label) { Emit(0xe9); branches.Add((Bytes.Count,label)); U32(0); }
        internal void Push(uint value) { Emit(0x68); U32(value); }
        internal void Store(uint location, uint value) { Emit(0xc7, 0x05); U32(location); U32(value); }
        internal byte[] Finish()
        {
            foreach (var branch in branches)
            {
                byte[] offset = BitConverter.GetBytes(labels[branch.Label] - branch.Offset - 4);
                for (int i = 0; i < 4; i++) Bytes[branch.Offset + i] = offset[i];
            }
            return Bytes.ToArray();
        }
        internal void Jump(uint target) { Emit(0xe9); U32(unchecked(target - (address + (uint)Bytes.Count + 4))); }
    }

    // One-shot code runs at the guarded LoadLibrary return after the debugger
    // has detached at the original packer exception. It never performs a game
    // operation. Unknown bytes/API failures terminate this owned process.
    internal static byte[] BuildBootstrap(uint allocation, uint orangeBase, uint virtualProtect, uint flush, uint exit, int thunkLength)
    {
        uint data = allocation + 4096, thunk = allocation + 2048;
        var code = new X86Code(allocation);
        code.Emit(0x9c, 0x60); code.Store(data + 12, 1); // flags and all registers
        code.Emit(0x3d); code.U32(orangeBase); code.Branch(0x85, "fail");
        code.Emit(0x8b, 0xc8, 0x81, 0xc1); code.U32(ExportRva); // ECX export
        code.Emit(0x80, 0x39, 0xe9); code.Branch(0x85, "fail");
        code.Emit(0x8b, 0x51, 0x01, 0x01, 0xca, 0x83, 0xc2, 0x05, 0x8b, 0xc2, 0x2d); code.U32(0x1670);
        code.Emit(0xa9); code.U32(0xfff); code.Branch(0x85, "fail");
        code.Emit(0x85, 0xc0); code.Branch(0x84, "fail");
        code.Emit(0x3d); code.U32(orangeBase); code.Branch(0x84, "fail");
        code.Emit(0x8b, 0xf8, 0x81, 0xc7); code.U32(0x50f5);
        code.Emit(0x39, 0x7a, 0x01); code.Branch(0x85, "fail");
        code.Emit(0x83, 0xef, 0x05, 0x39, 0x7a, 0x0b); code.Branch(0x85, "fail");
        byte[] signature = Convert.FromHexString("a0f5509b0c84c074238b0df0509b0c85c974198b4424108b54240c508b44240c528b54240c5052e8");
        for (int i = 0; i < signature.Length; i++)
        {
            if (i is >= 1 and <= 4 or >= 11 and <= 14) continue;
            code.Emit(0x80, 0x7a, (byte)i, signature[i]); code.Branch(0x85, "fail");
        }
        // Write the original destination into the final relative jump before
        // turning this allocation read/execute. ESI retains the export pointer.
        code.Emit(0x8b, 0xf1, 0x8b, 0xc2, 0x2d); code.U32(thunk + (uint)thunkLength);
        code.Emit(0xa3); code.U32(thunk + (uint)thunkLength - 4);
        code.Store(data + 12, 2);
        code.Push(data); code.Push(0x40); code.Push(5); code.Emit(0x56); code.Call(virtualProtect);
        code.Emit(0xc6, 0x06, 0xe9, 0xb8); code.U32(thunk);
        code.Emit(0x29, 0xf0, 0x83, 0xe8, 0x05, 0x89, 0x46, 0x01);
        // The unpacker leaves its export page RW; the installed entry must be RX for DEP.
        code.Push(data + 8); code.Push(0x20); code.Push(5); code.Emit(0x56); code.Call(virtualProtect);
        code.Push(data + 4); code.Push(0x40); code.Push(5); code.Push(0x718ff4); code.Call(virtualProtect);
        code.Store(0x718ff4, 0x76da80a3); code.Emit(0xc6, 0x05); code.U32(0x718ff8); code.Emit(0);
        code.Push(data + 8); code.Emit(0xff, 0x35); code.U32(data + 4); code.Push(5); code.Push(0x718ff4); code.Call(virtualProtect);
        code.Push(data + 8); code.Push(0x20); code.Push(4096); code.Push(allocation); code.Call(virtualProtect);
        code.Push(0); code.Push(0); code.Push(uint.MaxValue); code.Call(flush);
        code.Store(data + 12, 3); code.Emit(0x61, 0x9d, 0xa3); code.U32(0x76da80); code.Jump(0x718ff9);
        code.Label("fail"); code.Push(1); code.Emit(0xb8); code.U32(exit); code.Emit(0xff, 0xd0, 0xeb, 0xfe);
        return code.Finish();
    }

    internal static InProcessPlan PrepareInProcess(IntPtr process, ProcessModule[] modules, uint orangeBase, GameLaunchProfile profile)
    {
        uint protect = RemoteExport(process, modules, "kernel32.dll", "VirtualProtect");
        uint flush = RemoteExport(process, modules, "kernel32.dll", "FlushInstructionCache");
        uint exit = RemoteExport(process, modules, "kernel32.dll", "ExitProcess");
        IntPtr memory = VirtualAllocEx(process, IntPtr.Zero, 8192, 0x3000, 0x40);
        if (memory.ToInt64() <= 0 || memory.ToInt64() > uint.MaxValue - 8192)
            throw new IOException(L.Text("Не удалось выделить bootstrap x86."));
        uint allocation = (uint)memory.ToInt64(), thunkAddress = allocation + 2048;
        byte[] thunk = BuildThunk(thunkAddress, allocation + 2304, 0, profile.LoginPort, profile.SessionPort);
        byte[] bootstrap = BuildBootstrap(allocation, orangeBase, protect, flush, exit, thunk.Length);
        if (bootstrap.Length >= 2048) throw new IOException(L.Text("Bootstrap x86 превышает выделенный размер."));
        Write(process, allocation, bootstrap); Write(process, thunkAddress, thunk);
        Write(process, allocation + 2304, Encoding.ASCII.GetBytes("127.0.0.1\0"));
        if (!VirtualProtectEx(process, new IntPtr(allocation + 4096), 4096, 0x04, out _) ||
            !FlushInstructionCache(process, memory, 4096))
            throw new IOException(L.Text("Не удалось подготовить bootstrap x86."));
        byte[] detour = [(byte)0xe9, .. BitConverter.GetBytes(unchecked(allocation - (0x718ff4u + 5)))];
        GuardedPatch(process, 0x718ff4, Convert.FromHexString("a380da7600"), detour);
        return new InProcessPlan(allocation, orangeBase, thunk.Length);
    }
    internal static void GuardedPatch(IntPtr process, uint address, byte[] expected, byte[] replacement)
    {
        if (replacement.Length != expected.Length || !Read(process, address, expected.Length).SequenceEqual(expected))
            throw new InvalidDataException(L.Text("Неизвестная точка запуска защищённой игры."));
        if (!VirtualProtectEx(process, new IntPtr(address), (nuint)expected.Length, 0x40, out uint previous))
            throw new IOException(L.Text("Не удалось открыть точку запуска игры."));
        try
        {
            Write(process, address, replacement);
            if (!FlushInstructionCache(process, new IntPtr(address), (nuint)expected.Length))
                throw new IOException(L.Text("Не удалось обновить точку запуска игры."));
        }
        finally
        {
            if (!VirtualProtectEx(process, new IntPtr(address), (nuint)expected.Length, previous, out _))
                throw new IOException(L.Text("Не удалось восстановить защиту запуска игры."));
        }
    }
}
