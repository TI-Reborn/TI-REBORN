# Nonproduction fixtures only. Requires PowerShell 7 / .NET 10.
# Generated private keys are intentionally public test data, never service keys.
$ErrorActionPreference = 'Stop'
function New-FixtureRequest([string]$name,[System.Security.Cryptography.RSA]$key,[bool]$ca) {
    $request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new("CN=TIO TEST ONLY $name",$key,[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($ca,$false,0,$true))
    $usage = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature
    if ($ca) { $usage = $usage -bor [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign }
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new($usage,$true))
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($request.PublicKey,$false))
    return $request
}
$fixtureDirectory = $PSScriptRoot
$start = [System.DateTimeOffset]::new(2020,1,1,0,0,0,[System.TimeSpan]::Zero)
$end = [System.DateTimeOffset]::new(2045,1,1,0,0,0,[System.TimeSpan]::Zero)
$caKey = [System.Security.Cryptography.RSA]::Create(2048)
$caRequest = New-FixtureRequest 'CA' $caKey $true
$ca = $caRequest.CreateSelfSigned($start,$end)
[System.IO.File]::WriteAllText((Join-Path $fixtureDirectory 'ca.pem'),$ca.ExportCertificatePem())
$intermediateKey = [System.Security.Cryptography.RSA]::Create(2048)
$intermediateRequest = New-FixtureRequest 'Intermediate' $intermediateKey $true
$intermediateRequest.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509AuthorityKeyIdentifierExtension]::CreateFromCertificate($ca,$true,$false))
$intermediate = $intermediateRequest.Create($ca,$start,$end,[System.Security.Cryptography.RandomNumberGenerator]::GetBytes(20))
$intermediate = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey($intermediate,$intermediateKey)
[System.IO.File]::WriteAllText((Join-Path $fixtureDirectory 'intermediate.pem'),$intermediate.ExportCertificatePem())
foreach ($variant in @('valid','rotated','wrongsan','expired')) {
    $key = [System.Security.Cryptography.RSA]::Create(2048)
    $request = New-FixtureRequest $variant $key $false
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509AuthorityKeyIdentifierExtension]::CreateFromCertificate($intermediate,$true,$false))
    $san = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    if ($variant -eq 'wrongsan') { $san.AddDnsName('wrong.invalid'); $san.AddIpAddress([System.Net.IPAddress]::Parse('192.0.2.1')) }
    else { $san.AddDnsName('localhost');$san.AddIpAddress([System.Net.IPAddress]::Parse('127.0.0.1')) }
    $request.CertificateExtensions.Add($san.Build())
    $eku = [System.Security.Cryptography.OidCollection]::new()
    $eku.Add([System.Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1')) | Out-Null
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($eku,$true))
    $leafEnd = if ($variant -eq 'expired') { [System.DateTimeOffset]::new(2022,1,1,0,0,0,[System.TimeSpan]::Zero) } else { $end }
    $leaf = $request.Create($intermediate,$start,$leafEnd,[System.Security.Cryptography.RandomNumberGenerator]::GetBytes(20))
    [System.IO.File]::WriteAllText((Join-Path $fixtureDirectory "$variant.pem"),$leaf.ExportCertificatePem())
    [System.IO.File]::WriteAllText((Join-Path $fixtureDirectory "$variant-chain.pem"),($leaf.ExportCertificatePem()+"`n"+$intermediate.ExportCertificatePem()))
    [System.IO.File]::WriteAllText((Join-Path $fixtureDirectory "$variant-key.pem"),$key.ExportPkcs8PrivateKeyPem())
    $key.Dispose()
}
$caKey.Dispose();$intermediateKey.Dispose()
Write-Output 'Generated nonproduction TLS fixtures'
