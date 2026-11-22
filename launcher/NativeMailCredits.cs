using System.Security.Cryptography;

namespace TioLauncher;

internal static class NativeMailCredits
{
    private const string SilverSha256 = "45ae266752818ac9bf70a3bd85a3b856e23db6e9a0193c297eda7d84521a70e3";
    private const string CreditIdAndJump = "b80100ffffeb59";

    internal static readonly (uint Rva, string Expected, string Replacement)[] Patches =
    [
        (0x3ee92a, "bf1f0000008b1d", CreditIdAndJump),
        (0x3ee994, "eb06", "eb0c"),
        (0x3ef6ae, "be1f0000008b1d", CreditIdAndJump),
        (0x3ef718, "eb06", "eb0c"),
    ];

    internal static bool Apply(IntPtr process, uint silver, string image)
    {
        using var file = File.OpenRead(image);
        if (Convert.ToHexStringLower(SHA256.HashData(file)) is not (SilverSha256 or "f9aeb6c0673d6be7b957d4f9b2e4a20a92c08aef0264ee304febbb2e556eda0e"))
            return false;

        // Mail uses the server's credit ID, independent of loaded warehouse rows.
        foreach (var (rva, expected, replacement) in Patches)
            NativeTlsRoute.GuardedPatch(process, checked(silver + rva),
                Convert.FromHexString(expected), Convert.FromHexString(replacement));
        return true;
    }
}
