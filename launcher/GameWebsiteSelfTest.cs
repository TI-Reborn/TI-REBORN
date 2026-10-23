using System.Text;
using System.Text.Json;

namespace TioLauncher;

internal static class GameWebsiteSelfTest
{
    internal static void Run(string report)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-website-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            void Check(bool ok, string message) { if (!ok) throw new InvalidDataException(message); }
            byte[] Sample(string text) => Encoding.Latin1.GetBytes(text);
            string Updated(string text) => Encoding.Latin1.GetString(GameWebsite.Config(Sample(text)));
            string line = "g_weblink " + GameWebsite.Url;
            Check(Updated("// g_weblink ignored\r\ng_weblink_old keep\r\ng_weblink http://tionline.ru/?lang=\r\nr_width 1600\r\n") ==
                  "// g_weblink ignored\r\ng_weblink_old keep\r\n" + line + "\r\nr_width 1600\r\n", "Exact setting boundary");
            Check(Updated("g_weblink old\ng_weblink=other\n  g_weblink \"third\"") == line + "\n", "Duplicate settings");
            Check(Updated("r_width 1600") == "r_width 1600\n" + line + "\n", "Missing setting");
            Check(Updated("") == line + "\n", "Empty config");
            byte[] legacy = new byte[] { 0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2, 13, 10 };
            byte[] configured = GameWebsite.Config(legacy);
            Check(configured.AsSpan(0, legacy.Length).SequenceEqual(legacy), "CP1251 bytes changed");
            Check(GameWebsite.Config(configured).AsSpan().SequenceEqual(configured), "Non-idempotent configuration");
            byte[] bom = new byte[] { 0xef, 0xbb, 0xbf }.Concat(Sample("g_weblink old\r\n")).ToArray();
            Check(GameWebsite.Config(bom).AsSpan().SequenceEqual(new byte[] { 0xef, 0xbb, 0xbf }.Concat(Sample(line+"\r\n")).ToArray()), "BOM changed");
            Directory.CreateDirectory(Path.Combine(root, "base"));
            File.WriteAllBytes(Path.Combine(root, "base/config.cfg"), legacy);
            GameWebsite.Apply(root);
            Check(File.ReadAllBytes(Path.Combine(root, "base/config.cfg")).AsSpan().SequenceEqual(configured), "Existing installation");
            Check(File.ReadAllText(Path.Combine(root, "base/autoexec.cfg")) == line+"\n", "New installation");
            File.WriteAllText(report, JsonSerializer.Serialize(new { passed = true, url = GameWebsite.Url,
                exact_setting_only = true, duplicate_settings_removed = true, legacy_bytes_preserved = true,
                utf8_bom_preserved = true, idempotent = true, existing_and_new_configs = true }));
        }
        catch (Exception error) { File.WriteAllText(report, JsonSerializer.Serialize(new { passed = false, error = error.ToString() })); Environment.ExitCode = 1; }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
