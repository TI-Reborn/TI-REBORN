"""Generate disposable loopback TLS credentials; never store keys in the repo."""
from pathlib import Path
import os
import shutil
import subprocess


def create(root):
    root=Path(root)
    cert=root/'valid-chain.pem';key=root/'valid-key.pem'
    openssl=shutil.which('openssl')
    if openssl:
        subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes',
            '-keyout',str(key),'-out',str(cert),'-days','2','-subj','/CN=TIO TEST ONLY',
            '-addext','subjectAltName=IP:127.0.0.1','-addext','basicConstraints=critical,CA:TRUE'],
            check=True,capture_output=True,timeout=30)
    elif os.name=='nt' and shutil.which('pwsh'):
        script=r'''
$ErrorActionPreference='Stop'
$rsa=[System.Security.Cryptography.RSA]::Create(2048)
try {
  $req=[System.Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=TIO TEST ONLY',$rsa,[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
  $req.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true,$false,0,$true))
  $san=[System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
  $san.AddIpAddress([System.Net.IPAddress]::Loopback)
  $req.CertificateExtensions.Add($san.Build())
  $cert=$req.CreateSelfSigned([DateTimeOffset]::UtcNow.AddDays(-1),[DateTimeOffset]::UtcNow.AddDays(2))
  [IO.File]::WriteAllText((Join-Path $env:TIO_TEST_TLS_DIR 'valid-chain.pem'),$cert.ExportCertificatePem())
  [IO.File]::WriteAllText((Join-Path $env:TIO_TEST_TLS_DIR 'valid-key.pem'),$rsa.ExportPkcs8PrivateKeyPem())
} finally { $rsa.Dispose() }
'''
        subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',script],
            env={**os.environ,'TIO_TEST_TLS_DIR':str(root)},check=True,capture_output=True,timeout=30)
    else:
        raise RuntimeError('TLS integration test requires OpenSSL or PowerShell 7')
    shutil.copyfile(cert,root/'ca.pem')
    return root
