$ErrorActionPreference = 'Stop'
try {
    $target = Join-Path $PSScriptRoot 'silver.dll'
    $originalHash = 'a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11'
    $patchedHash = '6cb78fd9e71afa92d301a46ac7601e8280942dc97215d9826873fb83bb0fbe27'
    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -eq $patchedHash) { Write-Host 'Russian text fix is already installed.'; exit 0 }
    if ($hash -ne $originalHash) { throw 'Unknown silver.dll version. No files changed.' }
    if (Get-Process ti -ErrorAction SilentlyContinue) { throw 'Close the game first, then run this fix again.' }
    $backup = Join-Path $PSScriptRoot ('silver.before-russian-' + [guid]::NewGuid().ToString('N') + '.bak')
    Copy-Item -LiteralPath $target -Destination $backup
    $data = [IO.File]::ReadAllBytes($target)
    $replacement = [byte[]](0xb8,0xe3,0x04,0x00,0x00)
    [Array]::Copy($replacement,0,$data,0x6b4a90,5)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $computed = [BitConverter]::ToString($sha.ComputeHash($data)).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
    if ($computed -ne $patchedHash) { throw 'Checksum mismatch. Original file retained.' }
    try {
        [IO.File]::WriteAllBytes($target,$data)
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $patchedHash) { throw 'Written file checksum mismatch.' }
    } catch {
        Copy-Item -LiteralPath $backup -Destination $target -Force
        throw
    }
    Write-Host 'Russian text fix installed. Start Launcher.cmd.'
    Write-Host "Original file saved: $backup"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
