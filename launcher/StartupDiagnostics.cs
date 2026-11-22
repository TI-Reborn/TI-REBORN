using System.Text.Json;

namespace TioLauncher;

internal static class StartupDiagnostics
{
    internal static bool TrySave(string folder, string phase, TimeSpan elapsed, Exception error, object[] nativeEvents)
    {
        try
        {
            string report = JsonSerializer.Serialize(new
            {
                created_utc = DateTimeOffset.UtcNow,
                launcher_version = LauncherUpdate.CurrentVersion,
                phase,
                elapsed_ms = elapsed.TotalMilliseconds,
                native_timeout_seconds = GameStarter.StartupTimeout.TotalSeconds,
                error = new { type = error.GetType().FullName, message = error.Message, hresult = error.HResult,
                    win32_error_code = (error as System.ComponentModel.Win32Exception)?.NativeErrorCode },
                native_state = error.Data["native_startup"],
                native_events = nativeEvents.TakeLast(256).ToArray()
            }, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
            SettingsFile.Save(Path.Combine(folder, "startup-failure.json"), report);
            return true;
        }
        // Diagnostics must not hide the original launch failure on a full or read-only disk.
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }
}
