namespace TioLauncher;
internal static class NativeLaunchGate
{
    internal const string ImageSha256 = "d2c2343f89ed253695fff615fd504b80585b8c7fbbfed139b28e1bbe5fe0dfa0";
    internal const uint GuardRva = 0x40c200;
    internal static void Release(IntPtr process, uint imageBase, GameLaunchProfile? profile)
    {
        if (profile?.Verification is null) throw new InvalidDataException("Запускайте игру через TIO Launcher с проверкой обновлений.");
        byte[] jump = new byte[5]; jump[0] = 0xe9;
        BitConverter.GetBytes(unchecked((int)(0x358f6c - GuardRva - 5))).CopyTo(jump, 1);
        NativeTlsRoute.GuardedPatch(process, imageBase + GuardRva, Convert.FromHexString("e800000000"), jump);
    }
}
