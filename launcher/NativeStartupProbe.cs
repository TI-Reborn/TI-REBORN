using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace TioLauncher;

internal sealed record NativeProbeError(string Field, int? Win32Error, string Message);
internal sealed record NativeStartupState(uint Pid, bool? Exited, uint? ExitCode,
    uint? NetworkModuleHandle, uint? BootstrapPhase, bool? OrangeLoaded, bool? SilverLoaded, NativeProbeError[] Errors);

// Observes the owned process without changing its memory or loading any DLLs.
internal static class NativeStartupProbe
{
    [DllImport("kernel32", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] data, nuint size, out nuint read);
    [DllImport("kernel32", SetLastError = true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr process, out uint code);

    internal static uint ReadUInt32(IntPtr process, long address)
        => BitConverter.ToUInt32(ReadBytes(process, address, 4));

    internal static byte[] ReadBytes(IntPtr process, long address, int length)
    {
        var bytes = new byte[length];
        if (!ReadProcessMemory(process, new IntPtr(address), bytes, (nuint)length, out var read) || read != (nuint)length)
            throw new Win32Exception(Marshal.GetLastWin32Error(), $"ReadProcessMemory(0x{address:x}): {read}/{length} bytes.");
        return bytes;
    }

    internal static uint? ExitCode(IntPtr process)
    {
        uint state = WaitForSingleObject(process, 0);
        if (state == 258) return null;
        if (state == uint.MaxValue) throw new Win32Exception(Marshal.GetLastWin32Error());
        if (state != 0) throw new IOException($"Unexpected process wait result: {state}.");
        if (!GetExitCodeProcess(process, out uint code)) throw new Win32Exception(Marshal.GetLastWin32Error());
        return code;
    }

    internal static NativeStartupState Capture(IntPtr process, uint pid, long? bootstrapPhaseAddress)
    {
        var errors = new List<NativeProbeError>();
        uint? ReadValue(string field, long address)
        {
            try { return ReadUInt32(process, address); }
            catch (Win32Exception error)
            {
                errors.Add(new(field, error.NativeErrorCode, error.Message));
                return null;
            }
        }

        bool? exited = null, orange = null, silver = null;
        uint? exitCode = null, module = null, bootstrap = null;
        try { exitCode = ExitCode(process); exited = exitCode.HasValue; }
        catch (Exception error) when (error is Win32Exception or IOException)
        {
            errors.Add(new("process_state", (error as Win32Exception)?.NativeErrorCode, error.Message));
        }
        if (exited != true)
        {
            module = ReadValue("network_module_handle", 0x76da80);
            if (bootstrapPhaseAddress is long address) bootstrap = ReadValue("bootstrap_phase", address);
            try
            {
                using var live = Process.GetProcessById(checked((int)pid));
                var names = live.Modules.Cast<ProcessModule>().Select(m => m.ModuleName).ToHashSet(StringComparer.OrdinalIgnoreCase);
                orange = names.Contains("orange.dll"); silver = names.Contains("silver.dll");
            }
            catch (Exception error) when (error is Win32Exception or InvalidOperationException or ArgumentException)
            {
                errors.Add(new("modules", (error as Win32Exception)?.NativeErrorCode, error.Message));
            }
        }
        return new(pid, exited, exitCode, module, bootstrap, orange, silver, errors.ToArray());
    }
}
