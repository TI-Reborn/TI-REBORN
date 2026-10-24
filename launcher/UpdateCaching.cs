using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;

namespace TioLauncher;

public sealed class UpdateMetrics
{
    public int InstalledHashes { get; internal set; }
    public long InstalledBytesHashed { get; internal set; }
    public int FileCacheHits { get; internal set; }
    public int DirectoryScans { get; internal set; }
    public long ArchiveBytesHashed { get; internal set; }
    public int PayloadRequests { get; internal set; }
    public long PayloadBytes { get; internal set; }
    public long ElapsedMilliseconds { get; internal set; }
}

internal sealed class UpdateProgressThrottle(IProgress<UpdateProgress> target) : IProgress<UpdateProgress>
{
    long last=long.MinValue/2;
    string phase="";
    public void Report(UpdateProgress value)
    {
        string next=value.Message.Split(" · ",2)[0];long now=Environment.TickCount64;
        if (next!=phase || value.Percent==100 || now-last>=100)
        { phase=next;last=now;target.Report(value); }
    }
}

public sealed partial class Updater
{
    internal bool DisableMetadataCache; // Isolated fallback test; never a persisted preference.
    public UpdateMetrics Metrics { get; private set; } = new();
    public long ManifestBytesReceived { get; private set; }
    public bool ManifestNotModified { get; private set; }
    sealed record ManifestCache(int Schema, string? ETag, string Sha256, byte[] Data);

    byte[]? ReadCache(string name, int limit)
    {
        try
        {
            using var input=File.OpenRead(Target(".tio-update/"+name));
            if (input.Length>limit) return null;
            byte[] bytes=new byte[(int)input.Length];input.ReadExactly(bytes);return bytes;
        }
        catch (IOException) { return null; }
        catch (UnauthorizedAccessException) { return null; }
    }
    void WriteCache(string name, byte[] bytes)
    {
        string? temporary=null;
        try
        {
            Directory.CreateDirectory(Target(".tio-update"));
            string path=Target(".tio-update/"+name);
            temporary=Target(".tio-update/"+name+"."+Guid.NewGuid().ToString("N")+".tmp");
            using (var output=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None)) output.Write(bytes);
            File.Move(temporary,path,true);
        }
        catch (IOException) { } // A cache is optional; never prevent a verified launch.
        catch (UnauthorizedAccessException) { }
        finally
        {
            if (temporary!=null)
                try { if (File.Exists(temporary)) File.Delete(temporary); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
        }
    }
    ManifestCache? LoadManifestCache()
    {
        if (SteamDistribution.Enabled) return null;
        try
        {
            byte[]? bytes=ReadCache("manifest-cache.json",12*1024*1024);
            var cached=bytes==null ? null : JsonSerializer.Deserialize<ManifestCache>(bytes,Json);
            if (cached is not {Schema:1,Data:not null} || cached.Data.Length>8*1024*1024 ||
                Convert.ToHexStringLower(SHA256.HashData(cached.Data))!=cached.Sha256 ||
                !EntityTagHeaderValue.TryParse(cached.ETag,out _)) return null;
            // Validate cached content before permitting a 304 response to reuse it.
            Validate(JsonSerializer.Deserialize<Release>(cached.Data,Json) ?? throw new InvalidDataException());
            return cached;
        }
        catch (JsonException) { return null; }
        catch (InvalidDataException) { return null; }
    }
    public async Task<Release> Fetch(CancellationToken token)
    {
        ManifestBytesReceived=0;ManifestNotModified=false;
        var cached=LoadManifestCache();
        using var deadline=CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(TimeSpan.FromSeconds(20));token=deadline.Token;
        using var request=new HttpRequestMessage(HttpMethod.Get,Origin+"manifest.json");
        request.Headers.CacheControl=new CacheControlHeaderValue {NoCache=true};
        if (cached!=null) request.Headers.IfNoneMatch.Add(EntityTagHeaderValue.Parse(cached.ETag!));
        using var response=await http.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,token);
        byte[] bytes;
        if (response.StatusCode==HttpStatusCode.NotModified && cached!=null)
        { bytes=cached.Data;ManifestNotModified=true; }
        else
        {
            response.EnsureSuccessStatusCode();
            using var input=await response.Content.ReadAsStreamAsync(token);
            using var data=new MemoryStream();byte[] buffer=new byte[65536];int read;
            while ((read=await input.ReadAsync(buffer,token))!=0)
            {
                ManifestBytesReceived+=read;
                if (data.Length+read>8*1024*1024) throw new InvalidDataException(L.Text("Список файлов слишком большой"));
                data.Write(buffer,0,read);
            }
            bytes=data.ToArray();
        }
        var release=JsonSerializer.Deserialize<Release>(bytes,Json) ?? throw new InvalidDataException(L.Text("Пустой список файлов"));
        Validate(release);
        ManifestSha256 = Convert.ToHexStringLower(SHA256.HashData(bytes));
        if (!ManifestNotModified && !SteamDistribution.Enabled && response.Headers.ETag is { } etag)
            WriteCache("manifest-cache.json",JsonSerializer.SerializeToUtf8Bytes(new ManifestCache(1,etag.ToString(),Convert.ToHexStringLower(SHA256.HashData(bytes)),bytes)));
        return release;
    }
    internal string? ManifestSha256 { get; private set; }

    async Task<bool> VerifyInstalled(string path, ReleaseFile file, FileVerificationCache cache, CancellationToken token)
    {
        if (!File.Exists(path)) { cache.Forget(file.Path);return false; }
        using var stream=File.OpenRead(path); // Prevent writes/replacement during hashing and stamp capture.
        if (stream.Length!=file.Size) { cache.Forget(file.Path);return false; }
        Metrics.InstalledHashes++;Metrics.InstalledBytesHashed+=stream.Length;
        bool matches=Convert.ToHexStringLower(await SHA256.HashDataAsync(stream,token))==file.Sha256;
        if (matches && !Binaries.Contains(file.Path)) cache.Remember(file,DisableMetadataCache ? null : FileMetadata.Read(stream.SafeFileHandle));
        else cache.Forget(file.Path);
        return matches;
    }
}
