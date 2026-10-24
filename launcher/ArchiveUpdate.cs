using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace TioLauncher;

public sealed partial class Updater
{
    internal static string FilesDigest(Release release) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(
        string.Concat(release.Files.OrderBy(f => f.Path, StringComparer.Ordinal).Select(f =>
            $"{f.Path}\t{f.Size.ToString(CultureInfo.InvariantCulture)}\t{f.Sha256}\t{(f.Seed ? 1 : 0)}\n")))));

    static void ValidateArchive(Release release)
    {
        if (release.Archive is not { } a) return;
        if (a.Size is < 22 or > 4L * 1024 * 1024 * 1024 ||
            !Regex.IsMatch(a.Sha256 ?? "", "^[a-f0-9]{64}$") || !Regex.IsMatch(a.FilesSha256 ?? "", "^[a-f0-9]{64}$") ||
            release.Files.Sum(f => f.Size) > 8L * 1024 * 1024 * 1024)
            throw new InvalidDataException(L.Text("Недопустимый архив обновления."));
    }

    async Task PrepareArchive(Release release, List<ReleaseFile> pending, IProgress<UpdateProgress> progress, CancellationToken token)
    {
        // Old publishers may carry forward archive metadata. Only use an archive
        // bound to the exact file records; older manifests continue using blobs.
        if (pending.Count == 0 || SteamDistribution.Enabled || release.Archive is not { } a || a.FilesSha256 != FilesDigest(release)) return;
        var missing = new Dictionary<string, ReleaseFile>(StringComparer.Ordinal);
        foreach (var file in pending)
            if (!await Matches(Target(".tio-update/cache/" + file.Sha256), file, token)) missing.TryAdd(file.Sha256, file);
        if (missing.Count == 0) return;
        Directory.CreateDirectory(Target(".tio-update/archives"));
        string archive = Target(".tio-update/archives/" + a.Sha256);
        var descriptor = new ReleaseFile("client.zip", a.Size, a.Sha256);
        bool cached = await Matches(archive, descriptor, token);
        long bytes = missing.Values.Sum(f => f.Size);
        // Avoid thousands of round trips, but never fetch a full archive for a
        // tiny patch. Keep the existing per-file repair and old-server support.
        if (!cached && a.Size > bytes && (missing.Count < 32 || a.Size > bytes * 1.25)) return;
        if (!cached) await DownloadArchive(descriptor, archive, progress, token);

        progress.Report(new(L.Text("Проверка архива обновления…"), 0));
        var expected = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var file in release.Files)
            if (!expected.TryAdd(file.Sha256, file.Size) && expected[file.Sha256] != file.Size)
                throw new InvalidDataException("Inconsistent blob sizes");
        using (var zip = ZipFile.OpenRead(archive))
        {
            if (zip.Entries.Count != expected.Count) throw new InvalidDataException("Archive file count mismatch");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var entry in zip.Entries)
                if (!expected.TryGetValue(entry.FullName, out long size) || size != entry.Length || !seen.Add(entry.FullName))
                    throw new InvalidDataException("Unexpected archive entry");
            int completed = 0;
            string extracting=L.Text("Распаковка · ");
            foreach (var entry in zip.Entries)
            {
                token.ThrowIfCancellationRequested();
                if (!missing.TryGetValue(entry.FullName, out var file)) continue;
                string cache = Target(".tio-update/cache/" + file.Sha256);
                string partial = Target(".tio-update/cache/" + file.Sha256 + ".part");
                try
                {
                    using (var input = entry.Open())
                    using (var output = new FileStream(partial, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        byte[] buffer = new byte[131072]; long received = 0; int read;
                        while ((read = await input.ReadAsync(buffer, token)) != 0)
                        {
                            received += read;
                            if (received > file.Size) throw new InvalidDataException("Archive entry exceeds expected size");
                            await output.WriteAsync(buffer.AsMemory(0, read), token);
                        }
                    }
                    if (!await Matches(partial, file, token)) throw new InvalidDataException("Archive entry SHA256 mismatch");
                    File.Move(partial, cache, true);
                }
                finally { if (File.Exists(partial)) File.Delete(partial); }
                progress.Report(new(extracting + file.Path, ++completed * 100 / missing.Count));
            }
        }
        // Retain the current verified archive for offline repair, reclaim only
        // updater-owned archives from older releases after successful extraction.
        foreach (string path in Directory.EnumerateFiles(Target(".tio-update/archives")))
            if (Path.GetFileName(path) != a.Sha256 && Regex.IsMatch(Path.GetFileName(path), "^[a-f0-9]{64}(\\.part)?$"))
                File.Delete(Target(".tio-update/archives/" + Path.GetFileName(path)));
    }

    async Task DownloadArchive(ReleaseFile file, string destination, IProgress<UpdateProgress> progress, CancellationToken token)
    {
        string partial = Target(".tio-update/archives/" + file.Sha256 + ".part");
        if (await Matches(partial, file, token)) { File.Move(partial, destination, true); return; }
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
                throw new InvalidDataException(L.Text("Сервер прислал неверный диапазон архива."));
        }
        else offset = 0;
        using (var input = await response.Content.ReadAsStreamAsync(token))
        using (var output = new FileStream(partial, offset == 0 ? FileMode.Create : FileMode.Append, FileAccess.Write, FileShare.None))
        {
            byte[] buffer = new byte[131072]; long received = offset; int read;
            long last = Environment.TickCount64 - 200;
            progress.Report(new(L.Text("Загрузка архива клиента…"), (int)(offset * 100 / file.Size)));
            while ((read = await input.ReadAsync(buffer, token)) > 0)
            {
                received += read;
                Metrics.PayloadBytes+=read;
                if (received > file.Size) { output.Close(); File.Delete(partial); throw new InvalidDataException("Archive exceeds expected size"); }
                await output.WriteAsync(buffer.AsMemory(0, read), token);
                if (Environment.TickCount64 - last >= 100 || received == file.Size)
                {
                    progress.Report(new(L.Text($"Загрузка архива · {received/1048576:N1} / {file.Size/1048576:N1} МБ"), (int)(received * 100 / file.Size)));
                    last = Environment.TickCount64;
                }
            }
        }
        if (!await Matches(partial, file, token))
        {
            if (new FileInfo(partial).Length >= file.Size) File.Delete(partial);
            throw new InvalidDataException(L.Text("Архив загружен не полностью или повреждён. Повторите проверку."));
        }
        File.Move(partial, destination, true);
    }
}
