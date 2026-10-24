using System.Security;
using System.Text;

namespace TioLauncher;

/// <summary>Loads and saves the player's game folder without starting a download.</summary>
sealed class InstallLocation
{
    public static string DefaultSettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TioLauncher", "folder.txt");
    public static string DefaultGameRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TIO-Online");

    readonly string settingsPath;
    public string SuggestedPath { get; }

    public InstallLocation(string? settingsPath = null, string? suggestedPath = null)
    {
        this.settingsPath = Path.GetFullPath(settingsPath ?? DefaultSettingsPath);
        SuggestedPath = suggestedPath ?? DefaultGameRoot;
    }

    public bool TryLoadSaved(out string gameRoot, out string? reason)
    {
        gameRoot = SuggestedPath;
        reason = null;
        try
        {
            if (!File.Exists(settingsPath)) return false;
            string path = Normalize(File.ReadAllText(settingsPath));
            // An unplugged drive or deleted folder must be selected again by the player.
            // Reading settings must never recreate an old installation implicitly.
            CheckWritable(path, create: false);
            gameRoot = path;
            return true;
        }
        catch (Exception error) when (IsPathError(error))
        {
            reason = L.Text("Сохранённая папка игры недоступна. Выберите папку установки. ") + error.Message;
            return false;
        }
    }

    public bool TryChooseFolder(IWin32Window owner, string? initialPath, out string gameRoot, string? explanation = null)
    {
        gameRoot = initialPath ?? SuggestedPath;
        using var dialog = new InstallLocationDialog(this, gameRoot, explanation);
        if (dialog.ShowDialog(owner) != DialogResult.OK) return false;
        gameRoot = dialog.SelectedPath!;
        return true;
    }

    // A null choice means the dialog was cancelled. This is also the non-UI test seam.
    internal bool TryCommitSelection(string? choice, out string gameRoot, out string? error)
    {
        gameRoot = "";
        error = null;
        if (choice is null) return false;
        try
        {
            string path = Normalize(choice);
            CheckWritable(path, create: true);
            SaveAtomically(path);
            gameRoot = path;
            return true;
        }
        catch (Exception failure) when (IsPathError(failure))
        {
            error = L.Text("Не удалось выбрать папку: ") + failure.Message;
            return false;
        }
    }

    static bool IsPathError(Exception error) => error is IOException or UnauthorizedAccessException
        or ArgumentException or NotSupportedException or SecurityException;

    internal static string Normalize(string value)
    {
        string path = value.Trim();
        if (path.Length >= 2 && path[0] == '"' && path[^1] == '"') path = path[1..^1];
        path = Environment.ExpandEnvironmentVariables(path);
        if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException(L.Text("Укажите полный путь к папке игры."));
        if (!Path.IsPathFullyQualified(path)) throw new ArgumentException(L.Text("Укажите полный путь, например C:\\Games\\TIO-Online."));
        if (path.StartsWith(@"\\?\", StringComparison.Ordinal) || path.StartsWith(@"\\.\", StringComparison.Ordinal))
            throw new ArgumentException(L.Text("Выберите обычную папку на диске."));
        if (path.IndexOfAny(Path.GetInvalidPathChars()) >= 0) throw new ArgumentException(L.Text("В пути есть недопустимые символы."));
        // Windows may remove a trailing dot while resolving the full path. Reject it
        // before normalization so we cannot select a different folder than was typed.
        CheckSegments(path, allowDotSegments: true);
        string full = Path.GetFullPath(path);
        CheckSegments(full, allowDotSegments: false);
        return Path.TrimEndingDirectorySeparator(full);
    }

    static void CheckSegments(string path, bool allowDotSegments)
    {
        string root = Path.GetPathRoot(path)!;
        foreach (string segment in path[root.Length..].Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar], StringSplitOptions.RemoveEmptyEntries))
        {
            if (allowDotSegments && segment is "." or "..") continue;
            if (segment.EndsWith(' ') || segment.EndsWith('.') || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new ArgumentException(L.Text("В названии папки есть недопустимые символы или точка/пробел в конце."));
            string stem = segment.Split('.')[0];
            if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase)
                || stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase)
                || (stem.Length == 4 && (stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase))
                    && "123456789¹²³".Contains(stem[3])))
                throw new ArgumentException(L.Text("Это название папки зарезервировано Windows."));
        }
    }

    static void CheckWritable(string path, bool create)
    {
        RejectLinks(path);
        if (File.Exists(path)) throw new IOException(L.Text("Указанный путь занят файлом. Выберите папку."));
        if (create) Directory.CreateDirectory(path);
        else if (!Directory.Exists(path)) throw new DirectoryNotFoundException(L.Text("Папка не найдена: ") + path);
        RejectLinks(path);
        // Preserve the selected display/settings path, but reject a directory
        // the original native client cannot open before downloading game files.
        _ = GamePath.ForNativeClient(path);

        // DeleteOnClose only touches the uniquely named probe owned by this operation.
        string probe = Path.Combine(path, ".tio-write-check-" + Guid.NewGuid().ToString("N") + ".tmp");
        using var stream = new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            1, FileOptions.DeleteOnClose);
        stream.WriteByte(0);
        stream.Flush(flushToDisk: true);
    }

    static void RejectLinks(string path)
    {
        for (string? current = path; current is not null; current = Path.GetDirectoryName(current))
        {
            try
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException(L.Text("Папка игры содержит ссылку. Выберите обычную папку: ") + current);
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
        }
    }

    void SaveAtomically(string gameRoot)
    {
        string directory = Path.GetDirectoryName(settingsPath)!;
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, ".folder-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(Encoding.UTF8.GetBytes(gameRoot));
                stream.Flush(flushToDisk: true);
            }
            // The temporary file lives beside folder.txt so the rename stays on one volume.
            File.Move(temporary, settingsPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }
}

sealed class InstallLocationDialog : Form
{
    readonly TextBox path = new();
    readonly Label problem = new();
    readonly InstallLocation location;
    public string? SelectedPath { get; private set; }

    public InstallLocationDialog(InstallLocation location, string initialPath, string? explanation)
    {
        this.location = location;
        Text = L.Text("Total Influence · Папка установки");
        ClientSize = new Size(680, 260);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false;
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(24, 29, 24);
        ForeColor = Color.FromArgb(222, 223, 206);
        Controls.Add(new Label {
            Text = L.Text("Выберите папку для клиента игры. Можно указать существующую папку\nили ввести новый путь — лаунчер создаст её перед загрузкой."),
            Bounds = new Rectangle(22, 20, 636, 48)
        });
        Controls.Add(new Label { Text = L.Text("Папка игры"), Bounds = new Rectangle(22, 78, 180, 24) });
        path.SetBounds(22, 105, 510, 28);
        path.Text = initialPath;
        Controls.Add(path);
        var browse = new Button { Text = L.Text("ОБЗОР…"), Bounds = new Rectangle(543, 103, 115, 31) };
        browse.Click += (_, _) => Browse();
        Controls.Add(browse);
        problem.SetBounds(22, 145, 636, 62);
        problem.ForeColor = Color.FromArgb(235, 192, 128);
        problem.Text = explanation ?? L.Text("Выбранная папка будет сохранена для следующих запусков.");
        Controls.Add(problem);
        var confirm = new Button { Text = L.Text("ВЫБРАТЬ ПАПКУ"), Bounds = new Rectangle(308, 214, 222, 32) };
        confirm.Click += (_, _) => Confirm();
        Controls.Add(confirm);
        var cancel = new Button { Text = L.Text("ОТМЕНА"), Bounds = new Rectangle(543, 214, 115, 32), DialogResult = DialogResult.Cancel };
        Controls.Add(cancel);
        AcceptButton = confirm;
        CancelButton = cancel;
    }

    void Browse()
    {
        string initial = location.SuggestedPath;
        try
        {
            initial = InstallLocation.Normalize(path.Text);
            while (!Directory.Exists(initial))
            {
                string? parent = Path.GetDirectoryName(initial);
                if (parent is null) break;
                initial = parent;
            }
        }
        catch (Exception error) when (error is ArgumentException or IOException or NotSupportedException or SecurityException) { }
        using var dialog = new FolderBrowserDialog {
            Description = L.Text("Выберите или создайте папку игры"),
            UseDescriptionForTitle = true,
            ShowNewFolderButton = true,
            InitialDirectory = initial,
            SelectedPath = Directory.Exists(initial) ? initial : ""
        };
        if (dialog.ShowDialog(this) == DialogResult.OK) path.Text = dialog.SelectedPath;
    }

    void Confirm()
    {
        if (!location.TryCommitSelection(path.Text, out string selected, out string? error))
        {
            problem.Text = error;
            path.Focus();
            return;
        }
        SelectedPath = selected;
        DialogResult = DialogResult.OK;
        Close();
    }
}
