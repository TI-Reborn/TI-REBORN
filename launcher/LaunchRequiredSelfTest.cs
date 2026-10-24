using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Diagnostics;

namespace TioLauncher;

internal static class LaunchRequiredSelfTest
{
    sealed class Server(byte[] manifest, Dictionary<string, byte[]> blobs, string version) : HttpMessageHandler
    {
        internal int Requests;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Requests++;
            byte[] raw = request.RequestUri!.AbsolutePath switch
            {
                "/downloads/launcher-manifest.json" => JsonSerializer.SerializeToUtf8Bytes(new LauncherRelease(1, version, 100, new string('a',64))),
                "/updates/manifest.json" => manifest,
                _ => blobs[request.RequestUri.Segments[^1]]
            };
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(raw) });
        }
    }
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    internal static async Task Run(string output)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-launch-required-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root); var results = new List<string>();
        try
        {
            var blobs = new Dictionary<string,byte[]>();
            var files = new[] { "ti.exe", "silver.dll", "orange.dll", "gold.dll", "ode.dll", "d3dx9_26.dll" }.Select(name =>
            {
                byte[] bytes = Encoding.UTF8.GetBytes("fixture:"+name); string hash=Convert.ToHexStringLower(SHA256.HashData(bytes));
                blobs[hash]=bytes; return new ReleaseFile(name, bytes.Length, hash);
            }).ToArray();
            byte[] manifest=JsonSerializer.SerializeToUtf8Bytes(new Release(1,"launch-test","",files));
            var a=new Server(manifest,blobs,"0.1.24"); var b=new Server(manifest,blobs,"0.1.24");
            var proof=await LaunchVerification.Verify(root,CancellationToken.None,a,b,"0.1.24");
            byte[] header=proof.Preface(31001,"english");
            Check(header.Length==46 && header[4]==2 && header[5]==1 && header[6]==121 && header[7]==25,"Bad launch identity framing");
            Check(header.AsSpan(8,32).SequenceEqual(SHA256.HashData(manifest)),"Manifest identity differs");
            Check(header.AsSpan(40).SequenceEqual(new byte[]{0,0,0,1,0,24}),"Launcher version differs");
            Check(File.ReadAllBytes(Path.Combine(root,"ti.exe")).SequenceEqual(blobs[files[0].Sha256]),"Unverified install");
            Check(!Directory.Exists(Path.Combine(root,".tio-update/backup")),"Completed update retained backups");
            results.Add("PASS: fresh launcher/client checks precede launch; verified manifest and version on both TLS routes");
            File.WriteAllText(Path.Combine(root,"silver.dll"),"corrupt");
            await LaunchVerification.Verify(root,CancellationToken.None,new Server(manifest,blobs,"0.1.24"),new Server(manifest,blobs,"0.1.24"),"0.1.24");
            Check(File.ReadAllBytes(Path.Combine(root,"silver.dll")).SequenceEqual(blobs[files[1].Sha256]),"Damaged binary accepted");
            Check(!Directory.Exists(Path.Combine(root,".tio-update/backup")),"Repair retained backups");
            results.Add("PASS: starting again verifies and repairs tampered executables; temporary rollback files removed");
            var untouched=new Server(manifest,blobs,"0.1.24"); bool denied=false;
            try { await LaunchVerification.Verify(root,CancellationToken.None,new Server(manifest,blobs,"0.1.25"),untouched,"0.1.24"); }
            catch(InvalidDataException) { denied=true; }
            Check(denied && untouched.Requests==0,"Obsolete launcher passed verification");
            results.Add("PASS: newly published launcher blocks launch before game data or native credentials");
            bool direct=false;
            try { GameStarter.Start(root); } catch(InvalidDataException) { direct=true; }
            Check(direct,"Unchecked native startup accepted");
            results.Add("PASS: native startup without completed verification fails before creating a process");
            string old=Path.Combine(root,"TIO-Launcher-0.1.6.exe.previous-"+new string('a',32));
            File.Copy(Environment.ProcessPath!,old);
            bool nativeLauncher=FileVersionInfo.GetVersionInfo(old).ProductName=="TIO Launcher" && new FileInfo(old).Length>1024*1024;
            string preserve=Path.Combine(root,"personal.exe.previous-"+new string('a',32));File.WriteAllText(preserve,"keep");
            LauncherUpdate.CleanPreviousLaunchers(Path.Combine(root,"TIO Launcher.exe"));
            Check(!nativeLauncher || !File.Exists(old),"Old launcher copy retained");Check(File.Exists(preserve),"Unrelated file deleted");
            results.Add("PASS: exact launcher .previous patterns cleaned; unrelated files retained; native backup cleanup exercised="+nativeLauncher);
            File.WriteAllText(output,JsonSerializer.Serialize(new { passed=true,results,preface=Convert.ToHexStringLower(header),manifest=Convert.ToHexStringLower(SHA256.HashData(manifest)) },new JsonSerializerOptions{WriteIndented=true}));
        }
        catch(Exception e) { File.WriteAllText(output,JsonSerializer.Serialize(new {passed=false,results,error=e.ToString()}));Environment.ExitCode=1; }
        finally { Directory.Delete(root,true); }
    }
}
