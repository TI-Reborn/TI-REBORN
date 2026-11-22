using System.Runtime.InteropServices;
using System.Text.Json;

namespace TioLauncher;

internal static class NpcCityMenuSelfTest
{
    [DllImport("user32")] static extern IntPtr GetParent(IntPtr window);
    [DllImport("user32")] static extern uint GetWindowLong(IntPtr window, int index);

    internal static void Run(string report)
    {
        static void Check(bool rule, string failure)
        {
            if (!rule) throw new InvalidOperationException(failure);
        }

        using var server = JsonDocument.Parse("""
            {"town":3,"npcs":[
                {"id":"ruth","name":"Рут Восс","has_available_quest":false},
                {"id":"other","name":"Тест","has_available_quest":true}
            ]}
            """);
        var list = NpcCityMenu.Entries(server.RootElement, 3);
        Check(list.Length == 2 && !list[0].HasQuest && list[1].HasQuest, "Highlights belong to each NPC");
        Check(NpcCityMenu.HasQuest(list), "Any available NPC lights the shared icon");
        Check(!NpcCityMenu.HasQuest(list.Take(1)), "The icon dims when no NPC has an available quest");
        Check(NpcCityMenu.Entries(server.RootElement, 2).Length == 0, "Do not reuse one city's portraits in another");
        using var icon = NpcCityMenu.LoadArt("ruth-dialogue");
        using var portrait = NpcCityMenu.LoadArt("ruth-voss");
        Check(icon.Width >= 48 && portrait.Width >= 172 && icon.GetPixel(0, 0).A == 0,
            "Release embeds the NPC portrait and the transparent icon");
        Size[] presets = [new(800, 600), new(1024, 768), new(1280, 720), new(1280, 800),
            new(1366, 768), new(1600, 900), new(1920, 1080), new(2560, 1440), new(3440, 1440), new(3840, 2160)];
        int[] percents = [100, 125, 150, 200];
        int geometries = 0;
        foreach (var size in presets)
        foreach (int requested in percents)
        {
            // The native canvas falls back until a scaled preset has at least 800×768 logical pixels.
            int effective = percents.Last(percent => percent <= requested && (percent == 100 ||
                (size.Width * 100 / percent >= 800 && size.Height * 100 / percent >= 768)));
            var canvas = new Size(size.Width * 100 / effective, size.Height * 100 / effective);
            var client = new Rectangle(new Point(-size.Width, 75), size);
            var screen = Rectangle.Inflate(client, 24, 48);
            foreach (int logicalChat in new[] { canvas.Height - 113, canvas.Height - 256, canvas.Height - 384 })
            {
                var world = Rectangle.FromLTRB(144, 42, canvas.Width - 42, canvas.Height - 206);
                var card = NativeNpcAnchor.VisibleCard(client, screen, canvas, world, logicalChat);
                float scale = Math.Min(size.Width / (float)canvas.Width, size.Height / (float)canvas.Height);
                int X(int logical) => client.Left + (int)Math.Round(logical * (double)size.Width / canvas.Width);
                int Y(int logical) => client.Top + (int)Math.Round(logical * (double)size.Height / canvas.Height);
                var actions = Rectangle.FromLTRB(X(176), Y(112), X(326), Y(297));
                var closed = NpcCityMenu.Arrange(card, scale, 1, false, actions)!.Value;
                var open = NpcCityMenu.Arrange(card, scale, 1, true, actions)!.Value;
                var multipleClosed = NpcCityMenu.Arrange(card, scale, 8, false, actions)!.Value;
                var multiple = NpcCityMenu.Arrange(card, scale, 8, true, actions)!.Value;
                Check(card.Contains(closed.Window) && card.Contains(open.Window) && card.Contains(multiple.Window),
                    $"Every menu stays on the city card at {size}, {requested}%");
                Check(open.Window.Location + (Size)open.Emblem.Location == closed.Window.Location &&
                    multiple.Window.Location + (Size)multiple.Emblem.Location == multipleClosed.Window.Location,
                    "Opening the NPC list must not move the NPC icon");
                Check(closed.Emblem.Width == NpcCityMenu.Pixels(48, scale) && open.List.Left > open.Emblem.Right,
                    "The NPC icon and layout must follow the effective game scale");
                Check(open.Window.Bottom < Y(logicalChat) && !open.Window.IntersectsWith(actions) &&
                    !multiple.Window.IntersectsWith(actions), "The list must clear the chat and city buttons");
                geometries++;
            }
            float fit = RuthQuestWindow.FitScale(effective / 100f, client, screen);
            var dialogSize = new Size(NpcCityMenu.Pixels(RuthQuestWindow.DesignSize.Width, fit),
                NpcCityMenu.Pixels(RuthQuestWindow.DesignSize.Height, fit));
            var dialog = RuthQuestWindow.PanelBounds(client, screen, dialogSize);
            Check(new Rectangle(Point.Empty, client.Size).Contains(dialog) && dialog.Size == dialogSize,
                "The dialogue must fit the game client at the effective scale");
        }
        var oversized = new Rectangle(-600, 0, 3840, 2160);
        var monitor = new Rectangle(0, 0, 1920, 1080);
        var clipped = NativeNpcAnchor.VisibleCard(oversized, monitor, new Size(1920, 1080),
            Rectangle.FromLTRB(144, 42, 1878, 874), 824);
        Check(monitor.Contains(NpcCityMenu.Arrange(clipped, 2, 4)!.Value.Window),
            "A partially off-screen game window must keep the menu inside the monitor");
        var resized = new Rectangle(-600, 0, 875, 430);
        var panelBounds = RuthQuestWindow.PanelBounds(resized, monitor, new Size(650, 482));
        var screenBounds = panelBounds;
        screenBounds.Offset(resized.Location);
        Check(panelBounds.Width > 0 && panelBounds.Height > 0 && monitor.Contains(screenBounds) &&
            resized.Contains(screenBounds), "Keep the child panel within the visible client after a resize");

        using var host = new Form();
        IntPtr owner = host.Handle;
        NativeNpcAnchor.UsePhysicalPixels();
        Check(NativeNpcAnchor.MatchDpi(owner), "Use the host window's DPI awareness before creating dialogue controls");
        using var child = new RuthQuestWindow.GamePanel(host.Handle);
        using var reply = new Button();
        child.Controls.Add(reply);
        uint style = GetWindowLong(child.Handle, -16);
        Check(GetParent(child.Handle) == owner && GetParent(reply.Handle) == child.Handle && (style & 0x40000000) != 0 &&
            (style & 0x80c00000) == 0 && !child.ShowInTaskbar, "The dialogue must be a child without a Windows caption");
        Check(NpcCityMenu.Arrange(new Rectangle(0, 0, 50, 90), 1, 1) is null,
            "Do not open unreadably small menus on a sliver of the game");
        var compactCard = Rectangle.FromLTRB(148, 46, 754, 340);
        var groupButton = Rectangle.FromLTRB(176, 272, 326, 297);
        var compactOpen = NpcCityMenu.Arrange(compactCard, 1, 1, true, groupButton)!.Value;
        var compactClosed = NpcCityMenu.Arrange(compactCard, 1, 1, false, groupButton)!.Value;
        Check(!compactOpen.Window.IntersectsWith(groupButton) && !compactClosed.Window.IntersectsWith(groupButton)
            && compactClosed.Window.Left == compactOpen.Window.Left,
            "At 800×600 the NPC menu must not obscure the native Group button");

        using var fixture = new Bitmap(12, 12);
        using (var graphics = Graphics.FromImage(fixture)) graphics.Clear(Color.White);
        using var normal = new Bitmap(48, 48);
        using var active = new Bitmap(48, 48);
        var bounds = new Rectangle(12, 12, 12, 12);
        using (var graphics = Graphics.FromImage(normal)) NpcGlow.Icon(graphics, fixture, bounds, false);
        using (var graphics = Graphics.FromImage(active)) NpcGlow.Icon(graphics, fixture, bounds, true);
        Check(normal.GetPixel(10, 14).A == 0 && active.GetPixel(10, 14).R > 200 && active.GetPixel(10, 14).A > 0,
            "Icon glow must be painted outside the silhouette");
        Check(normal.GetPixel(16, 16) == active.GetPixel(16, 16), "The glow preserves the original glyph");
        using (var graphics = Graphics.FromImage(normal))
        {
            graphics.Clear(Color.Transparent);
            NpcGlow.Portrait(graphics, fixture, bounds, false);
        }
        using (var graphics = Graphics.FromImage(active))
        {
            graphics.Clear(Color.Transparent);
            NpcGlow.Portrait(graphics, fixture, bounds, true);
        }
        Check(normal.GetPixel(9, 16).A == 0 && active.GetPixel(9, 16).A > 0, "Portrait glow must reach the outer contour");
        File.WriteAllText(report, JsonSerializer.Serialize(new { passed = true, resolutionScalePairs = presets.Length * percents.Length,
            chatGeometryCases = geometries, checks = new[] { "location", "aggregate glow", "independent portrait glow",
                "native HUD geometry", "partially hidden window", "borderless child dialogue", "painted contours" } }));
    }
}
