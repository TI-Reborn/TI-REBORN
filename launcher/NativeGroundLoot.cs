namespace TioLauncher;

// The native backpack strip is in world pixels; Silver's GUI mouse is scaled.
internal static class NativeGroundLoot
{
    internal static readonly uint[] Sites = [0x55d54e, 0x55d55c];
    internal static byte[] LoadMouse(uint pointer) => [0x8b, 0x15, .. BitConverter.GetBytes(pointer)];

    internal static void Apply(IntPtr process, uint silver)
    {
        foreach (uint site in Sites)
            NativeTlsRoute.GuardedPatch(process, checked(silver + site),
                LoadMouse(checked(silver + 0x6c5a04)), LoadMouse(0x76e440));
    }
}
