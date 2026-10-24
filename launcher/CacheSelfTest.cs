using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TioLauncher;

internal static class CacheSelfTest
{
    sealed class Server : HttpMessageHandler
    {
        internal Release Release=null!;
        internal readonly Dictionary<string,byte[]> Blobs=new();
        internal int PayloadRequests,ManifestBodies,NotModified;
        internal bool IgnoreConditional;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            if (request.RequestUri!.AbsolutePath=="/updates/manifest.json")
            {
                byte[] data=JsonSerializer.SerializeToUtf8Bytes(Release);
                string etag="\""+Convert.ToHexStringLower(SHA256.HashData(data))+"\"";
                HttpResponseMessage response;
                if (!IgnoreConditional && request.Headers.IfNoneMatch.Any(e=>e.ToString()==etag))
                { NotModified++;response=new(HttpStatusCode.NotModified); }
                else { ManifestBodies++;response=new(HttpStatusCode.OK) {Content=new ByteArrayContent(data)}; }
                response.Headers.ETag=EntityTagHeaderValue.Parse(etag);return Task.FromResult(response);
            }
            PayloadRequests++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) {Content=new ByteArrayContent(Blobs[request.RequestUri.Segments[^1]])});
        }
        internal ReleaseFile Make(string path,string data,bool seed=false)
        {
            byte[] bytes=Encoding.UTF8.GetBytes(data);string hash=Convert.ToHexStringLower(SHA256.HashData(bytes));
            Blobs[hash]=bytes;return new(path,bytes.Length,hash,seed);
        }
    }
    sealed class Progress : IProgress<UpdateProgress> { internal int Count;public void Report(UpdateProgress p)=>Count++; }
    static void Assert(bool ok,string message) { if (!ok) throw new Exception(message); }

    internal static async Task Run(string output)
    {
        string root=Path.Combine(Path.GetTempPath(),"tio-cache-tests-"+Guid.NewGuid());
        Directory.CreateDirectory(root);var results=new List<string>();var progress=new Progress();
        try
        {
            var server=new Server();
            var files=new[] {"ti.exe","silver.dll","orange.dll","gold.dll","ode.dll","d3dx9_26.dll"}.Select(p=>server.Make(p,"binary:"+p)).ToList();
            files.Add(server.Make("base/checked.dat",new string('a',1024*1024)));
            files.Add(server.Make("base/other.dat","stable resource"));
            files.Add(server.Make("base/config.cfg","default config",true));
            // More entries than a single native directory buffer can hold.
            for (int i=0;i<900;i++) files.Add(server.Make($"base/many/resource-{i:D4}.dat","same resource"));
            server.Release=new(1,"cache-test","news",files.ToArray());
            string verified=Path.Combine(root,".tio-update/verified-files.json");
            string manifestCache=Path.Combine(root,".tio-update/manifest-cache.json");
            async Task<UpdateMetrics> Apply(bool full=false,bool fallback=false)
            {
                using var updater=new Updater(root,server) {DisableMetadataCache=fallback};
                var release=await updater.Fetch(CancellationToken.None);
                await updater.Apply(release,progress,CancellationToken.None,full);
                return updater.Metrics;
            }
            await Apply();int requests=server.PayloadRequests;
            Assert(File.Exists(verified),"Verified file cache was not saved");
            var warm=await Apply();
            Assert(warm.FileCacheHits==902 && warm.InstalledHashes==6 && warm.PayloadRequests==0 && warm.ArchiveBytesHashed==0,"Warm cache did not skip unchanged resources");
            Assert(server.NotModified==1 && server.ManifestBodies==1,"Unchanged manifest transferred again");
            Assert(server.PayloadRequests==requests,"Warm check downloaded payloads");
            Assert(progress.Count<300,"Progress flood was not coalesced");
            results.Add("PASS: persistent cache across updater instances; 902 resources skipped, six binaries rehashed; batched directory enumeration; no payload or ZIP reads");
            results.Add("PASS: conditional manifest GET returns 304 without a body; progress reports coalesced");

            string resource=Path.Combine(root,"base/checked.dat");DateTime time=File.GetLastWriteTimeUtc(resource);
            File.WriteAllText(resource,new string('b',1024*1024));File.SetLastWriteTimeUtc(resource,time);
            var changed=await Apply();
            Assert(File.ReadAllText(resource)==new string('a',1024*1024) && changed.InstalledHashes>6 && server.PayloadRequests==requests,"Same-size/mtime corruption not repaired from cache");
            results.Add("PASS: same-size corruption with restored last-write time detected through ChangeTime and repaired offline");

            string other=Path.Combine(root,"base/other.dat");time=File.GetLastWriteTimeUtc(other);
            string replacement=Path.Combine(root,"replacement.tmp");File.WriteAllText(replacement,new string('z',"stable resource".Length));
            File.SetLastWriteTimeUtc(replacement,time);File.Move(replacement,other,true);
            await Apply();Assert(File.ReadAllText(other)=="stable resource","Replacement with identical size/mtime accepted");
            File.Delete(other);await Apply();Assert(File.ReadAllText(other)=="stable resource","Missing cached file not restored");
            results.Add("PASS: replaced and missing cached resources detected and restored");

            var full=await Apply(full:true);
            Assert(full.FileCacheHits==0 && full.InstalledHashes==908 && full.PayloadRequests==0 && full.ArchiveBytesHashed==0,"Full verification did not hash every non-seed installed file");
            results.Add("PASS: explicit full check bypasses the cache without downloading or reading an archive");

            var state=JsonSerializer.Deserialize<VerificationState>(File.ReadAllText(verified),Updater.Json)!;
            var expired=state.Files.ToDictionary(p=>p.Key,p=>p.Value with {VerifiedUtcTicks=DateTime.UtcNow.Subtract(TimeSpan.FromDays(8)).Ticks});
            File.WriteAllText(verified,JsonSerializer.Serialize(state with {Files=expired}));
            var aged=await Apply();Assert(aged.FileCacheHits==0 && aged.InstalledHashes==908,"Expired verification records reused");
            results.Add("PASS: seven-day expiry forces a fresh SHA256 check");

            File.WriteAllText(verified,"{corrupted cache");var corrupt=await Apply();
            Assert(corrupt.FileCacheHits==0 && corrupt.InstalledHashes==908,"Corrupted cache trusted or blocked launch");
            var fallback=await Apply(fallback:true);
            Assert(fallback.FileCacheHits==0 && fallback.InstalledHashes==908,"Unsupported filesystem did not fall back to hashing");
            results.Add("PASS: malformed verification cache and unavailable filesystem identity fall back to hashing safely");

            await Apply();
            state=JsonSerializer.Deserialize<VerificationState>(File.ReadAllText(verified),Updater.Json)!;
            File.WriteAllText(verified,JsonSerializer.Serialize(state with {Root=root+"-another-install"}));
            var moved=await Apply();Assert(moved.FileCacheHits==0,"Verification state from another installation trusted");
            File.SetAttributes(verified,FileAttributes.ReadOnly);
            try { await Apply(full:true); } finally { File.SetAttributes(verified,FileAttributes.Normal); }
            results.Add("PASS: installation-bound cache; read-only cache does not block a fully verified launch");

            string linkSource=Path.Combine(root,"link-source.dat");File.WriteAllText(linkSource,new string('a',1024*1024));
            File.Delete(resource);bool linked=false;
            try { File.CreateSymbolicLink(resource,linkSource);linked=true; }
            catch (UnauthorizedAccessException) { }
            catch (IOException) { }
            if (linked)
            {
                using var updater=new Updater(root,server);bool rejected=false;
                try { await updater.Apply(server.Release,progress,CancellationToken.None); } catch (IOException) { rejected=true; }
                Assert(rejected,"Fast directory snapshot accepted a linked resource");
                File.Delete(resource);results.Add("PASS: reparse-point resource rejected before trusting cached metadata");
            }
            else results.Add("SKIP: symbolic-link rejection fixture unavailable without Windows link privilege");
            File.WriteAllBytes(resource,server.Blobs[files[6].Sha256]);await Apply();

            server.Release=server.Release with {Version="news-only",News="fresh news"};
            await Apply();Assert(server.ManifestBodies==2,"Changed manifest not fetched");
            int bodies=server.ManifestBodies;server.IgnoreConditional=true;await Apply();server.IgnoreConditional=false;
            Assert(server.ManifestBodies==bodies+1,"Server ignoring ETag not supported");
            File.WriteAllText(manifestCache,"invalid JSON");await Apply();
            Assert(server.ManifestBodies==bodies+2,"Corrupt manifest cache caused a 304 without usable data");
            results.Add("PASS: changed manifest, servers ignoring conditional GET and damaged manifest caches remain supported");

            var updated=server.Make("base/other.dat","new published bytes");
            server.Release=server.Release with {Files=server.Release.Files.Select(f=>f.Path==updated.Path ? updated : f).ToArray()};
            await Apply();Assert(File.ReadAllText(other)=="new published bytes" && server.PayloadRequests==requests+1,"Cached verification hid a new published SHA256");
            results.Add("PASS: manifest hash change invalidates the specific cached resource and downloads only that blob");

            File.WriteAllText(Path.Combine(root,"base/config.cfg"),"personal settings");
            File.WriteAllText(Path.Combine(root,"base/login.ini"),"personal login");await Apply(full:true);
            Assert(File.ReadAllText(Path.Combine(root,"base/config.cfg"))=="personal settings" && File.ReadAllText(Path.Combine(root,"base/login.ini"))=="personal login","Private files overwritten");
            results.Add("PASS: fast/full checks preserve personal config and login");

            string cancellationBefore=File.ReadAllText(verified);using var cancel=new CancellationTokenSource();cancel.Cancel();
            using(var updater=new Updater(root,server))
            {
                bool cancelled=false;
                try { await updater.Apply(server.Release,progress,cancel.Token); } catch(OperationCanceledException) {cancelled=true;}
                Assert(cancelled && File.ReadAllText(verified)==cancellationBefore,"Cancelled check committed verification state");
            }
            results.Add("PASS: cancelled checks do not commit a partially verified cache");
            File.WriteAllLines(output,results);
        }
        catch(Exception error) {File.WriteAllText(output,string.Join("\n",results)+"\nFAIL: "+error);Environment.ExitCode=1;}
        finally {Directory.Delete(root,true);}
    }
}
