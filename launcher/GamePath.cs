using System.Runtime.InteropServices;
using System.Text;

namespace TioLauncher;

/// <summary>Provides an ANSI-compatible name for the same installation directory.</summary>
internal static class GamePath
{
    internal const int MaximumNativeLength = 240;
    static string CompatibilityError => L.Text("Старый клиент игры не поддерживает этот полный путь, а Windows не предоставила совместимое короткое имя папки. Выберите папку с более коротким путём и латинскими буквами, например C:\\Games\\TIO-Online.");

    [DllImport("kernel32.dll", EntryPoint = "GetShortPathNameW", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    static extern uint GetShortPathName(string longPath, StringBuilder? shortPath, uint capacity);

    internal static string ForNativeClient(string root) => ForNativeClient(root, ResolveShortPath);

    // Only the short-name resolver is injectable; filesystem checks remain real.
    internal static string ForNativeClient(string root, Func<string, string?> shortPathResolver)
    {
        string full = Path.GetFullPath(root);
        if (!Directory.Exists(full)) throw new DirectoryNotFoundException(L.Text("Папка игры не найдена: ") + full);
        if (IsAscii(full) && full.Length < MaximumNativeLength) return full;

        string? alias = shortPathResolver(full);
        if (alias is not null && Path.IsPathFullyQualified(alias) && IsAscii(alias)
            && alias.Length <= MaximumNativeLength && Directory.Exists(alias)) return alias;
        throw new IOException(CompatibilityError);
    }

    static bool IsAscii(string path) => path.All(character => character <= 0x7f);

    static string? ResolveShortPath(string full)
    {
        // Windows returns an alias for this exact directory, not a copied or new
        // installation. A volume without usable 8.3 names may return the long name.
        uint capacity = GetShortPathName(full, null, 0);
        if (capacity is 0 or > 32768) return null;
        var buffer = new StringBuilder((int)capacity);
        uint written = GetShortPathName(full, buffer, capacity);
        return written > 0 && written < capacity ? buffer.ToString() : null;
    }
}
