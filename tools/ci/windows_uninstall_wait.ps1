param([Parameter(Mandatory = $true)][string]$Executable)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$process = Start-Process -FilePath $Executable -ArgumentList '/S' -Wait -PassThru
$process.Refresh()
if ($null -eq $process.ExitCode) { throw 'NSIS_UNINSTALL_EXIT_UNAVAILABLE' }
Write-Output ('NSIS_UNINSTALL_TREE_EXIT ' + $process.ExitCode)
exit $process.ExitCode
