using System.Security.Cryptography;
namespace TioLauncher;
// Exact immutable images share the existing hooks. The tooltip variant adds
// one presentation call and a section extension; existing hook spans remain.
internal static class NativePasswordLimit
{
 internal const string OriginalSha256="717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625";
 internal const string UpdatedSha256="7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96";
 internal const string TooltipSha256="28f33ff6a920182eeb7a81b9d3c30853081f3f52c7d505da15b54de97c01b2ad";
 // Barracks A2 appends a region and redirects presentation calls only; no
 // adapter site differs from the tooltip image (deploy/client_barracks_a2.py).
 internal const string BarracksSha256="9df0325aa332b332a85c0fae5f67674509b0fe76f34a0a0ad6030c4b91f4fd76";
 internal const string InterfaceModeSha256="8ec07dd8c2bdc80e05cb883f83dc1a1b01735dbc5d121ce9c144b962101aa7f2";
 internal const string WarehouseSha256="5c87d334ad3e7e8018339243132b65525030487188bd1c9d8535a4638d11b408";
 internal const string ItemCellsSha256="23367d6cb1021aec9de4f2ec8f9b159ea5931dc8fdbb61d265e2176f8fccb207";
 internal static string CompatibilityHash(byte[] image)
 {
  string hash=Convert.ToHexStringLower(SHA256.HashData(image));
  return hash is UpdatedSha256 or TooltipSha256 or BarracksSha256 or InterfaceModeSha256 or WarehouseSha256 or ItemCellsSha256 ? OriginalSha256 : hash;
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
