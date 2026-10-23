using System.Diagnostics;
using System.IO.Pipes;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace TioLauncher;

internal sealed record LauncherRelease(int Schema, string Version, long Size, string Sha256);
internal sealed record LauncherUpdatePlan(string Target, string OldSha256, LauncherRelease Release, int ParentPid,
    long ParentStartedUtcTicks, string ReadyPipe);

internal sealed class LauncherUpdate : IDisposable
{
    internal const string Origin = "https://185.184.42.88/downloads/";
    internal static string CurrentVersion => typeof(Program).Assembly.GetName().Version!.ToString(3);
    readonly HttpClient http;
    internal LauncherUpdate(HttpMessageHandler? handler = null)
    {
        http = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false });
        http.Timeout = TimeSpan.FromMinutes(10);
        http.DefaultRequestHeaders.CacheControl = new CacheControlHeaderValue { NoCache = true };
    }
    public void Dispose() => http.Dispose();
    internal static Version ParseVersion(string value)
    {
        if (value is null || !Regex.IsMatch(value, @"^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})$"))
            throw new InvalidDataException(L.Text("Неподдерживаемая версия лаунчера."));
        return Version.Parse(value);
    }
    internal static void Validate(LauncherRelease release)
    {
        ParseVersion(release.Version);
        if (release.Schema != 1 || release.Size is < 1 or > 256L * 1024 * 1024 || release.Sha256 is null ||
            !Regex.IsMatch(release.Sha256, "^[a-f0-9]{64}$"))
            throw new InvalidDataException(L.Text("Неподдерживаемое обновление лаунчера."));
    }
    internal static bool IsNewer(LauncherRelease release, string current)
    {
        Validate(release);
        return ParseVersion(release.Version) > ParseVersion(current);
    }
    internal async Task<LauncherRelease> Fetch(CancellationToken token)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(20));
        using var response = await http.GetAsync(Origin + "launcher-manifest.json", HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        response.EnsureSuccessStatusCode();
        using var input = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var data = new MemoryStream();
        byte[] buffer = new byte[4096]; int read;
        while ((read = await input.ReadAsync(buffer, timeout.Token)) > 0)
        {
            if (data.Length + read > 16384) throw new InvalidDataException(L.Text("Список обновлений лаунчера слишком большой."));
            data.Write(buffer, 0, read);
        }
        var release = JsonSerializer.Deserialize<LauncherRelease>(data.ToArray(), Updater.Json)
            ?? throw new InvalidDataException(L.Text("Пустой список обновлений лаунчера."));
        Validate(release);
        return release;
    }
    internal async Task Download(LauncherRelease release, string destination, IProgress<UpdateProgress> progress, CancellationToken token)
    {
        Validate(release);
        bool created = false;
        try
        {
            using var response = await http.GetAsync(Origin + "TIO-Launcher-" + release.Version + ".exe", HttpCompletionOption.ResponseHeadersRead, token);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long length && length != release.Size)
                throw new InvalidDataException(L.Text("Размер обновления лаунчера не совпадает."));
            using var input = await response.Content.ReadAsStreamAsync(token);
            using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None, 131072, true))
            {
                created = true;
                byte[] buffer = new byte[131072]; int read; long received = 0;
                while ((read = await input.ReadAsync(buffer, token)) > 0)
                {
                    received += read;
                    if (received > release.Size) throw new InvalidDataException(L.Text("Размер обновления лаунчера не совпадает."));
                    await output.WriteAsync(buffer.AsMemory(0, read), token);
                    progress.Report(new(L.Text($"Обновление лаунчера до {release.Version} · {received / 1024:N0} / {release.Size / 1024:N0} КБ"),
                        (int)(received * 100 / release.Size)));
                }
                await output.FlushAsync(token);
                output.Flush(true);
            }
            if (!await Matches(destination, release.Sha256, release.Size, token))
                throw new InvalidDataException(L.Text("Обновление лаунчера повреждено. Повторите проверку."));
        }
        catch { if (created) File.Delete(destination); throw; }
    }
    internal static async Task<bool> Matches(string path, string hash, long? size = null, CancellationToken token = default)
    {
        if (!File.Exists(path) || size is long expected && new FileInfo(path).Length != expected) return false;
        using var input = File.OpenRead(path);
        return Convert.ToHexStringLower(await SHA256.HashDataAsync(input, token)) == hash;
    }
    static ProcessStartInfo StartInfo(string executable)
        => new(executable) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Path.GetDirectoryName(executable)! };

    internal async Task HandOff(LauncherRelease release, IProgress<UpdateProgress> progress, CancellationToken token)
    {
        if (Updater.GameRunning()) throw new IOException(L.Text("Закройте игру, чтобы обновить лаунчер, и повторите проверку."));
        string target = Environment.ProcessPath ?? throw new IOException(L.Text("Не найден файл лаунчера."));
        if (Path.GetFileNameWithoutExtension(target).Equals("dotnet", StringComparison.OrdinalIgnoreCase) ||
            !File.Exists(target) || !Path.GetExtension(target).Equals(".exe", StringComparison.OrdinalIgnoreCase))
            throw new IOException(L.Text("Для самообновления запустите отдельный EXE лаунчера."));
        RejectLinks(target);
        // Check write access before downloading, without touching the executable.
        string probe = Path.Combine(Path.GetDirectoryName(target)!, ".tio-launcher-probe-" + Guid.NewGuid().ToString("N"));
        using (new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }
        string work = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TioLauncher", "self-update", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        string candidate = Path.Combine(work, "launcher.exe");
        await Download(release, candidate, progress, token);
        var emitted = FileVersionInfo.GetVersionInfo(candidate);
        if (new Version(emitted.FileMajorPart, emitted.FileMinorPart, emitted.FileBuildPart) != ParseVersion(release.Version))
            throw new InvalidDataException(L.Text("Версия загруженного лаунчера не совпадает с обновлением."));
        token.ThrowIfCancellationRequested();
        string helperPath = Path.Combine(work, "helper.exe");
        File.Copy(candidate, helperPath);
        string pipeName = "TIO.LauncherUpdate." + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeServerStream(pipeName, PipeDirection.In, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        using var parent = Process.GetCurrentProcess();
        using var source = File.OpenRead(target);
        string oldHash = Convert.ToHexStringLower(await SHA256.HashDataAsync(source, token));
        var plan = new LauncherUpdatePlan(target, oldHash, release, parent.Id, parent.StartTime.ToUniversalTime().Ticks, pipeName);
        string planPath = Path.Combine(work, "plan.json");
        File.WriteAllText(planPath, JsonSerializer.Serialize(plan));
        var start = StartInfo(helperPath);
        start.ArgumentList.Add("--launcher-update-helper"); start.ArgumentList.Add(planPath);
        using var helper = Process.Start(start) ?? throw new IOException(L.Text("Не удалось запустить обновление лаунчера."));
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            await pipe.WaitForConnectionAsync(timeout.Token);
            using var reader = new StreamReader(pipe);
            if (await reader.ReadLineAsync(timeout.Token) != "ready") throw new IOException(L.Text("Обновление лаунчера не подтвердило запуск."));
        }
        catch { if (!helper.HasExited) helper.Kill(); throw; }
    }
    internal static void RejectLinks(string path)
    {
        for (string? current = Path.GetFullPath(path); current is not null; current = Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new IOException(L.Text("Папка лаунчера содержит ссылку."));
    }
    internal static async Task Replace(string target, string candidate, string backup, string oldHash, LauncherRelease release)
    {
        Validate(release); RejectLinks(target); RejectLinks(candidate); RejectLinks(backup);
        if (!await Matches(target, oldHash) || !await Matches(candidate, release.Sha256, release.Size))
            throw new InvalidDataException(L.Text("Файл лаунчера изменился во время обновления. Повторите проверку."));
        if (File.Exists(backup)) throw new IOException(L.Text("Резервная копия обновления уже существует."));
        File.Replace(candidate, target, backup, true);
        if (!await Matches(target, release.Sha256, release.Size))
        {
            File.Replace(backup, target, null, true);
            throw new InvalidDataException(L.Text("Установленный лаунчер не прошёл проверку."));
        }
    }
    internal static async Task RunHelper(string planPath)
    {
        string? staged = null;
        string? work = null;
        try
        {
            planPath = Path.GetFullPath(planPath); work = Path.GetDirectoryName(planPath)!;
            string self = Environment.ProcessPath!;
            if (Path.GetFileName(planPath) != "plan.json" || Path.GetDirectoryName(self) != work)
                throw new InvalidDataException(L.Text("Недопустимый план обновления."));
            RejectLinks(planPath);
            var plan = JsonSerializer.Deserialize<LauncherUpdatePlan>(File.ReadAllText(planPath), Updater.Json)
                ?? throw new InvalidDataException(L.Text("Пустой план обновления."));
            Validate(plan.Release);
            if (!Regex.IsMatch(plan.ReadyPipe, "^TIO\\.LauncherUpdate\\.[a-f0-9]{32}$") ||
                !Regex.IsMatch(plan.OldSha256, "^[a-f0-9]{64}$") || !Path.IsPathFullyQualified(plan.Target) ||
                !Path.GetExtension(plan.Target).Equals(".exe", StringComparison.OrdinalIgnoreCase) ||
                Path.GetDirectoryName(Path.GetFullPath(plan.Target)) == work)
                throw new InvalidDataException(L.Text("Недопустимый адрес обновления."));
            string candidate = Path.Combine(work, "launcher.exe");
            if (!await Matches(candidate, plan.Release.Sha256, plan.Release.Size) ||
                !await Matches(self, plan.Release.Sha256, plan.Release.Size))
                throw new InvalidDataException(L.Text("Файлы обновления изменились."));
            using var parent = Process.GetProcessById(plan.ParentPid);
            if (parent.StartTime.ToUniversalTime().Ticks != plan.ParentStartedUtcTicks ||
                !string.Equals(parent.MainModule?.FileName, plan.Target, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException(L.Text("Процесс лаунчера изменился."));
            // Stage next to the target so File.Replace remains an atomic same-volume operation.
            string token = Guid.NewGuid().ToString("N");
            staged = Path.Combine(Path.GetDirectoryName(plan.Target)!, ".tio-launcher-" + token + ".exe");
            string backup = plan.Target + ".previous-" + token;
            File.Copy(candidate, staged);
            using (var ready = new NamedPipeClientStream(".", plan.ReadyPipe, PipeDirection.Out, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly))
            {
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
                await ready.ConnectAsync(deadline.Token);
                using var writer = new StreamWriter(ready) { AutoFlush = true };
                await writer.WriteLineAsync("ready");
            }
            using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60))) await parent.WaitForExitAsync(deadline.Token);
            if (Updater.GameRunning()) throw new IOException(L.Text("Игра запущена. Закройте её и снова запустите лаунчер."));
            for (int attempt = 0; ; attempt++)
            {
                try { await Replace(plan.Target, staged, backup, plan.OldSha256, plan.Release); break; }
                catch (IOException) when (attempt < 20) { await Task.Delay(500); }
            }
            int restartedPid;
            try
            {
                var restart = StartInfo(plan.Target); restart.WindowStyle = ProcessWindowStyle.Normal;
                using var started = Process.Start(restart) ?? throw new IOException(L.Text("Не удалось перезапустить лаунчер."));
                restartedPid = started.Id;
            }
            catch
            {
                if (await Matches(plan.Target, plan.Release.Sha256, plan.Release.Size)) File.Replace(backup, plan.Target, null, true);
                throw;
            }
            // Replacement/rollback needs a temporary copy on the same volume.
            // Once the verified replacement starts, keep release history on
            // the hosting server rather than beside every player's launcher.
            try { File.Delete(backup); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            WriteResult(work, new { passed = true, version = plan.Release.Version, backup_retained = File.Exists(backup), pid = restartedPid });
        }
        catch (Exception error)
        {
            Environment.ExitCode = 1;
            if (work is not null) WriteResult(work, new { passed = false, error = error.Message });
            MessageBox.Show(L.Text("Не удалось обновить лаунчер: ") + error.Message + L.Text("\nЗапустите лаунчер снова или скачайте новую версию с ti-reborn.com."),
                L.Text("Обновление TIO Launcher"), MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { if (staged is not null) File.Delete(staged); }
    }
    static void WriteResult(string work, object result)
    {
        try { File.WriteAllText(Path.Combine(work, "result.json"), JsonSerializer.Serialize(result)); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
    internal static void CleanCompletedDownloads()
    {
        CleanPreviousLaunchers(Environment.ProcessPath);
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TioLauncher", "self-update");
        if (!Directory.Exists(root)) return;
        try
        {
            RejectLinks(root);
            foreach (string directory in Directory.GetDirectories(root))
            {
                if (!Regex.IsMatch(Path.GetFileName(directory), "^[a-f0-9]{32}$")) continue;
                RejectLinks(directory);
                // Give the helper time to exit. Keep only its small receipt.
                if (Directory.GetLastWriteTimeUtc(directory) > DateTime.UtcNow.AddDays(-1)) continue;
                foreach (string name in new[] { "launcher.exe", "helper.exe" })
                {
                    string file = Path.Combine(directory, name); RejectLinks(file); File.Delete(file);
                }
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
    internal static void CleanPreviousLaunchers(string? executable)
    {
        if (executable is null) return;
        string root = Path.GetDirectoryName(Path.GetFullPath(executable))!;
        try
        {
            RejectLinks(root);
            foreach (string path in Directory.EnumerateFiles(root))
            {
                string name = Path.GetFileName(path);
                if (!Regex.IsMatch(name, @"^TIO[- ]Launcher(?:-\d+\.\d+\.\d+)?\.exe\.previous-[a-f0-9]{16,64}$", RegexOptions.IgnoreCase)) continue;
                RejectLinks(path);
                var version = FileVersionInfo.GetVersionInfo(path);
                if (version.ProductName != "TIO Launcher" || new FileInfo(path).Length < 1024 * 1024) continue;
                File.Delete(path);
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}
