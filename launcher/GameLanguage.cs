using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace TioLauncher;

static class GameLanguage
{
    static readonly string[] OverlayFiles = ["battlelog.xml", "quest/00000.xml", "quest/tut_1000.xml", "rules.txt", "help.txt"];
    internal static string SettingsPath => Path.Combine(SteamDistribution.SettingsRoot, "language.txt");
    internal static string Load(string? path = null)
    {
        try { string value = File.ReadAllText(path ?? SettingsPath).Trim(); return value == "english" ? value : "russian"; }
        catch (IOException) { return "russian"; }
        catch (UnauthorizedAccessException) { return "russian"; }
    }
    internal static void Save(string language, string? path = null)
    {
        Validate(language); string target = path ?? SettingsPath;
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        string pending = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(pending, language, new UTF8Encoding(false)); File.Move(pending, target, true); }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
    internal static void Validate(string value)
    {
        if (value is not ("russian" or "english")) throw new ArgumentException("Unsupported game language");
    }
    internal static byte[] Config(byte[] bytes, string language)
    {
        Validate(language);
        // Byte-preserving roundtrip: credentials and other settings may be cp1251.
        string text = Encoding.Latin1.GetString(bytes);
        var pattern = new Regex(@"(?m)^[\t ]*g_language[^\r\n]*(?:\r?\n|$)");
        string line = "g_language " + language + (text.Contains("\r\n") ? "\r\n" : "\n");
        bool written = false;
        text = pattern.Replace(text, _ => { if (written) return ""; written = true; return line; });
        if (!written) text += (text.Length != 0 && !text.EndsWith('\n') ? "\r\n" : "") + line;
        return Encoding.Latin1.GetBytes(text);
    }
    internal static void Apply(string root, string language, bool ownedQa = false)
    {
        Validate(language);
        if (Updater.GameRunning())
        {
            bool isolated=ownedQa && File.Exists(Path.Combine(root,".tio-owned-qa"));
            foreach(var process in System.Diagnostics.Process.GetProcessesByName("ti"))
            using(process)
            {
                try
                {
                    string? image=process.MainModule?.FileName;
                    if(image is null || string.Equals(Path.GetDirectoryName(image),Path.GetFullPath(root),StringComparison.OrdinalIgnoreCase))isolated=false;
                }
                catch(System.ComponentModel.Win32Exception){isolated=false;}
            }
            if(!isolated)throw new IOException(L.Text("Закройте игру перед сменой языка."));
        }
        string locale = language == "english" ? "en" : "ru";
        var replacements = new List<(string Target, byte[] Data)>();
        foreach (string name in OverlayFiles)
        {
            string source = Safe(root, "base/locales/" + locale + "/" + name);
            replacements.Add((Safe(root, "base/" + name), File.ReadAllBytes(source)));
        }
        string config = Safe(root, "base/config.cfg");
        replacements.Add((config, Config(File.Exists(config) ? File.ReadAllBytes(config) : [], language)));
        // Validate/read every resource before writing. Roll back partial writes.
        var previous = replacements.Select(x => (x.Target, Data: File.Exists(x.Target) ? File.ReadAllBytes(x.Target) : null)).ToArray();
        try { foreach (var entry in replacements) Atomic(entry.Target, entry.Data); }
        catch
        {
            foreach (var entry in previous)
                if (entry.Data != null) Atomic(entry.Target, entry.Data); else if (File.Exists(entry.Target)) File.Delete(entry.Target);
            throw;
        }
    }
    static string Safe(string root, string relative)
    {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        string target = Path.GetFullPath(Path.Combine(root, relative));
        if (!target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe locale path");
        for (string? p = target; p != null; p = Path.GetDirectoryName(p))
            if ((File.Exists(p) || Directory.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked locale path");
        return target;
    }
    static void Atomic(string path, byte[] data)
    {
        string pending = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllBytes(pending, data); File.Move(pending, path, true); }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
}

static class L
{
    internal static string Language = GameLanguage.Load();
    static readonly Dictionary<string, string> English = Load();
    static Dictionary<string, string> Load()
    {
        using var stream = typeof(L).Assembly.GetManifestResourceStream("TioLauncher.english.json")!;
        var result=JsonSerializer.Deserialize<Dictionary<string,string>>(stream)!;
        result["Клиент {version} готов к запуску"]="Client {version} ready to launch";
        result["Недопустимый архив обновления."]="Invalid update archive.";
        result["Проверка архива обновления…"]="Checking update archive…";
        result["Распаковка · "]="Extracting · ";
        result["Установка · "]="Installing · ";
        result["Полная проверка файлов · "]="Full file verification · ";
        result["Сервер прислал неверный диапазон архива."]="The server returned an invalid archive range.";
        result["Загрузка архива клиента…"]="Downloading client archive…";
        result["Загрузка архива · {received} / {size} МБ"]="Downloading archive · {received} / {size} MB";
        result["Архив загружен не полностью или повреждён. Повторите проверку."]="The archive is incomplete or corrupted. Retry verification.";
        return result;
    }
    internal static string Text(string source)
    {
        foreach (var pair in English)
        {
            string from = Language == "english" ? pair.Key : pair.Value;
            string to = Language == "english" ? pair.Value : pair.Key;
            if (source == from) return to;
        }
        foreach (var pair in English.OrderByDescending(x => x.Key.Length))
        {
            string from = Language == "english" ? pair.Key : pair.Value;
            string to = Language == "english" ? pair.Value : pair.Key;
            var tokens = Regex.Matches(from, @"\{[^{}]+\}");
            if (tokens.Count == 0) continue;
            string pattern = ""; int last = 0;
            foreach (Match token in tokens) { pattern += Regex.Escape(from[last..token.Index]) + "(.*?)"; last = token.Index + token.Length; }
            var match = Regex.Match(source, "^" + pattern + Regex.Escape(from[last..]) + "$", RegexOptions.Singleline);
            if (!match.Success) continue;
            int i = 0;
            return Regex.Replace(to, @"\{[^{}]+\}", _ => match.Groups[++i].Value);
        }
        // A complete message/template takes priority over a shorter fragment.
        // Preserve opaque file paths/version values in the remaining suffix.
        foreach (var pair in English.OrderByDescending(x => Language == "english" ? x.Key.Length : x.Value.Length))
        {
            string from=Language == "english" ? pair.Key : pair.Value;
            string to=Language == "english" ? pair.Value : pair.Key;
            if (from.Length >= 5 && from.EndsWith(' ') && source.StartsWith(from, StringComparison.Ordinal)) return to + source[from.Length..];
        }
        return source;
    }
    internal static void Refresh(Control control)
    {
        if (control is not ComboBox) control.Text = Text(control.Text);
        foreach (Control child in control.Controls) Refresh(child);
    }
}
