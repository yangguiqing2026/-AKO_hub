# AKO_hub_start.ps1
# Start AKO_hub Dashboard (port 8081) + Hub (port 8080 / heartbeat 5000).
# Logs are redirected to $hub\logs.
#
# ⚠ 调用方式注意（2026-09-14 查清）：
#   本脚本自身约 11 秒跑完并以 0 退出，但用 Start-Process 拉起的 hub / dashboard
#   是**长驻**进程，它们**继承了调用方的 stdout 管道句柄**。因此若以管道方式调用，
#   例如 `powershell -File AKO_hub_start.ps1 | tail`，管道永远等不到 EOF ——
#   即使本脚本早已退出，调用方仍会一直挂着，直到那两个服务进程被杀掉为止。
#   正常用法（双击、计划任务、直接执行）stdout 不是管道，不受影响。
#   需要程序化调用时请用文件重定向（`> log.txt`），不要接管道。

$hub = if ($env:AKO_HUB_DIR) { $env:AKO_HUB_DIR } else { "D:\AKO\AKO_hub" }
$py  = if ($env:AKO_PYTHON) { $env:AKO_PYTHON } else { "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" }
$log = "$hub\logs"

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== AKO_hub start (Dashboard :8081 + Hub :8080/:5000) ==="

# 1) Stop old AKO_hub processes, scoped strictly to the hub:
#    (a) command line references the hub dir (launches below use absolute
#        $hub paths / --app-dir) or the hub dashboard module (unique to AKO_hub);
#    (b) hub server: python processes listening on hub ports 8080/5000
#        (catches old relative-path "app.py" instances; python only).
#    Never touch nginx / WSL llama-server / other repos' app.py.
$old = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like "*$hub*" -or $_.CommandLine -like '*dashboard*')
}
foreach ($p in $old) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "  stopped old PID $($p.ProcessId)"
    } catch {
        Write-Host "  could not stop PID $($p.ProcessId): $_"
    }
}
foreach ($port in @(8080, 5000)) {
    $listeners = netstat -ano | Select-String ":$port " | Select-String "LISTEN"
    foreach ($line in $listeners) {
        $fields = ($line.ToString() -split '\s+') | Where-Object { $_ }
        # 变量名不可用 $pid：PowerShell 的 $PID 是只读自动变量，赋值会抛
        # "无法覆盖变量 PID"，使整个端口清理轮从未执行 —— 2026-09-14 双实例
        # 事故中，相对路径启动的老 hub 正是靠这一轮兜底才该被杀掉的。
        $targetPid = [int]$fields[-1]
        $name = (tasklist /FI "PID eq $targetPid" /FO CSV /NH | ConvertFrom-Csv -Header 'Name','PID','Session','Mem' | Select-Object -First 1).Name
        if ($name -in @('python.exe', 'pythonw.exe')) {
            try {
                Stop-Process -Id $targetPid -Force -ErrorAction Stop
                Write-Host "  stopped old hub PID $targetPid (port $port)"
            } catch {
                Write-Host "  could not stop PID ${targetPid}: $_"
            }
        }
    }
}
Start-Sleep -Seconds 2

# 2) Dashboard on port 8081 (--app-dir $hub keeps the hub path in the
#    command line so the cleanup filter above can identify it)
Start-Process -FilePath $py `
    -ArgumentList "-m","uvicorn","dashboard.app:app","--app-dir","$hub","--host","0.0.0.0","--port","8081" `
    -WorkingDirectory $hub -WindowStyle Hidden `
    -RedirectStandardOutput "$log\dash8081_out.log" -RedirectStandardError "$log\dash8081_err.log"
Write-Host "  launched Dashboard (port 8081)"

# 3) Hub on port 8080 + heartbeat on 5000 (absolute path for the cleanup filter)
Start-Process -FilePath $py `
    -ArgumentList "`"${hub}\app.py`"" `
    -WorkingDirectory $hub -WindowStyle Hidden `
    -RedirectStandardOutput "$log\hub_out.log" -RedirectStandardError "$log\hub_err.log"
Write-Host "  launched Hub (port 8080/5000)"

# 4) Wait and report port status
Start-Sleep -Seconds 8
foreach ($port in @(8081, 8080, 5000)) {
    $hit = netstat -ano | Select-String ":${port} " | Select-String "LISTEN"
    if ($hit) { Write-Host "  port $port : OK" } else { Write-Host "  port $port : NOT listening" }
}
Write-Host "  Dashboard: http://localhost:8081"
Write-Host "  Hub HTTP : http://localhost:8080"
Write-Host "  Hub Beat : http://localhost:5000"
Write-Host "  Logs     : $log\dash8081_out.log / $log\hub_out.log"
