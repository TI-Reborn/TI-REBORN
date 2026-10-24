# Run under SysWOW64 Windows PowerShell (32 bit). Loads only the local DLL.
param([string]$OutputDirectory = 'C:\TIO-emulator\evidence')
$ErrorActionPreference = 'Stop'
if ([IntPtr]::Size -ne 4) { throw 'Use 32-bit PowerShell.' }
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OrangeImage {
  [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr LoadLibraryW(string path);
  [DllImport("kernel32", CharSet=CharSet.Ansi)]
  public static extern IntPtr GetProcAddress(IntPtr module, string name);
}
'@
$module = [OrangeImage]::LoadLibraryW('C:\Program Files (x86)\TIOnline\orange.dll')
if ($module -eq [IntPtr]::Zero) { throw "LoadLibrary failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }
$peOffset = [Runtime.InteropServices.Marshal]::ReadInt32($module, 0x3c)
$size = [Runtime.InteropServices.Marshal]::ReadInt32($module, $peOffset + 0x50)
$bytes = New-Object byte[] $size
[Runtime.InteropServices.Marshal]::Copy($module, $bytes, 0, $size)
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
[IO.File]::WriteAllBytes((Join-Path $OutputDirectory 'orange.mapped.bin'), $bytes)
$exports = @{}
foreach ($name in @('AAaAA','AAaAa','AAaaa','AaaAa','aAAAa','aAaAa','aAaaA','aaAaA','aaAaa','aaaAa','aaaaa')) {
  $exports[$name] = ('0x{0:x8}' -f [OrangeImage]::GetProcAddress($module, $name).ToInt32())
}
@{ base = ('0x{0:x8}' -f $module.ToInt32()); size = $size; exports = $exports } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $OutputDirectory 'orange.mapped.json')
Write-Output "Mapped orange.dll: $size bytes"
