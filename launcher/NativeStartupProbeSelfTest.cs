using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace TioLauncher;

internal static class NativeStartupProbeSelfTest
{
    static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    internal static void Run(string output)
    {
        var results = new List<string>();
        string root = Path.Combine(Path.GetTempPath(), "tio-native-state-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        IntPtr memory = Marshal.AllocHGlobal(4);
        try
        {
            using var self = Process.GetCurrentProcess();
            Marshal.WriteInt32(memory, 0);
            Check(NativeStartupProbe.ReadUInt32(self.Handle, memory.ToInt64()) == 0, "a valid zero was rejected");
            Marshal.WriteInt32(memory, 3);
            Check(NativeStartupProbe.ReadUInt32(self.Handle, memory.ToInt64()) == 3, "a valid value was lost");
            try
            {
                NativeStartupProbe.ReadUInt32(self.Handle, 0);
                throw new Exception("an invalid address was silently treated as zero");
            }
            catch (Win32Exception error) { Check(error.NativeErrorCode != 0, "Windows read error was lost"); }
            results.Add("PASS: real process-memory reads distinguish a valid zero from an unreadable address");

            Check(NativeStartupProbe.ExitCode(self.Handle) is null, "a running process was reported as exited");
            foreach (uint code in new uint[] { 37, 259 })
            {
                var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"))
                    { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                foreach (string argument in new[] { "/d", "/c", "exit", "/b", code.ToString() }) start.ArgumentList.Add(argument);
                using var child = Process.Start(start) ?? throw new IOException("owned test process did not start");
                Check(child.WaitForExit(5000), "owned test process did not exit");
                Check(NativeStartupProbe.ExitCode(child.Handle) == code, "actual exit code was not preserved");
                var ended = NativeStartupProbe.Capture(child.Handle, (uint)child.Id, null);
                Check(ended.Exited == true && ended.ExitCode == code, "exited-process snapshot was incorrect");
                Check(ended.OrangeLoaded is null && ended.SilverLoaded is null, "module absence was fabricated after exit");
            }
            results.Add("PASS: running processes and exited processes are distinct, including an actual exit code of 259");

            var live = NativeStartupProbe.Capture(self.Handle, (uint)self.Id, memory.ToInt64());
            Check(live.Exited == false && live.BootstrapPhase == 3, "live process/bootstrap state was not captured");
            Check(live.OrangeLoaded == false && live.SilverLoaded == false, "absent native DLLs were reported as loaded");
            var unreadable = NativeStartupProbe.Capture(self.Handle, (uint)self.Id, 0);
            Check(unreadable.BootstrapPhase is null && unreadable.Errors.Any(e => e.Field == "bootstrap_phase" && e.Win32Error != 0),
                "an unreadable bootstrap phase was not diagnosed");
            Check(unreadable.OrangeLoaded == false, "a failed memory read prevented module inspection");
            results.Add("PASS: snapshots capture bootstrap/module state and preserve individual probe failures");

            var failure = new Win32Exception(5, "owned read failure");
            failure.Data["native_startup"] = live;
            Check(StartupDiagnostics.TrySave(root, "native_startup", TimeSpan.FromSeconds(1), failure, []), "snapshot report failed");
            using (var report = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "startup-failure.json"))))
            {
                var data = report.RootElement;
                Check(data.GetProperty("native_state").GetProperty("bootstrap_phase").GetUInt32() == 3, "snapshot was omitted from JSON");
                Check(data.GetProperty("error").GetProperty("win32_error_code").GetInt32() == 5, "native Windows error code was omitted");
            }
            results.Add("PASS: the saved failure report includes the native snapshot and Windows error code");
            File.WriteAllLines(output, results);
        }
        catch (Exception error)
        {
            File.WriteAllText(output, string.Join(Environment.NewLine, results) + Environment.NewLine + "FAIL: " + error);
            Environment.ExitCode = 1;
        }
        finally
        {
            Marshal.FreeHGlobal(memory);
            Directory.Delete(root, recursive: true);
        }
    }
}
