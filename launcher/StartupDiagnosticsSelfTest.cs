using System.Text.Json;

namespace TioLauncher;

internal static class StartupDiagnosticsSelfTest
{
    static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    internal static void Run(string output)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-startup-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var results = new List<string>();
        try
        {
            Check(GameStarter.StartupTimeout == TimeSpan.FromSeconds(90), "native startup must allow 90 seconds");
            results.Add("PASS: native startup deadline is 90 seconds");

            var error = new IOException("network module fixture timeout");
            object[] events = [new { phase = "tls_bootstrap_prepared" }, new { phase = "debugger_detached" }];
            Check(StartupDiagnostics.TrySave(root, "native_startup", TimeSpan.FromSeconds(91), error, events), "failure report was not saved");
            string path = Path.Combine(root, "startup-failure.json");
            using (var report = JsonDocument.Parse(File.ReadAllText(path)))
            {
                var data = report.RootElement;
                Check(data.GetProperty("launcher_version").GetString() == LauncherUpdate.CurrentVersion, "launcher version missing");
                Check(data.GetProperty("phase").GetString() == "native_startup", "startup phase missing");
                Check(data.GetProperty("elapsed_ms").GetDouble() == 91000, "elapsed time missing");
                Check(data.GetProperty("native_timeout_seconds").GetDouble() == 90, "deadline missing");
                Check(data.GetProperty("error").GetProperty("message").GetString() == error.Message, "error message missing");
                Check(data.GetProperty("error").GetProperty("type").GetString() == typeof(IOException).FullName, "error type missing");
                Check(data.GetProperty("error").GetProperty("hresult").GetInt32() == error.HResult, "Windows error information missing");
                Check(data.GetProperty("native_events")[1].GetProperty("phase").GetString() == "debugger_detached", "native progress missing");
                Check(data.GetProperty("created_utc").GetDateTimeOffset().Offset == TimeSpan.Zero, "report time must be UTC");
            }
            results.Add("PASS: failure report preserves the error, native stages, duration, deadline, version and UTC time");

            Check(StartupDiagnostics.TrySave(root, "tls_preflight", TimeSpan.FromSeconds(2), new IOException("second failure"), []), "second report failed");
            using (var report = JsonDocument.Parse(File.ReadAllText(path)))
            {
                Check(report.RootElement.GetProperty("phase").GetString() == "tls_preflight", "old report was not replaced");
                Check(report.RootElement.GetProperty("native_events").GetArrayLength() == 0, "old native events leaked into a new report");
            }
            Check(Directory.GetFiles(root).Length == 1, "temporary reports accumulated");
            results.Add("PASS: subsequent failures atomically replace the previous report without leftover temporary files");

            Check(!StartupDiagnostics.TrySave(path, "native_startup", TimeSpan.Zero, error, events), "unwritable report folder was accepted");
            using (var report = JsonDocument.Parse(File.ReadAllText(path)))
                Check(report.RootElement.GetProperty("phase").GetString() == "tls_preflight", "failed save damaged the previous report");
            results.Add("PASS: an unwritable diagnostics folder does not replace the original startup error or damage the previous report");

            object[] manyEvents = Enumerable.Range(0, 300).Select(index => (object)new { phase = "exception", index }).ToArray();
            Check(StartupDiagnostics.TrySave(root, "native_startup", TimeSpan.FromSeconds(90), error, manyEvents), "bounded trace report failed");
            using (var report = JsonDocument.Parse(File.ReadAllText(path)))
            {
                var trace = report.RootElement.GetProperty("native_events");
                Check(trace.GetArrayLength() == 256 && trace[255].GetProperty("index").GetInt32() == 299, "report must keep the latest 256 events");
            }
            results.Add("PASS: diagnostic trace is bounded and preserves the latest native events");
            File.WriteAllLines(output, results);
        }
        catch (Exception error)
        {
            File.WriteAllText(output, string.Join(Environment.NewLine, results) + Environment.NewLine + "FAIL: " + error);
            Environment.ExitCode = 1;
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
