using System.Diagnostics;
using System.Reflection.PortableExecutable;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

static class NativeSilverAdaptersSelfTest
{
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualAlloc(IntPtr address, nuint size, uint type, uint protection);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool VirtualFree(IntPtr address, nuint size, uint type);

    internal static void Run(string image, string report)
    {
        byte[] raw = File.ReadAllBytes(image);
        using var reader = new PEReader(new MemoryStream(raw));
        var header = reader.PEHeaders.PEHeader ?? throw new InvalidDataException("Silver has no PE header.");
        uint preferredBase = checked((uint)header.ImageBase);
        IntPtr memory = VirtualAlloc(new IntPtr(preferredBase), checked((nuint)header.SizeOfImage), 0x3000, 0x04);
        if (memory == IntPtr.Zero)
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            // Map file bytes at the preferred base so absolute operands require no relocation.
            foreach (var section in reader.PEHeaders.SectionHeaders)
            {
                if (section.SizeOfRawData == 0) continue;
                if (section.VirtualAddress < 0 || section.SizeOfRawData < 0 ||
                    (long)section.VirtualAddress + section.SizeOfRawData > header.SizeOfImage)
                    throw new InvalidDataException("Silver section exceeds the image.");
                Marshal.Copy(raw, section.PointerToRawData, memory + section.VirtualAddress, section.SizeOfRawData);
            }
            using var process = Process.GetCurrentProcess();
            bool bidTitle = NativeAuctionBidTitle.Apply(process.Handle, preferredBase, image);
            bool moderation = NativePlayerModeration.Apply(process.Handle, preferredBase, image);
            bool mailCredits = NativeMailCredits.Apply(process.Handle, preferredBase, image);
            var mailPatches = mailCredits ? NativeMailCredits.Patches.Select(p => new
            {
                rva = p.Rva,
                bytes = Convert.ToHexStringLower(NativeStartupProbe.ReadBytes(process.Handle,
                    preferredBase + p.Rva, p.Replacement.Length / 2))
            }).ToArray() : [];
            if (bidTitle && Marshal.PtrToStringUni(memory + 0x500960) != "m1240")
                throw new InvalidDataException("Auction bid title was not updated.");
            File.WriteAllText(report, JsonSerializer.Serialize(new
            {
                passed = bidTitle && moderation,
                sha256 = Convert.ToHexStringLower(SHA256.HashData(raw)), bidTitle, moderation, mailCredits, mailPatches
            }));
            Environment.ExitCode = bidTitle && moderation ? 0 : 1;
        }
        finally { VirtualFree(memory, 0, 0x8000); }
    }
}
