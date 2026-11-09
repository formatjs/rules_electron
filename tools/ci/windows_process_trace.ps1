param(
  [Parameter(Mandatory=$true)][string]$Output,
  [Parameter(Mandatory=$true)][string]$Ready
)
$ErrorActionPreference = 'Stop'
$names = @('sample-desktop.exe', 'Sample-2.0.0.exe', 'installer.exe', 'Uninstall.exe')
$filter = ($names | ForEach-Object { "ProcessName = '$_'" }) -join ' OR '
$script:nsisTraceCount = 0
function Write-NsisEvent([string]$Name, [string]$Stage, $ExitCode) {
  if ($script:nsisTraceCount -ge 128) { return }
  $record = @{name=$Name; stage=$Stage; exit_code=$ExitCode}
  [System.IO.File]::AppendAllText($Output, ($record | ConvertTo-Json -Compress) + [Environment]::NewLine)
  $script:nsisTraceCount += 1
}
try {
  Register-WmiEvent -Query ("SELECT * FROM Win32_ProcessStartTrace WHERE " + $filter) -SourceIdentifier 'nsis-start' | Out-Null
  Register-WmiEvent -Query 'SELECT * FROM Win32_ProcessStopTrace' -SourceIdentifier 'nsis-stop' | Out-Null
  [System.IO.File]::WriteAllText($Ready, 'ready')
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $owned = @{}
  $pending = @{}
  while ($timer.Elapsed.TotalSeconds -lt 240 -and $script:nsisTraceCount -lt 128) {
    foreach ($notice in @(Wait-Event -Timeout 2)) {
      $trace = $notice.SourceEventArgs.NewEvent
      $traceProcessId = [uint32]$trace.ProcessID
      $traceTime = [uint64]$trace.TIME_CREATED
      if ($notice.SourceIdentifier -eq 'nsis-start' -and $names -contains $trace.ProcessName) {
        $owned[$traceProcessId] = @{Name=[string]$trace.ProcessName; Started=$traceTime}
        Write-NsisEvent $owned[$traceProcessId].Name 'start' $null
        if ($pending.ContainsKey($traceProcessId)) {
          if ($pending[$traceProcessId].Stopped -ge $traceTime) {
            Write-NsisEvent $owned[$traceProcessId].Name 'stop' $pending[$traceProcessId].Code
            $owned.Remove($traceProcessId)
          }
          $pending.Remove($traceProcessId)
        }
      } elseif ($notice.SourceIdentifier -eq 'nsis-stop') {
        if ($owned.ContainsKey($traceProcessId)) {
          if ($traceTime -ge $owned[$traceProcessId].Started) {
            Write-NsisEvent $owned[$traceProcessId].Name 'stop' ([uint32]$trace.ExitStatus)
            $owned.Remove($traceProcessId)
          }
        } elseif ($pending.Count -lt 4096) {
          # Keep numeric events briefly when stop delivery precedes start delivery.
          $pending[$traceProcessId] = @{Stopped=$traceTime; Code=[uint32]$trace.ExitStatus}
        }
      }
      Remove-Event -EventIdentifier $notice.EventIdentifier
    }
  }
} finally {
  Unregister-Event -SourceIdentifier 'nsis-start' -ErrorAction SilentlyContinue
  Unregister-Event -SourceIdentifier 'nsis-stop' -ErrorAction SilentlyContinue
}
