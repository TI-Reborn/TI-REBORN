namespace TioLauncher;

// The player's barracks and warehouse presentation. "new" is the A2 layout
// with HD item art; "original" keeps the stock layout (NativeInterfaceMode)
// and asks the server for the previous item icons (LaunchVerification.Flags).
static class GameInterface
{
    internal const string New = "new";
    internal const string Original = "original";
    internal static string SettingsPath => Path.Combine(SteamDistribution.SettingsRoot, "interface.txt");
    internal static string Load(string? path = null)
    {
        try { return File.ReadAllText(path ?? SettingsPath).Trim() == Original ? Original : New; }
        catch (IOException) { return New; }
        catch (UnauthorizedAccessException) { return New; }
    }
    internal static void Save(string mode, string? path = null)
    {
        Validate(mode); SettingsFile.Save(path ?? SettingsPath, mode);
    }
    internal static void Validate(string mode)
    {
        if (mode is not (New or Original)) throw new ArgumentException("Unsupported interface mode");
    }
}
