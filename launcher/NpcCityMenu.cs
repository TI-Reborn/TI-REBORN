using System.Diagnostics;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Authentication;
using System.Text.Json;

namespace TioLauncher;

internal sealed class NpcCityMenu : IDisposable
{
    internal const int IconSize = 48;
    internal readonly record struct Entry(string Id, string Name, bool HasQuest);
    internal readonly record struct MenuLayout(Rectangle Window, Rectangle Emblem, Rectangle List, float Scale);
    static readonly Color Panel = Color.FromArgb(24, 28, 29);
    static readonly Color Text = Color.FromArgb(239, 229, 204);
    readonly CancellationTokenSource stopping = new();
    readonly NativeNpcAnchor anchor;
    readonly RuthQuestWindow ruth;
    Overlay? active;

    internal NpcCityMenu(TlsBridge bridge, Process game, string presentation)
    {
        anchor = new(game);
        ruth = new(bridge, game, presentation == GameInterface.New);
        var thread = new Thread(() =>
        {
            try { Run(bridge); }
            catch (Exception error) when (error is IOException or ArgumentException or InvalidOperationException)
            { Console.Error.WriteLine($"Location NPC menu: {error.Message}"); }
        }) { IsBackground = true, Name = "Location NPC menu" };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
    }

    internal static bool HasQuest(IEnumerable<Entry> npcs) => npcs.Any(npc => npc.HasQuest);
    internal static int Pixels(int logical, float scale) => (int)Math.Round(logical * scale);

    internal static MenuLayout? Arrange(Rectangle card, float scale, int rows, bool expanded = true,
        Rectangle actions = default)
    {
        scale = Math.Min(scale, Math.Min(card.Width / 275f, card.Height / 56f));
        int menuHeight = Math.Min(card.Height, Pixels(Math.Min(4, Math.Max(1, rows)) * 52 + 4, scale));
        var fullMenu = new Rectangle(card.Left, card.Bottom - menuHeight, Pixels(275, scale), menuHeight);
        if (!actions.IsEmpty && fullMenu.IntersectsWith(actions))
        {
            card = Rectangle.FromLTRB(actions.Right + Pixels(4, scale), card.Top, card.Right, card.Bottom);
            scale = Math.Min(scale, card.Width / 275f);
        }
        if (scale < .65f) return null; // A mostly off-screen card cannot fit readable controls.
        expanded &= rows > 0;
        int icon = Pixels(IconSize, scale);
        int height = expanded ? Math.Min(card.Height, Pixels(Math.Min(4, rows) * 52 + 4, scale)) : icon;
        int width = expanded ? Pixels(275, scale) : icon;
        int listLeft = Pixels(53, scale);
        return new MenuLayout(new Rectangle(card.Left, card.Bottom - height, width, height),
            new Rectangle(0, height - icon, icon, icon),
            expanded ? new Rectangle(listLeft, 0, width - listLeft, height) : Rectangle.Empty, scale);
    }

    internal static Entry[] Entries(JsonElement location, int town)
    {
        var current = location.GetProperty("town");
        if (current.ValueKind != JsonValueKind.Number || current.GetInt32() != town) return [];
        return location.GetProperty("npcs").EnumerateArray()
            .Select(npc => new Entry(npc.GetProperty("id").GetString()!, npc.GetProperty("name").GetString()!,
                npc.GetProperty("has_available_quest").GetBoolean())).ToArray();
    }

    internal static Bitmap LoadArt(string name)
    {
        using var stream = typeof(NpcCityMenu).Assembly.GetManifestResourceStream($"TioLauncher.{name}.png")
            ?? throw new InvalidDataException($"Missing NPC image: {name}");
        using var image = Image.FromStream(stream);
        return new Bitmap(image);
    }

    void Run(TlsBridge bridge)
    {
        NativeNpcAnchor.UsePhysicalPixels();
        using var icon = LoadArt("ruth-dialogue");
        using var portrait = LoadArt("ruth-voss");
        var speakers = new Dictionary<string, (Image Portrait, Action<NativeNpcAnchor.Placement> Talk)>
        {
            ["ruth"] = (portrait, ruth.Show)
        };
        using var window = new Overlay();
        using var loop = new ApplicationContext();
        using var timer = new System.Windows.Forms.Timer { Interval = 110 };
        using var tips = new ToolTip();
        active = window;
        var emblem = Button();
        emblem.AccessibleName = "Персонажи локации";
        emblem.Size = new Size(IconSize, IconSize);
        window.Controls.Add(emblem);
        var list = new FlowLayoutPanel
        {
            BackColor = Panel, BorderStyle = BorderStyle.FixedSingle, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, AutoScroll = true, Visible = false, AccessibleName = "Выбрать персонажа"
        };
        window.Controls.Add(list);

        Entry[] npcs = [];
        bool expanded = false, polling = false;
        int location = 0;
        var nextPoll = DateTime.MinValue;
        NativeNpcAnchor.Placement? placement = null;
        float scale = 1;
        int Px(int size) => Pixels(size, scale);
        void Layout()
        {
            if (placement is not { } point) return;
            if (Arrange(point.Card, point.Scale, npcs.Length, expanded, point.Actions) is not { } layout)
            {
                window.Hide();
                return;
            }
            scale = layout.Scale;
            window.Bounds = layout.Window;
            emblem.Bounds = layout.Emblem;
            list.Bounds = layout.List;
            list.SuspendLayout();
            foreach (Control row in list.Controls)
            {
                row.Size = new Size(Px(198), Px(46));
                row.Margin = new Padding(Px(2));
            }
            list.ResumeLayout();
            list.Visible = expanded;
            using var shape = new Region(emblem.Bounds);
            if (expanded) shape.Union(list.Bounds);
            window.Region?.Dispose();
            window.Region = shape.Clone();
        }
        void Expand(bool open)
        {
            if (expanded == open) return;
            expanded = open;
            Layout();
            if (open && list.Controls.Count != 0) list.Controls[0].Focus();
        }
        void Update(Entry[] found)
        {
            if (npcs.SequenceEqual(found)) return;
            npcs = found;
            emblem.AccessibleDescription = HasQuest(npcs) ? "Есть доступные задания" : "";
            tips.SetToolTip(emblem, HasQuest(npcs) ? "Персонажи локации · есть задания" : "Персонажи локации");
            emblem.Invalidate();
            list.SuspendLayout();
            try
            {
                while (list.Controls.Count != 0) list.Controls[0].Dispose();
                foreach (var npc in npcs)
                {
                    var speaker = speakers[npc.Id];
                    var row = Button();
                    row.AccessibleName = npc.Name;
                    row.AccessibleDescription = npc.HasQuest ? "Есть доступное задание" : "";
                    row.Paint += (_, e) =>
                    {
                        NpcGlow.Portrait(e.Graphics, speaker.Portrait, new Rectangle(Px(7), Px(6), Px(33), Px(33)), npc.HasQuest, scale);
                        using var font = new Font(row.Font.FontFamily, Px(13), GraphicsUnit.Pixel);
                        TextRenderer.DrawText(e.Graphics, npc.Name, font, new Rectangle(Px(51), 0, Px(140), row.Height),
                            Text, TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
                    };
                    row.Click += (_, _) =>
                    {
                        if (placement is not { } target) return;
                        Expand(false);
                        speaker.Talk(target);
                        window.Hide();
                    };
                    list.Controls.Add(row);
                }
            }
            finally { list.ResumeLayout(); }
            if (npcs.Length == 0) Expand(false);
            Layout();
        }

        emblem.Paint += (_, e) => NpcGlow.Icon(e.Graphics, icon,
            new Rectangle(Px(1), Px(1), Px(46), Px(46)), HasQuest(npcs), scale);
        emblem.Click += (_, _) => Expand(!expanded);
        window.Deactivate += (_, _) => Expand(false);
        window.KeyDown += (_, key) => { if (key.KeyCode == Keys.Escape) Expand(false); };
        timer.Tick += async (_, _) =>
        {
            if (stopping.IsCancellationRequested) { loop.ExitThread(); return; }
            var current = ruth.IsShowing ? null : anchor.Read(window.Handle);
            if (current is not { } point)
            {
                Expand(false);
                window.Hide();
                Update([]);
                placement = null;
                nextPoll = DateTime.MinValue;
                return;
            }
            if (placement != current)
            {
                placement = current;
                Layout();
            }
            if (location != point.Town)
            {
                location = point.Town;
                Update([]);
                window.Hide();
                nextPoll = DateTime.MinValue;
            }
            if (npcs.Length != 0 && !window.Visible
                && Arrange(point.Card, point.Scale, npcs.Length, expanded, point.Actions) is not null)
                window.ShowAboveGame();
            if (polling || DateTime.UtcNow < nextPoll) return;
            polling = true;
            nextPoll = DateTime.UtcNow.AddSeconds(1);
            try
            {
                var reply = await bridge.Contracts(new { action = "location_npcs" }, stopping.Token);
                if (stopping.IsCancellationRequested || placement?.Town != point.Town) return;
                Update(reply.GetProperty("ok").GetBoolean()
                    ? Entries(reply.GetProperty("state"), point.Town).Where(npc => speakers.ContainsKey(npc.Id)).ToArray()
                    : []);
                if (npcs.Length == 0) window.Hide();
            }
            catch (Exception error) when (error is IOException or SocketException or JsonException
                or AuthenticationException or OperationCanceledException)
            {
                Update([]);
                window.Hide();
            }
            finally { polling = false; }
        };
        timer.Start();
        Application.Run(loop);
        active = null;
    }

    static Button Button()
    {
        var button = new Button { BackColor = Panel, ForeColor = Text, FlatStyle = FlatStyle.Flat,
            UseVisualStyleBackColor = false, Margin = new Padding(2) };
        button.FlatAppearance.BorderColor = Color.FromArgb(91, 73, 49);
        return button;
    }

    sealed class Overlay : Form
    {
        [DllImport("user32", SetLastError = true)]
        static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

        internal void ShowAboveGame()
        {
            const uint noSizeMoveActivate = 0x0001 | 0x0002 | 0x0010;
            Show();
            if (!SetWindowPos(Handle, new IntPtr(-1), 0, 0, 0, 0, noSizeMoveActivate))
                throw new InvalidOperationException("Could not put the NPC menu above the game.");
        }

        internal Overlay()
        {
            Text = "Персонажи локации";
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = true;
            TopMost = true;
            AutoScaleMode = AutoScaleMode.None;
            KeyPreview = true;
        }

        protected override bool ShowWithoutActivation => true;
    }

    public void Dispose()
    {
        stopping.Cancel();
        ruth.Dispose();
        if (active is { IsHandleCreated: true, IsDisposed: false } window)
        {
            try { window.BeginInvoke(window.Close); }
            catch (InvalidOperationException) { }
        }
    }
}
