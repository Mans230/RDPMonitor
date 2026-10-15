# -*- coding: utf-8 -*-
"""
Run RDP Monitor automatically in the background after each login, including RDP logins.

Commands:
  python autostart.py install    Install a scheduled task that runs automatically when you log in
  python autostart.py uninstall  Remove the scheduled task
  python autostart.py status     View task and tool status

What does installation do?
  - Registers an at-logon task in Windows Task Scheduler
  - Runs without a console window through pythonw
  - Removes the default 72-hour execution limit
  - Restarts the process one minute after a crash
  - Uses the highest available run level for administrative operations

Note: Administrator privileges are required and Windows may display a UAC prompt.
"""

import os
import ctypes
import hashlib
import subprocess
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "rdp_monitor.py")
TASK_NAME = "RDPMonitor"


def instance_mutex_name():
    install_id = hashlib.sha256(BASE_DIR.lower().encode("utf-8")).hexdigest()[:20]
    return "Global\\RDPMonitor_" + install_id


def pause():
    try:
        input("Press Enter to exit...")
    except (EOFError, OSError):
        pass


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated():
    """Rerun the script with administrator privileges through UAC.

    Single quotes in executable and script paths are doubled for PowerShell.
    """
    script = os.path.abspath(__file__).replace("'", "''")
    exe = sys.executable.replace("'", "''")
    args = " ".join(f'"{a}"' for a in sys.argv[1:])
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process -FilePath '{exe}' "
         f"-ArgumentList '\"{script}\" {args}' -Verb RunAs"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print("Requesting admin rights - confirm the UAC popup...")
    time.sleep(2)
    sys.exit(0)


def find_pythonw():
    """pythonw = Python without a black window"""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def instance_running():
    """Check the same Windows named mutex used by the monitor."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenMutexW(
            0x00100000, False, instance_mutex_name())  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def write_install_ps1():
    pyw = find_pythonw().replace("'", "''")
    script = SCRIPT_PATH.replace("'", "''")
    workdir = os.path.dirname(SCRIPT_PATH).replace("'", "''")
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME", "")
    username = os.environ.get("USERNAME", "")
    user = f"{domain}\\{username}" if domain else username
    ps = f"""
$action = New-ScheduledTaskAction -Execute '{pyw}' -Argument ('"' + '{script}' + '"') -WorkingDirectory '{workdir}'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User '{user}'
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
if ($?) {{ Write-Host 'TASK_REGISTERED' }}
"""
    path = os.path.join(tempfile.gettempdir(), "rdpm_install.ps1")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(ps)
    return path


def install():
    if not is_admin():
        run_elevated()

    ps1 = write_install_ps1()
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
        capture_output=True, text=True, timeout=90)
    out = (r.stdout or "") + (r.stderr or "")
    if "TASK_REGISTERED" not in out:
        print("Install failed:\n" + out.strip())
        pause()
        return 1
    print("+ Scheduled task registered (runs at logon)")

    if instance_running():
        print("i  A copy is running manually right now.")
        print("   Close it (Ctrl+C) then run: python autostart.py status")
        print("   Or re-login and the background copy starts automatically.")
    else:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-ScheduledTask -TaskName '{TASK_NAME}'"],
            capture_output=True, timeout=30)
        time.sleep(3)
        if instance_running():
            print("+ Tool is now running in the background (no window)")
        else:
            print("i  Task registered - it will start automatically at next logon")
            print("   (If first-time setup is not done yet, run: python rdp_monitor.py from CMD once)")

    print()
    print("Setup complete:")
    print("  - Starts automatically at every logon (including RDP sessions)")
    print("  - Runs with no window - fully in the background")
    print("  - If the process crashes, Windows restarts it after 1 minute")
    print("  - After any restart/shutdown it comes back at next logon")
    print()
    pause()
    return 0


def uninstall():
    if not is_admin():
        run_elevated()

    # 1) Stop the task first; a running monitor could reapply policy during cleanup.
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue"],
        capture_output=True, timeout=30)

    # 2) Verify that the process stopped; terminate only a verified monitor process.
    for _ in range(10):
        if not instance_running():
            break
        time.sleep(1)
    if instance_running():
        needle = SCRIPT_PATH.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$needle='{needle}'; Get-CimInstance Win32_Process | "
             f"Where-Object {{ $_.CommandLine -and "
             f"$_.CommandLine.IndexOf($needle, "
             f"[StringComparison]::OrdinalIgnoreCase) -ge 0 }} | "
             f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force "
             f"-ErrorAction SilentlyContinue; Write-Host 'KILLED' }}"],
            capture_output=True, text=True, timeout=30)
        time.sleep(2)

    if instance_running():
        print("! RDP Monitor is still running (possibly a manually started relative path).")
        print("  Stop that console with Ctrl+C, then run uninstall again.")
        pause()
        return 1

    # 3) Revert managed system policy after the monitor has stopped to avoid races.
    cleaned = False
    if os.path.exists(SCRIPT_PATH):
        try:
            r = subprocess.run([sys.executable, SCRIPT_PATH, "--cleanup"],
                               capture_output=True, timeout=300)
            out = (r.stdout or b"").decode("utf-8", "replace")
            err = (r.stderr or b"").decode("utf-8", "replace")
            if r.returncode == 0 and "[cleanup] done" in out:
                cleaned = True
                print("+ System changes reverted:\n" + out.strip())
            else:
                print("! Cleanup reported problems (exit "
                      f"{r.returncode}):\n{out.strip()}\n{err.strip()}")
        except Exception as e:
            print(f"! Cleanup step failed: {e}")
    else:
        print("i  rdp_monitor.py not found - skipped cleanup")

    # 4) Remove the scheduled task.
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false; "
         f"if ($?) {{ Write-Host 'TASK_REMOVED' }}"],
        capture_output=True, text=True, timeout=90)
    task_removed = "TASK_REMOVED" in (r.stdout or "")
    if task_removed:
        print("+ Scheduled task removed")
    else:
        print("i  " + ((r.stdout or "") + (r.stderr or "")).strip())
    if not cleaned:
        print("! NOTE: system firewall changes may NOT have been fully reverted.")
        print("        Re-run:  python rdp_monitor.py --cleanup")
    pause()
    return 0 if cleaned and task_removed else 1


def status():
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
         f"if ($t) {{ Write-Host ('TASK:' + $t.State) }} else {{ Write-Host 'TASK:NOT_FOUND' }}"],
        capture_output=True, text=True, timeout=60)
    state = "not installed"
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("TASK:"):
            state = ln.split(":", 1)[1].strip()
    state_ar = {"Ready": "Ready (starts at logon)",
                "Running": "Running now"}.get(state, state)
    print(f"Scheduled task: {state_ar}")
    print(f"Tool running now: {'YES' if instance_running() else 'no'}")
    pause()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    if cmd == "install":
        sys.exit(install())
    elif cmd == "uninstall":
        sys.exit(uninstall())
    else:
        sys.exit(status())
