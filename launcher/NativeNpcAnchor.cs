using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace TioLauncher;

// Read-only binding to the local client's city surface.
internal sealed class NativeNpcAnchor(Process game, IntPtr initialOwner = default)
{
    internal readonly record struct Placement(IntPtr Owner, Rectangle Client, Rectangle Card, Rectangle Actions, float Scale, int Town);

    [StructLayout(LayoutKind.Sequential)]
    struct Rect { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    struct NativePoint { public int X, Y; }

    [DllImport("user32")] static extern bool GetClientRect(IntPtr window, out Rect bounds);
    [DllImport("user32")] static extern bool ClientToScreen(IntPtr window, ref NativePoint point);
    [DllImport("user32")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint owner);
    [DllImport("user32")] static extern bool IsWindowEnabled(IntPtr window);
    [DllImport("user32")] static extern bool IsIconic(IntPtr window);
    [DllImport("user32")] static extern IntPtr GetWindowDpiAwarenessContext(IntPtr window);
    [DllImport("user32")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);

    long silver;
    long executable;
    IntPtr owner = initialOwner;

    internal static void UsePhysicalPixels() => SetThreadDpiAwarenessContext(new IntPtr(-4));

    // WinForms reparents its controls while creating their HWNDs.
    internal static bool MatchDpi(IntPtr window)
    {
        var context = GetWindowDpiAwarenessContext(window);
        return context != IntPtr.Zero && SetThreadDpiAwarenessContext(context) != IntPtr.Zero;
    }

    internal static Rectangle VisibleCard(Rectangle client, Rectangle screen, Size canvas, Rectangle world, int chatTop)
    {
        if (canvas.Width <= 0 || canvas.Height <= 0) return Rectangle.Empty;
        int bottom = Math.Min(world.Bottom, chatTop);
        if (world.Left >= world.Right || world.Top >= bottom) return Rectangle.Empty;
        var card = Project(client, canvas,
            Rectangle.FromLTRB(world.Left + 4, world.Top + 4, world.Right - 4, bottom - 4));
        return Rectangle.Intersect(Rectangle.Intersect(card, client), screen);
    }

    static Rectangle Project(Rectangle client, Size canvas, Rectangle bounds)
    {
        int X(int value) => client.Left + (int)Math.Round(value * (double)client.Width / canvas.Width);
        int Y(int value) => client.Top + (int)Math.Round(value * (double)client.Height / canvas.Height);
        return Rectangle.FromLTRB(X(bounds.Left), Y(bounds.Top), X(bounds.Right), Y(bounds.Bottom));
    }

    uint Read(long address) => NativeStartupProbe.ReadUInt32(game.Handle, address);

    IEnumerable<uint> Controls(uint list)
    {
        if (list == 0) yield break;
        uint array = Read(list + 4L), count = Read(list + 8L);
        if (array == 0 || count > 512) yield break;
        for (int i = 0; i < count; i++)
        {
            uint control = Read(array + i * 4L);
            if (control != 0 && (Read(control + 0x49L) & 0xff) != 0) yield return control;
        }
    }

    (int ChatTop, Rectangle Actions) Hud(uint manager, int chatTop)
    {
        const string chat = "window_chat", actionsName = "window_pdamap_locmenu";
        Rectangle actions = Rectangle.Empty;
        if (manager == 0) return (chatTop, actions);
        foreach (uint control in Controls(Read(manager + 0x280L)))
        {
            uint name = Read(control + 0x68L);
            if (name < 4) continue;
            int length = (int)Read(name - 4L);
            if (length != chat.Length && length != actionsName.Length) continue;
            string id = Encoding.Unicode.GetString(NativeStartupProbe.ReadBytes(game.Handle, name, length * 2));
            if (id == chat) chatTop = (int)Read(control + 0x34L);
            if (id != actionsName) continue;
            int x = (int)Read(control + 0x30L), y = (int)Read(control + 0x34L);
            // The panel is wider than its buttons and includes a decorative image.
            long buttonClass = silver + 0xa2ed34 - 0x400000;
            foreach (uint button in Controls(Read(control + 0x2cL)))
            {
                if (Read(button) != buttonClass) continue;
                var bounds = new Rectangle(x + (int)Read(button + 0x30L), y + (int)Read(button + 0x34L),
                    (int)Read(button + 0x38L), (int)Read(button + 0x3cL));
                if (!bounds.IsEmpty) actions = actions.IsEmpty ? bounds : Rectangle.Union(actions, bounds);
            }
        }
        return (chatTop, actions);
    }

    internal Placement? Read(IntPtr menu, bool requireForeground = true)
    {
        try
        {
            if (game.HasExited) return null;
            if (silver == 0)
            {
                silver = game.Modules.Cast<ProcessModule>()
                    .FirstOrDefault(module => module.ModuleName.Equals("silver.dll", StringComparison.OrdinalIgnoreCase))
                    ?.BaseAddress.ToInt64() ?? 0;
                if (silver == 0) return null;
                executable = game.MainModule!.BaseAddress.ToInt64();
            }
            if (requireForeground)
            {
                var foreground = GetForegroundWindow();
                GetWindowThreadProcessId(foreground, out uint foregroundPid);
                if (foreground != menu && foregroundPid != game.Id) return null;
                // Delphi's MainWindowHandle can be its tiny, invisible application owner.
                if (foregroundPid == game.Id && GetClientRect(foreground, out var focused)
                    && focused.Right >= 640 && focused.Bottom >= 400)
                    owner = foreground;
            }
            if (owner == IntPtr.Zero || IsIconic(owner) || !IsWindowEnabled(owner)) return null;
            uint Silver(long va) => Read(silver + va - 0x400000);
            bool Set(uint pointer) => pointer != 0 && (Read(pointer) & 0xff) != 0;
            // Mode 1 draws the city background when the world overlay is zero.
            if ((Silver(0xac4c6c) & 0xffff00) != 0x100
                || Set(Silver(0xac64a0)) || Set(Read(executable + 0x36e1f0))) return null;
            uint current = Silver(0xac5d58);
            if (current == 0) return null;
            uint town = Read(current);
            if (town is 0 or > int.MaxValue || !GetClientRect(owner, out var bounds)) return null;
            var point = new NativePoint();
            if (!ClientToScreen(owner, ref point)) return null;
            var client = new Rectangle(point.X, point.Y, bounds.Right, bounds.Bottom);
            uint width = Silver(0xac56e0), height = Silver(0xac5e60), world = Silver(0xac5a4c);
            if (width == 0 || height == 0 || world == 0) return null;
            var canvas = new Size((int)Read(width), (int)Read(height));
            if (canvas.Width <= 0 || canvas.Height <= 0) return null;
            var viewport = Rectangle.FromLTRB((int)Read(world), (int)Read(world + 4L),
                (int)Read(world + 8L), (int)Read(world + 12L));
            var hud = Hud(Silver(0xb76650), canvas.Height);
            var card = VisibleCard(client, Screen.FromHandle(owner).Bounds, canvas, viewport, hud.ChatTop);
            if (card.Width <= 0 || card.Height <= 0) return null;
            var actions = hud.Actions.IsEmpty ? Rectangle.Empty : Project(client, canvas, hud.Actions);
            return new Placement(owner, client, card, actions, Math.Min(client.Width / (float)canvas.Width,
                client.Height / (float)canvas.Height), (int)town);
        }
        catch (Exception error) when (error is Win32Exception or InvalidOperationException)
        {
            return null; // The game can exit or switch scenes between reads.
        }
    }
}
