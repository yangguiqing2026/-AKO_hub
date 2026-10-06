# start_agents.ps1 - idempotent launcher for agent_supervisor (file-lock prevents duplicate instances even under concurrent retries)
$ErrorActionPreference = "Stop"
$py = "D:\AKO\ako_agent_env\Scripts\python.exe"
$hub = "D:\AKO\AKO_hub"
$lockPath = "$hub\logs\supervisor.lck"

# Acquire exclusive lock; if another invocation already holds it, skip.
try {
    $fs = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    Write-Host "[start_agents] lock held by another instance - skip"
    exit 0
}
try {
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'agent_supervisor\.py' }
    if ($existing) {
        Write-Host "[start_agents] supervisor already running (PID $($existing.ProcessId -join ',')) - skip"
        exit 0
    }
    # 2026-10-06（WO-HAI-20261006-009 铁律3）：-u 保证 supervisor 自身 stdout 无缓冲，
    # supervisor_out.log 存活期实时有字（等效 PYTHONUNBUFFERED；代码侧另有 main() 行缓冲兜底）
    Start-Process -FilePath $py -ArgumentList "-u","scripts/agent_supervisor.py" -WorkingDirectory $hub -RedirectStandardOutput "$hub\logs\supervisor_out.log" -RedirectStandardError "$hub\logs\supervisor_err.log" -NoNewWindow
    Write-Host "[start_agents] supervisor launched"
} finally {
    $fs.Close()
}
