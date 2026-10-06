#!/usr/bin/env python3
"""AKO Hub 一键启动脚本（UTF-8，纯 ASCII）"""
import subprocess, sys, os, time, socket

PY = os.environ.get("AKO_PYTHON", r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe")
HUB_DIR = os.environ.get("AKO_HUB_DIR", r"D:\AKO\AKO_hub")
PORTS = {8081: "Dashboard", 8080: "Hub HTTP", 5000: "Hub Heartbeat"}

def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def wait_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_in_use(port):
            return True
        time.sleep(0.5)
    return False

def proc_name(pid):
    """Resolve PID -> executable name via tasklist ("" if gone)."""
    out = subprocess.run(
        f'tasklist /FI "PID eq {pid}" /FO CSV /NH',
        shell=True, capture_output=True, text=True
    ).stdout
    for line in out.strip().splitlines():
        parts = line.split('","')
        if parts:
            return parts[0].strip('"')
    return ""

def kill_on_port(port):
    out = subprocess.run(
        f'netstat -ano | findstr ":{port} " | findstr LISTENING',
        shell=True, capture_output=True, text=True
    )
    for line in out.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[4] == "LISTENING":
            pid = int(parts[-1])
            # Never kill non-python processes (nginx, WSL llama-server ...)
            name = proc_name(pid)
            if name.lower() not in ("python.exe", "pythonw.exe"):
                print(f"  Skip PID {pid} ({name}) on :{port} - not python")
                continue
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, shell=True)
                print(f"  Stopped PID {pid}")
            except Exception as e:
                print(f"  Failed to kill PID {pid}: {e}")

def start_service(title, *args):
    kw = dict(
        cwd=HUB_DIR,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
    )
    subprocess.Popen([PY] + list(args), **kw)
    print(f"  {title}: started")

def main():
    print("=== AKO Hub Launcher ===\n")

    # stop old processes first
    print("[0] Stopping old processes...")
    for p in PORTS:
        kill_on_port(p)

    time.sleep(2)

    # start services
    print("\n[1] Starting services...")
    start_service("Dashboard (8081)", "-m", "uvicorn", "dashboard.app:app",
                  "--host", "0.0.0.0", "--port", "8081")
    start_service("Hub HTTP+Heartbeat (8080/5000)", "app.py")

    # wait and check
    print("\n[2] Waiting for services to come up...")
    all_ok = True
    for port, name in PORTS.items():
        ok = wait_port(port, timeout=15)
        status = "OK" if ok else "TIMEOUT"
        print(f"  {name} (:{port}): {status}")
        if not ok:
            all_ok = False

    print("\n=== Result ===")
    if all_ok:
        print("All services started successfully!")
        print("  Dashboard : http://127.0.0.1:8081")
        print("  Hub HTTP  : http://localhost:8080")
        print("  Hub Beat  : http://localhost:5000")
    else:
        print("Some services failed to start - check logs.")
    if sys.stdout.isatty():
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
