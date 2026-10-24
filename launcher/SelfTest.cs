using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TioLauncher;

static class SelfTest
{
    sealed class FakeServer : HttpMessageHandler
    {
        public Dictionary<string, byte[]> Blobs = new();
        public int Requests;
        public bool Corrupt;
        public long? LastRange;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Requests++;
            string hash = request.RequestUri!.Segments[^1];
            LastRange = request.Headers.Range?.Ranges.Single().From;
            byte[] data = Corrupt ? [255] : Blobs[hash];
            if (LastRange is long offset && !Corrupt)
            {
                var response = new HttpResponseMessage(HttpStatusCode.PartialContent) { Content = new ByteArrayContent(data[(int)offset..]) };
                response.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(offset,data.Length-1,data.Length);
                return Task.FromResult(response);
            }
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(data) });
        }
    }
    static void Assert(bool value, string text) { if (!value) throw new Exception(text); }
    public static async Task Run(string output)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-updater-tests-" + Guid.NewGuid());
        Directory.CreateDirectory(root); var results = new List<string>();
        try
        {
            var server = new FakeServer();
            ReleaseFile Make(string path, string content, bool seed = false)
            {
                var bytes = Encoding.UTF8.GetBytes(content); var hash = Convert.ToHexStringLower(SHA256.HashData(bytes));
                server.Blobs[hash] = bytes; return new(path,bytes.Length,hash,seed);
            }
            var files = new[] { "ti.exe", "silver.dll", "orange.dll", "gold.dll", "ode.dll", "d3dx9_26.dll" }.Select(p => Make(p,"test:" + p)).ToList();
            files.Add(Make("base/config.cfg", "default config", true));
            var release = new Release(1,"test","news",files.ToArray());
            using var updater = new Updater(root,server);
            var progress = new Progress<UpdateProgress>();
            await updater.Apply(release,progress,CancellationToken.None);
            Assert(server.Requests == files.Count,"initial download");
            File.WriteAllText(Path.Combine(root,"base/config.cfg"),"personal settings");
            await updater.Apply(release,progress,CancellationToken.None);
            Assert(server.Requests == files.Count,"unchanged files downloaded");
            Assert(File.ReadAllText(Path.Combine(root,"base/config.cfg")) == "personal settings","settings overwritten");
            results.Add("PASS: clean install, no redownload, personal settings preserved");
            File.WriteAllText(Path.Combine(root,"silver.dll"),"damaged");
            await updater.Apply(release,progress,CancellationToken.None);
            Assert(File.ReadAllText(Path.Combine(root,"silver.dll")) == "test:silver.dll","cache repair");
            results.Add("PASS: repair from verified cache");
            var crest = Make("tio_crest.dll","reviewed clan image helper");
            release = release with { Files = [..release.Files, crest] };
            await updater.Apply(release,progress,CancellationToken.None);
            Assert(File.ReadAllText(Path.Combine(root,crest.Path)) == "reviewed clan image helper","optional crest helper missing");
            File.WriteAllText(Path.Combine(root,crest.Path),"damaged helper");
            await updater.Apply(release,progress,CancellationToken.None);
            Assert(File.ReadAllText(Path.Combine(root,crest.Path)) == "reviewed clan image helper","crest helper not repaired");
            results.Add("PASS: older release without crest helper and upgrade with helper; damaged helper repaired");
            foreach (string path in new[] { "../escape", "base/../../escape", "base/test:stream", "base/CON", "base/login.ini", "base/config.cfg", "base/a.", "other.exe", "other.dll", "tio_crest.dll/child" })
            {
                bool rejected = false;
                try { Updater.Validate(release with { Files = [..files, Make(path,"bad")] }); }
                catch (InvalidDataException) { rejected = true; }
                Assert(rejected,"unsafe path accepted: " + path);
            }
            results.Add("PASS: traversal, device paths, streams and private files rejected");
            var update = Make("silver.dll","new silver");
            var next = release with { Files = release.Files.Select(f => f.Path == update.Path ? update : f).ToArray() };
            server.Corrupt = true; bool failed = false;
            try { await updater.Apply(next,progress,CancellationToken.None); } catch (InvalidDataException) { failed = true; }
            Assert(failed && File.ReadAllText(Path.Combine(root,"silver.dll")) == "test:silver.dll","corrupt download installed");
            server.Corrupt = false;
            File.WriteAllBytes(Path.Combine(root,".tio-update/cache/"+update.Sha256+".part"), server.Blobs[update.Sha256][..3]);
            await updater.Apply(next,progress,CancellationToken.None);
            Assert(server.LastRange == 3,"partial download was not resumed");
            results.Add("PASS: corrupted download leaves installation intact; retry succeeds");
            results.Add("PASS: interrupted file resumes using verified HTTP Content-Range and SHA256");
            string backup = Path.Combine(root,".tio-update/backup/silver.dll");
            Directory.CreateDirectory(Path.GetDirectoryName(backup)!); File.WriteAllText(backup,"pre-crash");
            File.WriteAllText(Path.Combine(root,".tio-update/journal.json"),JsonSerializer.Serialize(new[] { new Change("silver.dll",true) }));
            updater.Recover(); Assert(File.ReadAllText(Path.Combine(root,"silver.dll")) == "pre-crash","recovery failed");
            results.Add("PASS: interrupted installation rolls back from journal");
            File.WriteAllLines(output, results);
        }
        catch (Exception ex) { File.WriteAllText(output,string.Join("\n",results)+"\nFAIL: "+ex); Environment.ExitCode = 1; }
        finally { Directory.Delete(root,true); }
    }
}
