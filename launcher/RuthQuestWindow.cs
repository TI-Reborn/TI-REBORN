using System.ComponentModel;
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Authentication;
using System.Text.Json;

namespace TioLauncher;

internal sealed class RuthQuestWindow(TlsBridge bridge, Process game, bool themed) : IDisposable
{
    internal static readonly Size DesignSize = new(650, 482);
    const int Inset = 12;
    readonly CancellationTokenSource stopping = new();
    Form? visible;
    int showing;
    internal bool IsShowing => Volatile.Read(ref showing) != 0;

    static Rectangle SafeArea(Rectangle client, Rectangle screen)
        => Rectangle.Inflate(Rectangle.Intersect(client, screen), -Inset, -Inset);

    internal static float FitScale(float scale, Rectangle client, Rectangle screen)
    {
        var area = SafeArea(client, screen);
        return Math.Min(scale, Math.Min(area.Width / (float)DesignSize.Width, area.Height / (float)DesignSize.Height));
    }

    internal static Rectangle PanelBounds(Rectangle client, Rectangle screen, Size preferred)
    {
        var area = SafeArea(client, screen);
        if (area.Width <= 0 || area.Height <= 0) return Rectangle.Empty;
        var size = new Size(Math.Min(preferred.Width, area.Width), Math.Min(preferred.Height, area.Height));
        return new Rectangle(area.Left - client.Left + (area.Width - size.Width) / 2,
            area.Top - client.Top + (area.Height - size.Height) / 2, size.Width, size.Height);
    }

    internal void Show(NativeNpcAnchor.Placement target)
    {
        if (stopping.IsCancellationRequested || Interlocked.Exchange(ref showing, 1) != 0) return;
        var thread = new Thread(() =>
        {
            try
            {
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException, threadScope: true);
                Run(target);
            }
            catch (Exception error) when (error is Win32Exception or InvalidOperationException)
            {
                Console.Error.WriteLine($"NPC dialogue: {error.Message}");
            }
            finally
            {
                visible = null;
                Volatile.Write(ref showing, 0);
            }
        }) { IsBackground = true, Name = "Ruth quest dialogue" };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
    }

    void Run(NativeNpcAnchor.Placement target)
    {
        if (!NativeNpcAnchor.MatchDpi(target.Owner)) return;
        var anchor = new NativeNpcAnchor(game, target.Owner);
        if (anchor.Read(IntPtr.Zero, requireForeground: false) is not { } initial || initial.Town != target.Town) return;
        var screen = Screen.FromHandle(initial.Owner).WorkingArea;
        float scale = FitScale(initial.Scale, initial.Client, screen);
        if (scale < .65f) return;
        int Px(int value) => NpcCityMenu.Pixels(value, scale);
        Rectangle Box(int x, int y, int width, int height) => new(Px(x), Px(y), Px(width), Px(height));
        using var bodyFont = new Font("Segoe UI", Px(13), GraphicsUnit.Pixel);
        using var headingFont = new Font(bodyFont.FontFamily, Px(23), FontStyle.Bold, GraphicsUnit.Pixel);
        using var titleFont = new Font(bodyFont.FontFamily, bodyFont.Size, FontStyle.Bold, GraphicsUnit.Pixel);
        Color panel = Color.FromArgb(28, 32, 34);
        Color ivory = Color.FromArgb(239, 229, 204);
        Color amber = Color.FromArgb(231, 183, 112);
        var panelSize = new Size(Px(DesignSize.Width), Px(DesignSize.Height));
        using var form = new GamePanel(target.Owner)
        {
            Text = "Рут Восс · Резервация",
            Bounds = PanelBounds(initial.Client, screen, panelSize),
            AutoScrollMinSize = panelSize,
            Font = bodyFont
        };
        using var portrait = themed ? NpcCityMenu.LoadArt("ruth-voss") : null;
        using var icon = themed ? NpcCityMenu.LoadArt("ruth-dialogue") : null;
        if (themed)
        {
            form.BackColor = panel;
            form.ForeColor = ivory;
            form.Controls.Add(new PictureBox { Bounds = Box(22, 77, 172, 172),
                Image = portrait, SizeMode = PictureBoxSizeMode.Zoom, AccessibleName = "Портрет Рут Восс" });
            form.Controls.Add(new PictureBox { Bounds = Box(20, 17, 36, 36),
                Image = icon, SizeMode = PictureBoxSizeMode.Zoom });
        }
        int left = themed ? 214 : 24;
        var heading = new Label { Text = "Рут Восс", Bounds = Box(themed ? 65 : 22, 19, 480, 35),
            Font = headingFont };
        var title = new Label { Bounds = Box(left, 76, 626 - left, 32), Font = titleFont };
        if (themed) title.ForeColor = amber;
        var line = new Label { Bounds = Box(left, 110, 626 - left, 107) };
        var progress = new Label { Bounds = Box(left, 220, 626 - left, 91) };
        var answers = new FlowLayoutPanel
        {
            Bounds = Box(22, 317, 606, 151), FlowDirection = FlowDirection.TopDown,
            WrapContents = false, AutoScroll = true
        };
        var close = new Button
        {
            AccessibleName = "Закрыть диалог", Bounds = Box(599, 18, 33, 33)
        };
        if (themed)
        {
            close.FlatStyle = FlatStyle.Flat;
            close.BackColor = Color.FromArgb(43, 47, 46);
            close.FlatAppearance.BorderColor = Color.FromArgb(121, 94, 57);
        }
        close.Paint += (_, e) =>
        {
            int inset = Px(5);
            int edge = close.ClientSize.Width - inset - 1;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var stroke = new Pen(close.ForeColor, Px(2));
            e.Graphics.DrawLine(stroke, inset, inset, edge, edge);
            e.Graphics.DrawLine(stroke, inset, edge, edge, inset);
        };
        form.Paint += (_, e) => ControlPaint.DrawBorder(e.Graphics, form.ClientRectangle,
            themed ? Color.FromArgb(121, 94, 57) : SystemColors.ControlDark, ButtonBorderStyle.Solid);
        close.Click += (_, _) => form.Close();
        form.Controls.AddRange([heading, title, line, progress, answers, close]);
        visible = form;

        JsonElement state = default;
        bool pending = false;
        void Reply(string value, Action action, bool enabled = true)
        {
            var button = new Button { Text = value, TextAlign = ContentAlignment.MiddleLeft,
                Size = new Size(Px(598), Px(32)), Margin = new Padding(Px(2), Px(2), Px(2), Px(1)), Enabled = enabled };
            if (themed)
            {
                button.FlatStyle = FlatStyle.Flat;
                button.BackColor = Color.FromArgb(43, 47, 46);
                button.FlatAppearance.BorderColor = Color.FromArgb(121, 94, 57);
            }
            button.Click += (_, _) => action();
            answers.Controls.Add(button);
        }
        void Scene(string name, string text, string detail = "")
        {
            title.Text = name;
            line.Text = text;
            progress.Text = detail;
            while (answers.Controls.Count != 0) answers.Controls[0].Dispose();
        }
        string Phase(string key) => state.GetProperty(key).GetString()!;
        string Status(string phase) => phase switch {
            "locked" => " · после первого задания", "active" => " · в процессе",
            "ready" => " · готово к сдаче", "done" => " · сдано", _ => ""
        };

        async Task Request(string action, Action render)
        {
            if (pending || form.IsDisposed || stopping.IsCancellationRequested) return;
            pending = true;
            answers.Enabled = false;
            try
            {
                var reply = await bridge.Contracts(new { action = "ruth", value = action }, stopping.Token);
                if (form.IsDisposed) return;
                if (!reply.GetProperty("ok").GetBoolean())
                    throw new InvalidOperationException(reply.GetProperty("error").GetString());
                state = reply.GetProperty("state");
                if (!state.GetProperty("available").GetBoolean())
                    throw new InvalidOperationException("Поговорить с Рут можно в Резервации после вводного урока.");
                render();
            }
            catch (Exception error) when (error is IOException or SocketException or JsonException
                or AuthenticationException or OperationCanceledException or InvalidOperationException)
            {
                if (form.IsDisposed) return;
                Scene("Разговор недоступен", error is InvalidOperationException ? error.Message : "Сервер пока не ответил.");
                Reply("Обновить", async () => await Request("state", Greeting));
                Reply("Закрыть", form.Close);
            }
            finally
            {
                pending = false;
                if (!form.IsDisposed) answers.Enabled = true;
            }
        }
        void Greeting()
        {
            Scene("Дежурная у ворот", "Рут Восс. Дежурю у ворот. До этого водила караваны через Аризону. "
                + "Покажу, где здесь снаряжаются и как записаться на первый бой.");
            Reply("Добро пожаловать в пустошь" + Status(Phase("welcome")), Welcome);
            Reply("Боевое крещение" + Status(Phase("survival")), Survival);
            Reply("Зайду позже", form.Close);
        }
        void Welcome()
        {
            string phase = Phase("welcome");
            var purchased = state.GetProperty("purchases").EnumerateArray().Select(item => item.GetInt32()).ToHashSet();
            string Mark(bool done) => done ? "[+] " : "[ ] ";
            string checklist = Mark(purchased.Contains(245)) + "Heavy Combat Helmet\n"
                + Mark(purchased.Contains(246)) + "Heavy Combat Armor\n"
                + Mark(purchased.Contains(247)) + "Heavy Combat Longies\n"
                + Mark(state.GetProperty("weapon").GetBoolean()) + "Любое оружие";
            Scene("Добро пожаловать в пустошь", phase == "done"
                ? "Всё на месте. Открой снаряжение бойца и надень комплект перед боем."
                : "Возьми в магазине Heavy Combat: шлем, броню и защиту для ног. Его можно надеть с первого уровня. "
                  + "Выбери любое оружие, которым сможешь пользоваться сейчас. Купишь всё — возвращайся.", checklist);
            if (phase == "available") Reply("Беру задание. Иду в магазин", async () => await Request("accept_welcome", Welcome));
            if (phase == "ready") Reply("Сдать задание", async () => await Request("turn_in_welcome", Welcome));
            if (phase == "active") Reply("Вернуться в город", form.Close);
            if (phase == "done") Reply("Расскажи про «Выживание»", Survival);
            Reply("Как найти всё в магазине?", () =>
            {
                Scene("Где искать", "Открой «Торговля» → «Магазин» → «Броня». Шлем ищи в «Голова», броню в «Тело», "
                    + "Heavy Combat Longies в «Ноги». Затем выбери оружие в разделе «Оружие».");
                Reply("Назад", Welcome);
            });
            Reply("К списку заданий", Greeting);
        }
        void Survival()
        {
            string phase = Phase("survival");
            Scene("Боевое крещение", phase switch {
                "locked" => "Сначала закончим со снаряжением. Вернись, когда сдашь первое задание.",
                "ready" => "Победу вижу. Готов рассказать, как прошёл бой?",
                "done" => "Победу вижу. Теперь знаешь, где снаряжаться и как записаться на бой. Удачи за воротами.",
                _ => "Открой «Арену» и выбери «Выживание». Собери отряд и встань в очередь. "
                     + "Мне нужна одна победа. Если проиграешь, отдохни и попробуй снова."
            }, phase switch {
                "active" => "Победить в «Выживании» — 0/1" +
                    (state.GetProperty("outcome").ValueKind == JsonValueKind.Number ? "\nПопытку можно повторить." : ""),
                "ready" => "Победить в «Выживании» — 1/1",
                "done" => "Обучение в Резервации завершено",
                _ => ""
            });
            if (phase == "available") Reply("Беру задание. Пора на арену", async () => await Request("accept_survival", Survival));
            if (phase == "ready") Reply("Сдать задание", async () => await Request("turn_in_survival", Survival));
            if (phase == "active") Reply("Вернуться в город", form.Close);
            if (phase is "active" or "available") Reply("А если я проиграю?", () =>
            {
                Scene("Ещё одна попытка", "Задание останется у тебя. Если отряд ранен, сначала приведи бойцов в порядок.");
                Reply("Назад", Survival);
            });
            Reply("К списку заданий", Greeting);
        }

        form.Shown += async (_, _) =>
        {
            Scene("", "Загружаю задания…");
            await Request("state", Greeting);
        };
        if (!stopping.IsCancellationRequested)
        {
            if (game.HasExited) return;
            using var tracking = new System.Windows.Forms.Timer { Interval = 150 };
            tracking.Tick += (_, _) =>
            {
                var current = anchor.Read(IntPtr.Zero, requireForeground: false);
                if (current is not { } view || view.Town != target.Town)
                {
                    form.Close();
                    return;
                }
                var bounds = PanelBounds(view.Client, Screen.FromHandle(target.Owner).WorkingArea, panelSize);
                if (bounds.IsEmpty) form.Close();
                else if (bounds != form.Bounds) form.Bounds = bounds;
            };
            using var loop = new ApplicationContext(form);
            form.Shown += (_, _) =>
            {
                SetForegroundWindow(target.Owner);
                close.Focus();
                tracking.Start();
            };
            Application.Run(loop);
        }
    }

    [DllImport("user32")] static extern bool SetForegroundWindow(IntPtr window);

    internal sealed class GamePanel : Form
    {
        readonly IntPtr parent;

        internal GamePanel(IntPtr parent)
        {
            this.parent = parent;
            TopLevel = false;
            ShowInTaskbar = false;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            AutoScroll = true;
        }

        protected override CreateParams CreateParams
        {
            get
            {
                const int child = 0x40000000, popup = unchecked((int)0x80000000), caption = 0x00c00000;
                var parameters = base.CreateParams;
                parameters.Parent = parent;
                parameters.Style = (parameters.Style & ~(popup | caption)) | child;
                return parameters;
            }
        }

        protected override bool ProcessCmdKey(ref Message message, Keys keyData)
        {
            if (keyData != Keys.Escape) return base.ProcessCmdKey(ref message, keyData);
            Close();
            return true;
        }
    }

    public void Dispose()
    {
        stopping.Cancel();
        if (visible is { IsHandleCreated: true, IsDisposed: false } form)
        {
            try { form.BeginInvoke(form.Close); }
            catch (InvalidOperationException) { }
        }
    }
}
