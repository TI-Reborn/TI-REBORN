namespace TioLauncher;

// The player's barracks and warehouse presentation. "new" is the verified
// release: the A2 layout and HD item art. "original" restores the stock
// layout in Silver and the previous item icons in the client catalogue.
static class GameInterface
{
    internal const string New = "new";
    internal const string Original = "original";
    internal const string Catalogue = "base/shared config/items.xml";
    internal const string OriginalCatalogue = "base/interfaces/original/items.xml";
    internal static string SettingsPath => Path.Combine(SteamDistribution.SettingsRoot, "interface.txt");
    internal static string Load(string? path = null)
    {
        try { return File.ReadAllText(path ?? SettingsPath).Trim() == Original ? Original : New; }
        catch (IOException) { return New; }
        catch (UnauthorizedAccessException) { return New; }
    }
    internal static void Save(string mode, string? path = null)
    {
        Validate(mode); GameFiles.SaveSetting(path ?? SettingsPath, mode);
    }
    internal static void Validate(string mode)
    {
        if (mode is not (New or Original)) throw new ArgumentException("Unsupported interface mode");
    }
    // Launch verification restores the published catalogue immediately
    // before this call, so the new interface needs no file change.
    internal static void Apply(string root, string mode, bool ownedQa = false)
    {
        Validate(mode);
        if (mode == New) return;
        GameFiles.EnsureClosed(root, ownedQa, L.Text("Закройте игру перед сменой интерфейса."));
        byte[] catalogue = File.ReadAllBytes(GameFiles.Resolve(root, OriginalCatalogue));
        GameFiles.WriteAtomic(GameFiles.Resolve(root, Catalogue), catalogue);
    }
}
