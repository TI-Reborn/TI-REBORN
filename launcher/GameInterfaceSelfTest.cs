using System.Text.Json;

namespace TioLauncher;

static class GameInterfaceSelfTest
{
    internal static void Run(string report)
    {
        string directory = Path.Combine(Path.GetTempPath(), "tio-interface-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Check(bool pass, string name) { if (!pass) throw new Exception(name); checks.Add(name); }
        try
        {
            string settings = Path.Combine(directory, "interface.txt");
            Check(GameInterface.Load(settings) == GameInterface.New, "Absent preference keeps the new interface");
            GameInterface.Save(GameInterface.Original, settings);
            Check(GameInterface.Load(settings) == GameInterface.Original, "Saved original preference roundtrip");
            try { GameInterface.Save("classic", settings); throw new Exception("Invalid mode accepted"); }
            catch (ArgumentException) { checks.Add("Invalid mode rejected"); }
            Check(GameInterface.Load(settings) == GameInterface.Original, "Rejected selection preserves settings");
            File.WriteAllText(settings, "unexpected");
            Check(GameInterface.Load(settings) == GameInterface.New, "Unknown stored value falls back to the new interface");

            Check(LaunchVerification.Flags("russian", GameInterface.New) == 0, "Russian new interface keeps the old preface byte");
            Check(LaunchVerification.Flags("english", GameInterface.New) == 1, "English new interface keeps the old preface byte");
            Check(LaunchVerification.Flags("russian", GameInterface.Original) == 2, "Original interface sets its own bit");
            Check(LaunchVerification.Flags("english", GameInterface.Original) == 3, "Language and interface bits combine");
            try { LaunchVerification.Flags("russian", "classic"); throw new Exception("Invalid preface mode accepted"); }
            catch (ArgumentException) { checks.Add("Invalid preface mode rejected"); }

            var (expected, replacement) = NativeInterfaceMode.Patch();
            Check(expected.Length == replacement.Length && expected[0] == 0 && replacement[0] == 1, "Native patch selects the original layout");
            Check(expected.AsSpan(1).SequenceEqual(replacement.AsSpan(1)), "Native patch changes only the mode flag");

            var hd = NativeHdMapTextures.Plan;
            Check(hd.CallSite == 0x6b12f9 && hd.CallSiteBytes == "e8867de0ff", "HD maps replace the pinned LoadFromFile call");
            Check(hd.DimensionsSite == 0x6b133a && hd.DimensionsSiteBytes == "e8d1edf5ff" &&
                hd.DimensionsOffset == 0x200, "HD maps wrap the pinned texture creation call");
            const uint allocation = 0x20000000;
            byte[] code = NativeHdMapTextures.Build(allocation);
            Check(hd.Relocations.Select(r => r.Target).SequenceEqual(new uint[] { 0x4b9084, 0x610110 }) &&
                hd.Relocations.All(r => allocation + (uint)r.Offset + 4 + (uint)BitConverter.ToInt32(code, r.Offset) == r.Target),
                "HD map adapter calls the original loader and texture creator");
            Check(NativeHdMapTextures.Call(hd.CallSite, allocation).SequenceEqual(new byte[] { 0xe8, 0x02, 0xed, 0x94, 0x1f }), "HD map hook calls the adapter");
            Check(!NativeHdMapTextures.Apply(IntPtr.Zero, 0x400000, GameInterface.Original), "Original interface keeps native map textures");
            File.WriteAllText(report, JsonSerializer.Serialize(new { passed = true, checks }));
        }
        catch (Exception error) { File.WriteAllText(report, JsonSerializer.Serialize(new { passed = false, error = error.ToString(), checks })); Environment.ExitCode = 1; }
        finally { Directory.Delete(directory, true); }
    }

    // Checks a built Silver against the launcher's adapters and mode flag.
    internal static bool RunImage(string image, string output)
    {
        byte[] raw = File.ReadAllBytes(image);
        bool compatible = NativePasswordLimit.CompatibilityHash(raw) == NativePasswordLimit.OriginalSha256;
        bool englishCompatible = compatible && NativeEnglish.ForImage(image).Patches.Length > 0;
        int offset = FileOffset(raw, NativeInterfaceMode.ModeRva);
        var (expected, _) = NativeInterfaceMode.Patch();
        bool modeFlag = offset >= 0 && offset + expected.Length <= raw.Length && raw.AsSpan(offset, expected.Length).SequenceEqual(expected);
        byte[] changed = (byte[])raw.Clone();
        changed[^1] ^= 1;
        bool rejectsUnknown = NativePasswordLimit.CompatibilityHash(changed) != NativePasswordLimit.OriginalSha256;
        bool passed = compatible && englishCompatible && modeFlag && rejectsUnknown;
        File.WriteAllText(output, JsonSerializer.Serialize(new { passed, compatible, englishCompatible, modeFlag, rejectsUnknown }));
        return passed;
    }

    static int FileOffset(byte[] raw, uint rva)
    {
        int pe = BitConverter.ToInt32(raw, 0x3c), sections = BitConverter.ToUInt16(raw, pe + 6);
        int headers = pe + 24 + BitConverter.ToUInt16(raw, pe + 20);
        for (int i = 0; i < sections; i++)
        {
            int section = headers + i * 40;
            uint start = BitConverter.ToUInt32(raw, section + 12), size = BitConverter.ToUInt32(raw, section + 16);
            if (rva >= start && rva < start + size)
                return checked((int)(BitConverter.ToUInt32(raw, section + 20) + rva - start));
        }
        return -1;
    }
}
