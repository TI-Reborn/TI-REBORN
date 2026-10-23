using System.Collections.Concurrent;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace TioLauncher;

// Disposable TLS servers and private test roots; never change Windows trust or
// connect to production. These checks exercise real SslStream handshakes.
internal static class TlsSelfTest
{
    sealed class Server : IAsyncDisposable
    {
        readonly X509Certificate2 certificate;
        readonly bool login;
        readonly CancellationTokenSource stopping = new();
        readonly TcpListener listener = new(IPAddress.Loopback, 0);
        readonly ConcurrentBag<Task> clients = new();
        readonly Task loop;
        internal readonly ConcurrentBag<byte[]> Payloads = new();
        internal readonly ConcurrentBag<byte[]> Prefaces = new();
        internal readonly ConcurrentBag<SslProtocols> Protocols = new();
        internal readonly ConcurrentBag<Exception> Errors = new();
        internal int Port => ((IPEndPoint)listener.LocalEndpoint).Port;
        internal Server(X509Certificate2 certificate, bool login)
        {
            this.certificate = certificate; this.login = login;
            listener.Start(); loop = Accept();
        }
        async Task Accept()
        {
            try
            {
                while (!stopping.IsCancellationRequested)
                    clients.Add(Serve(await listener.AcceptTcpClientAsync(stopping.Token)));
            }
            catch (OperationCanceledException) { }
        }
        async Task Serve(TcpClient client)
        {
            using (client)
            using (var tls = new SslStream(client.GetStream(), false))
            {
                try
                {
                    await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
                    {
                        ServerCertificate = certificate, EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13
                    }, stopping.Token);
                    Protocols.Add(tls.SslProtocol);
                    if (login)
                    {
                        byte[] preface = new byte[8]; int count = 0;
                        while (count < preface.Length)
                        {
                            int read = await tls.ReadAsync(preface.AsMemory(count), stopping.Token);
                            if (read == 0) return; // Certificate-only startup preflight.
                            count += read;
                        }
                        Prefaces.Add(preface);
                    }
                    await tls.WriteAsync(new byte[] { 0x31, 0x41, 0x59 }, stopping.Token);
                    byte[] buffer = new byte[1024];
                    int size = await tls.ReadAsync(buffer, stopping.Token);
                    if (size == 0) return;
                    Payloads.Add(buffer[..size]); await tls.WriteAsync(buffer.AsMemory(0, size), stopping.Token);
                }
                catch (Exception ex) when (ex is AuthenticationException or IOException or OperationCanceledException or ObjectDisposedException) { Errors.Add(ex); }
            }
        }
        public async ValueTask DisposeAsync()
        {
            stopping.Cancel(); listener.Stop(); await loop; await Task.WhenAll(clients); stopping.Dispose();
        }
    }

    static void Assert(bool condition, string message) { if (!condition) throw new Exception(message); }
    static X509Certificate2 Certificate(X509Certificate2 root, string dns, bool expired = false)
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=" + dns, key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        var san = new SubjectAlternativeNameBuilder(); san.AddDnsName(dns); request.CertificateExtensions.Add(san.Build());
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(new OidCollection { new("1.3.6.1.5.5.7.3.1") }, true));
        var start = DateTimeOffset.UtcNow.AddDays(expired ? -3 : -1);
        var end = DateTimeOffset.UtcNow.AddDays(expired ? -1 : 1);
        using var certificate = request.Create(root, start, end, RandomNumberGenerator.GetBytes(16));
        using var withKey = certificate.CopyWithPrivateKey(key);
        // Schannel cannot serve TLS with a purely ephemeral private key. Import
        // into the user's temporary key container (no PersistKeySet); disposal
        // removes it. The certificate is never installed in any trust store.
        return X509CertificateLoader.LoadPkcs12(withKey.Export(X509ContentType.Pfx), null, X509KeyStorageFlags.UserKeySet);
    }
    static X509ChainPolicy Trust(X509Certificate2 root)
    {
        var chain = new X509ChainPolicy { TrustMode = X509ChainTrustMode.CustomRootTrust, RevocationMode = X509RevocationMode.NoCheck };
        chain.CustomTrustStore.Add(root); return chain;
    }
    static async Task Echo(int port, byte[] payload)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        using var tcp = new TcpClient(); await tcp.ConnectAsync(IPAddress.Loopback, port, timeout.Token);
        var stream = tcp.GetStream(); byte[] challenge = new byte[3]; await stream.ReadExactlyAsync(challenge, timeout.Token);
        Assert(challenge.SequenceEqual(new byte[] { 0x31, 0x41, 0x59 }), "server-first challenge changed");
        await stream.WriteAsync(payload, timeout.Token);
        byte[] returned = new byte[payload.Length]; await stream.ReadExactlyAsync(returned, timeout.Token);
        Assert(returned.SequenceEqual(payload), "native payload changed");
    }
    static async Task Reject(X509Certificate2 certificate, X509ChainPolicy? trust, string reason)
    {
        await using var login = new Server(certificate, true);
        await using var session = new Server(certificate, false);
        await using var bridge = new TlsBridge(new("localhost", login.Port, session.Port), trust);
        bool rejected = false;
        try { await bridge.ValidateEndpoints(CancellationToken.None); }
        catch (AuthenticationException) { rejected = true; }
        catch (IOException error) { throw new Exception("Local TLS server failure: " + string.Join(" | ", login.Errors.Select(e => e.ToString())), error); }
        Assert(rejected, reason + " accepted");
        Assert(login.Payloads.IsEmpty && session.Payloads.IsEmpty && login.Prefaces.IsEmpty, reason + " received native credentials");
    }
    internal static async Task Run(string output)
    {
        var results = new List<string>();
        try
        {
            using var rootKey = RSA.Create(2048);
            var rootRequest = new CertificateRequest("CN=TIO isolated TLS self-test", rootKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
            rootRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
            rootRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
            using var root = rootRequest.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-10), DateTimeOffset.UtcNow.AddDays(10));
            using var valid = Certificate(root, "localhost");
            using var wrongName = Certificate(root, "invalid.test");
            using var expired = Certificate(root, "localhost", true);
            await Reject(valid, null, "unknown issuer");
            await Reject(wrongName, Trust(root), "wrong SAN");
            await Reject(expired, Trust(root), "expired certificate");
            results.Add("PASS: unknown issuer, wrong SAN and expired certificate rejected before any native bytes; Windows trust unchanged");
            await using (var login = new Server(valid, true))
            await using (var session = new Server(valid, false))
            {
                var endpoint = new TlsEndpoint("localhost", login.Port, session.Port, "127.0.0.1");
                var a = new TlsBridge(endpoint, Trust(root)); var b = new TlsBridge(endpoint, Trust(root));
                int[] ports = [a.LoginPort, a.SessionPort, b.LoginPort, b.SessionPort];
                try
                {
                    Assert(ports.Distinct().Count() == 4 && ports.All(p => p >= 1024), "per-client loopback ports collide");
                    Assert(a.BoundAddress.Equals(IPAddress.Loopback) && b.BoundAddress.Equals(IPAddress.Loopback), "public listener created");
                    await a.ValidateEndpoints(CancellationToken.None); await b.ValidateEndpoints(CancellationToken.None);
                    a.Start(); b.Start();
                    byte[] dummy = Encoding.ASCII.GetBytes("synthetic-native-credential-fixture");
                    await Task.WhenAll(ports.Select(port => Echo(port, dummy)));
                    Assert(login.Payloads.Count == 2 && session.Payloads.Count == 2, "both channels not protected for both clients");
                    Assert(login.Prefaces.Any(p => p.SequenceEqual(TlsBridge.LoginPreface(a.SessionPort))) &&
                        login.Prefaces.Any(p => p.SequenceEqual(TlsBridge.LoginPreface(b.SessionPort))), "wrong advertised second port");
                    Assert(login.Protocols.Concat(session.Protocols).All(p => p is SslProtocols.Tls12 or SslProtocols.Tls13), "weak TLS accepted");
                    results.Add("PASS: two simultaneous clients, four exclusive loopback ports, genuine TLS for both channels, unchanged server-first challenges and payloads");
                    results.Add("PASS: exact TIOT v1 login preface advertises each owned session port; mode1 has no preface");
                    results.Add("PASS: TCP destination differs from TLS hostname; certificate name validation and SNI retain the original domain");
                }
                finally { await a.DisposeAsync(); await b.DisposeAsync(); }
                foreach (int port in ports)
                {
                    var released = new TcpListener(IPAddress.Loopback, port); released.Server.ExclusiveAddressUse = true;
                    released.Start(); released.Stop();
                }
                results.Add("PASS: bridge shutdown releases all listeners and active channels");
            }
            await using (var login = new Server(valid, true))
            await using (var session = new Server(valid, false))
            await using (var bridge = new TlsBridge(new("localhost", login.Port, session.Port, "127.0.0.1"), Trust(root)))
            {
                bridge.Start();
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                using var sessionNative = new TcpClient();
                await sessionNative.ConnectAsync(IPAddress.Loopback, bridge.SessionPort, timeout.Token);
                byte[] challenge = new byte[3]; await sessionNative.GetStream().ReadExactlyAsync(challenge, timeout.Token);
                Assert(challenge.SequenceEqual(new byte[] { 0x31, 0x41, 0x59 }), "mode1 challenge changed");
                using var loginNative = new TcpClient();
                await loginNative.ConnectAsync(IPAddress.Loopback, bridge.LoginPort, timeout.Token);
                await loginNative.GetStream().ReadExactlyAsync(challenge, timeout.Token);
                loginNative.Client.LingerState = new LingerOption(true, 0); loginNative.Close();
                await Task.Delay(100, timeout.Token);
                Assert(!bridge.Failure.IsCompleted, "normal mode0 native RST terminated the bridge");
                byte[] payload = Encoding.ASCII.GetBytes("mode1-survives-login-reset");
                await sessionNative.GetStream().WriteAsync(payload, timeout.Token);
                byte[] echo = new byte[payload.Length]; await sessionNative.GetStream().ReadExactlyAsync(echo, timeout.Token);
                Assert(echo.SequenceEqual(payload), "mode1 was lost after mode0 reset");
                await Echo(bridge.LoginPort, Encoding.ASCII.GetBytes("relogin-after-reset"));
                Assert(!bridge.Failure.IsCompleted, "bridge no longer accepts reconnect after native RST");
                results.Add("PASS: native mode0 RST closes only that channel; simultaneous authenticated mode1 and subsequent login remain usable");
            }
            await using (var login = new Server(valid, true))
            await using (var session = new Server(valid, false))
            await using (var bridge = new TlsBridge(new("localhost", login.Port, session.Port)))
            {
                bridge.Start();
                using var local = new TcpClient(); await local.ConnectAsync(IPAddress.Loopback, bridge.LoginPort);
                await local.GetStream().WriteAsync(Encoding.ASCII.GetBytes("synthetic-password-must-not-leave-localhost"));
                var error = await bridge.Failure.WaitAsync(TimeSpan.FromSeconds(10));
                Assert(error is AuthenticationException && login.Prefaces.IsEmpty && login.Payloads.IsEmpty, "invalid relay forwarded credentials");
                results.Add("PASS: invalid certificate during live relay closes channel without forwarding buffered native credentials or falling back");
            }
            File.WriteAllLines(output, results);
        }
        catch (Exception error) { File.WriteAllText(output, string.Join("\n", results) + "\nFAIL: " + error); Environment.ExitCode = 1; }
    }
}
