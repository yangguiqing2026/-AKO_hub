# setup_supervisor_autostart.ps1
# 注册 AKO-Supervisor 开机自启计划任务（AtStartup，对齐 AKO_netwatch_agent 的 setup_autostart.ps1 模式）
# 任务动作：运行 start_agents.ps1（文件锁幂等）→ 拉起 agent_supervisor（7 服务看护 + 自动重启）
# 用法：PowerShell -ExecutionPolicy Bypass -File setup_supervisor_autostart.ps1
# 移除：Unregister-ScheduledTask -TaskName "AKO-Supervisor" -Confirm:$false

$ErrorActionPreference = "Stop"
$hub = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$startScript = Join-Path $hub "start_agents.ps1"
$taskName = "AKO-Supervisor"

if (-not (Test-Path $startScript)) {
    Write-Error "未找到 $startScript"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "[setup_autostart] 已移除旧任务 $taskName"
}

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings | Out-Null
Write-Host "[setup_autostart] 已注册开机自启任务 $taskName（SYSTEM，启动延迟由 start_agents 文件锁保证幂等）"
