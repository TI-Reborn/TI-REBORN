using System.Security.AccessControl;
using System.Security.Principal;

namespace TioLauncher;

static class InstallLocationSelfTest
{
    static void Assert(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    public static void Run(string output)
    {
        string root = Path.Combine(Path.GetTempPath(), "tio-install-location-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var results = new List<string>();
        try
        {
            string settings = Path.Combine(root, "preferences", "folder.txt");
            string suggested = Path.Combine(root, "default-installation");
            var location = new InstallLocation(settings, suggested);
            Assert(!location.TryLoadSaved(out string initial, out string? reason), "first run accepted an unselected folder");
            Assert(initial == suggested && reason is null, "first-run default suggestion");
            Assert(!Directory.Exists(suggested), "reading settings created the default game folder");
            Assert(!location.TryCommitSelection(null, out _, out reason) && reason is null, "cancel was accepted");
            Assert(!File.Exists(settings), "cancel saved first-run settings");
            results.Add("PASS: first run waits for a folder; cancel creates no settings or installation");

            string selected = Path.Combine(root, "Игры с пробелами", "Новая папка", "TIO");
            Assert(location.TryCommitSelection(selected, out string saved, out reason), "new Unicode folder failed: " + reason);
            Assert(Directory.Exists(selected), "selected folder was not created");
            Assert(saved == selected && File.ReadAllText(settings) == selected, "selected path was not saved");
            Assert(location.TryLoadSaved(out saved, out reason) && saved == selected, "saved path was not restored: " + reason);
            Assert(!Directory.EnumerateFiles(selected).Any(), "write validation left a probe file");
            results.Add("PASS: a new nested Unicode folder with spaces is created and restored from folder.txt");

            string personal = Path.Combine(selected, "personal-save.dat");
            File.WriteAllText(personal, "preserve this player's file");
            Assert(location.TryCommitSelection(selected, out _, out reason), "existing folder failed: " + reason);
            Assert(File.ReadAllText(personal) == "preserve this player's file", "selection changed personal data");
            string previous = File.ReadAllText(settings);
            Assert(!location.TryCommitSelection(null, out _, out reason) && reason is null, "cancel returned an error");
            Assert(File.ReadAllText(settings) == previous, "cancel changed existing settings");
            Assert(!Directory.EnumerateFiles(Path.GetDirectoryName(settings)!).Any(p => Path.GetFileName(p).StartsWith(".folder-", StringComparison.Ordinal)), "atomic save left temporary settings");
            results.Add("PASS: existing installation data is preserved; cancellation preserves the old selection");

            string occupied = Path.Combine(root, "occupied");
            File.WriteAllText(occupied, "existing file");
            foreach (string invalid in new[] {
                occupied, Path.Combine(occupied, "child"), "relative-folder", "", "   ",
                Path.Combine(root, "NUL"), Path.Combine(root, "COM1.txt"), Path.Combine(root, "bad:stream"),
                Path.Combine(root, "bad<name"), Path.Combine(root, "trailing."), @"\\?\C:\Games\TIO"
            })
            {
                Assert(!location.TryCommitSelection(invalid, out _, out reason) && reason is not null, "invalid path accepted: " + invalid);
                Assert(File.ReadAllText(settings) == previous, "invalid path changed the previous selection: " + invalid);
            }
            Assert(File.ReadAllText(occupied) == "existing file", "selection replaced a regular file");
            results.Add("PASS: file paths, invalid Windows names, relative and device paths are rejected without replacing settings or data");

            string readOnlyFolder = Path.Combine(root, "write-denied");
            var readOnlyDirectory = Directory.CreateDirectory(readOnlyFolder);
            var originalPermissions = readOnlyDirectory.GetAccessControl(AccessControlSections.Access);
            var deniedPermissions = readOnlyDirectory.GetAccessControl(AccessControlSections.Access);
            deniedPermissions.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User!,
                FileSystemRights.CreateFiles, AccessControlType.Deny));
            readOnlyDirectory.SetAccessControl(deniedPermissions);
            try
            {
                Assert(!location.TryCommitSelection(readOnlyFolder, out _, out reason) && reason is not null, "unwritable folder was accepted");
                Assert(File.ReadAllText(settings) == previous, "unwritable folder changed existing settings");
                File.WriteAllText(settings, readOnlyFolder);
                Assert(!location.TryLoadSaved(out _, out reason) && reason is not null, "saved unwritable folder was accepted");
            }
            finally
            {
                readOnlyDirectory.SetAccessControl(originalPermissions);
                File.WriteAllText(settings, previous);
            }
            results.Add("PASS: Windows denies new files in a protected folder; selection and saved-path checks reject it");

            string missing = Path.Combine(root, "missing-installation");
            File.WriteAllText(settings, missing);
            Assert(!location.TryLoadSaved(out _, out reason) && reason is not null, "missing saved folder was accepted");
            Assert(!Directory.Exists(missing), "loading settings silently recreated a missing installation");
            File.WriteAllText(settings, "invalid-relative-path");
            Assert(!location.TryLoadSaved(out _, out reason) && reason is not null, "malformed settings were accepted");
            File.WriteAllText(settings, occupied);
            Assert(!location.TryLoadSaved(out _, out reason) && reason is not null, "saved regular-file path was accepted");
            results.Add("PASS: missing or malformed saved paths require a fresh selection");

            string blockedSettings = Path.Combine(root, "settings-is-a-directory");
            Directory.CreateDirectory(blockedSettings);
            var blocked = new InstallLocation(blockedSettings, suggested);
            Assert(!blocked.TryCommitSelection(selected, out _, out reason) && reason is not null, "settings persistence failure was ignored");
            Assert(Directory.Exists(blockedSettings) && File.ReadAllText(personal) == "preserve this player's file", "persistence failure damaged existing data");
            results.Add("PASS: failure to save settings leaves the dialog unresolved and preserves installation data");

            File.WriteAllLines(output, results);
        }
        catch (Exception error)
        {
            File.WriteAllText(output, string.Join(Environment.NewLine, results) + Environment.NewLine + "FAIL: " + error);
            Environment.ExitCode = 1;
        }
        finally
        {
            // root is a unique test directory we created above; it contains no player data.
            Directory.Delete(root, recursive: true);
        }
    }
}
