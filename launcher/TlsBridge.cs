using System.Buffers;
using System.Collections.Concurrent;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Security.Cryptography;
using System.Text.Json;
using System.Buffers.Binary;

namespace TioLauncher;

// Only this process's loopback channels carry the original ORANGE transport.
// Every external connection authenticates TLS before any native bytes are read.
internal sealed record TlsEndpoint(string Host, int LoginPort, int SessionPort, string? ConnectHost = null)
{
    // The website DNS is behind an HTTP-only proxy. TCP connects to the actual
    // game VPS; SNI and certificate identity remain the public domain.
    public static readonly TlsEndpoint Production = new("ti-reborn.com", 29512, 29513, "185.184.42.88");
}

internal sealed class TlsBridge : IAsyncDisposable
{
    readonly TlsEndpoint endpoint;
    readonly string language;
    readonly string presentation;
    readonly LaunchVerification? verification;
    readonly Action<string> diagnostic;
    readonly byte[] contractsToken = RandomNumberGenerator.GetBytes(32);
    readonly SemaphoreSlim contractsRequests = new(1);
    readonly X509ChainPolicy? testChainPolicy;
    readonly CancellationTokenSource stopping = new();
    readonly TcpListener login;
    readonly TcpListener session;
    readonly ConcurrentDictionary<long, Task> relays = new();
    readonly SemaphoreSlim loginSlots = new(4), sessionSlots = new(4);
    readonly TaskCompletionSource<Exception> failure = new(TaskCreationOptions.RunContinuationsAsynchronously);
    Task? loginLoop, sessionLoop;
    long nextRelay;
    bool disposed;
    internal static readonly TimeSpan ConnectTimeout = TimeSpan.FromSeconds(10);
    internal int LoginPort => ((IPEndPoint)login.LocalEndpoint).Port;
    internal int SessionPort => ((IPEndPoint)session.LocalEndpoint).Port;
    internal IPAddress BoundAddress => ((IPEndPoint)login.LocalEndpoint).Address;
    internal Task<Exception> Failure => failure.Task;

    internal TlsBridge(TlsEndpoint endpoint, X509ChainPolicy? testChainPolicy = null, string language = "russian", LaunchVerification? verification = null, string presentation = GameInterface.New, Action<string>? diagnostic = null)
    {
        this.endpoint = endpoint;
        this.verification = verification;
        this.diagnostic = diagnostic ?? WriteDiagnostic;
        GameLanguage.Validate(language); this.language = language;
        GameInterface.Validate(presentation); this.presentation = presentation;
        this.testChainPolicy = testChainPolicy;
        login = Listen();
        try { session = Listen(); }
        catch { login.Stop(); throw; }
    }

    static TcpListener Listen()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Server.ExclusiveAddressUse = true;
        listener.Start(4);
        return listener;
    }

    // Neither the startup check nor the relay has an accepting certificate callback.
    // The optional custom root policy belongs solely to isolated local self-tests.
    async Task<(TcpClient Tcp, SslStream Tls)> Connect(int port, CancellationToken token)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(ConnectTimeout);
        var tcp = new TcpClient { NoDelay = true };
        SslStream? tls = null;
        try
        {
            await tcp.ConnectAsync(endpoint.ConnectHost ?? endpoint.Host, port, deadline.Token);
            tls = new SslStream(tcp.GetStream(), false);
            await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions
            {
                TargetHost = endpoint.Host,
                EnabledSslProtocols = SslProtocols.None,
                CertificateRevocationCheckMode = testChainPolicy is null ? X509RevocationMode.Online : X509RevocationMode.NoCheck,
                CertificateChainPolicy = testChainPolicy,
                EncryptionPolicy = EncryptionPolicy.RequireEncryption
            }, deadline.Token);
            if (tls.SslProtocol is not (SslProtocols.Tls12 or SslProtocols.Tls13))
                throw new AuthenticationException(L.Text("Сервер не согласовал TLS 1.2 или новее."));
            return (tcp, tls);
        }
        catch { tls?.Dispose(); tcp.Dispose(); throw; }
    }

    internal async Task ValidateEndpoints(CancellationToken token)
    {
        // Check both certificates before launching a process which can ask for a password.
        foreach (int port in new[] { endpoint.LoginPort, endpoint.SessionPort })
        {
            var connection = await Connect(port, token);
            using (connection.Tcp)
            using (connection.Tls) { }
        }
    }

    internal void Start()
    {
        if (loginLoop is not null) throw new InvalidOperationException("Bridge already started.");
        loginLoop = Accept(login, endpoint.LoginPort, true, loginSlots);
        sessionLoop = Accept(session, endpoint.SessionPort, false, sessionSlots);
    }

    internal static byte[] LoginPreface(int port)
    {
        if (port is < 1024 or > 65535) throw new ArgumentOutOfRangeException(nameof(port));
        return [(byte)'T', (byte)'I', (byte)'O', (byte)'T', 1, 0, (byte)(port >> 8), (byte)port];
    }

    async Task Accept(TcpListener listener, int remotePort, bool initial, SemaphoreSlim slots)
    {
        try
        {
            while (!stopping.IsCancellationRequested)
            {
                var native = await listener.AcceptTcpClientAsync(stopping.Token);
                if (!slots.Wait(0)) { native.Dispose(); continue; }
                long id = Interlocked.Increment(ref nextRelay);
                var task = Relay(native, remotePort, initial, slots);
                relays[id] = task;
                _ = task.ContinueWith(completed => relays.TryRemove(id, out var removed), TaskScheduler.Default);
            }
        }
        catch (Exception ex) when (stopping.IsCancellationRequested && ex is OperationCanceledException or ObjectDisposedException or SocketException) { }
        catch (Exception ex) { failure.TrySetResult(ex); }
    }

    async Task Relay(TcpClient native, int remotePort, bool initial, SemaphoreSlim slots)
    {
        using (native)
        using (var channel = CancellationTokenSource.CreateLinkedTokenSource(stopping.Token))
        {
            byte[] trace = RandomNumberGenerator.GetBytes(16);
            RelayEnd? first = null;
            void Record(string operation, Exception? error)
            {
                Interlocked.CompareExchange(ref first, new RelayEnd(DateTime.UtcNow, operation, error), null);
            }

            bool authenticated = false;
            string phase = "vps_connect";
            try
            {
                native.NoDelay = true;
                var connection = await Connect(remotePort, channel.Token);
                authenticated = true;
                using (connection.Tcp)
                using (connection.Tls)
                {
                    phase = "vps_bootstrap_write";
                    if (verification is not null)
                    {
                        byte[] preface = verification.Preface(SessionPort, language, presentation);
                        preface[4] = 4;
                        byte[] envelope = [..preface, ..contractsToken, ..trace];
                        await connection.Tls.WriteAsync(envelope, channel.Token);
                    }
                    else if (initial)
                    {
                        byte[] preface = LoginPreface(SessionPort); preface[5] = LaunchVerification.Flags(language, presentation);
                        await connection.Tls.WriteAsync(preface, channel.Token);
                    }
                    using var local = native.GetStream();
                    phase = "relay";
                    var toServer = Copy(local, connection.Tls, "native_read", "vps_write", Record, channel.Token);
                    var toNative = Copy(connection.Tls, local, "vps_read", "native_write", Record, channel.Token);
                    try { await await Task.WhenAny(toServer, toNative); }
                    finally
                    {
                        // ORANGE intentionally closes mode0 when switching to mode1;
                        // one socket ending must not terminate the game's bridge.
                        // Always observe both tasks, including the failed-first case.
                        channel.Cancel(); native.Dispose(); connection.Tcp.Dispose();
                        try { await Task.WhenAll(toServer, toNative); }
                        catch (Exception ex) when (ex is OperationCanceledException or ObjectDisposedException or IOException or SocketException) { }
                    }
                }
            }
            catch (OperationCanceledException ex) when (stopping.IsCancellationRequested) { Record(phase, ex); }
            catch (Exception ex) when (authenticated && ex is IOException or SocketException or ObjectDisposedException) { Record(phase, ex); }
            catch (Exception ex) { Record(phase, ex); failure.TrySetResult(ex); }
            finally
            {
                slots.Release();
                if (first is not null)
                {
                    string kind = initial ? "login" : "game";
                    diagnostic($"{first.Time:O} tls_relay_end trace_id={Convert.ToHexStringLower(trace)} kind={kind} " +
                               $"operation={first.Operation} event={first.Event} error={first.ErrorName} socket_error={first.SocketCode}");
                }
            }
        }
    }

    static async Task Copy(Stream source, Stream target, string read, string write,
        Action<string, Exception?> record, CancellationToken token)
    {
        byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);
        string operation = read;
        try
        {
            while (true)
            {
                operation = read;
                int size = await source.ReadAsync(buffer.AsMemory(), token);
                if (size == 0)
                {
                    record(operation, null);
                    return;
                }
                operation = write;
                await target.WriteAsync(buffer.AsMemory(0, size), token);
            }
        }
        catch (Exception error)
        {
            record(operation, error);
            throw;
        }
        finally { ArrayPool<byte>.Shared.Return(buffer, clearArray: true); }
    }

    sealed record RelayEnd(DateTime Time, string Operation, Exception? Error)
    {
        SocketError? SocketErrorCode => (Error as SocketException ?? Error?.InnerException as SocketException)?.SocketErrorCode;
        internal string SocketCode => SocketErrorCode?.ToString() ?? "-";
        internal string ErrorName => Error?.GetType().Name ?? "-";
        internal string Event => SocketErrorCode switch
        {
            SocketError.ConnectionReset or SocketError.NetworkReset => "reset",
            SocketError.TimedOut => "timeout",
            _ => Error switch
            {
                null => "eof",
                OperationCanceledException => Operation == "vps_connect" ? "timeout_or_cancelled" : "cancelled",
                _ => "error"
            }
        };
    }

    static readonly object LogLock = new();

    static void WriteDiagnostic(string line)
    {
        try
        {
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TioLauncher");
            Directory.CreateDirectory(folder);
            lock (LogLock)
                File.AppendAllText(Path.Combine(folder, $"tls-relay-{Environment.ProcessId}.log"), line + Environment.NewLine);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    internal async Task<JsonElement> Contracts(object request, CancellationToken token)
    {
        if (verification is null) throw new InvalidOperationException("Verified game session required.");
        await contractsRequests.WaitAsync(token);
        try
        {
            using var deadline=CancellationTokenSource.CreateLinkedTokenSource(token);
            deadline.CancelAfter(TimeSpan.FromSeconds(12));
            byte[] body=JsonSerializer.SerializeToUtf8Bytes(request);
            if(body.Length>4096) throw new InvalidDataException("Contract request too large.");
            var connection=await Connect(endpoint.SessionPort,deadline.Token);
            using(connection.Tcp)
            using(connection.Tls)
            {
                byte[] header=[(byte)'T',(byte)'I',(byte)'O',(byte)'C',1,0,0,0];
                BinaryPrimitives.WriteUInt16BigEndian(header.AsSpan(6),checked((ushort)body.Length));
                byte[] identity=verification.Preface(SessionPort,language)[8..];
                await connection.Tls.WriteAsync(header.Concat(identity).Concat(contractsToken).Concat(body).ToArray(),deadline.Token);
                byte[] length=new byte[4];await connection.Tls.ReadExactlyAsync(length,deadline.Token);
                int size=checked((int)BinaryPrimitives.ReadUInt32BigEndian(length));
                if(size is <2 or >65536) throw new InvalidDataException("Invalid contract response.");
                byte[] raw=new byte[size];await connection.Tls.ReadExactlyAsync(raw,deadline.Token);
                using var json=JsonDocument.Parse(raw);return json.RootElement.Clone();
            }
        }
        finally { contractsRequests.Release(); }
    }

    public async ValueTask DisposeAsync()
    {
        if (disposed) return;
        disposed = true;
        stopping.Cancel(); login.Stop(); session.Stop();
        if (loginLoop is not null) await Task.WhenAll(loginLoop, sessionLoop!);
        await Task.WhenAll(relays.Values);
        stopping.Dispose(); loginSlots.Dispose(); sessionSlots.Dispose();
    }
}
