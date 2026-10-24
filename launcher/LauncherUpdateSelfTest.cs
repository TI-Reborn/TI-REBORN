using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TioLauncher;

// All HTTP responses and files belong to this test. It never contacts production,
// replaces the running launcher, or starts another application.
internal static class LauncherUpdateSelfTest
{
    sealed class FakeServer(Func<HttpRequestMessage, CancellationToken, HttpResponseMessage> respond) : HttpMessageHandler
    {
        internal readonly List<Uri> Requests = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            Requests.Add(request.RequestUri!);
            Assert(request.Headers.CacheControl?.NoCache == true, "update requests permit cached manifests");
            return Task.FromResult(respond(request, token));
        }
    }

    sealed class ImmediateProgress(Action<UpdateProgress>? action = null) : IProgress<UpdateProgress>
    {
        internal readonly List<UpdateProgress> Reports = [];
        public void Report(UpdateProgress value) { Reports.Add(value); action?.Invoke(value); }
    }

    // A non-seekable body makes Content-Length unavailable, exercising the actual
    // byte-count checks instead of only the response header check.
    sealed class UnknownLengthStream(byte[] bytes) : Stream
    {
        readonly MemoryStream input = new(bytes, writable: false);
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => input.Read(buffer, offset, count);
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default) => input.ReadAsync(buffer, token);
        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        protected override void Dispose(bool disposing) { if (disposing) input.Dispose(); base.Dispose(disposing); }
    }

    static void Assert(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    static async Task Reject<T>(Func<Task> action, string message) where T : Exception
    {
        try { await action(); }
        catch (T) { return; }
        throw new Exception(message);
    }

    static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    static LauncherRelease Release(byte[] bytes, string version = "0.1.4") => new(1, version, bytes.Length, Hash(bytes));
    static HttpResponseMessage Body(byte[] bytes, bool unknownLength = false)
        => new(HttpStatusCode.OK) { Content = unknownLength ? new StreamContent(new UnknownLengthStream(bytes)) : new ByteArrayContent(bytes) };

    public static async Task Run(string output)
    {
        string root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "tio-launcher-update-tests-" + Guid.NewGuid().ToString("N")));
        Directory.CreateDirectory(root);
        var results = new List<string>();
        Exception? failure = null;
        try
        {
            byte[] original = Encoding.UTF8.GetBytes("the old launcher must survive failed updates");
            byte[] updated = Encoding.UTF8.GetBytes("the verified new launcher payload");
            var release = Release(updated);
            Assert(LauncherUpdate.IsNewer(release, "0.1.3"), "0.1.3 did not update to 0.1.4");
            Assert(LauncherUpdate.IsNewer(release with { Version = "0.1.10" }, "0.1.9"), "versions were compared as strings");
            Assert(!LauncherUpdate.IsNewer(release, "0.1.4"), "equal versions were updated");
            Assert(!LauncherUpdate.IsNewer(release, "0.1.10"), "launcher was downgraded");
            Assert(LauncherUpdate.IsNewer(release with { Version = "1.0.0" }, "0.99999.99999"), "major version ordering failed");
            foreach (string version in new[] { "0.1", "0.1.4.0", "01.1.4", "0.1.04", "v0.1.4", "0.1.4-beta", "0.1.100000", "../0.1.4", "" })
                await Reject<InvalidDataException>(() => Task.FromResult(LauncherUpdate.IsNewer(release with { Version = version }, "0.1.3")), "unsafe version accepted: " + version);
            results.Add("PASS: numeric 0.1.3 → 0.1.4 and 0.1.9 → 0.1.10 ordering; equal/older releases and invalid versions rejected");

            using (var server = new FakeServer((_, _) => Body(JsonSerializer.SerializeToUtf8Bytes(release))))
            using (var updater = new LauncherUpdate(server))
            {
                Assert(await updater.Fetch(CancellationToken.None) == release, "manifest did not round-trip");
                Assert(server.Requests.Count == 1 && server.Requests[0].AbsoluteUri == LauncherUpdate.Origin + "launcher-manifest.json", "manifest used an unexpected origin");
            }
            foreach (byte[] manifest in new[] {
                Encoding.UTF8.GetBytes("null"), Encoding.UTF8.GetBytes("{}"), Encoding.UTF8.GetBytes("{"),
                JsonSerializer.SerializeToUtf8Bytes(release with { Schema = 2 }),
                JsonSerializer.SerializeToUtf8Bytes(release with { Size = 0 }),
                JsonSerializer.SerializeToUtf8Bytes(release with { Size = 256L * 1024 * 1024 + 1 }),
                JsonSerializer.SerializeToUtf8Bytes(release with { Sha256 = "bad" }),
                JsonSerializer.SerializeToUtf8Bytes(release with { Sha256 = new string('A', 64) }),
                Encoding.UTF8.GetBytes(new string(' ', 16385))
            })
            {
                using var updater = new LauncherUpdate(new FakeServer((_, _) => Body(manifest, unknownLength: true)));
                bool rejected = false;
                try { await updater.Fetch(CancellationToken.None); }
                catch (InvalidDataException) { rejected = true; }
                catch (JsonException) { rejected = true; }
                Assert(rejected, "invalid or oversized manifest accepted");
            }
            results.Add("PASS: trusted manifest endpoint; malformed, empty, oversized, unsupported and invalid-hash manifests rejected");

            string target = Path.Combine(root, "launcher.exe");
            File.WriteAllBytes(target, original);
            string candidate = Path.Combine(root, "candidate.exe");
            var progress = new ImmediateProgress();
            using (var server = new FakeServer((_, _) => Body(updated)))
            using (var updater = new LauncherUpdate(server))
            {
                await updater.Download(release, candidate, progress, CancellationToken.None);
                Assert(await LauncherUpdate.Matches(candidate, release.Sha256, release.Size), "verified download bytes changed");
                Assert(server.Requests.Count == 1 && server.Requests[0].AbsoluteUri == LauncherUpdate.Origin + "TIO-Launcher-0.1.4.exe", "download used an unexpected URL");
                Assert(progress.Reports.Count > 0, "download did not report progress");
                File.Delete(candidate);
            }
            results.Add("PASS: versioned executable is downloaded from the fixed HTTPS origin and verified by exact size and SHA-256");

            var wrongHash = release with { Sha256 = Hash(original) };
            foreach (var bad in new[] {
                (Release: wrongHash, Bytes: updated, Unknown: false),
                (Release: release with { Size = updated.Length + 1 }, Bytes: updated, Unknown: false),
                (Release: release with { Size = updated.Length + 1 }, Bytes: updated, Unknown: true),
                (Release: release with { Size = updated.Length - 1 }, Bytes: updated, Unknown: true)
            })
            {
                using var updater = new LauncherUpdate(new FakeServer((_, _) => Body(bad.Bytes, bad.Unknown)));
                await Reject<InvalidDataException>(() => updater.Download(bad.Release, candidate, progress, CancellationToken.None), "corrupt or wrong-size download accepted");
                Assert(!File.Exists(candidate), "failed download left a candidate");
                Assert(File.ReadAllBytes(target).SequenceEqual(original), "failed download changed the installed launcher");
            }
            results.Add("PASS: bad SHA-256, incorrect Content-Length, truncated and overlong streamed bodies leave the old executable intact and remove partial downloads");

            foreach (HttpStatusCode status in new[] { HttpStatusCode.Redirect, HttpStatusCode.TemporaryRedirect, HttpStatusCode.NotFound })
            {
                using var server = new FakeServer((_, _) => {
                    var response = new HttpResponseMessage(status) { Content = new ByteArrayContent(updated) };
                    response.Headers.Location = new Uri("https://unexpected.example/launcher.exe");
                    return response;
                });
                using var updater = new LauncherUpdate(server);
                await Reject<HttpRequestException>(() => updater.Fetch(CancellationToken.None), "manifest accepted redirect or HTTP error");
                await Reject<HttpRequestException>(() => updater.Download(release, candidate, progress, CancellationToken.None), "download accepted redirect or HTTP error");
                Assert(server.Requests.Count == 2 && server.Requests.All(uri => uri.Host == new Uri(LauncherUpdate.Origin).Host), "HTTP rejection followed another origin");
                Assert(!File.Exists(candidate) && File.ReadAllBytes(target).SequenceEqual(original), "HTTP rejection damaged launcher files");
            }
            results.Add("PASS: redirects and HTTP errors are rejected without following an alternate executable origin");

            using (var cancellation = new CancellationTokenSource())
            using (var updater = new LauncherUpdate(new FakeServer((_, _) => Body(new byte[300000]))))
            {
                var cancelledRelease = Release(new byte[300000]);
                await Reject<OperationCanceledException>(() => updater.Download(cancelledRelease, candidate,
                    new ImmediateProgress(_ => cancellation.Cancel()), cancellation.Token), "download ignored cancellation");
                Assert(!File.Exists(candidate) && File.ReadAllBytes(target).SequenceEqual(original), "cancel left a partial update or changed the old executable");
            }
            File.WriteAllBytes(candidate, original);
            using (var updater = new LauncherUpdate(new FakeServer((_, _) => Body(updated))))
                await Reject<IOException>(() => updater.Download(release, candidate, progress, CancellationToken.None), "download overwrote an existing destination");
            Assert(File.Exists(candidate) && File.ReadAllBytes(candidate).SequenceEqual(original), "download deleted a destination it did not create");
            using (var cancellation = new CancellationTokenSource())
            using (var updater = new LauncherUpdate(new FakeServer((_, _) => Body(updated))))
            {
                cancellation.Cancel();
                await Reject<OperationCanceledException>(() => updater.Download(release, candidate, progress, cancellation.Token), "pre-cancelled download ran");
                Assert(File.ReadAllBytes(candidate).SequenceEqual(original), "pre-cancelled download deleted an existing destination");
            }
            File.Delete(candidate);
            results.Add("PASS: cancellation removes owned partial files; existing destinations are never overwritten or deleted");

            string backup = target + ".previous-test";
            File.WriteAllBytes(candidate, updated);
            await LauncherUpdate.Replace(target, candidate, backup, Hash(original), release);
            Assert(File.ReadAllBytes(target).SequenceEqual(updated), "atomic replacement installed incorrect bytes");
            Assert(File.ReadAllBytes(backup).SequenceEqual(original), "previous launcher backup was not preserved");
            Assert(!File.Exists(candidate), "atomic replacement did not consume the staged executable");
            File.Delete(backup);
            results.Add("PASS: atomic same-volume replacement installs the verified executable and preserves the exact old executable in .previous backup");

            File.WriteAllBytes(target, original);
            File.WriteAllBytes(candidate, updated);
            File.WriteAllBytes(backup, original);
            await Reject<IOException>(() => LauncherUpdate.Replace(target, candidate, backup, Hash(original), release), "existing backup was replaced");
            Assert(File.ReadAllBytes(target).SequenceEqual(original) && File.ReadAllBytes(candidate).SequenceEqual(updated) && File.ReadAllBytes(backup).SequenceEqual(original), "backup collision changed files");
            File.Delete(backup);
            byte[] changed = Encoding.UTF8.GetBytes("changed by another process");
            File.WriteAllBytes(target, changed);
            await Reject<InvalidDataException>(() => LauncherUpdate.Replace(target, candidate, backup, Hash(original), release), "changed installed launcher was replaced");
            Assert(File.ReadAllBytes(target).SequenceEqual(changed) && File.ReadAllBytes(candidate).SequenceEqual(updated) && !File.Exists(backup), "target guard changed files");
            File.WriteAllBytes(target, original);
            File.WriteAllBytes(candidate, changed);
            await Reject<InvalidDataException>(() => LauncherUpdate.Replace(target, candidate, backup, Hash(original), release), "changed candidate was installed");
            Assert(File.ReadAllBytes(target).SequenceEqual(original) && File.ReadAllBytes(candidate).SequenceEqual(changed) && !File.Exists(backup), "candidate guard changed files");
            Assert(!await LauncherUpdate.Matches(Path.Combine(root, "missing.exe"), release.Sha256, release.Size), "missing launcher matched a release");
            results.Add("PASS: existing backup, changed installed executable, changed candidate and missing files fail safely before replacement");
        }
        catch (Exception error) { failure = error; }
        finally
        {
            try
            {
                // The absolute target is the unique test root created above.
                string expectedPrefix = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                Assert(root.StartsWith(expectedPrefix, StringComparison.OrdinalIgnoreCase) &&
                    Path.GetFileName(root).StartsWith("tio-launcher-update-tests-", StringComparison.Ordinal), "unsafe cleanup target");
                Directory.Delete(root, recursive: true);
                Assert(!Directory.Exists(root), "test directory cleanup failed");
                results.Add("PASS: temporary files removed; no production network or player data used");
            }
            catch (Exception error) { failure ??= error; }
        }
        if (failure is not null) { results.Add("FAIL: " + failure); Environment.ExitCode = 1; }
        File.WriteAllLines(output, results);
    }
}
