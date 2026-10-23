namespace TioLauncher;

internal static class GamePathSelfTest
{
    static void Assert(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    static void ExpectRejection(string root, Func<string, string?> resolver)
    {
        try { GamePath.ForNativeClient(root, resolver); }
        catch (IOException error)
        {
            Assert(error.Message.Contains("латинскими", StringComparison.Ordinal), "path rejection lacked an actionable compatibility message");
            return;
        }
        throw new Exception("unsupported native path was accepted");
    }

    internal static void Run(string output)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-native-path-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var results = new List<string>();
        try
        {
            string ascii = Path.Combine(root, "ASCII game folder with spaces");
            Directory.CreateDirectory(ascii);
            Assert(GamePath.ForNativeClient(ascii, _ => throw new Exception("short name was requested for an ordinary ASCII folder")) == Path.GetFullPath(ascii),
                "ordinary ASCII folder changed");
            results.Add("PASS: short ASCII paths, including spaces, are used unchanged without querying 8.3 names");

            string unicode = Path.Combine(root, "Игры с пробелами", "Клиент TIO");
            Directory.CreateDirectory(unicode);
            string alias = GamePath.ForNativeClient(unicode);
            Assert(alias.All(character => character <= 0x7f) && alias.Length <= GamePath.MaximumNativeLength && Directory.Exists(alias),
                "Windows did not provide a usable native alias");
            string marker = "owned-directory-identity-" + Guid.NewGuid().ToString("N") + ".txt";
            string content = Guid.NewGuid().ToString("N");
            File.WriteAllText(Path.Combine(unicode, marker), content);
            Assert(File.ReadAllText(Path.Combine(alias, marker)) == content, "short alias did not reach the selected directory");
            File.Delete(Path.Combine(alias, marker));
            Assert(!File.Exists(Path.Combine(unicode, marker)), "short alias and selected directory were different installations");
            Assert(Directory.Exists(unicode), "using the native alias moved the installation");
            results.Add("PASS: the real Windows short alias is ASCII and resolves to the exact same Unicode installation (bidirectional marker check)");

            ExpectRejection(unicode, _ => null);
            ExpectRejection(unicode, _ => unicode);
            ExpectRejection(unicode, _ => Path.Combine(root, "missing-short-alias"));
            ExpectRejection(unicode, _ => "relative-alias");
            results.Add("PASS: unavailable, Unicode, missing-directory and relative short aliases are rejected with a Russian folder-choice message");

            string tooLong = Path.Combine(root, new string('a', 95), new string('b', 95), new string('c', 50));
            Directory.CreateDirectory(tooLong);
            Assert(tooLong.Length > GamePath.MaximumNativeLength, "long-path fixture was too short");
            bool resolvedLongPath = false;
            ExpectRejection(tooLong, full => { resolvedLongPath = full == Path.GetFullPath(tooLong); return full; });
            Assert(resolvedLongPath, "overlong ASCII path bypassed native compatibility checks");
            ExpectRejection(unicode, _ => tooLong);
            ExpectRejection(tooLong, _ => null);
            results.Add("PASS: overlong ASCII folders request a shorter native alias and cannot pass with overlong or missing aliases");

            File.WriteAllLines(output, results);
        }
        catch (Exception error)
        {
            File.WriteAllText(output, string.Join(Environment.NewLine, results) + Environment.NewLine + "FAIL: " + error);
            Environment.ExitCode = 1;
        }
        finally
        {
            // Only this unique, owned test directory is removed.
            Directory.Delete(root, recursive: true);
        }
    }
}
