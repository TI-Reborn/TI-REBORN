namespace TioLauncher;

// Pre-launch choices that apply to the next game start.
sealed class LauncherSettingsDialog : Form
{
    static readonly Color Gold = Color.FromArgb(221, 200, 112);
    readonly RadioButton modern = new(), original = new();
    readonly Label note = new();
    public string? SavedInterface { get; private set; }

    public LauncherSettingsDialog(string currentInterface)
    {
        GameInterface.Validate(currentInterface);
        Text = L.Text("Total Influence · Настройки");
        ClientSize = new Size(560, 340);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(24, 29, 24);
        ForeColor = Color.FromArgb(222, 223, 206);
        Controls.Add(new Label { Text = L.Text("ИНТЕРФЕЙС"), Bounds = new Rectangle(22, 18, 516, 26),
            Font = new Font("Segoe UI", 12, FontStyle.Bold), ForeColor = Gold });
        AddChoice(modern, L.Text("Новый"), 56,
            L.Text("Крупный боец, экипировка слева, вкладки справа и HD-иконки предметов."));
        AddChoice(original, L.Text("Оригинальный"), 136,
            L.Text("Классическая казарма и склад, прежние иконки предметов."));
        modern.Checked = currentInterface == GameInterface.New;
        original.Checked = currentInterface == GameInterface.Original;
        note.SetBounds(22, 214, 516, 66);
        note.ForeColor = Color.FromArgb(235, 192, 128);
        note.Text = L.Text("Изменение применится при следующем запуске игры. Если окно игры меньше 1200×544 с учётом масштаба интерфейса, казарма показывается в оригинальной раскладке.");
        Controls.Add(note);
        var save = Button(L.Text("СОХРАНИТЬ"), 278, 292, 140);
        save.Click += (_, _) => Save();
        var cancel = Button(L.Text("ОТМЕНА"), 428, 292, 110);
        cancel.DialogResult = DialogResult.Cancel;
        AcceptButton = save;
        CancelButton = cancel;
    }

    void AddChoice(RadioButton choice, string title, int y, string description)
    {
        choice.Text = title;
        choice.SetBounds(22, y, 516, 28);
        choice.Font = new Font("Segoe UI", 11, FontStyle.Bold);
        choice.ForeColor = Gold;
        choice.Cursor = Cursors.Hand;
        Controls.Add(choice);
        Controls.Add(new Label { Text = description, Bounds = new Rectangle(44, y + 30, 494, 44) });
    }

    Button Button(string text, int x, int y, int width)
    {
        var button = new Button { Text = text, Bounds = new Rectangle(x, y, width, 34), FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(27, 32, 25), ForeColor = Gold, Font = new Font("Segoe UI", 10, FontStyle.Bold), Cursor = Cursors.Hand };
        button.FlatAppearance.BorderColor = Color.FromArgb(105, 108, 73);
        button.FlatAppearance.MouseOverBackColor = Color.FromArgb(58, 65, 40);
        Controls.Add(button);
        return button;
    }

    void Save()
    {
        string selected = original.Checked ? GameInterface.Original : GameInterface.New;
        try { GameInterface.Save(selected); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            note.Text = L.Text("Не удалось сохранить настройки: ") + error.Message;
            return;
        }
        SavedInterface = selected;
        DialogResult = DialogResult.OK;
        Close();
    }
}
