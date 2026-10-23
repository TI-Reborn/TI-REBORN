param([string]$ListPath,[string]$ReportPath)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'LegacyDegrainTextureNative.cs')
$results = [LegacyDegrainTextureNative]::Verify($ListPath, 'C:\Program Files (x86)\TIOnline')
if ($results.Count % 2 -ne 0) { throw 'Baseline/candidate pairs required.' }
$pairs = @()
for ($pairIndex = 0; $pairIndex -lt $results.Count; $pairIndex += 2) {
    $before = $results[$pairIndex]
    $after = $results[$pairIndex + 1]
    foreach ($field in @('Width','Height','TextureWidth','TextureHeight','TextureLevels','ImageFormat','TextureFormat','Device','Codec')) {
        if ($before.$field -ne $after.$field) { throw ('Native baseline invariant changed: {0} {1}' -f $after.Path,$field) }
    }
    $pairs += [ordered]@{ before = $before; after = $after; invariants_equal = $true }
}
$report = [ordered]@{ passed = $true; pair_count = $pairs.Count; scope = 'Original x86 D3DX9 decoder and offscreen device; compare baseline image/texture dimensions, formats, mip count and codec'; pairs = $pairs }
$report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output ('Native D3DX9 baseline/candidate invariants: {0} pairs PASS' -f $pairs.Count)
