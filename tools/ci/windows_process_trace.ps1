param(
  [Parameter(Mandatory=$true)][string]$Output,
  [Parameter(Mandatory=$true)][string]$Ready
)
$ErrorActionPreference = 'Stop'
$names = @('sample-desktop.exe', 'Sample-2.0.0.exe', 'installer.exe', 'Uninstall.exe')
$filter = ($names | ForEach-Object { "ProcessName = '$_'" }) -join ' OR '
try {
  Register-WmiEvent -Query ("SELECT * FROM Win32_ProcessStartTrace WHERE " + $filter) -SourceIdentifier 'nsis-start' | Out-Null
  Register-WmiEvent -Query ("SELECT * FROM Win32_ProcessStopTrace WHERE " + $filter) -SourceIdentifier 'nsis-stop' | Out-Null
  [System.IO.File]::WriteAllText($Ready, 'ready')
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $count = 0
  while ($timer.Elapsed.TotalSeconds -lt 240 -and $count -lt 128) {
    foreach ($notice in @(Wait-Event -Timeout 2)) {
      $trace = $notice.SourceEventArgs.NewEvent
      if ($names -contains $trace.ProcessName -and $notice.SourceIdentifier -in @('nsis-start', 'nsis-stop')) {
        $record = @{name=[string]$trace.ProcessName; stage='start'; exit_code=$null}
        if ($notice.SourceIdentifier -eq 'nsis-stop') {
          $record.stage = 'stop'
          $record.exit_code = [uint32]$trace.ExitStatus
        }
        [System.IO.File]::AppendAllText($Output, ($record | ConvertTo-Json -Compress) + [Environment]::NewLine)
        $count += 1
      }
      Remove-Event -EventIdentifier $notice.EventIdentifier
    }
  }
} finally {
  Unregister-Event -SourceIdentifier 'nsis-start' -ErrorAction SilentlyContinue
  Unregister-Event -SourceIdentifier 'nsis-stop' -ErrorAction SilentlyContinue
}
