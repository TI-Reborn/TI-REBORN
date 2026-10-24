using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

static class NativeThrowableEffects
{
    internal sealed record Patch(uint Rva,string Before,string After);
    internal sealed record Plan(string Sha256,Patch[] Patches);
    internal static bool Apply(IntPtr process,uint silver,string image)
    {
        using var stream=typeof(NativeThrowableEffects).Assembly.GetManifestResourceStream("TioLauncher.native-throwable-effects.json")!;
        var plan=JsonSerializer.Deserialize<Plan>(stream,Updater.Json)!;
        using var file=File.OpenRead(image);
        if(NativePasswordLimit.CompatibilityHash(File.ReadAllBytes(image))!=plan.Sha256) return false;
        foreach(var patch in plan.Patches)
            NativeTlsRoute.GuardedPatch(process,checked(silver+patch.Rva),Convert.FromHexString(patch.Before),Convert.FromHexString(patch.After));
        return true;
    }
}
