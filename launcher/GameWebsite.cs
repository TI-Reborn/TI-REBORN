using System.Text;
using System.Text.RegularExpressions;

namespace TioLauncher;

internal static class GameWebsite
{
    internal const string Url = "https://ti-reborn.com/";
    internal static byte[] Config(byte[] original)
    {
        // Native settings may contain CP1251 names: round-trip every other byte.
        bool bom = original.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf });
        string text = Encoding.Latin1.GetString(original.AsSpan(bom ? 3 : 0));
        string newline = text.Contains("\r\n") ? "\r\n" : "\n";
        string line = "g_weblink " + Url + newline;
        bool written = false;
        text = Regex.Replace(text, @"(?m)^[\t ]*g_weblink(?=[\t =\r\n]|$)[^\r\n]*(?:\r?\n|$)",
            _ => { if (written) return ""; written = true; return line; });
        if (!written) text += (text.Length > 0 && !text.EndsWith('\n') ? newline : "") + line;
        byte[] output = Encoding.Latin1.GetBytes(text);
        return bom ? new byte[] { 0xef, 0xbb, 0xbf }.Concat(output).ToArray() : output;
    }

    internal static void Apply(string root)
    {
        root = Path.GetFullPath(root);
        var changes = new List<(string Path, byte[]? Before, byte[] After)>();
        foreach (string name in new[] { "config.cfg", "autoexec.cfg" })
        {
            string target = Path.Combine(root, "base", name);
            for (string? path = target; path != null; path = Path.GetDirectoryName(path))
                if ((File.Exists(path) || Directory.Exists(path)) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Linked game settings path.");
            byte[]? before = File.Exists(target) ? File.ReadAllBytes(target) : null;
            byte[] after = Config(before ?? []);
            if (before == null || !before.AsSpan().SequenceEqual(after)) changes.Add((target, before, after));
        }
        try { foreach (var change in changes) Atomic(change.Path, change.After); }
        catch
        {
            foreach (var change in changes)
                if (change.Before != null) Atomic(change.Path, change.Before);
                else if (File.Exists(change.Path)) File.Delete(change.Path);
            throw;
        }
    }

    static void Atomic(string path, byte[] bytes)
    {
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllBytes(temporary, bytes); File.Move(temporary, path, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
