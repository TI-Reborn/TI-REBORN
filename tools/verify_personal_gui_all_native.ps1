param([string]$ListPath,[string]$ReportPath)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'LegacyDegrainTextureNative.cs')
$results = [LegacyDegrainTextureNative]::Verify($ListPath, 'C:\Program Files (x86)\TIOnline')
if ($results.Count % 2 -ne 0) { throw 'Baseline/candidate pairs required.' }
$pairs = @()
$conversions = @()
for ($pairIndex = 0; $pairIndex -lt $results.Count; $pairIndex += 2) {
    $before = $results[$pairIndex]
    $after = $results[$pairIndex + 1]
    foreach ($field in @('Width','Height','TextureWidth','TextureHeight','TextureLevels','Device','Codec')) {
        if ($before.$field -ne $after.$field) { throw ('Native geometry/codec changed: {0} {1}' -f $after.Path,$field) }
    }
    if ($before.ImageFormat -ne $after.ImageFormat -or $before.TextureFormat -ne $after.TextureFormat) {
        if ($after.ImageFormat -ne 21 -or $after.TextureFormat -ne 21) { throw 'Unexpected native format conversion' }
        $conversions += [ordered]@{path=$after.Path;before=$before.ImageFormat;after=$after.ImageFormat}
    }
    $pairs += [ordered]@{before=$before;after=$after;geometry_and_mip_levels_equal=$true}
}
[ordered]@{passed=$true;pairs=$pairs.Count;format_conversions=$conversions;results=$pairs} |
    ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output ('Native D3DX9 texture creation: {0} pairs PASS; {1} supported RGBA conversions' -f $pairs.Count,$conversions.Count)
