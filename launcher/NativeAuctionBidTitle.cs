using System.Security.Cryptography;

namespace TioLauncher;

internal static class NativeAuctionBidTitle
{
    private const string PreviousSilverSha256 =
        "cae8fe433d8fd9be70600e0695ad033d388bd2c2d01c513d95b9e16dae4a81c5";
    private const string CurrentSilverSha256 =
        "cdaa45eff2df7d0cd64a93f82449a3157e6bfd2ff17d54e2a9c7f0e866842ced";
    private const uint BidTitleRva = 0x500960;

    internal static bool Apply(IntPtr process, uint silver, string image)
    {
        using var file = File.OpenRead(image);
        if (Convert.ToHexStringLower(SHA256.HashData(file)) is not (PreviousSilverSha256 or CurrentSilverSha256 or
            "46374254b8ba48afb0f1ae67b87e797f83c4555d2938b612d085e27ceaeafe42" or
            "c4246171012d4e70969e849d4123824c6437b45584d3417ea58873d822a258cb" or
            "45ae266752818ac9bf70a3bd85a3b856e23db6e9a0193c297eda7d84521a70e3" or
             "f9aeb6c0673d6be7b957d4f9b2e4a20a92c08aef0264ee304febbb2e556eda0e"))
            return false;

        // This copy of m1219 belongs to the bid confirmation. m1240 is its localized title.
        NativeTlsRoute.GuardedPatch(process, checked(silver + BidTitleRva),
            System.Text.Encoding.Unicode.GetBytes("m1219\0"),
            System.Text.Encoding.Unicode.GetBytes("m1240\0"));
        return true;
    }
}
