param(
  [Parameter(Mandatory=$true)][string]$Packages,
  [Parameter(Mandatory=$true)][ValidateSet('x64','arm64')][string]$Architecture,
  [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
$identity = 'org.example.MsixProbe'
$desktopIdentity = 'org.example.DesktopMsix'
$signed = Join-Path $Packages 'msix_signed_probe.msix'
$unsigned = Join-Path $Packages 'msix_probe.msix'
$changed = Join-Path $Packages 'msix_signed_probe.tampered.msix'
$certificateFile = Join-Path $Packages 'msix_signed_probe.cer'
$reader = Join-Path $Packages 'msix_reader.exe'
function Assert-Trust([string]$Path, [string]$Expected) {
  & $reader --signature $Path $Expected
  if ($LASTEXITCODE -ne 0) { throw 'MSIX native trust check failed' }
}
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certificateFile)
$certificatePath = 'Cert:\LocalMachine\TrustedPeople\' + $certificate.Thumbprint
if (Test-Path -LiteralPath $certificatePath) { throw 'MSIX fixture certificate already trusted' }
if (Get-AppxPackage -Name $identity) { throw 'MSIX fixture package already installed' }
if (Get-AppxPackage -Name $desktopIdentity) { throw 'MSIX desktop package already installed' }
Assert-Trust $unsigned 'unsigned'
Assert-Trust $signed 'untrusted'
$untrusted = Get-AuthenticodeSignature -LiteralPath $signed
if ($untrusted.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) { throw 'MSIX signer certificate mismatch' }
Write-Output 'MSIX_UNTRUSTED_CERTIFICATE_REJECTED'
$trusted = $false
try {
  Import-Certificate -FilePath $certificateFile -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
  $trusted = $true
  Assert-Trust $signed 'valid'
  $verified = Get-AuthenticodeSignature -LiteralPath $signed
  if ($verified.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) { throw 'MSIX trusted signer certificate mismatch' }
  Write-Output 'MSIX_WINDOWS_SIGNATURE_OK'
  Assert-Trust $changed 'tampered'
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
  $family = $null
  foreach ($release in @(@{Suffix='v1'; Version='1.0.0'}, @{Suffix='v2'; Version='2.0.0'})) {
    $desktop = Join-Path $Packages ('msix_signed_desktop_' + $release.Suffix + '.msix')
    Assert-Trust $desktop 'valid'
    Add-AppxPackage -Path $desktop -ForceApplicationShutdown
    $package = Get-AppxPackage -Name $desktopIdentity
    if (-not $package -or $package.Version.ToString() -ne ($release.Version + '.7') -or
        $package.Publisher -ne 'CN=Example' -or $package.Architecture.ToString() -ine $Architecture) {
      throw 'MSIX desktop package identity mismatch'
    }
    if ($family -and $family -ne $package.PackageFamilyName) { throw 'MSIX upgrade changed package family' }
    $family = $package.PackageFamilyName
    & $reader --handlers $family present
    if ($LASTEXITCODE -ne 0) { throw 'MSIX installed handlers missing' }
    $executable = Join-Path $package.InstallLocation 'sample-desktop.exe'
    & $Python 'examples/desktop/tools/smoke_test.py' $executable --installed --msix --target-os windows --target-arch $Architecture --expected-version $release.Version
    if ($LASTEXITCODE -ne 0) { throw 'MSIX installed Electron smoke failed' }
    Write-Output ('MSIX_DESKTOP_VERSION_OK ' + $release.Version)
  }
  Remove-AppxPackage -Package $package.PackageFullName
  if (Get-AppxPackage -Name $desktopIdentity) { throw 'MSIX desktop uninstall left package registration' }
  & $reader --handlers $family absent
  if ($LASTEXITCODE -ne 0) { throw 'MSIX uninstall left handlers registered' }
  Write-Output 'MSIX_DESKTOP_INSTALL_UPDATE_REMOVE_OK'
} finally {
  try {
    foreach ($name in @($identity, $desktopIdentity)) {
      $remaining = Get-AppxPackage -Name $name
      if ($remaining) { Remove-AppxPackage -Package $remaining.PackageFullName }
    }
  } finally {
    if ($trusted) { Remove-Item -LiteralPath $certificatePath }
    $certificate.Dispose()
  }
}
if (Test-Path -LiteralPath $certificatePath) { throw 'MSIX test certificate cleanup failed' }
Write-Output 'MSIX_TEST_CERTIFICATE_REMOVED'
