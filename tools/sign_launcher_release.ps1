[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $InputExecutable,
    [Parameter(Mandatory = $true)] [string] $OutputExecutable,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string] $CertificateThumbprint,
    [string] $SignToolPath,
    [string] $TimestampUrl = 'http://timestamp.digicert.com',
    [ValidateSet('CurrentUser', 'LocalMachine')] [string] $CertificateStore = 'CurrentUser',
    [string] $AuditReport
)

$ErrorActionPreference = 'Stop'
$thumbprint = $CertificateThumbprint.Replace(' ', '').ToUpperInvariant()

function Resolve-SignTool {
    param([string] $RequestedPath)
    if ($RequestedPath) {
        $resolved = (Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path
        if ((Split-Path -Leaf $resolved) -ine 'signtool.exe') { throw 'SignToolPath must point to signtool.exe.' }
        return $resolved
    }
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $candidate = Get-ChildItem -LiteralPath $kits -Filter signtool.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
    throw 'Windows SDK SignTool was not found. Install the Windows 10/11 SDK or pass -SignToolPath.'
}

$sourcePath = (Resolve-Path -LiteralPath $InputExecutable -ErrorAction Stop).Path
$source = Get-Item -LiteralPath $sourcePath
if ($source.PSIsContainer) { throw 'InputExecutable must be a file.' }
$destinationPath = [IO.Path]::GetFullPath($OutputExecutable)
if ([StringComparer]::OrdinalIgnoreCase.Equals($sourcePath, $destinationPath)) {
    throw 'InputExecutable and OutputExecutable must be different files.'
}
if (Test-Path -LiteralPath $destinationPath) { throw 'Refusing to overwrite an existing output file.' }
$reportPath = $null
if ($AuditReport) {
    $reportPath = [IO.Path]::GetFullPath($AuditReport)
    if (Test-Path -LiteralPath $reportPath) { throw 'Refusing to overwrite an existing audit report.' }
    $reportDirectory = Split-Path -Parent $reportPath
    if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
        throw 'AuditReport parent directory must already exist.'
    }
}
$destinationDirectory = Split-Path -Parent $destinationPath
if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
    throw 'OutputExecutable parent directory must already exist.'
}

$storePath = "Cert:\$CertificateStore\My\$thumbprint"
$certificate = Get-Item -LiteralPath $storePath -ErrorAction SilentlyContinue
if (-not $certificate) { throw "Code Signing certificate $thumbprint was not found in $CertificateStore\My." }
if (-not $certificate.HasPrivateKey) { throw 'The selected certificate has no private key available for signing.' }
if ($certificate.NotBefore -gt (Get-Date) -or $certificate.NotAfter -le (Get-Date)) {
    throw 'The selected certificate is not currently valid.'
}
$codeSigningEku = $false
foreach ($extension in $certificate.Extensions) {
    if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
        foreach ($usage in $extension.EnhancedKeyUsages) {
            if ($usage.Value -eq '1.3.6.1.5.5.7.3.3') { $codeSigningEku = $true }
        }
    }
}
if (-not $codeSigningEku) { throw 'The selected certificate does not permit Code Signing.' }
if ($certificate.Subject -eq $certificate.Issuer) { throw 'A self-signed certificate cannot establish a public publisher identity.' }

$chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
$chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::Online
$chain.ChainPolicy.RevocationFlag = [Security.Cryptography.X509Certificates.X509RevocationFlag]::ExcludeRoot
$chain.ChainPolicy.VerificationFlags = [Security.Cryptography.X509Certificates.X509VerificationFlags]::NoFlag
$chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(20)
$chainValid = $chain.Build($certificate)
if (-not $chainValid) {
    $status = ($chain.ChainStatus | ForEach-Object { $_.Status.ToString() + ': ' + $_.StatusInformation.Trim() }) -join '; '
    throw "The Code Signing certificate chain could not be trusted and checked online: $status"
}

$signTool = Resolve-SignTool -RequestedPath $SignToolPath
$stagingPath = Join-Path $destinationDirectory ('.' + [IO.Path]::GetFileName($destinationPath) + '.' + [guid]::NewGuid().ToString('N') + '.signing.tmp')
try {
    [IO.File]::Copy($sourcePath, $stagingPath, $false)
    $signArguments = @('sign', '/sha1', $thumbprint, '/fd', 'SHA256', '/tr', $TimestampUrl, '/td', 'SHA256')
    if ($CertificateStore -eq 'LocalMachine') { $signArguments += '/sm' }
    $signArguments += $stagingPath
    & $signTool @signArguments
    if ($LASTEXITCODE -ne 0) { throw "SignTool signing failed (exit $LASTEXITCODE)." }
    & $signTool verify /pa /all /tw $stagingPath
    if ($LASTEXITCODE -ne 0) { throw "SignTool Authenticode/timestamp verification failed (exit $LASTEXITCODE)." }

    $signature = Get-AuthenticodeSignature -LiteralPath $stagingPath
    if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or
        $signature.SignerCertificate.Thumbprint -ne $thumbprint -or
        -not $signature.TimeStamperCertificate) {
        throw 'The signed file does not have the expected valid publisher and timestamp.'
    }
    if (Test-Path -LiteralPath $destinationPath) { throw 'Output appeared during signing; refusing to overwrite it.' }
    [IO.File]::Move($stagingPath, $destinationPath)
    $file = Get-Item -LiteralPath $destinationPath
    $report = [ordered]@{
        output = $destinationPath
        version = $file.VersionInfo.FileVersion
        bytes = $file.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destinationPath).Hash.ToLowerInvariant()
        signature = $signature.Status.ToString()
        publisher = $signature.SignerCertificate.Subject
        publisherThumbprint = $signature.SignerCertificate.Thumbprint
        timestampAuthority = $signature.TimeStamperCertificate.Subject
        signedUtc = (Get-Date).ToUniversalTime().ToString('o')
    }
    if ($reportPath) {
        $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding utf8
    }
    $report | ConvertTo-Json -Depth 4
}
finally {
    if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Force }
}
