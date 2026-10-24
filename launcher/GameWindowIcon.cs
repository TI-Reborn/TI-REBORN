using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

// The TLS helper retains these HICONs for its child's entire lifetime. Only
// visible top-level windows belonging to that exact process receive WM_SETICON.
// No client executable/resource hash, game memory or window class is changed.
internal sealed class GameWindowIcon : IAsyncDisposable
{
    const uint GetIcon = 0x007f, SetIcon = 0x0080;
    const uint AbortIfHung = 0x0002;
    readonly Process game;
    readonly Icon small, large;
    readonly CancellationTokenSource stop = new();
    readonly Task monitor;
    int applications;
    internal int Applications => Volatile.Read(ref applications);

    delegate bool WindowCallback(IntPtr window, IntPtr parameter);
    [DllImport("user32")] static extern bool EnumWindows(WindowCallback callback, IntPtr parameter);
    [DllImport("user32")] static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32", CharSet = CharSet.Unicode)]
    static extern IntPtr SendMessageTimeout(IntPtr window, uint message, UIntPtr wparam, IntPtr lparam,
        uint flags, uint timeout, out IntPtr result);

    internal GameWindowIcon(Process game)
    {
        this.game = game;
        using var stream = typeof(GameWindowIcon).Assembly.GetManifestResourceStream("TioLauncher.icon.ico")!;
        small = new Icon(stream, SystemInformation.SmallIconSize);
        stream.Position = 0;
        large = new Icon(stream, new Size(256, 256));
        monitor = Task.Run(Monitor);
    }

    static bool Message(IntPtr window, uint message, uint kind, IntPtr icon, out IntPtr result) =>
        SendMessageTimeout(window, message, kind, icon, AbortIfHung, 100, out result) != IntPtr.Zero;

    internal bool Matches(IntPtr window) =>
        Message(window, GetIcon, 0, IntPtr.Zero, out var smallIcon) && smallIcon == small.Handle &&
        Message(window, GetIcon, 1, IntPtr.Zero, out var largeIcon) && largeIcon == large.Handle;

    internal bool Apply(IntPtr window)
    {
        GetWindowThreadProcessId(window, out var owner);
        if (owner != (uint)game.Id || !IsWindowVisible(window)) return true;
        if (!Matches(window) &&
            Message(window, SetIcon, 0, small.Handle, out _) &&
            Message(window, SetIcon, 1, large.Handle, out _) && Matches(window))
            Interlocked.Increment(ref applications);
        return true;
    }

    async Task Monitor()
    {
        try
        {
            while (!stop.IsCancellationRequested && !game.HasExited)
            {
                EnumWindows((window, _) => Apply(window), IntPtr.Zero);
                await Task.Delay(250, stop.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (InvalidOperationException) { } // Process exited/disposed during polling.
        catch (System.ComponentModel.Win32Exception) { } // Cosmetic failure cannot end a game.
    }

    public async ValueTask DisposeAsync()
    {
        stop.Cancel();
        await monitor.ConfigureAwait(false);
        small.Dispose(); large.Dispose(); stop.Dispose();
    }

    // Apply the cosmetic update to an already running, SHA-pinned native client.
    // This helper keeps its icons alive until that process exits; it never owns
    // the player's process lifetime and never closes/restarts the game.
    internal static async Task AttachExisting(int pid, string report)
    {
        using var game = Process.GetProcessById(pid);
        string executable = game.MainModule?.FileName ?? throw new IOException("Missing native game image.");
        using (var file = File.OpenRead(executable))
            if (!Path.GetFileName(executable).Equals("ti.exe", StringComparison.OrdinalIgnoreCase) ||
                Convert.ToHexStringLower(SHA256.HashData(file)) is var hash && hash != "e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c" && hash != NativeLaunchGate.ImageSha256)
                throw new InvalidDataException("Unsupported native game image.");
        await using var icon = new GameWindowIcon(game);
        while (!game.HasExited && icon.Applications == 0) await Task.Delay(100).ConfigureAwait(false);
        File.WriteAllText(report, JsonSerializer.Serialize(new { passed = icon.Applications > 0, pid,
            icon_applications = icon.Applications, game_restarted = false, client_files_changed = false }));
        if (!game.HasExited) await game.WaitForExitAsync().ConfigureAwait(false);
    }
}
