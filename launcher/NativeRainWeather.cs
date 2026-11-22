using System.Security.Cryptography;
using System.Text;

namespace TioLauncher;

// Silver's weather extension used an ANSI constant with a Unicode SDK loader.
// Correct that constant before the first battle; the DLL on disk stays intact.
internal static class NativeRainWeather
{
    internal const uint PathRva = 0x87f100;
    internal const string Texture = "gfx\\rain.tga";
    internal static byte[] Before()
    {
        byte[] value = new byte[(Texture.Length + 1) * 2];
        Encoding.ASCII.GetBytes(Texture).CopyTo(value, 0);
        return value;
    }
    internal static byte[] After() => Encoding.Unicode.GetBytes(Texture + "\0");

    internal static bool Apply(IntPtr process, uint silver, string image)
    {
        byte[] raw = File.ReadAllBytes(image);
        if (!SilverRegions.Matches(raw, "rain")) return false;
        NativeTlsRoute.GuardedPatch(process, checked(silver + PathRva), Before(), After());
        return true;
    }

    internal static void Test(string image, string output)
    {
        byte[] raw = File.ReadAllBytes(image);
        if (!SilverRegions.Matches(raw, "rain"))
            throw new InvalidDataException("Unrecognized weather image");
        // This release has identical raw/RVA mapping in the appended section.
        int pe = BitConverter.ToInt32(raw, 0x3c), sections = BitConverter.ToUInt16(raw, pe + 6);
        int headers = pe + 24 + BitConverter.ToUInt16(raw, pe + 20), offset = -1;
        for (int i = 0; i < sections; i++)
        {
            int section = headers + i * 40;
            uint rva = BitConverter.ToUInt32(raw, section + 12), size = BitConverter.ToUInt32(raw, section + 16);
            if (PathRva >= rva && PathRva + Before().Length <= rva + size)
                offset = checked((int)(BitConverter.ToUInt32(raw, section + 20) + PathRva - rva));
        }
        if (offset < 8 || !raw.AsSpan(offset, Before().Length).SequenceEqual(Before()) ||
            BitConverter.ToInt32(raw, offset - 8) != -1 || BitConverter.ToInt32(raw, offset - 4) != Texture.Length ||
            Before().Length != After().Length || Encoding.Unicode.GetString(After()) != Texture + "\0")
            throw new InvalidDataException("Rain constant layout changed");
        byte[] changed = (byte[])raw.Clone(); After().CopyTo(changed, offset);
        Before().CopyTo(changed, offset);
        if (!changed.AsSpan().SequenceEqual(raw)) throw new InvalidDataException("Unrelated bytes changed");
        raw[offset] ^= 1;
        if (SilverRegions.Matches(raw, "rain"))
            throw new InvalidDataException("Unknown weather image accepted");
        File.WriteAllText(output, "PASS: exact image, Unicode weather texture, constant length, bounded region and changed-constant rejection");
    }
}
