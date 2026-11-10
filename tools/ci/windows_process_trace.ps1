param(
  [Parameter(Mandatory=$true)][string]$Output,
  [Parameter(Mandatory=$true)][string]$Ready
)
$ErrorActionPreference = 'Stop'
$names = @('sample-desktop.exe', 'Sample-2.0.0.exe', 'installer.exe', 'Uninstall.exe')
$script:nsisTraceCount = 0
$script:resolvedStarts = 0
$script:truncatedStarts = 0
$script:installerHandles = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$script:installerHandleMisses = 0
function Resolve-NsisName([uint32]$Identifier, [string]$EventName) {
  if ($names -contains $EventName) { return ($names | Where-Object { $_ -ieq $EventName } | Select-Object -First 1) }
  if ($EventName.Length -eq 15) {
    $matchingNames = @($names | Where-Object { $_.Length -gt 15 -and $_.Substring(0, 15) -ieq $EventName })
    if ($matchingNames.Count -eq 1) {
      $script:truncatedStarts += 1
      [System.IO.File]::WriteAllText(($Output + '.truncated'), [string]$script:truncatedStarts)
      return $matchingNames[0]
    }
  }
  if ($EventName -inotmatch '^(sample|instal|uninstal)') { return $null }
  $process = $null
  try {
    $process = [System.Diagnostics.Process]::GetProcessById($Identifier)
    $name = [System.IO.Path]::GetFileName($process.MainModule.FileName)
    if ($names -contains $name) {
      $script:resolvedStarts += 1
      [System.IO.File]::WriteAllText(($Output + '.resolved'), [string]$script:resolvedStarts)
      return ($names | Where-Object { $_ -ieq $name } | Select-Object -First 1)
    }
  } catch {
  } finally {
    if ($process) { $process.Dispose() }
  }
  return $null
}
function Track-Installer([uint32]$Identifier, [uint64]$TraceTime) {
  $process = $null
  try {
    $process = [System.Diagnostics.Process]::GetProcessById($Identifier)
    $null = $process.Handle
    $started = [uint64]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
    if ($process.ProcessName -ine 'Sample-2.0.0' -or $started -gt $TraceTime -or
        $TraceTime - $started -gt 50000000) { throw 'Installer PID lifetime mismatch' }
    $script:installerHandles.Add($process)
    $process = $null
  } catch {
    $script:installerHandleMisses += 1
  } finally {
    if ($process) { $process.Dispose() }
  }
}
function Write-InstallerState {
  $running = 0
  $unknown = 0
  $codes = @()
  foreach ($process in $script:installerHandles) {
    try {
      if ($process.HasExited) { $codes += [uint32]([int64]$process.ExitCode -band [int64]4294967295) } else { $running += 1 }
    } catch { $unknown += 1 }
  }
  $state = @{tracked=$script:installerHandles.Count; running=$running; unknown=$unknown;
             handle_misses=$script:installerHandleMisses; exit_codes=@($codes);
             queued_events=@(Get-Event -ErrorAction SilentlyContinue).Count}
  [System.IO.File]::WriteAllText(($Output + '.state'), ($state | ConvertTo-Json -Compress))
}
function Write-NsisEvent([string]$Name, [string]$Stage, $ExitCode) {
  if ($script:nsisTraceCount -ge 128) { return }
  $record = @{name=$Name; stage=$Stage; exit_code=$ExitCode}
  [System.IO.File]::AppendAllText($Output, ($record | ConvertTo-Json -Compress) + [Environment]::NewLine)
  $script:nsisTraceCount += 1
}
try {
  Register-WmiEvent -Query 'SELECT * FROM Win32_ProcessStartTrace' -SourceIdentifier 'nsis-start' | Out-Null
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
      if ($notice.SourceIdentifier -eq 'nsis-start') {
        $name = Resolve-NsisName $traceProcessId ([string]$trace.ProcessName)
        if (-not $name) {
          Remove-Event -EventIdentifier $notice.EventIdentifier
          continue
        }
        if ($name -ieq 'Sample-2.0.0.exe') { Track-Installer $traceProcessId $traceTime }
        $owned[$traceProcessId] = @{Name=$name; Started=$traceTime}
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
    Write-InstallerState
  }
} finally {
  foreach ($process in $script:installerHandles) { $process.Dispose() }
  Unregister-Event -SourceIdentifier 'nsis-start' -ErrorAction SilentlyContinue
  Unregister-Event -SourceIdentifier 'nsis-stop' -ErrorAction SilentlyContinue
}
