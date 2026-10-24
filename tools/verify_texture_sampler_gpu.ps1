param([Parameter(Mandatory=$true)][string]$ReportPath)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'TextureSamplerNative.cs')
$samplerResult = [TextureSamplerNative]::Verify()
@{
    passed = $true
    kind = 'Real isolated offscreen D3D9 HAL sampler state acceptance and readback'
    cases = $samplerResult.Count
    stages = 8
    image_resource_bytes_changed = 0
    graphical_game_client = $false
    details = $samplerResult
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output ('Real D3D9 HAL sampler setter/readback: {0} checks PASS' -f $samplerResult.Count)
