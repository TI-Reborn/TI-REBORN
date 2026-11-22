using System.Text.Json;
using System.Security.Cryptography;
using System.Buffers.Binary;
namespace TioLauncher;

internal static class NativePlayerModeration
{
    sealed record Edit(uint Rva, string Expected, string Replacement, bool RelocatePointer);
    static readonly Edit[] Edits = ReadPlan();
    static Edit[] ReadPlan()
    {
        using var stream = typeof(NativePlayerModeration).Assembly
            .GetManifestResourceStream("TioLauncher.native-player-moderation.json")!;
        return JsonSerializer.Deserialize<Edit[]>(stream)!;
    }

    internal static bool Apply(IntPtr process, uint silver, string image)
    {
        using var file = File.OpenRead(image);
        // shortcut: an unreviewed Silver build stays unchanged until its menu adapter is verified.
        if (Convert.ToHexStringLower(SHA256.HashData(file)) is not
            ("70647b21fc26ffdcdedc4ef27a79bab4dc6c6e8c255a3980c2386bce44495cfb" or
             "cae8fe433d8fd9be70600e0695ad033d388bd2c2d01c513d95b9e16dae4a81c5" or
             "cdaa45eff2df7d0cd64a93f82449a3157e6bfd2ff17d54e2a9c7f0e866842ced" or
             "46374254b8ba48afb0f1ae67b87e797f83c4555d2938b612d085e27ceaeafe42" or
             "c4246171012d4e70969e849d4123824c6437b45584d3417ea58873d822a258cb" or
             "45ae266752818ac9bf70a3bd85a3b856e23db6e9a0193c297eda7d84521a70e3" or
             "f9aeb6c0673d6be7b957d4f9b2e4a20a92c08aef0264ee304febbb2e556eda0e")) return false;
        foreach (var edit in Edits)
        {
            byte[] expected = Convert.FromHexString(edit.Expected);
            byte[] replacement = Convert.FromHexString(edit.Replacement);
            if (edit.RelocatePointer)
            {
                Relocate(expected, silver);
                Relocate(replacement, silver);
            }
            NativeTlsRoute.GuardedPatch(process, checked(silver + edit.Rva), expected, replacement);
        }
        return true;
    }

    static void Relocate(byte[] instruction, uint silver)
    {
        var operand = instruction.AsSpan(1, 4);
        uint preferred = BinaryPrimitives.ReadUInt32LittleEndian(operand);
        BinaryPrimitives.WriteUInt32LittleEndian(operand, checked(silver + (preferred - 0x400000)));
    }
}
