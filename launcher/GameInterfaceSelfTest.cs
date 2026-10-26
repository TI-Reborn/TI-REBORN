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

            string root = Path.Combine(directory, "game");
            string catalogue = Path.Combine(root, GameInterface.Catalogue);
            string overlay = Path.Combine(root, GameInterface.OriginalCatalogue);
            Directory.CreateDirectory(Path.GetDirectoryName(catalogue)!);
            Directory.CreateDirectory(Path.GetDirectoryName(overlay)!);
            File.WriteAllText(catalogue, "published");
            File.WriteAllText(overlay, "original");
            GameInterface.Apply(root, GameInterface.New);
            Check(File.ReadAllText(catalogue) == "published", "New interface keeps the verified catalogue");
            GameInterface.Apply(root, GameInterface.Original);
            Check(File.ReadAllText(catalogue) == "original", "Original interface installs the previous item icons");
            File.WriteAllText(catalogue, "published");
            File.Delete(overlay);
            try { GameInterface.Apply(root, GameInterface.Original); throw new Exception("Missing overlay accepted"); }
            catch (FileNotFoundException) { checks.Add("Missing original catalogue rejected"); }
            Check(File.ReadAllText(catalogue) == "published", "Failed overlay leaves the catalogue intact");

            var (expected, replacement) = NativeInterfaceMode.Patch();
            Check(expected.Length == replacement.Length && expected[0] == 0 && replacement[0] == 1, "Native patch selects the original layout");
            Check(expected.AsSpan(1).SequenceEqual(replacement.AsSpan(1)), "Native patch changes only the mode flag");
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
