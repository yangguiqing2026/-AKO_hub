<#
start_all.ps1 - AKO full-stack idempotent launcher (created 2026-09-11)

Single responsibility: make the "three workbenches + agent cluster" present.
Each step probes its port first and is skipped when already listening, so this
script may be invoked repeatedly (boot task / one-click bat / manual) without
ever producing duplicate instances.

Covers:
  1) AKO_hub core       :8080 HTTP + :5000 heartbeat  - the dispatcher itself
  2) Boss workbench     :8081        - uvicorn dashboard (/governor, /heatmap)
  3) nginx              :80 / :443   - employee entry (static dist + proxy :5026)
  4) intake backend     :5026        - scripts/autostart_backend.py
  5) agent supervisor                - scripts/agent_supervisor.py (watches 10 agents)

NOT covered: intake frontend dev server :5027 (dev only; employees use the
nginx-served production build on :80, so it does not need to be resident).

Order is dependency order: hub before intake (intake delivers into the hub
queue), nginx before the intake frontend (proxy target must exist), agents last
(their heartbeats go to hub :5000).

Relationship to existing scripts: this script deliberately does NOT call
AKO_hub_start.ps1, whose semantics are "kill then start" and would therefore
interrupt live services when re-run. This script only fills gaps. The supervisor
is still launched exclusively through start_agents.ps1, which holds the file
lock and is the single legitimate entry point for it.

NOTE ON ENCODING: this file is intentionally pure ASCII. powershell.exe 5.1
decodes BOM-less files using the system ANSI codepage (GBK here), which
mangles non-ASCII text and can even emit stray quote bytes that break parsing.
Launcher scripts in this repo stay ASCII for that reason.

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File start_all.ps1
  powershell ... -File start_all.ps1 -Quiet      # for scheduled tasks, no console output
  powershell ... -File start_all.ps1 -DryRun     # print actions only, spawn nothing

Exit code: 0 = everything in place; 1 = at least one step failed.
#>
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$DryRun,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$Hub      = if ($env:AKO_HUB_DIR)    { $env:AKO_HUB_DIR }    else { "D:\AKO\AKO_hub" }
$Intake   = if ($env:AKO_INTAKE_DIR) { $env:AKO_INTAKE_DIR } else { "D:\AKO\AKO_hub_intake_agent" }
$NginxDir = if ($env:AKO_NGINX_DIR)  { $env:AKO_NGINX_DIR }  else { "C:\nginx" }
$ComfyDir = if ($env:AKO_COMFY_INSTANCE) { $env:AKO_COMFY_INSTANCE } else { "D:\Comfy-Desktop\ComfyUI-Installs\AKO_sdxl_flower" }
$ArchDir  = if ($env:AKO_ARCHITECT_DIR)  { $env:AKO_ARCHITECT_DIR }  else { "D:\AKO\AKO_architect_agent" }
$Py       = if ($env:AKO_PYTHON)     { $env:AKO_PYTHON }     else { "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" }
$PyW      = Join-Path (Split-Path $Py -Parent) "pythonw.exe"
if (-not (Test-Path $PyW)) { $PyW = $Py }

$LogDir = Join-Path $Hub "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir ("start_all_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

$script:Results = @()
$script:SupervisorLaunched = $true

function Write-Line {
    param([string]$Text, [string]$Color = "Gray")
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if (-not $Quiet) { Write-Host $Text -ForegroundColor $Color }
}

function Test-Port {
    param([int]$Port, [string]$TargetHost = "127.0.0.1", [int]$TimeoutMs = 1000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Port {
    param([int]$Port, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port -Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-Background {
    param([string]$Exe, [string[]]$Argv, [string]$WorkDir, [string]$StdOut, [string]$StdErr)
    if ($DryRun) {
        Write-Line ("        [DRYRUN] {0} {1}  (cwd={2})" -f $Exe, ($Argv -join " "), $WorkDir) DarkGray
        return
    }
    # PS 5.1 的 Start-Process 对空 ArgumentList 做 ValidateNotNullOrEmpty 校验，
    # 空数组直接传会抛参数验证异常（2026-09-15 nginx 冷启动失败根因）。空参数时省略该参数。
    $spArgs = @{
        FilePath = $Exe
        WorkingDirectory = $WorkDir
        WindowStyle = 'Hidden'
        RedirectStandardOutput = $StdOut
        RedirectStandardError = $StdErr
    }
    if ($Argv.Count -gt 0) { $spArgs.ArgumentList = $Argv }
    Start-Process @spArgs | Out-Null
}

function Add-Result {
    param([string]$Name, [bool]$Ok, [string]$Status)
    $script:Results += [pscustomobject]@{ Name = $Name; Ok = $Ok; Status = $Status }
}

# A venv's Scripts\python.exe is a uv trampoline that re-execs the real
# interpreter with identical arguments, so one logical supervisor shows up as a
# parent/child pair. Either half matching means it is up.
function Test-SupervisorRunning {
    $hit = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'agent_supervisor\.py' }
    return [bool]$hit
}

# "skip if the port is up, otherwise start it and wait for the port"
# -WaitSeconds overrides the global -TimeoutSeconds for slow cold starts
# (ComfyUI loads checkpoints and can exceed the default 30s); 0 = use global.
function Invoke-PortStep {
    param([string]$Name, [int]$Port, [scriptblock]$Start, [int]$WaitSeconds = 0)
    if ($WaitSeconds -le 0) { $WaitSeconds = $TimeoutSeconds }
    if (Test-Port -Port $Port) {
        Write-Line ("  [SKIP]  {0,-18} :{1} already listening" -f $Name, $Port) DarkGray
        Add-Result -Name $Name -Ok $true -Status "SKIP"
        return
    }
    Write-Line ("  [START] {0,-18} :{1}" -f $Name, $Port) Cyan
    try {
        & $Start
    } catch {
        Write-Line ("  [FAIL]  {0,-18} :{1} launch error: {2}" -f $Name, $Port, $_) Red
        Add-Result -Name $Name -Ok $false -Status "FAIL"
        return
    }
    if ($DryRun) {
        Add-Result -Name $Name -Ok $true -Status "DRYRUN"
        return
    }
    if (Wait-Port -Port $Port -TimeoutSeconds $WaitSeconds) {
        Write-Line ("  [OK]    {0,-18} :{1} ready" -f $Name, $Port) Green
        Add-Result -Name $Name -Ok $true -Status "OK"
    } else {
        Write-Line ("  [FAIL]  {0,-18} :{1} timeout after {2}s, not listening (logs: {3})" -f $Name, $Port, $WaitSeconds, $LogDir) Red
        Add-Result -Name $Name -Ok $false -Status "TIMEOUT"
    }
}

# -- main ----------------------------------------------------------
Write-Line "=== AKO full-stack start (three workbenches + agent cluster) ===" "White"
if ($DryRun) { Write-Line "  (DryRun: listing actions only, no processes spawned)" "Yellow" }

# 1) AKO_hub core - one process serving :8080 HTTP and :5000 heartbeat
Invoke-PortStep -Name "AKO_hub core" -Port 8080 -Start {
    Start-Background -Exe $PyW -Argv @("app.py") -WorkDir $Hub `
        -StdOut (Join-Path $LogDir "hub_out.log") -StdErr (Join-Path $LogDir "hub_err.log")
}

# 2) Boss workbench (governance command room + heatmap overview)
Invoke-PortStep -Name "Boss workbench" -Port 8081 -Start {
    Start-Background -Exe $PyW `
        -Argv @("-m", "uvicorn", "dashboard.app:app", "--app-dir", $Hub,
                "--host", "0.0.0.0", "--port", "8081") `
        -WorkDir $Hub `
        -StdOut (Join-Path $LogDir "dash8081_out.log") -StdErr (Join-Path $LogDir "dash8081_err.log")
}

# 3) nginx employee entry (:80 redirects 301 to :443)
Invoke-PortStep -Name "nginx entry" -Port 80 -Start {
    $nginxExe = Join-Path $NginxDir "nginx.exe"
    if (-not (Test-Path $nginxExe)) { throw "not found: $nginxExe" }
    Start-Background -Exe $nginxExe -Argv @() -WorkDir $NginxDir `
        -StdOut (Join-Path $LogDir "nginx_out.log") -StdErr (Join-Path $LogDir "nginx_err.log")
}

# 4) intake backend (:5026; contains its own ensure_hub bootstrap, already satisfied by step 1)
Invoke-PortStep -Name "intake backend" -Port 5026 -Start {
    $entry = Join-Path $Intake "scripts\autostart_backend.py"
    if (-not (Test-Path $entry)) { throw "not found: $entry" }
    Start-Background -Exe $PyW -Argv @("scripts\autostart_backend.py") -WorkDir $Intake `
        -StdOut (Join-Path $LogDir "intake_out.log") -StdErr (Join-Path $LogDir "intake_err.log")
}

# 5) Local SDXL image stack - ComfyUI :8188 + A1111-compat bridge :7860
# Rationale (2026-09-16): the architect render path tries wanx first and falls
# back to the bridge on :7860. During the Alibaba Cloud arrears both services
# were down AND were not covered by this script, so a render task burned its
# full per-call timeout (SD_API_TIMEOUT=300s, 4 views) and then failed anyway;
# the hub task sat in "running" for ~10 minutes. Probing the ports here turns
# the local fallback from a dead endpoint into a real one.
# The bridge is stdlib-only and speaks the A1111 subset the architect expects;
# its checkpoint/LoRA defaults (Juggernaut-XL v9 + realistic-architecture LoRA)
# already match this ComfyUI instance's models folder.
Invoke-PortStep -Name "ComfyUI SDXL" -Port 8188 -WaitSeconds 90 -Start {
    $comfyHome = Join-Path $ComfyDir "ComfyUI"
    $comfyPy   = Join-Path $comfyHome ".venv\Scripts\python.exe"
    $comfyMain = Join-Path $comfyHome "main.py"
    if (-not (Test-Path $comfyPy))   { throw "not found: $comfyPy" }
    if (-not (Test-Path $comfyMain)) { throw "not found: $comfyMain" }
    Start-Background -Exe $comfyPy -Argv @($comfyMain, "--port", "8188") -WorkDir $comfyHome `
        -StdOut (Join-Path $LogDir "comfyui_out.log") -StdErr (Join-Path $LogDir "comfyui_err.log")
}

Invoke-PortStep -Name "SD bridge" -Port 7860 -Start {
    $bridge = Join-Path $ArchDir "sd_comfy_bridge.py"
    if (-not (Test-Path $bridge)) { throw "not found: $bridge" }
    Start-Background -Exe $Py -Argv @("sd_comfy_bridge.py") -WorkDir $ArchDir `
        -StdOut (Join-Path $LogDir "sd_bridge_out.log") -StdErr (Join-Path $LogDir "sd_bridge_err.log")
}

# 6) agent supervisor - only via start_agents.ps1 (it holds the file lock)
$startAgents = Join-Path $Hub "start_agents.ps1"
if ($DryRun) {
    Write-Line ("  [DRYRUN] {0,-18}    powershell -File {1}" -f "agent supervisor", $startAgents) DarkGray
    Add-Result -Name "agent supervisor" -Ok $true -Status "DRYRUN"
} elseif (-not (Test-Path $startAgents)) {
    Write-Line ("  [FAIL]  {0,-18}    not found: {1}" -f "agent supervisor", $startAgents) Red
    Add-Result -Name "agent supervisor" -Ok $false -Status "FAIL"
} elseif (Test-SupervisorRunning) {
    Write-Line ("  [SKIP]  {0,-18}    already running" -f "agent supervisor") DarkGray
    Add-Result -Name "agent supervisor" -Ok $true -Status "SKIP"
} else {
    Write-Line ("  [RUN]   {0,-18}    via start_agents.ps1 (idempotent)" -f "agent supervisor") Cyan
    try {
        # Deliberately NOT -Wait: the supervisor is long-lived and holds the
        # redirected stdout handle open, so waiting on it never returns. That
        # hung start_all.ps1 on 2026-09-11. Launch detached, then poll instead.
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startAgents) `
            -WindowStyle Hidden | Out-Null
    } catch {
        Write-Line ("  [FAIL]  {0,-18}    launch error: {1}" -f "agent supervisor", $_) Red
        Add-Result -Name "agent supervisor" -Ok $false -Status "FAIL"
        $script:SupervisorLaunched = $false
    }

    if ($script:SupervisorLaunched) {
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline -and -not (Test-SupervisorRunning)) {
            Start-Sleep -Milliseconds 500
        }
        if (Test-SupervisorRunning) {
            Write-Line ("  [OK]    {0,-18}    up" -f "agent supervisor") Green
            Add-Result -Name "agent supervisor" -Ok $true -Status "OK"
        } else {
            Write-Line ("  [FAIL]  {0,-18}    not running after {1}s" -f "agent supervisor", $TimeoutSeconds) Red
            Add-Result -Name "agent supervisor" -Ok $false -Status "TIMEOUT"
        }
    }
}

# -- summary -------------------------------------------------------
$failed = @($script:Results | Where-Object { -not $_.Ok })
Write-Line ""
Write-Line "=== result ===" "White"
foreach ($r in $script:Results) {
    $mark = if ($r.Ok) { "OK  " } else { "FAIL" }
    $color = if ($r.Ok) { "Gray" } else { "Red" }
    Write-Line ("  {0} {1,-18} {2}" -f $mark, $r.Name, $r.Status) $color
}

if (-not $Quiet) {
    Write-Line ""
    Write-Line "  Employee workbench : https://akoagent" "White"
    Write-Line "  Boss workbench     : http://localhost:8081" "White"
    Write-Line "  Hub HTTP           : http://localhost:8080" "White"
    Write-Line "  Log                : $LogFile" "White"
}

if ($failed.Count -gt 0) {
    Write-Line ("  {0} step(s) failed" -f $failed.Count) Red
    exit 1
}
Write-Line "  all in place" Green
exit 0
