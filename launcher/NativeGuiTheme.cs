using System.Security.Cryptography;

namespace TioLauncher;

// Chat's three native solid fills have no bitmap resource. Enable the new
// palette only with the exact installed personal-GUI frame, and guard each
// original PUSH instruction. Control geometry and callbacks remain untouched.
internal static class NativeGuiTheme
{
    internal const string FrameHash = "14ef84c63a9ee89e759fc930bb6c46d193d6ae2fe5222383a3b8b3c3eb94a037";
    internal static readonly uint[] FillOffsets = [0x602b03, 0x602b1e, 0x602bab];
    internal static bool Apply(IntPtr process, uint module, string root)
    {
        string frame = Path.Combine(root, "base", "pda", "gui_main_1-7.png");
        if (!File.Exists(frame)) return false;
        using (var stream = File.OpenRead(frame))
            if (Convert.ToHexStringLower(SHA256.HashData(stream)) != FrameHash) return false;
        foreach (uint offset in FillOffsets)
            NativeTlsRoute.GuardedPatch(process, module + offset,
                Convert.FromHexString("68212a18cc"), Convert.FromHexString("681a2026ff")); // Native ABGR, opaque slate.
        return true;
    }
}
