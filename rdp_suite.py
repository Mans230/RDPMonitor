#!/usr/bin/env python3
"""Unified launcher and management CLI for RDP Suite.

The monitor and WebConsole share a SYSTEM startup supervisor. Desktop-only
features need an interactive session; monitoring and panel access do not.
"""
import ctypes
import json
import os
import secrets
import subprocess
import sys
import time
import ssl
import urllib.request
import webbrowser


ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(ROOT, "backup")
CONTROL_DIR = os.path.join(BACKUP_ROOT, "control")
CONTROL_REQUEST = os.path.join(CONTROL_DIR, "request.json")
CONTROL_STATUS = os.path.join(CONTROL_DIR, "status.json")
PID_FILE = os.path.join(ROOT, "suite_user.pid.json")
NO_WINDOW = 0x08000000


def _python(windowed=False):
    if windowed and os.name == "nt":
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + "." + secrets.token_hex(4) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)


def request_backup():
    """Queue one manual backup for the SYSTEM worker."""
    os.makedirs(CONTROL_DIR, exist_ok=True)
    lock_path = CONTROL_REQUEST + ".lock"
    # Clear a lock abandoned by a crash so requests are not blocked forever.
    try:
        if os.path.exists(lock_path) and time.time() - os.path.getmtime(lock_path) > 120:
            os.remove(lock_path)
    except OSError:
        pass
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("another backup request is being queued")
    try:
        if os.path.exists(CONTROL_REQUEST):
            try:
                with open(CONTROL_REQUEST, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
            if time.time() - float(existing.get("created", 0) or 0) > 3600:
                try:
                    os.remove(CONTROL_REQUEST)
                except OSError:
                    pass
        if os.path.exists(CONTROL_REQUEST):
            raise RuntimeError("a backup request is already pending")
        request_id = secrets.token_urlsafe(18)
        _atomic_json(CONTROL_REQUEST, {
            "version": 1, "id": request_id, "action": "backup",
            "created": time.time(), "requested_by": os.environ.get("USERNAME", "unknown")
        })
        return request_id
    finally:
        os.close(fd)
        try:
            os.remove(lock_path)
        except OSError:
            pass


def backup_status():
    try:
        with open(CONTROL_STATUS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "unknown", "message": "No worker status is available"}


def _create_kill_job():
    """Create a Windows job that terminates child processes with the supervisor."""
    if os.name != "nt":
        return None
    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.SetInformationJobObject.restype = ctypes.c_int
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_void_p, ctypes.c_uint32]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.AssignProcessToJobObject.restype = ctypes.c_int
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    job = k.CreateJobObjectW(None, None)
    if not job:
        return None
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32)]
    class IO(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]
    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC),
                    ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x00002000
    ok = k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    if not ok:
        k.CloseHandle(job)
        return None
    return job


def run_user_runtime():
    """Supervise the monitor and hardened local WebConsole."""
    mutex = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        mutex = kernel.CreateMutexW(None, False, "Global\\RDPSuite-" +
                                   __import__("hashlib").sha256(ROOT.lower().encode()).hexdigest()[:24])
        if not mutex:
            raise OSError("Cannot create suite runtime mutex")
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)
            return 0  # Interactive or boot runtime already owns these ports/bots.
    specs = {
        "monitor": [_python(True), os.path.join(ROOT, "rdp_monitor.py")],
        "webconsole": [_python(False), os.path.join(ROOT, "webconsole", "RDPWebConsole.py"), "--run"],
    }
    job = _create_kill_job()
    children = {}
    started_at = {}
    failures = {name: 0 for name in specs}
    next_try = {name: 0.0 for name in specs}
    backoff = {name: 5.0 for name in specs}
    max_backoff = 300.0
    max_failures = 8
    try:
        while True:
            now = time.time()
            for name, argv in specs.items():
                proc = children.get(name)
                if proc is not None and proc.poll() is None:
                    continue
                if proc is not None:
                    # The child exited. Count rapid crashes, then back off.
                    alive = now - started_at.get(name, now)
                    if alive < 30:
                        failures[name] += 1
                        backoff[name] = min(backoff[name] * 2, max_backoff)
                    else:
                        failures[name] = 0
                        backoff[name] = 5.0
                    next_try[name] = now + backoff[name]
                    children[name] = None
                if failures.get(name, 0) >= max_failures:
                    continue  # stop respawning a permanently failing child
                if now < next_try.get(name, 0):
                    continue
                kw = {"cwd": ROOT}
                if os.name == "nt":
                    kw["creationflags"] = NO_WINDOW
                try:
                    proc = subprocess.Popen(argv, **kw)
                except Exception as exc:
                    failures[name] = failures.get(name, 0) + 1
                    backoff[name] = min(backoff.get(name, 5.0) * 2, max_backoff)
                    next_try[name] = now + backoff[name]
                    print("[suite] could not start %s: %r" % (name, exc))
                    continue
                children[name] = proc
                started_at[name] = now
                if job:
                    try:
                        ctypes.windll.kernel32.AssignProcessToJobObject(
                            job, ctypes.c_void_p(int(proc._handle)))
                    except Exception:
                        pass
            _atomic_json(PID_FILE, {"supervisor": os.getpid(),
                                    "children": {k: v.pid for k, v in children.items() if v},
                                    "failures": dict(failures),
                                    "updated": time.time()})
            time.sleep(5)
    except KeyboardInterrupt:
        return 0
    finally:
        if job:
            ctypes.windll.kernel32.CloseHandle(job)
        for proc in children.values():
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception:
                    pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        if mutex:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)


def _backup_module(name):
    """Import a module from backup/app (restore, config_manager) on demand."""
    import importlib
    path = os.path.join(BACKUP_ROOT, "app")
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def _run_monitor_cleanup():
    """Run the monitor's system cleanup so managed firewall/registry policy is reverted."""
    monitor = os.path.join(ROOT, "rdp_monitor.py")
    if not os.path.isfile(monitor):
        print("monitor cleanup failed: script is missing")
        return False
    try:
        r = subprocess.run([sys.executable, monitor, "--cleanup"],
                           capture_output=True, text=True, timeout=180)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        print(out[-500:] if out else "monitor cleanup finished")
        return r.returncode == 0 and "[cleanup] done" in out
    except Exception as e:
        print("monitor cleanup failed: %r" % e)
        return False


def _run_webconsole_uninstall():
    """Remove the WebConsole task and report whether its cleanup succeeded."""
    wc = os.path.join(ROOT, "webconsole", "RDPWebConsole.py")
    if not os.path.isfile(wc):
        print("webconsole uninstall failed: script is missing")
        return False
    try:
        result = subprocess.run([sys.executable, wc, "uninstall"],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            print("webconsole uninstall failed: " +
                  ((result.stdout or "") + (result.stderr or "")).strip())
        return result.returncode == 0
    except Exception as e:
        print("webconsole uninstall failed: %r" % e)
        return False


def _webconsole_endpoint():
    """Resolve the local panel endpoint without decrypting or modifying state."""
    try:
        with open(os.path.join(ROOT, "webconsole", "webconsole_state.json"),
                  encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    try:
        port = max(1024, min(65535, int(os.environ.get(
            "RDPWC_PORT", state.get("port", 8399)))))
    except (TypeError, ValueError):
        port = 8399
    bind = os.environ.get("RDPWC_BIND", state.get("bind", "127.0.0.1"))
    tls = bind not in ("127.0.0.1", "::1", "localhost")
    host = "127.0.0.1" if bind in ("0.0.0.0", "localhost") else str(bind)
    if ":" in host:
        host = "[%s]" % ("::1" if host == "::" else host)
    return ("%s://%s:%d/" % ("https" if tls else "http", host, port),
            os.environ.get("RDPWC_TLS_CERT", state.get("tls_cert", "")))


def print_status():
    result = {"webconsole": False, "backup": backup_status()}
    try:
        url, cert = _webconsole_endpoint()
        context = ssl.create_default_context(cafile=cert or None) if url.startswith("https:") else None
        with urllib.request.urlopen(url + "health", timeout=3, context=context) as response:
            result["webconsole"] = bool(json.loads(response.read()).get("ok"))
    except Exception:
        pass
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            result["user_runtime"] = json.load(f)
    except Exception:
        result["user_runtime"] = None
    print(json.dumps(result, indent=2, default=str))


def prepare_service():
    """Migrate owner DPAPI blobs before changing task identity, without plaintext files.

    Machine DPAPI is appropriate only with an Administrators/SYSTEM-only ACL.
    Abort before task replacement if any credential cannot be decrypted.
    """
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError("prepare-service requires an Administrator terminal")
    os.environ["RDPWC_NO_INIT"] = "1"
    sys.path.insert(0, os.path.join(ROOT, "webconsole"))
    import rdp_monitor as monitor
    import RDPWebConsole as panel
    replacements = []
    for path, key, module in (
            (os.path.join(ROOT, "config.json"), "telegram_token_enc", monitor),
            (os.path.join(ROOT, "webconsole", "webconsole_state.json"), "token_enc", panel)):
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get(key):
            data[key] = module.dpapi_protect(module.dpapi_unprotect(data[key]), machine=True)
        replacements.append((path, data))
    paths = [ROOT, os.path.join(ROOT, "webconsole"), os.path.join(ROOT, "control")]
    for path in paths:
        os.makedirs(path, exist_ok=True)
        subprocess.run(["icacls", path, "/inheritance:r", "/grant:r",
                        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       capture_output=True, check=True, creationflags=NO_WINDOW)
    for path, data in replacements:
        # Restrict existing files too: removing inherited access alone is insufficient.
        subprocess.run(["icacls", path, "/reset"], capture_output=True,
                       check=True, creationflags=NO_WINDOW)
        _atomic_json(path, data)
    _atomic_json(os.path.join(ROOT, "control", "service.json"), {"version": 1})
    print("Credentials prepared for startup hosting; desktop capture requires an interactive session.")
    return 0


def main():
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    if command == "--user-runtime":
        # At logon, hand hosting to the desktop session so screenshot/OAuth/GUI
        # capabilities keep working. At logoff the periodic boot task takes over.
        if os.name == "nt":
            subprocess.run(["schtasks", "/End", "/TN", "RDPSuiteBoot"],
                           capture_output=True, creationflags=NO_WINDOW)
            time.sleep(1)
        return run_user_runtime()
    if command == "--service-runtime":
        return run_user_runtime()
    if command == "prepare-service":
        return prepare_service()
    if command == "status":
        print_status(); return 0
    if command == "backup-now":
        print("Backup request queued: " + request_backup()); return 0
    if command == "backup-status":
        print(json.dumps(backup_status(), indent=2)); return 0
    if command == "open":
        webbrowser.open(_webconsole_endpoint()[0]); return 0
    if command == "backup-gui":
        subprocess.Popen([_python(False), os.path.join(BACKUP_ROOT, "app", "main.py")],
                         cwd=os.path.join(BACKUP_ROOT, "app")); return 0
    if command == "restore-list":
        r = _backup_module("restore")
        items = r.list_backups()
        if not items:
            print("No local backups.")
        for b in items:
            print("%s\t%.1f MB\t%s" % (b["name"], b["size"] / 1048576,
                                       time.strftime("%Y-%m-%d %H:%M",
                                                     time.localtime(b["mtime"]))))
        return 0
    if command == "restore":
        args = sys.argv[2:]
        name = args[0] if args else ""
        dest = ""
        if "--to" in args:
            i = args.index("--to")
            dest = args[i + 1] if i + 1 < len(args) else ""
        if not name or not dest:
            print("Usage: rdp_suite.py restore <archive-name> --to <destination-dir>")
            return 2
        r = _backup_module("restore")
        cfg = _backup_module("config_manager").load_config()
        b = next((x for x in r.list_backups() if x["name"] == name), None)
        if not b:
            print("Archive not found: " + name); return 1
        pw = (cfg.get("backup", {}).get("archive_password") or "").strip()
        res = r.restore_archive(b["path"], dest, password=pw,
                                progress_cb=lambda p, m: print("%3d%% %s" % (p, m)))
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("status") == "ok" else 1
    if command == "drill":
        r = _backup_module("restore")
        cfg = _backup_module("config_manager").load_config()
        dest = sys.argv[2] if len(sys.argv) > 2 else \
            (cfg.get("restore_drill", {}) or {}).get("dest", "")
        res = r.run_drill(cfg, dest, log=print)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("status") == "ok" else 1
    if command == "install":
        script = os.path.join(ROOT, "scripts", "install_suite.ps1")
        return subprocess.call(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                "Bypass", "-File", script, "-Python", sys.executable])
    if command == "uninstall":
        script = os.path.join(ROOT, "scripts", "install_suite.ps1")
        rc = subprocess.call(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                              "Bypass", "-File", script, "-Remove"])
        if rc:
            print("Task removal failed; refusing policy cleanup while workers may still run.")
            return rc
        cleanup_ok = _run_monitor_cleanup()
        webconsole_ok = _run_webconsole_uninstall()
        return 0 if cleanup_ok and webconsole_ok else 1
    print("Usage: rdp_suite.py status|open|backup-now|backup-status|backup-gui|"
          "restore-list|restore|drill|install|uninstall")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
