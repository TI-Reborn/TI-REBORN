using System.Security.Cryptography;
namespace TioLauncher;
// Only these two complete immutable images are equivalent for existing hooks.
// The newer image differs solely in the password constructor's 16 -> 64 byte.
internal static class NativePasswordLimit
{
 internal const string OriginalSha256="717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625";
 internal const string UpdatedSha256="7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96";
 internal static string CompatibilityHash(byte[] image)
 {
  string hash=Convert.ToHexStringLower(SHA256.HashData(image));
  return hash==UpdatedSha256?OriginalSha256:hash;
 }
 internal static void Test(string image,string output)
 {
  byte[] raw=File.ReadAllBytes(image);
  if(raw.Length!=8167936 || Convert.ToHexStringLower(SHA256.HashData(raw))!=UpdatedSha256 || !raw.AsSpan(0x47e1b8,7).SequenceEqual(Convert.FromHexString("c6838002000040")))throw new InvalidDataException("Unrecognized password64 image");
  byte[] restored=(byte[])raw.Clone();restored[0x47e1be]=16;
  if(Convert.ToHexStringLower(SHA256.HashData(restored))!=OriginalSha256)throw new InvalidDataException("Unrelated client bytes changed");
  if(CompatibilityHash(raw)!=OriginalSha256 || CompatibilityHash(restored)!=OriginalSha256)throw new InvalidDataException("Adapter parity failed");
  restored[0]^=1;if(CompatibilityHash(restored)==OriginalSha256)throw new InvalidDataException("Unknown variant accepted");
  File.WriteAllText(output,"PASS: full SHA256, PE constructor limit64, exact one-byte diff, adapter parity and unknown-image rejection");
 }
}
