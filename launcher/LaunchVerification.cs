using System.Buffers.Binary;

namespace TioLauncher;

// Created only after a fresh HTTPS check and successful verification of this
// installation. It is carried on both TLS routes, before native credentials.
internal sealed class LaunchVerification
{
    readonly byte[] identity;
    LaunchVerification(string manifest, string version)
    {
        identity = new byte[38];
        Convert.FromHexString(manifest).CopyTo(identity, 0);
        Version v = LauncherUpdate.ParseVersion(version);
        BinaryPrimitives.WriteUInt16BigEndian(identity.AsSpan(32), checked((ushort)v.Major));
        BinaryPrimitives.WriteUInt16BigEndian(identity.AsSpan(34), checked((ushort)v.Minor));
        BinaryPrimitives.WriteUInt16BigEndian(identity.AsSpan(36), checked((ushort)v.Build));
    }
    internal byte[] Preface(int port, string language)
    {
        byte[] header = TlsBridge.LoginPreface(port);
        header[4] = 2; header[5] = language == "english" ? (byte)1 : (byte)0;
        return header.Concat(identity).ToArray();
    }
    internal static async Task<LaunchVerification> Verify(string root, CancellationToken token,
        HttpMessageHandler? launcherHandler = null, HttpMessageHandler? clientHandler = null, string? version = null, bool ownedQa = false)
    {
        version ??= LauncherUpdate.CurrentVersion;
        using var launcher = new LauncherUpdate(launcherHandler);
        var current = await launcher.Fetch(token);
        if (current.Version != version)
            throw new InvalidDataException(L.Text("Версия лаунчера изменилась. Откройте лаунчер заново и установите обновление."));
        using var updater = new Updater(root, clientHandler ?? (SteamDistribution.Enabled ? SteamDistribution.ContentHandler() : null));
        var release = await updater.Fetch(token);
        if(ownedQa && Updater.GameRunning())await updater.VerifyOwnedQa(release,token);
        else await updater.Apply(release, new Progress<UpdateProgress>(), token);
        return new LaunchVerification(updater.ManifestSha256 ?? throw new InvalidDataException("Missing verified manifest"), version);
    }
}
