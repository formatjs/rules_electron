param(
  [Parameter(Mandatory=$true)][string]$Packages,
  [Parameter(Mandatory=$true)][ValidateSet('x64','arm64')][string]$Architecture,
  [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
$identity = 'org.example.MsixProbe'
$desktopIdentity = 'org.example.DesktopMsix'
$appinstallerIdentity = 'org.example.DesktopAppInstaller'
$signed = Join-Path $Packages 'msix_signed_probe.msix'
$unsigned = Join-Path $Packages 'msix_probe.msix'
$changed = Join-Path $Packages 'msix_signed_probe.tampered.msix'
$certificateFile = Join-Path $Packages 'msix_signed_probe.cer'
$reader = Join-Path $Packages 'msix_reader.exe'
function Assert-Trust([string]$Path, [string]$Expected) {
  & $reader --signature $Path $Expected
  if ($LASTEXITCODE -ne 0) { throw 'MSIX native trust check failed' }
}
function Assert-Activation([string]$Family, [string]$Version, [string]$Executable) {
  foreach ($handler in @(
      @{Kind='protocol'; Name='sample-msix'},
      @{Kind='protocol'; Name='sample-msix-alt'},
      @{Kind='file'; Name='.samplemsix'},
      @{Kind='file'; Name='.samplemsix_alt'})) {
    $nonce = [guid]::NewGuid().ToString('N')
    $directory = Join-Path ([System.IO.Path]::GetTempPath()) ('rules-electron-msix-' + $nonce)
    New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
    $marker = Join-Path ([System.IO.Path]::GetTempPath()) 'rules-electron-msix-activation.json'
    $markerCreated = $false
    try {
      $content = 'MSIX activation document ' + [char]0x4e16 + [char]0x754c
      if ($handler.Kind -eq 'protocol') {
        $value = $handler.Name + '://activation-smoke/' + $nonce
      } else {
        $value = Join-Path $directory ('activation document ' + [char]0x4e16 + [char]0x754c + $handler.Name)
        [System.IO.File]::WriteAllText($value, $content, [System.Text.UTF8Encoding]::new($false))
      }
      $request = @{nonce=$nonce; kind=$handler.Kind; value=$value} | ConvertTo-Json -Compress
      [System.IO.File]::WriteAllText((Join-Path $directory 'request.json'), $request, [System.Text.UTF8Encoding]::new($false))
      $stream = [System.IO.File]::Open($marker, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
      $markerCreated = $true
      $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
      try { $writer.Write((@{nonce=$nonce} | ConvertTo-Json -Compress)) } finally { $writer.Dispose() }
      & $reader --activate $Family $handler.Kind $value
      if ($LASTEXITCODE -ne 0) { throw 'MSIX activation API failed' }
      $reportPath = Join-Path $directory 'report.json'
      $deadline = [DateTime]::UtcNow.AddSeconds(30)
      while (-not (Test-Path -LiteralPath $reportPath)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'MSIX activation report timeout' }
        Start-Sleep -Milliseconds 100
      }
      $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($report.failure) { throw ('MSIX_ACTIVATION_ARGUMENT_DIAGNOSTICS ' + ($report | ConvertTo-Json -Compress -Depth 4)) }
      if ($report.kind -cne $handler.Kind -or $report.value -cne $value -or $report.nonce -cne $nonce -or
          $report.architecture -cne $Architecture -or $report.version -cne $Version -or
          $report.windows_store -ne $true -or $report.packaged -ne $true) {
        throw 'MSIX Electron activation report mismatch'
      }
      if ($handler.Kind -eq 'file' -and $report.content -cne $content) { throw 'MSIX file activation changed document bytes' }
      if ($handler.Kind -eq 'protocol' -and $null -ne $report.content) { throw 'MSIX protocol activation returned document content' }
      if ($report.executable -ine $Executable) { throw 'MSIX activation executable path mismatch' }
      $activated = Get-Process -Id $report.pid -ErrorAction SilentlyContinue
      if ($activated -and -not $activated.HasExited) {
        if (-not $activated.WaitForExit(30000)) { throw 'MSIX activated Electron did not exit' }
      }
      Write-Output ('MSIX_ACTIVATION_DELIVERY_OK ' + $handler.Kind + ' ' + $handler.Name + ' ' + $Version)
    } finally {
      if ($markerCreated) {
        Get-Process -Name 'sample-desktop' -ErrorAction SilentlyContinue |
          Where-Object { $_.Path -ieq $Executable } | Stop-Process -Force
        Remove-Item -LiteralPath $marker
      }
      Remove-Item -LiteralPath $directory -Recurse -Force
    }
  }
}
function Assert-DocumentIcons($Package) {
  $manifest = Get-AppxPackageManifest -Package $Package.PackageFullName
  $namespaces = [System.Xml.XmlNamespaceManager]::new($manifest.NameTable)
  $namespaces.AddNamespace('uap', 'http://schemas.microsoft.com/appx/manifest/uap/windows10')
  $namespaces.AddNamespace('uap3', 'http://schemas.microsoft.com/appx/manifest/uap/windows10/3')
  $associations = $manifest.SelectNodes('//uap3:FileTypeAssociation', $namespaces)
  if ($associations.Count -ne 2) { throw 'MSIX deployed document associations mismatch' }
  foreach ($association in $associations) {
    $extension = $association.SelectSingleNode('uap:SupportedFileTypes/uap:FileType', $namespaces).InnerText
    $logo = $association.SelectSingleNode('uap:Logo', $namespaces).InnerText
    if ($logo -cnotmatch '^Assets/FileType[a-f0-9]{16}\.png$') { throw 'MSIX deployed document logo path mismatch' }
    $slot = switch ($extension) {
      '.samplemsix' { 'Assets/Square44x44Logo.png' }
      '.samplemsix_alt' { 'Assets/Square150x150Logo.png' }
      default { throw 'MSIX unexpected document extension' }
    }
    $actual = [System.IO.File]::ReadAllBytes((Join-Path $Package.InstallLocation $logo))
    $expected = [System.IO.File]::ReadAllBytes((Join-Path $Package.InstallLocation $slot))
    if ([Convert]::ToBase64String($actual) -cne [Convert]::ToBase64String($expected)) {
      throw 'MSIX deployed document logo bytes mismatch'
    }
  }
  Write-Output 'MSIX_DOCUMENT_ICONS_OK'
}
function Assert-AppInstallerAvailability($Package, [ValidateSet('NoUpdates','Available')][string]$Expected) {
  # Load Windows' async projection; no source compilation.
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $resultType = [Windows.ApplicationModel.PackageUpdateAvailabilityResult,Windows.ApplicationModel,ContentType=WindowsRuntime]
  $methods = @([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -ceq 'AsTask' -and $_.IsGenericMethodDefinition -and
    $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -ceq 'IAsyncOperation`1'
  })
  if ($methods.Count -ne 1) { throw 'MSIX WinRT async projection unavailable' }
  $operation = $Package.CheckUpdateAvailabilityAsync()
  $conversion = $methods[0].MakeGenericMethod([Type[]]@($resultType))
  $task = $conversion.Invoke($null, [object[]]@($operation))
  if (-not $task.Wait(60000)) { $operation.Cancel(); throw 'MSIX update availability timeout' }
  $availability = $task.Result.Availability.ToString()
  if (@('Unknown','NoUpdates','Available','Required','Error') -cnotcontains $availability) {
    throw 'MSIX update availability returned unknown value'
  }
  if ($availability -cne $Expected) {
    $code = if ($task.Result.ExtendedError) { $task.Result.ExtendedError.HResult } else { 0 }
    Write-Output ('MSIX_APPINSTALLER_AVAILABILITY_MISMATCH expected=' + $Expected + ' actual=' + $availability + ' hresult=' + $code)
    throw 'MSIX update availability mismatch'
  }
  Write-Output ('MSIX_APPINSTALLER_AVAILABILITY_OK ' + $Expected)
}
function Assert-AppInstaller {
  $uri = 'http://127.0.0.1:31827/desktop.appinstaller'
  $arguments = @('-u', 'tools/ci/windows_appinstaller_server.py', '--packages', ('"' + $Packages + '"'), '--port', '31827')
  $server = Start-Process -FilePath $Python -ArgumentList $arguments -PassThru -NoNewWindow
  try {
    $ready = $false
    foreach ($attempt in 1..100) {
      if ($server.HasExited) { throw 'MSIX App Installer server exited' }
      try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:31827/ready' -UseBasicParsing -TimeoutSec 2
        if ($response.Content -ceq 'MSIX_APPINSTALLER_READY') { $ready = $true; break }
      } catch { Start-Sleep -Milliseconds 100 }
    }
    if (-not $ready) { throw 'MSIX App Installer server startup timeout' }
    $manager = [Windows.Management.Deployment.PackageManager,Windows.Management.Deployment,ContentType=WindowsRuntime]::new()
    $family = $null
    foreach ($release in @(@{Suffix='v1'; Version='1.0.0'}, @{Suffix='v2'; Version='2.0.0'})) {
      if ($release.Suffix -eq 'v2') {
        Invoke-WebRequest -Uri 'http://127.0.0.1:31827/use-v2' -Method Post -UseBasicParsing -TimeoutSec 5 | Out-Null
        Assert-AppInstallerAvailability $native 'Available'
      }
      Add-AppxPackage -Path $uri -AppInstallerFile -ForceTargetApplicationShutdown
      $package = Get-AppxPackage -Name $appinstallerIdentity
      if (-not $package -or $package.Version.ToString() -cne ($release.Version + '.7') -or
          $package.Publisher -cne 'CN=Example' -or $package.Architecture.ToString() -ine $Architecture) {
        throw 'MSIX App Installer package identity mismatch'
      }
      if ($family -and $family -cne $package.PackageFamilyName) { throw 'MSIX App Installer changed package family' }
      $family = $package.PackageFamilyName
      $native = $manager.FindPackageForUser('', $package.PackageFullName)
      $info = $native.GetAppInstallerInfo()
      if (-not $info -or $info.Uri.AbsoluteUri -cne $uri) { throw 'MSIX App Installer URI was not adopted' }
      Assert-AppInstallerAvailability $native 'NoUpdates'
      Assert-DocumentIcons $package
      & $reader --handlers $family present
      if ($LASTEXITCODE -ne 0) { throw 'MSIX App Installer handlers missing' }
      $executable = Join-Path $package.InstallLocation 'sample-desktop.exe'
      & $Python 'examples/desktop/tools/smoke_test.py' $executable --installed --msix --target-os windows --target-arch $Architecture --expected-version $release.Version
      if ($LASTEXITCODE -ne 0) { throw 'MSIX App Installer Electron smoke failed' }
      Write-Output ('MSIX_APPINSTALLER_VERSION_OK ' + $release.Version)
    }
    Remove-AppxPackage -Package $package.PackageFullName
    if (Get-AppxPackage -Name $appinstallerIdentity) { throw 'MSIX App Installer uninstall left registration' }
    & $reader --handlers $family absent
    if ($LASTEXITCODE -ne 0) { throw 'MSIX App Installer uninstall left handlers' }
    Write-Output 'MSIX_APPINSTALLER_INSTALL_UPDATE_REMOVE_OK'
  } finally {
    if (-not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
  }
}
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certificateFile)
$certificatePath = 'Cert:\LocalMachine\TrustedPeople\' + $certificate.Thumbprint
if (Test-Path -LiteralPath $certificatePath) { throw 'MSIX fixture certificate already trusted' }
if (Get-AppxPackage -Name $identity) { throw 'MSIX fixture package already installed' }
if (Get-AppxPackage -Name $desktopIdentity) { throw 'MSIX desktop package already installed' }
if (Get-AppxPackage -Name $appinstallerIdentity) { throw 'MSIX App Installer package already installed' }
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
    Assert-DocumentIcons $package
    & $reader --handlers $family present
    if ($LASTEXITCODE -ne 0) { throw 'MSIX installed handlers missing' }
    $executable = Join-Path $package.InstallLocation 'sample-desktop.exe'
    & $Python 'examples/desktop/tools/smoke_test.py' $executable --installed --msix --target-os windows --target-arch $Architecture --expected-version $release.Version
    if ($LASTEXITCODE -ne 0) { throw 'MSIX installed Electron smoke failed' }
    Assert-Activation $family $release.Version $executable
    Write-Output ('MSIX_DESKTOP_VERSION_OK ' + $release.Version)
  }
  Remove-AppxPackage -Package $package.PackageFullName
  if (Get-AppxPackage -Name $desktopIdentity) { throw 'MSIX desktop uninstall left package registration' }
  & $reader --handlers $family absent
  if ($LASTEXITCODE -ne 0) { throw 'MSIX uninstall left handlers registered' }
  Write-Output 'MSIX_DESKTOP_INSTALL_UPDATE_REMOVE_OK'
  Assert-AppInstaller
} finally {
  try {
    foreach ($name in @($identity, $desktopIdentity, $appinstallerIdentity)) {
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
