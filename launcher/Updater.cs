using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace TioLauncher;

public record ReleaseFile(string Path, long Size, string Sha256, bool Seed = false);
public record ReleaseArchive(long Size, string Sha256, string FilesSha256);
public record Release(int Schema, string Version, string News, ReleaseFile[] Files, string? NewsEn = null, ReleaseArchive? Archive = null);
public record Change(string Path, bool Existed);
public record UpdateProgress(string Message, int Percent);

public sealed partial class Updater : IDisposable
{
    public const string Origin = "https://185.184.42.88/updates/";
    public static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true };
    readonly HttpClient http;
    readonly string root;
    string Work => System.IO.Path.Combine(root, ".tio-update");
    string Journal => System.IO.Path.Combine(Work, "journal.json");
    static readonly HashSet<string> Binaries = new(StringComparer.OrdinalIgnoreCase)
        { "ti.exe", "silver.dll", "orange.dll", "gold.dll", "ode.dll", "d3dx9_26.dll" };
    static readonly HashSet<string> OptionalBinaries = new(StringComparer.OrdinalIgnoreCase) { "tio_crest.dll" };
    static bool IsBinary(string path) => Binaries.Contains(path) || OptionalBinaries.Contains(path);
    public Updater(string directory, HttpMessageHandler? handler = null)
    {
        root = System.IO.Path.GetFullPath(directory);
        http = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false });
        http.Timeout = TimeSpan.FromMinutes(30);
    }
    public void Dispose() => http.Dispose();
    public static bool GameRunning() => Process.GetProcessesByName("ti").Any(p => { p.Dispose(); return true; });
    public static void Validate(Release release)
    {
        if (release.Schema != 1 || string.IsNullOrWhiteSpace(release.Version) || release.Files is null || release.Files.Length is < 1 or > 20000)
            throw new InvalidDataException(L.Text("Неподдерживаемый список обновлений."));
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var f in release.Files)
        {
            if (f is null || string.IsNullOrEmpty(f.Path) || f.Sha256 is null)
                throw new InvalidDataException(L.Text("Неподдерживаемый список обновлений."));
            var parts = f.Path.Split('/');
            if (parts.Any(p => !Regex.IsMatch(p, @"^[A-Za-z0-9_ .()\-]+$") || p is "." or ".." || p.EndsWith('.') || p.EndsWith(' ') ||
                Regex.IsMatch(p, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", RegexOptions.IgnoreCase)) ||
                !(IsBinary(f.Path) || (parts.Length > 1 && parts[0] == "base")) || !seen.Add(f.Path) ||
                f.Size < 0 || f.Size > 512L * 1024 * 1024 || !Regex.IsMatch(f.Sha256, "^[a-f0-9]{64}$"))
                throw new InvalidDataException(L.Text("Недопустимый файл обновления: ") + f.Path);
            var name = parts[^1].ToLowerInvariant();
            var normalized = f.Path.ToLowerInvariant();
            if (name == "login.ini" || name.StartsWith("notes-") || name == "skillbar.dat" || name.EndsWith(".log") || name.EndsWith(".bak") ||
                (normalized is "base/config.cfg" or "base/autoexec.cfg") && !f.Seed || f.Seed && normalized is not ("base/config.cfg" or "base/autoexec.cfg"))
                throw new InvalidDataException(L.Text("Обновление затрагивает личные настройки: ") + f.Path);
        }
        foreach (var name in Binaries)
            if (!seen.Contains(name)) throw new InvalidDataException(L.Text("В выпуске отсутствует ") + name);
        ValidateArchive(release);
    }
    string Target(string path)
    {
        string full = System.IO.Path.GetFullPath(System.IO.Path.Combine(root, path.Replace('/', System.IO.Path.DirectorySeparatorChar)));
        if (!full.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Invalid target");
        for (string? current = full; current != null; current = System.IO.Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new IOException(L.Text("Папка игры содержит ссылку: ") + current);
        return full;
    }
    async Task<bool> Matches(string path, ReleaseFile file, CancellationToken token)
    {
        if (!File.Exists(path) || new FileInfo(path).Length != file.Size) return false;
        using var stream = File.OpenRead(path);
        if (file.Path=="client.zip") Metrics.ArchiveBytesHashed+=stream.Length;
        return Convert.ToHexStringLower(await SHA256.HashDataAsync(stream, token)) == file.Sha256;
    }
    public void Recover()
    {
        if (!File.Exists(Journal)) { CleanBackups(); return; }
        var changes = JsonSerializer.Deserialize<Change[]>(File.ReadAllText(Journal), Json) ?? throw new InvalidDataException("Invalid recovery journal");
        foreach (var change in changes.Reverse())
        {
            string target = Target(change.Path);
            if (change.Existed) File.Copy(Target(".tio-update/backup/" + change.Path), target, true);
            else if (File.Exists(target)) File.Delete(target);
        }
        File.Delete(Journal);
        CleanBackups();
    }
    void CleanBackups()
    {
        // Only updater-owned rollback files, after its recovery journal is
        // gone. Reject every link before deleting anything in this subtree.
        try
        {
            if (File.Exists(Journal)) return;
            string folder = Target(".tio-update/backup");
            if (!Directory.Exists(folder)) return;
            var options = new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = FileAttributes.ReparsePoint };
            var files = Directory.GetFiles(folder, "*", options);
            var folders = Directory.GetDirectories(folder, "*", options);
            foreach (string path in folders.Concat(files)) Target(Path.GetRelativePath(root, path).Replace('\\', '/'));
            foreach (string path in files) File.Delete(path);
            foreach (string path in folders.OrderByDescending(p => p.Length)) Directory.Delete(path);
            Directory.Delete(folder);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
    public async Task Apply(Release release, IProgress<UpdateProgress> progress, CancellationToken token, bool fullVerification = false)
    {
        var timer=Stopwatch.StartNew();Metrics=new();
        progress=new UpdateProgressThrottle(progress);
        Validate(release);
        if (GameRunning()) throw new IOException(L.Text("Закройте игру перед проверкой и обновлением."));
        Directory.CreateDirectory(root);
        Target(".tio-update/lock");
        Directory.CreateDirectory(Work);
        using var updateLock = new FileStream(System.IO.Path.Combine(Work,"lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        Recover();
        var verification=new FileVerificationCache(root,ReadCache("verified-files.json",8*1024*1024));
        var directories=new Dictionary<string,Dictionary<string,FileStamp>?>(StringComparer.OrdinalIgnoreCase);
        string checking=L.Text(fullVerification ? "Полная проверка файлов · " : "Проверка файлов · ");
        var pending = new List<ReleaseFile>();
        for (int i = 0; i < release.Files.Length; i++)
        {
            token.ThrowIfCancellationRequested();
            var file = release.Files[i];
            int slash=file.Path.LastIndexOf('/');
            string directory=slash<0 ? "" : file.Path[..slash], name=file.Path[(slash+1)..];
            if (!directories.TryGetValue(directory,out var entries))
            {
                // Check directory ancestors once. The native listing supplies
                // each child's attributes/identity without opening every file.
                string parent=System.IO.Path.GetDirectoryName(Target((directory.Length==0 ? "" : directory+"/")+".tio-directory-check"))!;
                entries=DisableMetadataCache ? null : FileMetadata.Directory(parent,token);
                directories.Add(directory,entries);Metrics.DirectoryScans++;
            }
            FileStamp? stamp=null;entries?.TryGetValue(name,out stamp);
            if (stamp!=null && (stamp.Attributes & (uint)(FileAttributes.ReparsePoint|FileAttributes.Directory))!=0)
                throw new IOException(L.Text("Папка игры содержит ссылку: ")+file.Path);
            bool exists=entries!=null ? stamp!=null : File.Exists(Target(file.Path));
            if (file.Seed && exists) { verification.Forget(file.Path); }
            else if (!fullVerification && !IsBinary(file.Path) && verification.Matches(file,stamp)) Metrics.FileCacheHits++;
            else if (!exists || !await VerifyInstalled(Target(file.Path),file,verification,token))
            { verification.Forget(file.Path);pending.Add(file); }
            progress.Report(new(checking + file.Path, (i + 1) * 100 / release.Files.Length));
        }
        void Complete()
        {
            if (verification.Dirty) WriteCache("verified-files.json",verification.Serialize(release));
            Metrics.ElapsedMilliseconds=timer.ElapsedMilliseconds;
            progress.Report(new(L.Text("Клиент ") + release.Version + L.Text(" готов к запуску"),100));
        }
        // A verification with no changes never opens/downloads an archive or
        // even scans the payload cache. It only checks the installed tree.
        if (pending.Count==0) { token.ThrowIfCancellationRequested();Complete();return; }
        Directory.CreateDirectory(Target(".tio-update/cache"));
        await PrepareArchive(release, pending, progress, token);
        for (int i = 0; i < pending.Count; i++)
        {
            var file = pending[i]; string cache = Target(".tio-update/cache/" + file.Sha256);
            if (!await Matches(cache, file, token))
            {
                string partial = cache + ".part";
                if (await Matches(partial, file, token)) { File.Move(partial, cache, true); continue; }
                long offset = File.Exists(partial) ? new FileInfo(partial).Length : 0;
                if (offset >= file.Size) offset = 0;
                using var request = new HttpRequestMessage(HttpMethod.Get, Origin + "blobs/" + file.Sha256);
                if (offset > 0) request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(offset, null);
                using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
                Metrics.PayloadRequests++;
                response.EnsureSuccessStatusCode();
                if (response.StatusCode == HttpStatusCode.PartialContent)
                {
                    var range = response.Content.Headers.ContentRange;
                    if (range?.From != offset || range.Length != file.Size || range.To != file.Size - 1)
                        throw new InvalidDataException(L.Text("Сервер прислал неверный диапазон файла: ") + file.Path);
                }
                else offset = 0; // A server without Range support sent the complete file.
                using (var input = await response.Content.ReadAsStreamAsync(token))
                using (var output = new FileStream(partial, offset == 0 ? FileMode.Create : FileMode.Append, FileAccess.Write, FileShare.None))
                {
                    var buffer = new byte[131072]; long received = offset; int read;
                    while ((read = await input.ReadAsync(buffer, token)) > 0)
                    {
                        received += read;
                        Metrics.PayloadBytes+=read;
                        if (received > file.Size) throw new InvalidDataException(L.Text("Размер загрузки не совпадает: ") + file.Path);
                        await output.WriteAsync(buffer.AsMemory(0, read), token);
                        progress.Report(new(L.Text($"Загрузка {i+1}/{pending.Count} · {file.Path} · {received/1024:N0} / {file.Size/1024:N0} КБ"),
                            (int)(100.0 * (i + (file.Size == 0 ? 1 : (double)received/file.Size)) / pending.Count)));
                    }
                }
                if (!await Matches(partial, file, token))
                {
                    // A short response can resume. A full corrupt file must restart.
                    if (new FileInfo(partial).Length >= file.Size) File.Delete(partial);
                    throw new InvalidDataException(L.Text("Загрузка неполная или повреждена: ") + file.Path + L.Text(". Повторите проверку."));
                }
                File.Move(partial, cache, true);
            }
        }
        token.ThrowIfCancellationRequested();
        if (GameRunning()) throw new IOException(L.Text("Игра запущена. Закройте её и повторите обновление."));
        var journal = new List<Change>();
        try
        {
            // Prepare every backup before touching installed files. One durable
            // journal then covers both completed and not-yet-started copies.
            // Rewriting a growing journal for each of thousands of files made
            // clean installs perform quadratic JSON/disk work.
            foreach (var file in pending)
            {
                token.ThrowIfCancellationRequested();
                var target = Target(file.Path); bool existed = File.Exists(target);
                Directory.CreateDirectory(System.IO.Path.GetDirectoryName(target)!);
                if (existed)
                {
                    string backup = Target(".tio-update/backup/" + file.Path);
                    Directory.CreateDirectory(System.IO.Path.GetDirectoryName(backup)!);
                    File.Copy(target, backup, true);
                }
                journal.Add(new(file.Path, existed));
            }
            if (journal.Count != 0)
            {
                File.WriteAllText(Journal + ".tmp", JsonSerializer.Serialize(journal));
                File.Move(Journal + ".tmp", Journal, true);
            }
            string installing=L.Text("Установка · ");
            for (int i = 0; i < pending.Count; i++)
            {
                token.ThrowIfCancellationRequested();
                var file = pending[i];
                File.Copy(Target(".tio-update/cache/" + file.Sha256), Target(file.Path), true);
                if (!await VerifyInstalled(Target(file.Path),file,verification,token)) throw new InvalidDataException("Installed resource failed verification: "+file.Path);
                progress.Report(new(installing + file.Path, (i + 1) * 100 / pending.Count));
            }
            File.Delete(Journal);
            CleanBackups();
        }
        catch { Recover(); throw; }
        Complete();
    }

    // Concurrent owned QA clients may validate an already prepared tree. This
    // path never installs, repairs, recovers journals or writes file caches.
    internal async Task VerifyOwnedQa(Release release,CancellationToken token)
    {
        Validate(release);
        if(!File.Exists(Path.Combine(root,".tio-owned-qa")) || File.Exists(Path.Combine(root,"login.ini")) || File.Exists(Path.Combine(root,"base","login.ini")) || File.Exists(Journal))
            throw new InvalidDataException("Owned QA validation requires a prepared isolated client.");
        foreach(var file in release.Files)
        {
            token.ThrowIfCancellationRequested();string path=Target(file.Path);
            if(file.Seed && File.Exists(path))continue;
            if(!await Matches(path,file,token))throw new InvalidDataException("Prepare the owned QA client before starting concurrent games: "+file.Path);
        }
    }
}
