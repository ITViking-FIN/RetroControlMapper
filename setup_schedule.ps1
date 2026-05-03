# RB-Controller_fix — install nightly Wikimedia controller-image sync.
#
# Registers a Windows Task Scheduler entry that runs controller_sync.py
# every night at 03:00 (your local time). Runs as the current user, only
# when the user is logged in (no admin required).
#
# Usage (from PowerShell, in this folder):
#     .\setup_schedule.ps1                  # install
#     .\setup_schedule.ps1 -Uninstall       # remove
#     .\setup_schedule.ps1 -RunNow          # install + immediately trigger one run
#     .\setup_schedule.ps1 -Time "04:30"    # install at custom local time

param(
    [switch] $Uninstall,
    [switch] $RunNow,
    [string] $Time = "03:00",
    [string] $TaskName = "RB-Controller_fix Nightly Sync"
)

$ErrorActionPreference = "Stop"

# Resolve script + Python paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SyncScript = Join-Path $ScriptDir "controller_sync.py"

# Locate py launcher (preferred — uses Windows Python 3 install)
$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $PyLauncher) {
    Write-Error "Cannot find 'py' launcher. Install Python from python.org first."
    exit 1
}

# Uninstall path
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed task: $TaskName" -ForegroundColor Yellow
    } else {
        Write-Host "No task '$TaskName' to remove." -ForegroundColor Gray
    }
    exit 0
}

if (-not (Test-Path $SyncScript)) {
    Write-Error "Sync script not found: $SyncScript"
    exit 1
}

Write-Host "Installing task: $TaskName" -ForegroundColor Cyan
Write-Host "  schedule:    Daily at $Time (current user, only when logged in)"
Write-Host "  script:      $SyncScript"
Write-Host "  python:      $($PyLauncher.Source)"

# Build the action
$Action = New-ScheduledTaskAction `
    -Execute $PyLauncher.Source `
    -Argument "`"$SyncScript`"" `
    -WorkingDirectory $ScriptDir

# Daily trigger at chosen time
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

# Settings: don't run if on battery; allow demand start; wake to run no
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries:$false `
    -DontStopIfGoingOnBatteries:$false `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

# Run as current interactive user, no elevation
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# (Re)register
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Pulls controller image updates from Wikimedia Commons for RB-Controller_fix." | Out-Null

Write-Host "Task registered." -ForegroundColor Green

if ($RunNow) {
    Write-Host "Running once now..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Triggered. See controller_sync.log for output."
}

Write-Host ""
Write-Host "View status:    Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Run on demand:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove:         .\setup_schedule.ps1 -Uninstall"
