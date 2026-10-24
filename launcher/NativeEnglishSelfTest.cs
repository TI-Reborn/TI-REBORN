using System.Diagnostics;
using System.Reflection.PortableExecutable;
using System.Runtime.InteropServices;
using System.Text.Json;
namespace TioLauncher;
static class NativeEnglishSelfTest
{
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr VirtualAlloc(IntPtr address,nuint size,uint type,uint protection);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool VirtualFree(IntPtr address,nuint size,uint type);
    internal static void Run(string image,string report)
    {
        IntPtr memory=IntPtr.Zero;var checks=new List<string>();
        try
        {
            byte[] raw=File.ReadAllBytes(image);
            var captions=NativeEnglish.ForImage(image);
            using var pe=new PEReader(new MemoryStream(raw));
            foreach(var p in captions.Patches)
            {
                var section=pe.PEHeaders.SectionHeaders.Single(s=>p.Rva>=s.VirtualAddress&&p.Rva<s.VirtualAddress+s.VirtualSize);
                // Authored extension sections contain both executable thunks and
                // their inline constants. Every reviewed buffer is beyond the
                // original image and pinned to the exact string/header bytes.
                if(p.Rva<0x800000) throw new Exception("Caption exceeds reviewed extension storage");
                byte[] expected=Convert.FromHexString(p.Expected);int offset=checked((int)p.Rva-section.VirtualAddress+section.PointerToRawData);
                if(!raw.AsSpan(offset,expected.Length).SequenceEqual(expected)||p.Expected.Length!=p.Replacement.Length) throw new Exception("Unexpected file/patch buffer");
            }
            checks.Add($"All {captions.Patches.Length} buffers match exact published caption storage");
            uint address=0x26000000;memory=VirtualAlloc(new IntPtr(address),0x900000,0x3000,0x04);
            if(memory==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            foreach(var p in captions.Patches) { byte[] data=Convert.FromHexString(p.Expected);Marshal.Copy(data,0,memory+checked((int)p.Rva),data.Length); }
            string corrupt=Path.Combine(Path.GetTempPath(),Guid.NewGuid()+".dll");
            try
            {
                byte[] changed=(byte[])raw.Clone();changed[^1]^=1;File.WriteAllBytes(corrupt,changed);
                try { NativeEnglish.Apply(Process.GetCurrentProcess().Handle,address,corrupt);throw new Exception("Unknown image accepted"); }
                catch(InvalidDataException) { checks.Add("Unknown image rejected before memory writes"); }
                foreach(var p in captions.Patches)
                {
                    byte[] data=new byte[p.Expected.Length/2];Marshal.Copy(memory+checked((int)p.Rva),data,0,data.Length);
                    if(!data.SequenceEqual(Convert.FromHexString(p.Expected)))throw new Exception("Rejected image changed memory");
                }
            }
            finally { File.Delete(corrupt); }
            NativeEnglish.Apply(Process.GetCurrentProcess().Handle,address,image);
            foreach(var p in captions.Patches)
            {
                byte[] data=new byte[p.Replacement.Length/2];Marshal.Copy(memory+checked((int)p.Rva),data,0,data.Length);
                if(!data.SequenceEqual(Convert.FromHexString(p.Replacement))) throw new Exception("Applied caption differs");
            }
            checks.Add("All in-memory English captions applied exactly");
            try { NativeEnglish.Apply(Process.GetCurrentProcess().Handle,address,image); throw new Exception("Unexpected memory accepted"); }
            catch(InvalidDataException) { checks.Add("Changed memory rejected"); }
            if(!File.ReadAllBytes(image).SequenceEqual(raw))throw new Exception("Client DLL file changed");
            checks.Add("Native DLL file unchanged");
            File.WriteAllText(report,JsonSerializer.Serialize(new { passed=true,checks }));
        }
        catch(Exception error) { File.WriteAllText(report,JsonSerializer.Serialize(new { passed=false,error=error.ToString(),checks }));Environment.ExitCode=1; }
        finally { if(memory!=IntPtr.Zero)VirtualFree(memory,0,0x8000); }
    }
}
