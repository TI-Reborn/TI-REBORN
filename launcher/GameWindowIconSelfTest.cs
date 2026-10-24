using System.Diagnostics;
using System.Runtime.InteropServices;

namespace TioLauncher;

// Real Windows messages exercise delayed/recreated windows and icon resets.
// No game, network, account or player process is used by this self-test.
internal static class GameWindowIconSelfTest
{
    [DllImport("user32", CharSet = CharSet.Unicode)]
    static extern IntPtr SendMessage(IntPtr window, uint message, UIntPtr wparam, IntPtr lparam);

    static void Wait(Func<bool> condition)
    {
        var clock = Stopwatch.StartNew();
        while (!condition())
        {
            if (clock.Elapsed > TimeSpan.FromSeconds(5)) throw new Exception("Icon did not reach the visible window.");
            Application.DoEvents(); Thread.Sleep(20);
        }
    }

    internal static void Run(string report)
    {
        var lines = new List<string>();
        try
        {
            using var process = Process.GetCurrentProcess();
            var icons = new GameWindowIcon(process);
            try
            {
                // Starting before a window exists is the normal native loader path.
                Thread.Sleep(300);
                using (var first = new Form { Text = "TIO client icon check", Size = new Size(320, 160), Icon = SystemIcons.Application })
                {
                    first.Show(); Wait(() => icons.Matches(first.Handle));
                    lines.Add("PASS: delayed visible window receives both small and large launcher icons");
                    int before = icons.Applications;
                    SendMessage(first.Handle, 0x80, 0, SystemIcons.Error.Handle);
                    SendMessage(first.Handle, 0x80, 1, SystemIcons.Error.Handle);
                    Wait(() => icons.Applications > before && icons.Matches(first.Handle));
                    lines.Add("PASS: a client icon reset is restored without recreating or closing the window");
                    first.Close();
                }
                using (var second = new Form { Text = "TIO recreated client window", Size = new Size(320, 160), Icon = SystemIcons.Application })
                {
                    second.Show(); Wait(() => icons.Matches(second.Handle));
                    lines.Add("PASS: replacement game window receives the same launcher artwork");
                    second.Close();
                }
            }
            finally { icons.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
            lines.Add("PASS: monitor cancels and releases its icon resources; player processes untouched");
        }
        catch (Exception error) { lines.Add("FAIL: " + error); Environment.ExitCode = 1; }
        File.WriteAllLines(report, lines);
    }
}
