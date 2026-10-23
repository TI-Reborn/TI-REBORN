using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Authentication;
using System.Text;
using System.Text.Json;

namespace TioLauncher;

internal sealed record SecureGameStatus(uint Pid, int BridgePid, int LoginPort, int SessionPort, string? Error = null, bool EndpointCertificatesValidated = false);

internal static class SecureGame
{
    static void Trace(string phase)
    {
        try
        {
            string folder=SteamDistribution.SettingsRoot;
            Directory.CreateDirectory(folder);
            File.AppendAllText(Path.Combine(folder,$"secure-startup-{Environment.ProcessId}.log"),$"{DateTime.UtcNow:O} phase={phase}\n");
        }
        catch(IOException) { }
        catch(UnauthorizedAccessException) { }
    }
    internal static async Task<SecureGameStatus> Start(string root, bool ownedQa = false)
    {
        string pipeName = "TIO.TLS." + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeServerStream(pipeName, PipeDirection.In, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        string executable = Environment.ProcessPath ?? throw new IOException(L.Text("Не найден исполняемый файл лаунчера."));
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
        if (Path.GetFileNameWithoutExtension(executable).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(Path.Combine(AppContext.BaseDirectory, SteamDistribution.Enabled ? "TIO Steam.dll" : "TIO Launcher.dll"));
        start.ArgumentList.Add("--tls-game"); start.ArgumentList.Add(Path.GetFullPath(root));
        start.ArgumentList.Add(pipeName); start.ArgumentList.Add(ownedQa ? "qa" : "player");
        start.Environment["TIO_GAME_LANGUAGE"] = L.Language;
        using var helper = Process.Start(start) ?? throw new IOException(L.Text("Не удалось запустить защищённый мост игры."));
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(30));
        try
        {
            await pipe.WaitForConnectionAsync(timeout.Token);
            Trace("parent_connected");
            using var reader = new StreamReader(pipe, Encoding.UTF8, false, 4096, true);
            string? line = await reader.ReadLineAsync(timeout.Token);
            Trace("parent_status_received");
            var status = JsonSerializer.Deserialize<SecureGameStatus>(line ?? "") ?? throw new IOException(L.Text("Мост не подтвердил запуск игры."));
            if (status.Error is not null) throw new IOException(status.Error);
            if (status.Pid == 0 || !status.EndpointCertificatesValidated || status.BridgePid != helper.Id || status.LoginPort < 1024 || status.SessionPort < 1024 || status.LoginPort == status.SessionPort)
                throw new IOException(L.Text("Мост сообщил неподдерживаемый профиль запуска."));
            return status;
        }
        catch
        {
            // The helper's job closes on termination, cleaning only its own game.
            if (!helper.HasExited) helper.Kill();
            throw;
        }
    }

    internal static async Task RunChild(string root, string pipeName, bool ownedQa)
    {
        bool reported = false;
        using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.Out, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        StreamWriter? writer = null;
        try
        {
            using var connect = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await pipe.ConnectAsync(connect.Token).ConfigureAwait(false);
            Trace("child_connected");
            writer = new StreamWriter(pipe, new UTF8Encoding(false), 4096, true) { AutoFlush = true };
            string locale = Environment.GetEnvironmentVariable("TIO_GAME_LANGUAGE") ?? "russian";
            GameLanguage.Validate(locale); L.Language = locale;
            using var verificationTimeout = new CancellationTokenSource(TimeSpan.FromMinutes(25));
            var verification = await LaunchVerification.Verify(root, verificationTimeout.Token,ownedQa:ownedQa).ConfigureAwait(false);
            // Apply locale after verification, which can install language files.
            GameLanguage.Apply(root, locale,ownedQa:ownedQa);
            await using var bridge = new TlsBridge(TlsEndpoint.Production, language: locale, verification: verification);
            await bridge.ValidateEndpoints(CancellationToken.None).ConfigureAwait(false);
            bridge.Start();
            using var lifetime = new GameLifetime();
            var profile = new GameLaunchProfile(bridge.LoginPort, bridge.SessionPort, ownedQa, verification);
            uint pid = await Task.Run(() => GameStarter.Start(root, profile: profile, attachLifetime: lifetime.Assign)).ConfigureAwait(false);
            Trace("child_game_started");
            using var game = Process.GetProcessById(checked((int)pid));
            await using var windowIcon = new GameWindowIcon(game);
            using var contracts = NativeContractsUi.Attach(bridge,game);
            await writer.WriteLineAsync(JsonSerializer.Serialize(new SecureGameStatus(pid, Environment.ProcessId, bridge.LoginPort, bridge.SessionPort, EndpointCertificatesValidated: true))).ConfigureAwait(false);
            Trace("child_status_sent");
            reported = true; writer.Dispose(); writer = null; pipe.Dispose();
            var exit = game.WaitForExitAsync();
            if (await Task.WhenAny(exit, bridge.Failure).ConfigureAwait(false) == bridge.Failure) throw await bridge.Failure.ConfigureAwait(false);
            await exit.ConfigureAwait(false);
        }
        catch (Exception error)
        {
            Environment.ExitCode = 1;
            string message = Describe(error);
            if (!reported && writer is not null)
            {
                try { await writer.WriteLineAsync(JsonSerializer.Serialize(new SecureGameStatus(0, Environment.ProcessId, 0, 0, message))); }
                catch (IOException) { }
            }
            if (reported) MessageBox.Show(message, L.Text("Защищённое соединение TIO"), MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { writer?.Dispose(); }
    }

    internal static string Describe(Exception error) => error switch
    {
        AuthenticationException => L.Text("Сертификат игрового сервера не прошёл проверку Windows. Защищённое соединение закрыто. Проверьте дату компьютера и повторите запуск."),
        OperationCanceledException => L.Text("Истекло время подключения к защищённому игровому серверу. Повторите запуск позже."),
        System.Net.Sockets.SocketException => L.Text("Защищённый игровой сервер недоступен. Проверьте интернет и повторите запуск."),
        _ => L.Text("Защищённый запуск остановлен: ") + error.Message
    };
}
