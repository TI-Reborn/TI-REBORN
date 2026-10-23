using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
namespace TioLauncher;

static class NativeEnglish
{
    internal record Patch(uint Rva,string Expected,string Replacement,string Source,string English);
    internal record Resource(string Sha256,Patch[] Patches);
    internal static readonly Resource[] Images = Load();
    static Resource[] Load()
    {
        using var stream=typeof(NativeEnglish).Assembly.GetManifestResourceStream("TioLauncher.native-english.json")!;
        return JsonSerializer.Deserialize<Resource[]>(stream,Updater.Json)!;
    }
    internal static Resource ForImage(string image)
    {
        using var file=File.OpenRead(image);
        string hash=NativePasswordLimit.CompatibilityHash(File.ReadAllBytes(image));
        return Images.SingleOrDefault(plan=>plan.Sha256==hash)
            ?? throw new InvalidDataException("Unsupported English UI image. Check client files.");
    }
    internal static int Apply(IntPtr process,uint module,string image)
    {
        var captions=ForImage(image);
        foreach(var p in captions.Patches)
            NativeTlsRoute.GuardedPatch(process,checked(module+p.Rva),Convert.FromHexString(p.Expected),Convert.FromHexString(p.Replacement));
        return captions.Patches.Length;
    }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern uint GetFinalPathNameByHandle(IntPtr file,System.Text.StringBuilder path,uint count,uint flags);
    internal static bool IsSilver(IntPtr file)
    {
        var name=new System.Text.StringBuilder(1024);
        uint size=GetFinalPathNameByHandle(file,name,(uint)name.Capacity,0);
        return size>0&&size<name.Capacity&&Path.GetFileName(name.ToString()).Equals("silver.dll",StringComparison.OrdinalIgnoreCase);
    }
}
