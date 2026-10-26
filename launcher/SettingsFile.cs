using System.Text;

namespace TioLauncher;

// One launcher preference per file, replaced atomically.
static class SettingsFile
{
    internal static void Save(string path, string value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string pending = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(pending, value, new UTF8Encoding(false)); File.Move(pending, path, true); }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
}
