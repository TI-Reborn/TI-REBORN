param([string]$ListPath,[string]$ReportPath)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'EquipmentTextureNative.cs')
$result = [EquipmentTextureNative]::Verify($ListPath, 'C:\Program Files (x86)\TIOnline')
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output ('Original x86 D3DX9 decoder and offscreen texture creation: {0} resources PASS' -f $result.Count)
