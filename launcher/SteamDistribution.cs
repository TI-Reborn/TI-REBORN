using System.Net;
using System.Text.Json;

namespace TioLauncher;

// The depot is immutable. Native writable files live in a separate user profile.
// This handler serves only the embedded release and its local, hash-checked files.
// It has no network fallback; Steam owns every distribution update.
internal static class SteamDistribution
{
#if STEAM_DISTRIBUTION
    internal static readonly bool Enabled = true;
#else
    internal static readonly bool Enabled = false;
#endif
    internal static string SettingsRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        Enabled ? "TIO-Online-Steam" : "TioLauncher");
    internal static string GameRoot => Path.Combine(SettingsRoot, "Client");
    internal static string Message(string russian, string english) => L.Language == "english" ? english : russian;
    internal static byte[] Manifest()
    {
        using var stream = typeof(SteamDistribution).Assembly.GetManifestResourceStream("TioLauncher.steam-manifest.json")
            ?? throw new InvalidDataException("Steam client manifest is missing.");
        using var output = new MemoryStream(); stream.CopyTo(output); return output.ToArray();
    }
    internal static HttpMessageHandler ContentHandler() => new LocalContentHandler(Path.Combine(AppContext.BaseDirectory, "Game"), Manifest());

    internal sealed class LocalContentHandler : HttpMessageHandler
    {
        readonly string root;
        readonly byte[] manifest;
        readonly Dictionary<string, ReleaseFile> blobs;
        internal LocalContentHandler(string root, byte[] manifest)
        {
            this.root = Path.GetFullPath(root); this.manifest = manifest;
            var release = JsonSerializer.Deserialize<Release>(manifest, Updater.Json) ?? throw new InvalidDataException("Empty depot manifest.");
            Updater.Validate(release);
            blobs = release.Files.GroupBy(f => f.Sha256).ToDictionary(g => g.Key, g => g.First());
        }
        internal static string SafePath(string root, string relative)
        {
            root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
            string target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe depot path.");
            for (string? p=target; p != null; p=Path.GetDirectoryName(p))
                if ((File.Exists(p) || Directory.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Linked depot path.");
            return target;
        }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            string url=request.RequestUri?.AbsoluteUri ?? "";
            HttpContent content;
            if (request.Method != HttpMethod.Get || !url.StartsWith(Updater.Origin, StringComparison.Ordinal))
                throw new HttpRequestException("Steam distribution does not use remote updates.");
            string path=url[Updater.Origin.Length..];
            if (path == "manifest.json") content = new ByteArrayContent(manifest);
            else if (path.StartsWith("blobs/", StringComparison.Ordinal) && blobs.TryGetValue(path[6..], out var file))
                content = new StreamContent(File.OpenRead(SafePath(root, file.Path)));
            else throw new HttpRequestException("File is not in the reviewed Steam depot.");
            // Local complete responses intentionally reset resumable downloads.
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content=content, RequestMessage=request });
        }
    }
}
