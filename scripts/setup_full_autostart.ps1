<#
setup_full_autostart.ps1 - register the AKO boot task and retire the legacy ones
(created 2026-09-11)

Goal: the whole stack comes up at boot, with nobody logged in.

Registers ONE task, AKO_Hub_Stack (AtStartup / SYSTEM / Highest), which runs
start_all.ps1 -Quiet. start_all.ps1 is idempotent, so this task and a manual
run of the one-click launcher bat (AKO_hub_ + CJK for "one-click start") are
the same operation.

Legacy tasks are DISABLED (not deleted), so reverting is one cmdlet:
  AKO_hub_intake_agent : was ONLOGON, action set now folded into start_all.ps1 step 4
  AKO_nginx_80         : was ONLOGON, folded into start_all.ps1 step 3
  AKO-Supervisor       : was ONBOOT,  folded into start_all.ps1 step 5
  AKO_probe_backend2   : DELETED - it points at scripts/_probe_backend2.py,
                         which no longer exists, so every run failed. Its XML is
                         exported to backups\ first as a courtesy.

NOTE ON ENCODING: pure ASCII on purpose. powershell.exe 5.1 decodes BOM-less
files with the system ANSI codepage (GBK here), which mangles non-ASCII text and
can emit stray quote bytes that break parsing.

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File setup_full_autostart.ps1
  powershell ... -File setup_full_autostart.ps1 -DryRun      # show, change nothing
  powershell ... -File setup_full_autostart.ps1 -Uninstall   # remove the new task,
                                                             # re-enable the legacy ones

Requires elevation (the task runs as SYSTEM).
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Hub        = if ($env:AKO_HUB_DIR) { $env:AKO_HUB_DIR } else { Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$startAll   = Join-Path $Hub "start_all.ps1"
$TaskName   = "AKO_Hub_Stack"
$Legacy     = @("AKO_hub_intake_agent", "AKO_nginx_80", "AKO-Supervisor")
$DeadTask   = "AKO_probe_backend2"
$BackupDir  = Join-Path $Hub "backups"

function Write-Out {
    param([string]$Text, [string]$Color = "Gray")
    Write-Host $Text -ForegroundColor $Color
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# -- uninstall path ------------------------------------------------
if ($Uninstall) {
    Write-Out "=== uninstall $TaskName ===" "White"
    if ($DryRun) { Write-Out "  [DRYRUN] would unregister $TaskName" DarkGray }
    else {
        if (-not (Test-Elevated)) { Write-Out "  ERROR: needs elevation" Red; exit 1 }
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Write-Out "  removed $TaskName" Green }
        else { Write-Out "  $TaskName not present" DarkGray }
    }
    foreach ($name in $Legacy) {
        if ($DryRun) { Write-Out "  [DRYRUN] would re-enable $name" DarkGray; continue }
        $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($t) { Enable-ScheduledTask -TaskName $name | Out-Null; Write-Out "  re-enabled $name" Green }
        else { Write-Out "  $name not present" DarkGray }
    }
    Write-Out "  done. stack no longer starts at boot." Yellow
    exit 0
}

# -- preflight -----------------------------------------------------
Write-Out "=== register boot task: $TaskName ===" "White"

if (-not (Test-Path $startAll)) {
    Write-Out "  ERROR: not found: $startAll" Red
    exit 1
}
if (-not $DryRun -and -not (Test-Elevated)) {
    Write-Out "  ERROR: needs elevation (task principal is SYSTEM)." Red
    Write-Out "         Re-run this script from an elevated PowerShell." Yellow
    exit 1
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startAll`" -Quiet" `
    -WorkingDirectory $Hub

$trigger = New-ScheduledTaskTrigger -AtStartup

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
    -LogonType ServiceAccount -RunLevel Highest

# MultipleInstances=IgnoreNew is the second line of defence behind start_all's own
# idempotency: it stops a second run from starting while one is still in flight.
# RestartCount applies when the task exits non-zero, which start_all signals (exit 1).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Write-Out "  1) task     : $TaskName" Gray
Write-Out "     trigger  : AtStartup (SYSTEM, Highest, IgnoreNew, restart x3)" DarkGray
Write-Out "     action   : powershell -File `"$startAll`" -Quiet" DarkGray
Write-Out "  2) disable  : $($Legacy -join ', ')" Gray
Write-Out "  3) delete   : $DeadTask (points at a missing script)" Gray

if ($DryRun) {
    Write-Out ""
    Write-Out "  [DRYRUN] no changes made." Yellow
    exit 0
}

# -- 1) register ---------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Out "  removed previous $TaskName" DarkGray
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings | Out-Null
Write-Out "  registered $TaskName" Green

# -- 2) retire legacy tasks ----------------------------------------
foreach ($name in $Legacy) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Out "  $name not present, skipped" DarkGray; continue }
    if ($t.State -eq "Disabled") { Write-Out "  $name already disabled" DarkGray; continue }
    Disable-ScheduledTask -TaskName $name | Out-Null
    Write-Out "  disabled $name (definition kept for rollback)" Green
}

# -- 3) remove the dead task ---------------------------------------
$dead = Get-ScheduledTask -TaskName $DeadTask -ErrorAction SilentlyContinue
if ($dead) {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null }
    $xmlPath = Join-Path $BackupDir ("{0}_{1}.xml" -f $DeadTask, (Get-Date -Format "yyyyMMdd_HHmmss"))
    try {
        Export-ScheduledTask -TaskName $DeadTask | Set-Content -Path $xmlPath -Encoding UTF8
        Write-Out "  exported $DeadTask to $xmlPath" DarkGray
    } catch {
        Write-Out "  WARN: could not export $DeadTask ($_) - deleting anyway" Yellow
    }
    Unregister-ScheduledTask -TaskName $DeadTask -Confirm:$false
    Write-Out "  deleted $DeadTask" Green
} else {
    Write-Out "  $DeadTask not present, skipped" DarkGray
}

# -- summary -------------------------------------------------------
Write-Out ""
Write-Out "=== done ===" "White"
Get-ScheduledTask | Where-Object { $_.TaskName -like "*AKO*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize | Out-String -Width 200 | Write-Host

Write-Out "  Verify now  : schtasks /Run /TN `"$TaskName`"" "White"
Write-Out "  Rollback    : powershell -File `"$PSCommandPath`" -Uninstall" "White"
Write-Out "  Reboot test : services should be listening with nobody logged in." "White"
exit 0
