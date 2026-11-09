param(
  [Parameter(Mandatory=$true)][string]$Packages,
  [Parameter(Mandatory=$true)][ValidateSet('x64','arm64')][string]$Architecture
)
$ErrorActionPreference = 'Stop'
$identity = 'org.example.MsixProbe'
$signed = Join-Path $Packages 'msix_signed_probe.msix'
$unsigned = Join-Path $Packages 'msix_probe.msix'
$changed = Join-Path $Packages 'msix_signed_probe.tampered.msix'
$certificateFile = Join-Path $Packages 'msix_signed_probe.cer'
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certificateFile)
$certificatePath = 'Cert:\LocalMachine\TrustedPeople\' + $certificate.Thumbprint
if (Test-Path -LiteralPath $certificatePath) { throw 'MSIX fixture certificate already trusted' }
if (Get-AppxPackage -Name $identity) { throw 'MSIX fixture package already installed' }
if ((Get-AuthenticodeSignature -LiteralPath $unsigned).Status -ne 'NotSigned') {
  throw 'MSIX unsigned package status unexpected'
}
$untrusted = Get-AuthenticodeSignature -LiteralPath $signed
if ($untrusted.Status -ne 'NotTrusted') { throw ('MSIX untrusted signature status: ' + $untrusted.Status) }
if ($untrusted.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) { throw 'MSIX signer certificate mismatch' }
Write-Output 'MSIX_UNTRUSTED_CERTIFICATE_REJECTED'
$trusted = $false
try {
  Import-Certificate -FilePath $certificateFile -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
  $trusted = $true
  $verified = Get-AuthenticodeSignature -LiteralPath $signed
  if ($verified.Status -ne 'Valid' -or $verified.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
    throw ('MSIX trusted signature status: ' + $verified.Status)
  }
  Write-Output 'MSIX_WINDOWS_SIGNATURE_OK'
  $tampered = Get-AuthenticodeSignature -LiteralPath $changed
  if ($tampered.Status -ne 'HashMismatch') { throw ('MSIX tamper status: ' + $tampered.Status) }
  Write-Output 'MSIX_WINDOWS_SIGNATURE_TAMPER_REJECTED'
  Add-AppxPackage -Path $signed
  $package = Get-AppxPackage -Name $identity
  if (-not $package -or $package.Version.ToString() -ne '1.0.0.7' -or
      $package.Publisher -ne 'CN=Example' -or $package.Architecture.ToString() -ine $Architecture) {
    throw 'MSIX installed package identity mismatch'
  }
  $helper = Join-Path $package.InstallLocation 'helper.exe'
  $output = & $helper
  if ($LASTEXITCODE -ne 0 -or ($output | ConvertFrom-Json).message -ne 'native helper ready') {
    throw 'MSIX installed native helper failed'
  }
  Write-Output 'MSIX_INSTALLED_NATIVE_HELPER_OK'
  Remove-AppxPackage -Package $package.PackageFullName
  if (Get-AppxPackage -Name $identity) { throw 'MSIX uninstall left package registration' }
  Write-Output 'MSIX_INSTALL_REMOVE_OK'
} finally {
  try {
    $remaining = Get-AppxPackage -Name $identity
    if ($remaining) { Remove-AppxPackage -Package $remaining.PackageFullName }
  } finally {
    if ($trusted) { Remove-Item -LiteralPath $certificatePath }
    $certificate.Dispose()
  }
}
if (Test-Path -LiteralPath $certificatePath) { throw 'MSIX test certificate cleanup failed' }
Write-Output 'MSIX_TEST_CERTIFICATE_REMOVED'
