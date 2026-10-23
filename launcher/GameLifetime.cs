using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace TioLauncher;

// The bridge helper owns the job handle. Windows closes it even after an abrupt
// helper exit, ending only its assigned native child and releasing local ports.
internal sealed class GameLifetime : IDisposable
{
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong Read, Write, Other, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateJobObject(IntPtr attributes, string? name);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool SetInformationJobObject(SafeFileHandle job, int kind, ref ExtendedLimits value, uint size);
    [DllImport("kernel32", SetLastError = true)]
    static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    readonly SafeFileHandle handle;
    internal GameLifetime()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        var limits = new ExtendedLimits { Basic = new BasicLimits { Flags = 0x2000 } };
        if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>()))
        {
            int error = Marshal.GetLastWin32Error(); handle.Dispose();
            throw new System.ComponentModel.Win32Exception(error);
        }
    }
    internal void Assign(IntPtr process)
    {
        if (!AssignProcessToJobObject(handle, process))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    }
    public void Dispose() => handle.Dispose();
}
