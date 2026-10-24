using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace TioLauncher;

static class ArchiveSelfTest
{
    sealed class Server : HttpMessageHandler
    {
        internal readonly Dictionary<string, byte[]> Blobs = new();
        internal readonly List<string> Requests = new();
        internal long? LastRange;
        internal bool Short, Corrupt, BadRange, IgnoreRange;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            string hash = request.RequestUri!.Segments[^1]; Requests.Add(hash);
            byte[] data = Blobs[hash];
            LastRange = request.Headers.Range?.Ranges.Single().From;
            if (Corrupt) data = new byte[data.Length];
            var response = new HttpResponseMessage(HttpStatusCode.OK);
            if (LastRange is long offset && !IgnoreRange)
            {
                response.StatusCode = HttpStatusCode.PartialContent;
                response.Content = new ByteArrayContent(data[(int)offset..]);
                response.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(BadRange ? offset+1 : offset, data.Length-1, data.Length);
            }
            else response.Content = new ByteArrayContent(Short ? data[..(data.Length/2)] : data);
            return Task.FromResult(response);
        }
    }
    sealed class Progress(Action<UpdateProgress>? report = null) : IProgress<UpdateProgress>
    {
        public void Report(UpdateProgress value) => report?.Invoke(value);
    }
    static void Assert(bool ok, string message) { if (!ok) throw new Exception(message); }
    static async Task Reject(Func<Task> action)
    {
        try { await action(); } catch (InvalidDataException) { return; }
        throw new Exception("Invalid archive accepted");
    }
    static byte[] Zip(IEnumerable<(string Name, byte[] Data)> entries)
    {
        using var data = new MemoryStream();
        using (var zip = new ZipArchive(data, ZipArchiveMode.Create, true))
            foreach (var entry in entries)
            { using var output = zip.CreateEntry(entry.Name, CompressionLevel.Optimal).Open(); output.Write(entry.Data); }
        return data.ToArray();
    }
    static Release Pack(Release release, Server server, byte[]? bytes = null)
    {
        bytes ??= Zip(release.Files.GroupBy(f => f.Sha256).Select(g => (g.Key, server.Blobs[g.Key])));
        string hash = Convert.ToHexStringLower(SHA256.HashData(bytes)); server.Blobs[hash] = bytes;
        return release with { Archive = new(bytes.Length, hash, Updater.FilesDigest(release)) };
    }
    internal static async Task Run(string output)
    {
        string suite = Path.Combine(Path.GetTempPath(), "tio-archive-tests-" + Guid.NewGuid());
        Directory.CreateDirectory(suite); var results = new List<string>();
        string NewRoot() { string path = Path.Combine(suite, Guid.NewGuid().ToString()); Directory.CreateDirectory(path); return path; }
        try
        {
            var server = new Server();
            ReleaseFile Make(string path, string content, bool seed = false)
            {
                byte[] bytes = Encoding.UTF8.GetBytes(content); string hash = Convert.ToHexStringLower(SHA256.HashData(bytes));
                server.Blobs[hash] = bytes; return new(path, bytes.Length, hash, seed);
            }
            var files = new[] { "ti.exe", "silver.dll", "orange.dll", "gold.dll", "ode.dll", "d3dx9_26.dll" }
                .Select(p => Make(p, string.Concat(Enumerable.Repeat(p, 8192)))).ToList();
            files.Add(Make("base/config.cfg", "default config", true));
            files.Add(Make("base/autoexec.cfg", "default route", true));
            files.Add(files[0] with { Path = "base/duplicate.dat" });
            files.Add(Make("base/empty.dat", ""));
            var release = Pack(new Release(1, "archive-test", "news", files.ToArray()), server);
            var progress = new Progress();
            string root = NewRoot();
            Directory.CreateDirectory(Path.Combine(root, "base"));
            File.WriteAllText(Path.Combine(root, "base/config.cfg"), "personal settings");
            File.WriteAllText(Path.Combine(root, "base/login.ini"), "private login");
            using (var updater = new Updater(root, server))
            {
                await updater.Apply(release, progress, CancellationToken.None);
                Assert(server.Requests.SequenceEqual(new[] { release.Archive!.Sha256 }), "Clean install did not use one archive");
                foreach (var f in files.Where(f => !f.Seed))
                    Assert(File.ReadAllBytes(Path.Combine(root, f.Path)).SequenceEqual(server.Blobs[f.Sha256]), "Installed content mismatch");
                Assert(File.ReadAllText(Path.Combine(root, "base/config.cfg")) == "personal settings", "Settings overwritten");
                Assert(File.ReadAllText(Path.Combine(root, "base/login.ini")) == "private login", "Login overwritten");
                await updater.Apply(release, progress, CancellationToken.None);
                Assert(server.Requests.Count == 1, "Unchanged install redownloaded");
                results.Add("PASS: one compressed request; deduplicated and empty resources; personal settings/login preserved; no redownload");
                File.WriteAllText(Path.Combine(root, "silver.dll"), "damaged");
                File.Delete(Path.Combine(root, ".tio-update/cache", files[1].Sha256));
                await updater.Apply(release, progress, CancellationToken.None);
                Assert(server.Requests.Count == 1 && File.ReadAllBytes(Path.Combine(root, "silver.dll")).SequenceEqual(server.Blobs[files[1].Sha256]), "Offline archive repair failed");
                results.Add("PASS: damaged installed resource repaired from verified archive without network");
                var small = Make("silver.dll", "small patch");
                var next = Pack(release with { Files = release.Files.Select(f => f.Path == small.Path ? small : f).ToArray() }, server);
                await updater.Apply(next, progress, CancellationToken.None);
                Assert(server.Requests.Count == 2 && server.Requests[^1] == small.Sha256, "Small patch fetched full archive");
                results.Add("PASS: small update downloads only the changed blob");
            }
            foreach (string mode in new[] { "short", "ignored-range", "bad-range", "corrupt" })
            {
                var s = new Server(); foreach (var pair in server.Blobs) s.Blobs[pair.Key] = pair.Value;
                string r = NewRoot(); using var u = new Updater(r, s);
                string partial = Path.Combine(r, ".tio-update/archives", release.Archive!.Sha256 + ".part");
                if (mode == "corrupt")
                {
                    s.Corrupt = true; await Reject(() => u.Apply(release, progress, CancellationToken.None));
                    Assert(!File.Exists(partial) && !File.Exists(Path.Combine(r, "ti.exe")), "Corrupt archive retained or installed"); s.Corrupt = false;
                }
                else
                {
                    s.Short = true; await Reject(() => u.Apply(release, progress, CancellationToken.None)); s.Short = false;
                    Assert(new FileInfo(partial).Length > 0 && !File.Exists(Path.Combine(r, "ti.exe")), "Short download not retained safely");
                    s.IgnoreRange = mode == "ignored-range"; s.BadRange = mode == "bad-range";
                    if (s.BadRange)
                    { await Reject(() => u.Apply(release, progress, CancellationToken.None)); Assert(!File.Exists(Path.Combine(r,"ti.exe")), "Bad range installed"); s.BadRange = false; }
                }
                await u.Apply(release, progress, CancellationToken.None);
                Assert(File.Exists(Path.Combine(r, "ti.exe")), "Retry failed");
                results.Add("PASS: " + mode + " download rejected/resumed safely; retry installs verified bytes");
            }
            var entries = files.GroupBy(f => f.Sha256).Select(g => (Name:g.Key, Data:server.Blobs[g.Key])).ToArray();
            foreach (string mode in new[] { "traversal", "unknown", "duplicate", "missing", "wrong-hash", "wrong-size", "invalid-zip" })
            {
                var bad = entries.ToList();
                switch (mode)
                {
                    case "traversal": bad[0] = ("../escape", bad[0].Data); break;
                    case "unknown": bad[0] = (new string('f',64), bad[0].Data); break;
                    case "duplicate": bad[1] = bad[0]; break;
                    case "missing": bad.RemoveAt(0); break;
                    case "wrong-hash": bad[0] = (bad[0].Name, new byte[bad[0].Data.Length]); break;
                    case "wrong-size": bad[0] = (bad[0].Name, [1]); break;
                }
                var invalid = Pack(release, server, mode == "invalid-zip" ? new byte[128] : Zip(bad));
                string r = NewRoot(); File.WriteAllText(Path.Combine(r, "ti.exe"), "previous install");
                using var u = new Updater(r, server);
                await Reject(() => u.Apply(invalid, progress, CancellationToken.None));
                Assert(File.ReadAllText(Path.Combine(r,"ti.exe")) == "previous install" && !File.Exists(Path.Combine(suite,"escape")), "Invalid archive changed installation");
                results.Add("PASS: " + mode + " archive rejected before installation");
            }
            {
                string r = NewRoot(); using var cts = new CancellationTokenSource(); using var u = new Updater(r, server);
                bool cancelled = false;
                try { await u.Apply(release, new Progress(p => { if (p.Message.StartsWith("Загрузка архива")) cts.Cancel(); }), cts.Token); }
                catch (OperationCanceledException) { cancelled = true; }
                Assert(cancelled && !File.Exists(Path.Combine(r,"ti.exe")), "Cancellation changed installation");
                await u.Apply(release, progress, CancellationToken.None);
                results.Add("PASS: cancellation keeps installation intact and permits retry");
            }
            {
                string r = NewRoot(); var stale = release with { Files = release.Files.Select(f => f.Path == "silver.dll" ? Make(f.Path,"new version") : f).ToArray() };
                int requests = server.Requests.Count; using var u = new Updater(r, server);
                await u.Apply(stale, progress, CancellationToken.None);
                Assert(!server.Requests.Skip(requests).Contains(release.Archive!.Sha256), "Stale archive selected");
                results.Add("PASS: carried-forward archive with stale file-list binding ignored; legacy blob path works");
            }
            foreach (var bad in new[] { release.Archive! with { Size = -1 }, release.Archive! with { Sha256 = "../escape" }, release.Archive! with { FilesSha256 = "bad" } })
            {
                bool rejected=false; try { Updater.Validate(release with { Archive=bad }); } catch (InvalidDataException) { rejected=true; }
                Assert(rejected,"Invalid archive metadata accepted");
            }
            results.Add("PASS: unsafe archive metadata rejected");
            {
                string r = NewRoot(); File.WriteAllText(Path.Combine(r,"ti.exe"),"previous executable");
                using var cts = new CancellationTokenSource(); using var u = new Updater(r,server);
                bool cancelled=false;
                try { await u.Apply(release,new Progress(p => { if (p.Message.StartsWith("Установка · ")) cts.Cancel(); }),cts.Token); }
                catch (OperationCanceledException) { cancelled=true; }
                Assert(cancelled && File.ReadAllText(Path.Combine(r,"ti.exe"))=="previous executable" &&
                    !File.Exists(Path.Combine(r,"silver.dll")) && !File.Exists(Path.Combine(r,".tio-update/journal.json")),"Multi-file cancellation rollback failed");
                await u.Apply(release,progress,CancellationToken.None);
                Assert(File.ReadAllBytes(Path.Combine(r,"ti.exe")).SequenceEqual(server.Blobs[files[0].Sha256]),"Retry after rollback failed");
                results.Add("PASS: cancellation during installation rolls back existing/new files with one journal; retry succeeds");
            }
            File.WriteAllLines(output, results);
        }
        catch (Exception ex) { File.WriteAllText(output, string.Join("\n", results)+"\nFAIL: "+ex); Environment.ExitCode=1; }
        finally { Directory.Delete(suite, true); }
    }
}
