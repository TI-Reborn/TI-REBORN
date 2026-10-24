using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

internal static class ItemEffectTooltipSelfTest
{
    internal static bool Run(string image, string output)
    {
        byte[] raw = File.ReadAllBytes(image);
        bool recognized = Convert.ToHexStringLower(SHA256.HashData(raw)) == NativePasswordLimit.TooltipSha256;
        bool compatible = NativePasswordLimit.CompatibilityHash(raw) == NativePasswordLimit.OriginalSha256;
        byte[] changed = (byte[])raw.Clone();
        changed[^1] ^= 1;
        bool rejectsUnknown = NativePasswordLimit.CompatibilityHash(changed) != NativePasswordLimit.OriginalSha256;
        bool englishCompatible = compatible && NativeEnglish.ForImage(image).Patches.Length > 0;
        bool passed = recognized && compatible && rejectsUnknown && englishCompatible;
        File.WriteAllText(output, JsonSerializer.Serialize(new {
            passed, recognized, compatible, rejectsUnknown, englishCompatible
        }));
        return passed;
    }
}
