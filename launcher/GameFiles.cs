using System.Text;

namespace TioLauncher;

// Launch-time presentation choices rewrite verified game files. They share
// one path guard, atomic replacement and the running-game check.
static class GameFiles
{
    internal static string Resolve(string root, string relative)
    {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        string target = Path.GetFullPath(Path.Combine(root, relative));
        if (!target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe game path");
        for (string? p = target; p != null; p = Path.GetDirectoryName(p))
            if ((File.Exists(p) || Directory.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked game path");
        return target;
    }
    internal static void WriteAtomic(string path, byte[] data)
    {
        string pending = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllBytes(pending, data); File.Move(pending, path, true); }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
    internal static void SaveSetting(string path, string value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string pending = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(pending, value, new UTF8Encoding(false)); File.Move(pending, path, true); }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
    // An owned QA client in its own folder may run beside the player's game.
    internal static void EnsureClosed(string root, bool ownedQa, string message)
    {
        if (!Updater.GameRunning()) return;
        bool isolated = ownedQa && File.Exists(Path.Combine(root, ".tio-owned-qa"));
        foreach (var process in System.Diagnostics.Process.GetProcessesByName("ti"))
        using (process)
        {
            try
            {
                string? image = process.MainModule?.FileName;
                if (image is null || string.Equals(Path.GetDirectoryName(image), Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase)) isolated = false;
            }
            catch (System.ComponentModel.Win32Exception) { isolated = false; }
        }
        if (!isolated) throw new IOException(message);
    }
}
