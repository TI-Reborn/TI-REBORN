using System.Text;
using System.Text.Json;
namespace TioLauncher;
static class GameLanguageSelfTest
{
    internal static void Run(string report)
    {
        string directory = Path.Combine(Path.GetTempPath(), "tio-language-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Check(bool pass, string name) { if (!pass) throw new Exception(name); checks.Add(name); }
        try
        {
            byte[] original = Encoding.Latin1.GetBytes("volume 77\r\ncl_lastpass opaque\r\ng_language russian\r\nname \u00c8\u00e2\u00e0\u00ed\r\n");
            byte[] selected = GameLanguage.Config(original,"english");
            Check(Encoding.Latin1.GetString(selected).Contains("g_language english\r\n"),"English selected");
            Check(GameLanguage.Config(selected,"russian").SequenceEqual(original),"Russian restoration preserves all unrelated bytes");
            Check(Encoding.Latin1.GetString(GameLanguage.Config(Encoding.ASCII.GetBytes("g_language russian\ng_language english\n"),"russian")).Split("g_language").Length==2,"Duplicate preferences collapse");
            string settings = Path.Combine(directory,"language.txt");
            Check(GameLanguage.Load(settings)=="russian","Absent preference defaults to Russian");
            GameLanguage.Save("english",settings);Check(GameLanguage.Load(settings)=="english","Saved preference roundtrip");
            try { GameLanguage.Save("unknown",settings); throw new Exception("Invalid value accepted"); } catch (ArgumentException) { checks.Add("Invalid locale rejected"); }
            Check(GameLanguage.Load(settings)=="english","Rejected selection preserves settings");
            L.Language="english";Check(L.Text("ИГРАТЬ")=="PLAY","English launcher button");
            Check(L.Text("Клиент 2026.10.13.1 готов к запуску")=="Client 2026.10.13.1 ready to launch","Whole ready message takes priority over partial prefix");
            L.Language="russian";Check(L.Text("PLAY")=="ИГРАТЬ","Russian launcher restoration");
            Check(L.Text("Client 2026.10.13.1 ready to launch")=="Клиент 2026.10.13.1 готов к запуску","Whole ready message restores Russian");
            foreach (string locale in new[] { "en", "ru" })
                foreach (string name in new[] { "battlelog.xml","quest/00000.xml","quest/tut_1000.xml","rules.txt","help.txt" })
                {
                    string target=Path.Combine(directory,"base/locales",locale,name);Directory.CreateDirectory(Path.GetDirectoryName(target)!);File.WriteAllText(target,locale+name);
                    Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(directory,"base",name))!);
                }
            File.WriteAllBytes(Path.Combine(directory,"base/config.cfg"),original);
            GameLanguage.Apply(directory,"english");Check(File.ReadAllText(Path.Combine(directory,"base/quest/tut_1000.xml")).StartsWith("en"),"English tutorial overlay");
            GameLanguage.Apply(directory,"russian");Check(File.ReadAllBytes(Path.Combine(directory,"base/config.cfg")).SequenceEqual(original),"Overlay switch preserves credentials/settings");
            Check(File.ReadAllText(Path.Combine(directory,"base/quest/tut_1000.xml")).StartsWith("ru"),"Russian tutorial overlay restored");
            File.Delete(Path.Combine(directory,"base/locales/en/help.txt"));
            try { GameLanguage.Apply(directory,"english"); throw new Exception("Missing overlay accepted"); } catch (FileNotFoundException) { checks.Add("Missing resources rejected before writes"); }
            Check(File.ReadAllBytes(Path.Combine(directory,"base/config.cfg")).SequenceEqual(original),"Failed overlay leaves config intact");
            File.WriteAllText(report,JsonSerializer.Serialize(new { passed=true,checks }));
        }
        catch (Exception error) { File.WriteAllText(report,JsonSerializer.Serialize(new { passed=false,error=error.ToString(),checks }));Environment.ExitCode=1; }
        finally { L.Language=GameLanguage.Load(); Directory.Delete(directory,true); }
    }
}
