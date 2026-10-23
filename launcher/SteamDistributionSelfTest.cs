using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
namespace TioLauncher;

internal static class SteamDistributionSelfTest
{
    internal static async Task Run(string report)
    {
        string root=Path.Combine(Path.GetTempPath(),"tio-steam-test-"+Guid.NewGuid().ToString("N"));
        string depot=Path.Combine(root,"depot"), profile=Path.Combine(root,"profile");
        Directory.CreateDirectory(depot);
        var checks=new List<string>();
        void Check(bool pass,string name) { if (!pass) throw new Exception(name); checks.Add(name); }
        try
        {
            ReleaseFile Make(string name,string text,bool seed=false)
            {
                byte[] bytes=Encoding.UTF8.GetBytes(text);
                string target=Path.Combine(depot,name);Directory.CreateDirectory(Path.GetDirectoryName(target)!);File.WriteAllBytes(target,bytes);
                return new(name,bytes.Length,Convert.ToHexStringLower(SHA256.HashData(bytes)),seed);
            }
            var entries=new[]{"ti.exe","silver.dll","orange.dll","gold.dll","ode.dll","d3dx9_26.dll"}.Select(n=>Make(n,"original:"+n)).ToList();
            entries.Add(Make("base/config.cfg","default",true));entries.Add(Make("base/autoexec.cfg","default autoexec",true));
            byte[] manifest=JsonSerializer.SerializeToUtf8Bytes(new Release(1,"test","news",entries.ToArray()));
            using var updater=new Updater(profile,new SteamDistribution.LocalContentHandler(depot,manifest));
            var release=await updater.Fetch(CancellationToken.None);
            await updater.Apply(release,new Progress<UpdateProgress>(),CancellationToken.None);
            Check(File.ReadAllText(Path.Combine(profile,"ti.exe"))=="original:ti.exe","Full client installs without network");
            File.WriteAllText(Path.Combine(profile,"base/config.cfg"),"private credentials and settings");
            File.WriteAllText(Path.Combine(profile,"login.ini"),"private login");
            File.WriteAllText(Path.Combine(profile,"ti.exe"),"corrupt runtime");
            await updater.Apply(release,new Progress<UpdateProgress>(),CancellationToken.None);
            Check(File.ReadAllText(Path.Combine(profile,"ti.exe"))=="original:ti.exe","Runtime repair uses depot files");
            Check(File.ReadAllText(Path.Combine(profile,"base/config.cfg"))=="private credentials and settings"&&File.ReadAllText(Path.Combine(profile,"login.ini"))=="private login","Personal config and login survive repair");
            Check(File.ReadAllText(Path.Combine(depot,"base/config.cfg"))=="default","Read-only depot remains unchanged");
            using var client=new HttpClient(new SteamDistribution.LocalContentHandler(depot,manifest));
            try { await client.GetAsync("https://example.com/updates/manifest.json");throw new Exception("Remote URL accepted"); }
            catch(HttpRequestException) { checks.Add("Remote URL rejected without fallback"); }
            try { await client.GetAsync(Updater.Origin+"blobs/../login.ini");throw new Exception("Unknown URL accepted"); }
            catch(HttpRequestException) { checks.Add("Unknown and traversal requests rejected"); }
            try { SteamDistribution.LocalContentHandler.SafePath(depot,"../private");throw new Exception("Escaped path accepted"); }
            catch(IOException) { checks.Add("Depot path traversal rejected"); }
            Directory.Delete(Path.Combine(profile,".tio-update/cache"),true);
            File.WriteAllText(Path.Combine(depot,"ti.exe"),"tampered source");
            File.WriteAllText(Path.Combine(profile,"ti.exe"),"existing runtime");
            try { await updater.Apply(release,new Progress<UpdateProgress>(),CancellationToken.None);throw new Exception("Tampered depot accepted"); }
            catch(InvalidDataException) { checks.Add("Tampered depot hash rejected"); }
            Check(File.ReadAllText(Path.Combine(profile,"ti.exe"))=="existing runtime","Failed repair preserves previous installation");
            File.WriteAllText(report,JsonSerializer.Serialize(new {passed=true,steam=SteamDistribution.Enabled,checks}));
        }
        catch(Exception error) { File.WriteAllText(report,JsonSerializer.Serialize(new {passed=false,error=error.ToString(),checks}));Environment.ExitCode=1; }
        finally { Directory.Delete(root,true); }
    }
}
