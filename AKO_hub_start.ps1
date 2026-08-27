# AKO_hub_start.ps1
# Start AKO_hub Dashboard (port 80) + Hub (port 8080 / heartbeat 5000).
# Logs are redirected to $hub\logs.

$hub = if ($env:AKO_HUB_DIR) { $env:AKO_HUB_DIR } else { "D:\AKO\AKO_hub" }
$py  = if ($env:AKO_PYTHON) { $env:AKO_PYTHON } else { "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" }
$log = "$hub\logs"

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== AKO_hub start (Dashboard :80 + Hub :8080/:5000) ==="

# 1) Stop old AKO_hub python processes by command line.
#    NOTE: filter by command line (dashboard / app.py) so we never touch the
#    WSL wslrelay / llama-server running on port 8081.
$old = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -like '*dashboard*' -or $_.CommandLine -like '*app.py*'
}
foreach ($p in $old) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "  stopped old PID $($p.ProcessId)"
    } catch {
        Write-Host "  could not stop PID $($p.ProcessId): $_"
    }
}
Start-Sleep -Seconds 2

# 2) Dashboard on port 80
Start-Process -FilePath $py `
    -ArgumentList "-m","uvicorn","dashboard.app:app","--host","0.0.0.0","--port","80" `
    -WorkingDirectory $hub -WindowStyle Hidden `
    -RedirectStandardOutput "$log\dash80_out.log" -RedirectStandardError "$log\dash80_err.log"
Write-Host "  launched Dashboard (port 80)"

# 3) Hub on port 8080 + heartbeat on 5000
Start-Process -FilePath $py `
    -ArgumentList "app.py" `
    -WorkingDirectory $hub -WindowStyle Hidden `
    -RedirectStandardOutput "$log\hub_out.log" -RedirectStandardError "$log\hub_err.log"
Write-Host "  launched Hub (port 8080/5000)"

# 4) Wait and report port status
Start-Sleep -Seconds 8
foreach ($port in @(80, 8080, 5000)) {
    $hit = netstat -ano | Select-String ":${port} " | Select-String "LISTEN"
    if ($hit) { Write-Host "  port $port : OK" } else { Write-Host "  port $port : NOT listening" }
}
Write-Host "  Dashboard: http://localhost"
Write-Host "  Hub HTTP : http://localhost:8080"
Write-Host "  Hub Beat : http://localhost:5000"
Write-Host "  Logs     : $log\dash80_out.log / $log\hub_out.log"
