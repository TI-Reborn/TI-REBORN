using System.Text;

namespace TioLauncher;

// Silver's A2 layout reads this flag each time the barracks is laid out
// (deploy/client_barracks_a2.py MODE). One guarded write covers the zeroed
// flag and the mode-aware signature, so an unknown image is never changed.
internal static class NativeInterfaceMode
{
    internal const uint ModeRva = 0x89ff04;
    internal const uint SignatureRva = 0x89ff40;
    internal const string Signature = "TIO-barracks-A2-layout-v2";
    internal static (byte[] Expected, byte[] Replacement) Patch()
    {
        int offset = checked((int)(SignatureRva - ModeRva));
        byte[] expected = new byte[offset + Signature.Length];
        Encoding.ASCII.GetBytes(Signature).CopyTo(expected, offset);
        byte[] replacement = (byte[])expected.Clone();
        replacement[0] = 1;
        return (expected, replacement);
    }
    internal static void Apply(IntPtr process, uint silver, string mode)
    {
        GameInterface.Validate(mode);
        if (mode == GameInterface.New) return;
        var (expected, replacement) = Patch();
        try { NativeTlsRoute.GuardedPatch(process, checked(silver + ModeRva), expected, replacement); }
        catch (InvalidDataException error)
        {
            throw new InvalidDataException(L.Text("Этот клиент не поддерживает оригинальный интерфейс. Нажмите «Проверить файлы»."), error);
        }
    }
}
