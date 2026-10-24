#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RDPWebConsole v2 — one-file web control center for any Windows RDP/VPS.

Quick start:   python RDPWebConsole.py            (local: 127.0.0.1, opens browser)
Install local: python RDPWebConsole.py install    (local-only scheduled task)
Remote mode:   python RDPWebConsole.py install-remote
               Requires TLS certificate/key and an explicit source-IP allow-list.
Remove:        python RDPWebConsole.py uninstall

Commands: install | install-remote | uninstall | url | token | rotate-token | (default: run server)
Env: RDPWC_PORT (8399), RDPWC_BIND, RDPWC_TOKEN, RDPWC_RDPDIR (C:\\RDPMonitor)
"""
import os, sys, json, time, socket, threading, subprocess, re
import collections, webbrowser, tempfile, base64, secrets, ssl, hmac, ipaddress, shlex, ctypes, hashlib, contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from http.cookies import SimpleCookie
from action_policy import CONFIRMED_ACTIONS, audit_action, confirmation_arguments, requires_confirmation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))
from audit_store import append_event, read_events, summarize
# Default to the suite root (parent of this webconsole folder) instead of a
# hard-coded C:\RDPMonitor, so the panel follows wherever the suite is installed.
RDPDIR = os.environ.get("RDPWC_RDPDIR") or os.path.dirname(BASE_DIR)
STATE_FILE = os.path.join(BASE_DIR, "webconsole_state.json")
HIST_FILE = os.path.join(BASE_DIR, "webconsole_history.json")
AUDIT_FILE = os.path.join(BASE_DIR, "webconsole_audit.jsonl")
USAGE_FILE = os.path.join(BASE_DIR, "usage_audit.jsonl")
PID_FILE = os.path.join(BASE_DIR, "webconsole.pid")
HTML_PATH = os.path.join(BASE_DIR, "webconsole_ui.html")
SHOT_DIR = os.path.join(BASE_DIR, "screenshots")
BACKUP_DIR = os.path.join(RDPDIR, "backup")
BACKUP_CONTROL_DIR = os.path.join(BACKUP_DIR, "control")
BACKUP_REQUEST = os.path.join(BACKUP_CONTROL_DIR, "request.json")
BACKUP_STATUS = os.path.join(BACKUP_CONTROL_DIR, "status.json")
MONITOR_CONTROL_DIR = os.path.join(RDPDIR, "control")
MONITOR_REQUEST = os.path.join(MONITOR_CONTROL_DIR, "request.json")
MONITOR_RESULT = os.path.join(MONITOR_CONTROL_DIR, "result.json")
NO_WINDOW = 0x08000000
IS_WIN = sys.platform == "win32"
TASK_NAME = "RDPWebConsole"
RULE_NAME = "RDPWebConsole"
MAX_BODY = 64 * 1024
MAX_DOWNLOAD = 50 * 1024 * 1024
SESSION_TTL = 30 * 60
MAX_THREADS = 24
MAX_SESSIONS = 64
MAX_AUDIT_SIZE = 2 * 1024 * 1024
_sessions = {}
_login_attempts = collections.defaultdict(collections.deque)
_session_lock = threading.Lock()
_login_lock = threading.Lock()
_audit_lock = threading.Lock()
_token_lock = threading.Lock()
_otp_lock = threading.Lock()
_used_otps = {}
_panel_request_lock = threading.Lock()


# ---------------------------------------------------------------- deps
def bootstrap_deps():
    try:
        __import__("psutil")
        return True
    except ImportError:
        print("[setup] psutil is required. Run: python -m pip install -r requirements.txt")
        return False


if not bootstrap_deps():
    print("Cannot continue without psutil. Install manually: pip install psutil")
    if os.name == "nt": os.system("pause")
    sys.exit(1)
import psutil  # noqa: E402


# ---------------------------------------------------------------- utils
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def atomic_write(path, data):
    tmp = path + ".tmp." + secrets.token_hex(4)
    try:
        with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    out = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out._buf = buf
    return out


def dpapi_protect(text):
    if not IS_WIN:
        return base64.b64encode(text.encode()).decode()
    inp, out = _blob(text.encode("utf-8")), _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    try:
        return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode()
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def dpapi_unprotect(value):
    raw = base64.b64decode(value)
    if not IS_WIN:
        return raw.decode()
    inp, out = _blob(raw), _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def harden_file(path):
    if not IS_WIN or not os.path.exists(path):
        return True
    rc, _out = run_cmd(["icacls", path, "/inheritance:r", "/grant:r",
                        "*S-1-5-32-544:F", "*S-1-5-18:F"], timeout=20)
    return rc == 0


def harden_private_storage():
    if not IS_WIN:
        return True
    rc, _out = run_cmd(["icacls", BASE_DIR, "/inheritance:r", "/grant:r",
                        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], timeout=30)
    return rc == 0

def run_cmd(args, timeout=25):
    try:
        kw = dict(capture_output=True, timeout=timeout)
        if IS_WIN: kw["creationflags"] = NO_WINDOW
        r = subprocess.run(args, **kw)
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        return r.returncode, out
    except Exception as e:
        return -1, repr(e)

def human_b(n):
    if n is None: return None
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024: return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024
    return "%.1f PB" % n


# ---------------------------------------------------------------- state
def get_state(readonly=False, initialize_only=False):
    st = {} if initialize_only else load_json(STATE_FILE, {})
    changed = False
    legacy_plaintext_token = bool(st.get("token"))
    if st.get("token"):
        if not st.get("token_enc"):
            st["token_enc"] = dpapi_protect(st["token"])
        st.pop("token", None); changed = True
    if legacy_plaintext_token:
        # Old releases exposed a URL token and enabled an administrator shell.
        # A migration must not silently preserve those dangerous defaults.
        st["exec_enabled"] = False
        st["downloads_enabled"] = False
        changed = True
    if not st.get("token_enc"):
        st["token_enc"] = dpapi_protect(secrets.token_urlsafe(32))
        st["created"] = time.time(); changed = True
    for k, v in (("port", 8399), ("bind", "127.0.0.1"),
                 ("exec_enabled", False), ("downloads_enabled", False),
                 ("download_roots", [RDPDIR]), ("tls_cert", ""),
                 ("tls_key", ""), ("allowed_ips", []), ("server_name", "")):
        if k not in st: st[k] = v; changed = True
    if changed and not readonly:
        atomic_write(STATE_FILE, st)
    if not readonly and not harden_file(STATE_FILE):
        raise PermissionError("could not protect webconsole_state.json ACL")
    return st

# RDPWC_NO_INIT=1 lets tests and tooling import this module without requiring
# Administrator rights or touching the real state/ACL.
_NO_INIT = os.environ.get("RDPWC_NO_INIT") == "1"

if IS_WIN and not _NO_INIT and not ctypes.windll.shell32.IsUserAnAdmin():
    print("RDPWebConsole must run from an Administrator terminal.")
    sys.exit(1)

STATE = get_state(readonly=_NO_INIT, initialize_only=_NO_INIT)
TOKEN = os.environ.get("RDPWC_TOKEN") or dpapi_unprotect(STATE["token_enc"])
_token_cache = {"mtime": 0.0, "value": TOKEN}


def current_token():
    """Return the live login token, reloading it if the state file changed.

    This lets rotate-token take effect without restarting the server.
    """
    if os.environ.get("RDPWC_TOKEN"):
        return os.environ["RDPWC_TOKEN"]
    with _token_lock:
        try:
            mtime = os.stat(STATE_FILE).st_mtime_ns
        except OSError:
            return _token_cache["value"]
        if mtime != _token_cache["mtime"]:
            st = load_json(STATE_FILE, {}) or {}
            enc = st.get("token_enc")
            try:
                value = dpapi_unprotect(enc) if enc else _token_cache["value"]
            except Exception:
                value = _token_cache["value"]
            if value != _token_cache["value"]:
                with _session_lock:
                    _sessions.clear()
                _token_cache["value"] = value
            _token_cache["mtime"] = mtime
        return _token_cache["value"]
try:
    PORT = max(1024, min(65535, int(os.environ.get("RDPWC_PORT", str(STATE.get("port", 8399))))))
except ValueError:
    PORT = 8399
BIND = os.environ.get("RDPWC_BIND", STATE.get("bind", "127.0.0.1"))
EXEC_ENABLED = bool(STATE.get("exec_enabled", False))
DOWNLOADS_ENABLED = bool(STATE.get("downloads_enabled", False))

def audit(action, detail=""):
    rec = {"t": time.time(), "action": action, "detail": str(detail)[:300]}
    with _audit_lock:
        try:
            existed = os.path.exists(AUDIT_FILE)
            if existed and os.path.getsize(AUDIT_FILE) >= MAX_AUDIT_SIZE:
                old = AUDIT_FILE + ".1"
                try: os.remove(old)
                except FileNotFoundError: pass
                os.replace(AUDIT_FILE, old)
                existed = False
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if not existed:
                harden_file(AUDIT_FILE)
        except (OSError, ValueError): pass
    print("[audit] %s %s" % (action, detail))


# ---------------------------------------------------------------- RDPMonitor integration
def rdpm_config(): return load_json(os.path.join(RDPDIR, "config.json"), {}) or {}
def rdpm_blocked(): return load_json(os.path.join(RDPDIR, "blocked.json"), {}) or {}
def rdpm_traffic(): return load_json(os.path.join(RDPDIR, "traffic.json"), {}) or {}
def rdpm_history(): return load_json(os.path.join(RDPDIR, "history.json"), []) or []


@contextlib.contextmanager
def blocked_file_guard():
    """Cross-process mutex shared with the patched RDPMonitor core."""
    handle = None
    acquired = False
    try:
        if IS_WIN:
            name = "Global\\RDPMonitorBlocked_" + hashlib.sha256(
                os.path.abspath(RDPDIR).lower().encode()).hexdigest()[:20]
            k = ctypes.windll.kernel32
            k.CreateMutexW.restype = ctypes.c_void_p
            k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            k.WaitForSingleObject.restype = ctypes.c_ulong
            k.ReleaseMutex.argtypes = [ctypes.c_void_p]
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k.CreateMutexW(None, False, name)
            if not handle:
                raise TimeoutError("blocked.json lock creation failed")
            wait = k.WaitForSingleObject(handle, 15000)
            # WAIT_OBJECT_0 (0) and WAIT_ABANDONED (0x80) both mean we own the
            # mutex now; a previous holder that crashed must not lock us out.
            if wait not in (0, 0x80):
                raise TimeoutError("blocked.json lock timeout")
            acquired = True
        yield
    finally:
        if handle:
            if acquired:
                ctypes.windll.kernel32.ReleaseMutex(handle)
            ctypes.windll.kernel32.CloseHandle(handle)


def valid_ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None

def block_ip(ip):
    ip = valid_ip(ip)
    if not ip:
        return False, "invalid IP address"
    rc, out = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule",
                       "name=RDPMonitor Block %s" % ip, "dir=in", "action=block", "remoteip=%s" % ip])
    if rc == 0:
        try:
            with blocked_file_guard():
                b = rdpm_blocked(); b[ip] = time.time()
                atomic_write(os.path.join(RDPDIR, "blocked.json"), b)
        except Exception as e:
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule",
                     "name=RDPMonitor Block %s" % ip])
            audit("block_ip_rollback", "%s %r" % (ip, e))
            return False, "tracking update failed; firewall rule rolled back"
    audit("block_ip", ip)
    return rc == 0, out[:200]

def unblock_ip(ip):
    ip = valid_ip(ip)
    if not ip:
        return False, "invalid IP address"
    rc, out = run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule",
                       "name=RDPMonitor Block %s" % ip])
    qrc, count = run_cmd(["powershell", "-NoProfile", "-Command",
                          "(Get-NetFirewallRule -DisplayName 'RDPMonitor Block %s' "
                          "-ErrorAction SilentlyContinue).Count" % ip])
    gone = qrc == 0 and count.strip() in ("", "0")
    if gone:
        with blocked_file_guard():
            b = rdpm_blocked(); b.pop(ip, None)
            atomic_write(os.path.join(RDPDIR, "blocked.json"), b)
    audit("unblock_ip", ip)
    return gone, out[:200] if gone else "firewall rule still exists"

def rdp_sessions():
    rc, out = run_cmd(["qwinsta"]) if IS_WIN else (1, "")
    sessions = []
    if rc == 0 and out:
        states = {"active", "disc", "listen", "conn", "idle", "down"}
        for line in out.splitlines():
            toks = line.split()
            idx = None
            for i, t in enumerate(toks):
                if t.lower().rstrip("#") in states: idx = i; break
            if idx is None or idx < 2: continue
            user = toks[idx - 2]
            if not user or user.lower().startswith(("rdp-tcp", "console", "service", ">")): continue
            sessions.append({"session": toks[0].lstrip(">"), "user": user,
                             "id": toks[idx - 1], "state": toks[idx]})
    if not sessions:
        for u in psutil.users():
            term = u.terminal or "console"
            sessions.append({"session": term, "user": u.name, "id": "",
                             "state": "RDP" if "rdp" in term.lower() else "active"})
    return sessions

def get_rdp_ips():
    port = str(rdpm_config().get("rdp_port", 3389)); ips = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_ESTABLISHED and c.laddr and str(c.laddr.port) == port and c.raddr:
                ips.add(c.raddr.ip)
    except Exception: pass
    return sorted(ips)


# ---------------------------------------------------------------- live sampler
_lock = threading.Lock()
LIVE = {}
HIST = [] if _NO_INIT else load_json(HIST_FILE, [])
_prev = {"t": None, "net": {}, "disk": {}, "cpu_times": None}
proc_cpu_prev = {}
LAST_ERR = None

def sample_once():
    global LAST_ERR
    now = time.time(); prev_t = _prev["t"]
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        freq = psutil.cpu_freq()
        ct = psutil.cpu_times()
        steal = None
        if prev_t and _prev["cpu_times"] is not None and now > prev_t:
            dt = now - prev_t
            cap = dt * (psutil.cpu_count() or 1)
            acc = sum(v for v in ct._asdict().values()) - sum(v for v in _prev["cpu_times"]._asdict().values())
            steal = max(0.0, (cap - acc) / cap * 100.0)
        _prev["t"] = now; _prev["cpu_times"] = ct
        vm = psutil.virtual_memory(); sm = psutil.swap_memory()

        disks = []
        for p in psutil.disk_partitions(all=False):
            try: u = psutil.disk_usage(p.mountpoint)
            except Exception: continue
            disks.append({"dev": p.device, "mount": p.mountpoint, "fstype": p.fstype,
                          "total": u.total, "used": u.used, "free": u.free, "pct": u.percent})
        dmap = {}
        try:
            for name, c in (psutil.disk_io_counters(perdisk=True) or {}).items(): dmap[name] = c._asdict()
        except Exception: pass

        nics, nmap = [], {}
        try:
            counters = psutil.net_io_counters(pernic=True) or {}
            addrs = psutil.net_if_addrs() or {}
            stats = psutil.net_if_stats() or {}
            for name, c in counters.items():
                nmap[name] = c._asdict(); ips = []
                for a in addrs.get(name, []):
                    if int(a.family) == socket.AF_INET: ips.append(a.address)
                st = stats.get(name)
                nics.append({"name": name, "sent": c.bytes_sent, "recv": c.bytes_recv,
                             "errin": c.errin, "errout": c.errout, "dropin": c.dropin,
                             "dropout": c.dropout, "up": bool(st.isup) if st else None,
                             "speed": getattr(st, "speed", None) if st else None, "ips": ips})
        except Exception: pass

        apps = collections.defaultdict(lambda: {"cpu": 0.0, "ram": 0, "io_r": 0, "io_w": 0, "procs": 0, "pids": []})
        procs_rows = []
        for p in psutil.process_iter(["pid", "name", "username", "memory_info", "cpu_times",
                                      "io_counters", "create_time", "status"]):
            try:
                info = p.info; name = info.get("name") or "?"
                cpu_t = info.get("cpu_times"); mi = info.get("memory_info"); ioc = info.get("io_counters")
                cpu_now = 0.0
                if cpu_t:
                    cur = (cpu_t.user or 0) + (cpu_t.system or 0)
                    prevt = proc_cpu_prev.get(p.pid)
                    if prevt and now > prevt[1]:
                        cpu_now = max(0.0, (cur - prevt[0]) / (now - prevt[1]) * 100.0)
                    proc_cpu_prev[p.pid] = (cur, now)
                rss = getattr(mi, "rss", 0) or 0
                ior = getattr(ioc, "read_bytes", 0) if ioc is not None else 0
                iow = getattr(ioc, "write_bytes", 0) if ioc is not None else 0
                a = apps[name.lower()]
                a["cpu"] += cpu_now; a["ram"] += rss; a["io_r"] += ior; a["io_w"] += iow; a["procs"] += 1
                if len(a["pids"]) < 60: a["pids"].append(p.pid)
                if len(procs_rows) < 400:
                    procs_rows.append({"pid": p.pid, "name": name, "user": info.get("username") or "",
                                       "cpu": round(cpu_now, 1), "rss": rss, "status": info.get("status") or ""})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if len(proc_cpu_prev) > 1200:
            alive = set(x.pid for x in psutil.process_iter(["pid"]))
            for pid in list(proc_cpu_prev):
                if pid not in alive: del proc_cpu_prev[pid]
        prev_apps = LIVE.get("apps") or []
        prev_by = {a["app"]: a for a in prev_apps}
        dt = now - LIVE.get("ts", now - 2) if LIVE.get("ts") else 2.0
        app_list = []
        for name, a in apps.items():
            pa = prev_by.get(name); io_rps = io_wps = 0.0
            if pa and dt > 0:
                io_rps = max(0.0, (a["io_r"] - pa.get("io_r_total", 0)) / dt)
                io_wps = max(0.0, (a["io_w"] - pa.get("io_w_total", 0)) / dt)
            app_list.append({"app": name, "cpu": round(a["cpu"], 1), "ram": a["ram"], "procs": a["procs"],
                             "io_rps": round(io_rps, 1), "io_wps": round(io_wps, 1),
                             "io_r_total": a["io_r"], "io_w_total": a["io_w"], "pids": a["pids"]})
        app_list.sort(key=lambda x: -(x["cpu"] + x["ram"] / 1048576))

        net_rate, disk_rate = {}, {}
        dt = now - prev_t if prev_t else 0
        for name, cur in nmap.items():
            pv = _prev["net"].get(name)
            if pv and dt > 0:
                net_rate[name] = {"up": max(0, (cur["bytes_sent"] - pv["bytes_sent"]) / dt),
                                  "down": max(0, (cur["bytes_recv"] - pv["bytes_recv"]) / dt)}
        for name, cur in dmap.items():
            pv = _prev["disk"].get(name)
            if pv and dt > 0:
                disk_rate[name] = {"r": max(0, (cur["read_bytes"] - pv["read_bytes"]) / dt),
                                   "w": max(0, (cur["write_bytes"] - pv["write_bytes"]) / dt)}
        _prev["net"] = nmap; _prev["disk"] = dmap
        snap = {"ts": now,
                "cpu": {"pct": cpu_pct, "per_core": per_core, "cores": psutil.cpu_count(),
                        "physical": psutil.cpu_count(logical=False), "freq": getattr(freq, "current", None),
                        "freq_max": getattr(freq, "max", None),
                        "steal": round(steal, 1) if steal is not None else None,
                        "ctx": psutil.cpu_stats().ctx_switches, "irq": psutil.cpu_stats().interrupts},
                "ram": {"total": vm.total, "used": vm.used, "avail": vm.available, "pct": vm.percent,
                        "swap_total": sm.total, "swap_used": sm.used, "swap_pct": sm.percent},
                "disks": disks, "disk_rate": disk_rate, "nic_rate": net_rate,
                "up_bps": sum(v["up"] for v in net_rate.values()),
                "down_bps": sum(v["down"] for v in net_rate.values()),
                "disk_r_bps": sum(v["r"] for v in disk_rate.values()),
                "disk_w_bps": sum(v["w"] for v in disk_rate.values()),
                "nics": nics, "apps": app_list[:60],
                "procs": sorted(procs_rows, key=lambda x: -x["cpu"])[:40],
                "proc_count": sum(a["procs"] for a in apps.values()),
                "sessions": rdp_sessions() if (int(now) % 10) < 2 or not LIVE.get("sessions") else LIVE.get("sessions"),
                "rdp_ips": get_rdp_ips() if (int(now) % 30) < 2 or not LIVE.get("rdp_ips") else LIVE.get("rdp_ips")}
        with _lock:
            LIVE.clear(); LIVE.update(snap)
    except Exception as e:
        LAST_ERR = repr(e)

def per_minute_job():
    while True:
        time.sleep(60)
        try:
            with _lock: s = dict(LIVE)
            if not s: continue
            HIST.append({"t": time.time(), "c": s["cpu"]["pct"], "r": s["ram"]["pct"],
                         "steal": s["cpu"].get("steal"), "up": s["up_bps"], "down": s["down_bps"],
                         "dr": s["disk_r_bps"], "dw": s["disk_w_bps"]})
            cutoff = time.time() - 3 * 86400
            while HIST and HIST[0].get("t", 0) < cutoff: HIST.pop(0)
            atomic_write(HIST_FILE, HIST)
        except Exception: pass


# ---------------------------------------------------------------- actions
def act_kill(pids):
    n, errs = 0, []
    for pid in list(pids)[:50]:
        try:
            pid = int(pid)
            if pid in (0, 4, os.getpid()):
                raise ValueError("protected PID")
            p = psutil.Process(pid); nm = p.name(); p.kill(); n += 1
            audit("kill", "%s pid=%s" % (nm, pid))
        except Exception as e: errs.append("%s:%s" % (pid, e))
    return n, errs

def act_proc_detail(pid):
    p = psutil.Process(int(pid))
    d = p.as_dict(attrs=["pid", "name", "exe", "cmdline", "username", "status", "create_time",
                         "cpu_percent", "memory_info", "io_counters", "num_threads"])
    try:
        conns_raw = p.net_connections()[:15]
    except Exception:
        conns_raw = []
    conns = [{"l": "%s:%s" % (c.laddr.ip, c.laddr.port) if c.laddr else "",
              "r": "%s:%s" % (c.raddr.ip, c.raddr.port) if c.raddr else "",
              "s": c.status} for c in conns_raw]
    mi, ioc = d.get("memory_info"), d.get("io_counters")
    audit("proc_detail", "%s" % pid)
    return {"pid": d.get("pid"), "name": d.get("name"), "exe": d.get("exe"),
            "cmdline": " ".join(d.get("cmdline") or [])[:500], "user": d.get("username"),
            "status": str(d.get("status")), "started": d.get("create_time"),
            "cpu": d.get("cpu_percent"), "rss": getattr(mi, "rss", None),
            "vms": getattr(mi, "vms", None), "threads": d.get("num_threads"),
            "io_read": getattr(ioc, "read_bytes", None), "io_write": getattr(ioc, "write_bytes", None),
            "conns": conns}

def act_clean_temp():
    freed, files = 0, 0
    for d in (tempfile.gettempdir(), r"C:\Windows\Temp"):
        if not os.path.isdir(d): continue
        for root, dirs, fs in os.walk(d):
            for f in fs:
                try:
                    fp = os.path.join(root, f)
                    if time.time() - os.path.getmtime(fp) < 86400: continue
                    sz = os.path.getsize(fp); os.unlink(fp); freed += sz; files += 1
                except Exception: continue
    audit("clean_temp", "%d files, %s" % (files, human_b(freed)))
    return files, freed

def act_msg(text):
    if IS_WIN: run_cmd(["msg", "*", text])
    audit("msg", "characters=%d" % len(text)); return True

def act_logoff(sid):
    sid = str(sid).strip()
    if not sid.isdigit() or len(sid) > 10:
        return False, "invalid session ID"
    rc, out = run_cmd(["logoff", str(sid)])
    audit("logoff", "session=%s rc=%d" % (sid, rc)); return rc == 0, out[:150]

def act_service(name, action):
    name = str(name)
    if not name or len(name) > 128 or not all(c.isalnum() or c in "_.-$ " for c in name):
        return False, "invalid service name"
    if action == "restart":
        rc1, o1 = run_cmd(["net", "stop", name], timeout=60)
        rc2, o2 = run_cmd(["net", "start", name], timeout=60)
        ok = rc2 == 0; out = (o1 + o2)[-250:]
    elif action == "start":
        rc, out = run_cmd(["net", "start", name], timeout=60); ok = rc == 0
    elif action == "stop":
        rc, out = run_cmd(["net", "stop", name], timeout=60); ok = rc == 0
    else:
        rc, out = run_cmd(["sc", "query", name]); ok = rc == 0
    audit("service_%s" % action, name); return ok, out

def act_list_services():
    rc, out = run_cmd(["powershell", "-NoProfile", "-Command",
                       "Get-Service | Where-Object {$_.StartType -ne 'Disabled'} | "
                       "Sort-Object {$_.Status -ne 'Running'}, DisplayName | "
                       "Select-Object -First 80 Status,Name,DisplayName | ConvertTo-Json -Compress"], timeout=40)
    try:
        items = json.loads(out)
        if isinstance(items, dict): items = [items]
        return [{"status": i.get("Status"), "name": i.get("Name"), "display": i.get("DisplayName")} for i in items]
    except Exception:
        return []

def act_run_command(cmd, timeout=30):
    if not EXEC_ENABLED:
        audit("run_command BLOCKED", "sha256=" + hashlib.sha256(cmd.encode()).hexdigest()[:16]); return False, "exec disabled in webconsole_state.json"
    audit("run_command", "sha256=" + hashlib.sha256(cmd.encode()).hexdigest()[:16])
    try:
        timeout = max(1, min(60, int(timeout)))
        kw = dict(capture_output=True, timeout=timeout)
        if IS_WIN: kw["creationflags"] = NO_WINDOW
        r = subprocess.run(cmd, shell=True, **kw)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
        return r.returncode == 0, out[-4000:]
    except Exception as e:
        return False, repr(e)

def act_start_program(path, args=""):
    if not EXEC_ENABLED:
        return False, "program execution disabled in webconsole_state.json"
    path = os.path.abspath(os.path.expandvars(str(path).strip().strip('"')))
    if not os.path.isfile(path):
        return False, "executable path does not exist"
    audit("start_program", path[:200])
    try:
        kw = {}
        if IS_WIN: kw["creationflags"] = 0x00000008  # DETACHED_PROCESS
        argv = [path] + shlex.split(str(args), posix=False)
        subprocess.Popen(argv, shell=False, **kw)
        return True, "started"
    except Exception as e:
        return False, repr(e)

def act_screenshot():
    audit("screenshot", "")
    try:
        from PIL import ImageGrab
    except ImportError:
        return None, "pillow is required; install dependencies before starting"
    os.makedirs(SHOT_DIR, exist_ok=True)
    fp = os.path.join(SHOT_DIR, "shot_%s.png" % secrets.token_hex(8))
    img = ImageGrab.grab(all_screens=True)
    img.save(fp)
    shots = sorted((os.path.join(SHOT_DIR, x) for x in os.listdir(SHOT_DIR)),
                   key=lambda x: os.path.getmtime(x), reverse=True)
    for old in shots[10:]:
        try: os.remove(old)
        except OSError: pass
    return fp, None

def act_sysinfo():
    u = psutil.virtual_memory(); d = []
    for p in psutil.disk_partitions(all=False):
        try:
            du = psutil.disk_usage(p.mountpoint)
            d.append({"dev": p.device, "total": du.total, "free": du.free})
        except Exception: pass
    import platform as pf
    return {"hostname": socket.gethostname(), "os": "%s %s" % (pf.system(), pf.release()),
            "version": pf.version(), "arch": pf.machine(), "python": pf.python_version(),
            "cpu_model": pf.processor() or "unknown", "cores": psutil.cpu_count(),
            "ram_total": u.total, "boot": psutil.boot_time(),
            "uptime_s": time.time() - psutil.boot_time(), "disks": d,
            "external_ip": next((ip for nic in LIVE.get("nics", [])
                                 for ip in nic.get("ips", [])), None)}

def act_netstat(limit=60):
    rows = []
    for c in psutil.net_connections(kind="tcp"):
        if c.status != psutil.CONN_ESTABLISHED or not c.raddr: continue
        proc = ""
        try:
            if c.pid: proc = psutil.Process(c.pid).name()
        except Exception: pass
        rows.append({"l": "%s:%s" % (c.laddr.ip, c.laddr.port), "r": "%s:%s" % (c.raddr.ip, c.raddr.port),
                     "pid": c.pid, "proc": proc})
        if len(rows) >= limit: break
    return rows

def act_reboot():
    audit("reboot", "requested")
    rc, _out = run_cmd(["shutdown", "/r", "/t", "5"])
    return rc == 0

def act_shutdown():
    audit("shutdown", "requested")
    rc, _out = run_cmd(["shutdown", "/s", "/t", "5"])
    return rc == 0


def backup_info():
    """Return a bounded, secret-free backup status snapshot."""
    cfg = load_json(os.path.join(BACKUP_DIR, "config.json"), {})
    last = load_json(os.path.join(BACKUP_DIR, "logs", "last_run.json"), {})
    worker = load_json(BACKUP_STATUS, {})
    items = []
    local_dir = os.path.join(BACKUP_DIR, "local_backups")
    try:
        names = sorted(os.listdir(local_dir), reverse=True)
        for name in names:
            path = os.path.join(local_dir, name)
            if not name.startswith("Backup_") or not os.path.isfile(path):
                continue
            items.append({"name": name, "size": os.path.getsize(path),
                          "modified": os.path.getmtime(path)})
            if len(items) >= 10:
                break
    except OSError:
        pass
    recent = []
    logs = os.path.join(BACKUP_DIR, "logs")
    try:
        log_files = sorted((os.path.join(logs, x) for x in os.listdir(logs)
                            if x.startswith("backup_") and x.endswith(".log")),
                           key=os.path.getmtime, reverse=True)
        if log_files:
            with open(log_files[0], "r", encoding="utf-8", errors="replace") as f:
                recent = list(collections.deque((x.rstrip() for x in f), maxlen=30))
    except OSError:
        pass
    bcfg, scfg, ccfg = cfg.get("backup", {}), cfg.get("schedule", {}), cfg.get("cloud", {})
    progress = load_json(os.path.join(BACKUP_CONTROL_DIR, "progress.json"), {}) or {}
    return {"installed": os.path.isfile(os.path.join(BACKUP_DIR, "app", "main.py")),
            "worker": worker, "last": last, "items": items, "recent_log": recent,
            "progress": progress,
            "settings": {"engine": bcfg.get("engine", "zip"),
                         "sources": len(bcfg.get("sources", [])),
                         "schedule_enabled": bool(scfg.get("enabled", False)),
                         "schedule_time": scfg.get("time", ""),
                         "cloud_destinations": len(ccfg.get("remotes", [])),
                         "keep_local_copies": bcfg.get("keep_local_copies", 1),
                         "config_version": (cfg.get("_meta") or {}).get("version", 0),
                         "config_revision": (cfg.get("_meta") or {}).get("revision", 0),
                         "drill_enabled": bool((cfg.get("restore_drill") or {}).get("enabled")),
                         "drill_interval_days": (cfg.get("restore_drill") or {}).get("interval_days", 7)}}


def act_backup_now():
    """Queue a single validated request for the isolated SYSTEM worker."""
    if not os.path.isfile(os.path.join(BACKUP_DIR, "app", "main.py")):
        return False, "backup component is not installed"
    os.makedirs(BACKUP_CONTROL_DIR, exist_ok=True)
    lock_path = os.path.join(BACKUP_CONTROL_DIR, "request.lock")
    # Clear a lock file abandoned by a crash so "Backup now" is not blocked
    # forever; a live request is consumed by the worker within seconds.
    try:
        if os.path.exists(lock_path) and time.time() - os.path.getmtime(lock_path) > 120:
            os.remove(lock_path)
    except OSError:
        pass
    fd = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        if os.path.exists(BACKUP_REQUEST):
            # Drop a request the worker never picked up (for example it was down).
            req = load_json(BACKUP_REQUEST, {}) or {}
            if time.time() - float(req.get("created", 0) or 0) > 3600:
                try:
                    os.remove(BACKUP_REQUEST)
                except OSError:
                    pass
        if os.path.exists(BACKUP_REQUEST):
            return False, "a backup request is already pending"
        request_id = secrets.token_urlsafe(18)
        atomic_write(BACKUP_REQUEST, {"version": 1, "id": request_id,
                                     "action": "backup", "created": time.time(),
                                     "requested_by": "webconsole"})
        audit("backup_now", "request=" + request_id[:10])
        return True, request_id
    except FileExistsError:
        return False, "another backup request is being queued"
    except Exception as e:
        return False, repr(e)
    finally:
        if fd is not None:
            os.close(fd)
            try: os.remove(lock_path)
            except OSError: pass


def act_backup_gui():
    """Open the fixed backup settings GUI in the current user session."""
    script = os.path.join(BACKUP_DIR, "app", "main.py")
    if not os.path.isfile(script):
        return False, "backup component is not installed"
    try:
        subprocess.Popen([sys.executable, script], cwd=os.path.dirname(script), shell=False)
        audit("backup_gui", script)
        return True, "backup settings opened"
    except Exception as e:
        return False, repr(e)


def panel_request(action, args=None, timeout=25):
    """Serialize the single-slot monitor mailbox until its response arrives."""
    deadline = time.monotonic() + timeout
    if not _panel_request_lock.acquire(timeout=max(0, timeout)):
        return False, "timed out waiting for the monitor mailbox"
    try:
        os.makedirs(MONITOR_CONTROL_DIR, exist_ok=True)
        while os.path.exists(MONITOR_REQUEST):
            if time.monotonic() >= deadline:
                return False, "a monitor request is already pending"
            time.sleep(0.1)
        rid = secrets.token_hex(8)
        atomic_write(MONITOR_REQUEST, {"id": rid, "action": action,
                                      "args": args or {}, "created": time.time()})
        while time.monotonic() < deadline:
            res = load_json(MONITOR_RESULT, {})
            if res.get("id") == rid:
                return bool(res.get("ok")), res.get("out")
            time.sleep(0.1)
        return False, "timed out waiting for the monitor"
    finally:
        _panel_request_lock.release()


def _backup_module(name):
    import importlib
    path = os.path.join(BACKUP_DIR, "app")
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def act_restore(name):
    """Restore one archive into an isolated folder under the suite root."""
    name = str(name).strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return False, "invalid archive name"
    try:
        restore_mod = _backup_module("restore")
        config_manager = _backup_module("config_manager")
        cfg = config_manager.load_config()
        password = (cfg.get("backup", {}).get("archive_password") or "").strip()
        entry = next((x for x in restore_mod.list_backups() if x["name"] == name), None)
        if not entry:
            return False, "archive not found"
        # A fresh, unique folder per restore so a repeat never overwrites.
        dest = restore_mod.new_restore_dir(os.path.join(RDPDIR, "restore"), name)
        res = restore_mod.restore_archive(entry["path"], dest, password=password)
        audit("restore", "%s -> %s (%s)" % (name, dest, res.get("status")))
        return res.get("status") == "ok", res.get("message", "")
    except Exception as e:
        return False, repr(e)


def act_drill():
    """Restore the newest archive into an isolated folder and verify it."""
    try:
        restore_mod = _backup_module("restore")
        config_manager = _backup_module("config_manager")
        cfg = config_manager.load_config()
        dest = (cfg.get("restore_drill", {}) or {}).get("dest", "")
        res = restore_mod.run_drill(cfg, dest, log=lambda *a, **k: None)
        audit("drill", str(res.get("status")))
        return res.get("status") == "ok", res.get("message", "")
    except Exception as e:
        return False, repr(e)


# ---------------------------------------------------------------- install / uninstall
def external_ip():
    for srv in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            import urllib.request
            return urllib.request.urlopen(srv, timeout=8).read().decode().strip()
        except Exception: continue
    return None

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin()) if IS_WIN else os.geteuid() == 0
    except Exception:
        return False


def parse_allowed_ips(raw):
    out = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(str(ipaddress.ip_network(item, strict=False)))
        except ValueError:
            raise ValueError("invalid allowed IP/network: " + item)
    return out


# ---------------------------------------------------------------- remote mode
TLS_DIR = os.path.join(BASE_DIR, "tls")
DEFAULT_CERT = os.path.join(TLS_DIR, "panel.crt.pem")
DEFAULT_KEY = os.path.join(TLS_DIR, "panel.key.pem")


def local_ipv4s():
    """Non-loopback IPv4 addresses on this host (works on any RDP/machine)."""
    ips = set()
    try:
        for _name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if getattr(a, "family", None) == socket.AF_INET and getattr(a, "address", ""):
                    if not a.address.startswith("127."):
                        ips.add(a.address)
    except Exception:
        pass
    return sorted(ips)


def ensure_tls_cert(extra_hosts=None):
    """Create a self-signed TLS certificate for the panel when one is missing."""
    os.makedirs(TLS_DIR, exist_ok=True)
    cert, key = DEFAULT_CERT, DEFAULT_KEY
    if os.path.isfile(cert) and os.path.isfile(key):
        return cert, key
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime as _dt
    key_obj = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, socket.gethostname() or "RDPWebConsole"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RDPWebConsole"),
    ])
    dns = {"localhost", socket.gethostname(), socket.getfqdn()}
    ips = {"127.0.0.1"}
    ips.update(local_ipv4s())
    for h in (extra_hosts or []):
        h = str(h).strip()
        if not h:
            continue
        try:
            ipaddress.ip_address(h); ips.add(h)
        except ValueError:
            dns.add(h)
    try:
        pub = external_ip()
        if pub:
            ips.add(pub)
    except Exception:
        pass
    san = [x509.DNSName(d) for d in sorted(x for x in dns if x)]
    san += [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]
    now = _dt.datetime.now(_dt.timezone.utc)
    crt = (x509.CertificateBuilder()
           .subject_name(name).issuer_name(name)
           .public_key(key_obj.public_key())
           .serial_number(x509.random_serial_number())
           .not_valid_before(now - _dt.timedelta(days=1))
           .not_valid_after(now + _dt.timedelta(days=825))
           .add_extension(x509.SubjectAlternativeName(san), critical=False)
           .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
           .sign(key_obj, hashes.SHA256()))
    with open(cert, "wb") as f:
        f.write(crt.public_bytes(serialization.Encoding.PEM))
    with open(key, "wb") as f:
        f.write(key_obj.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    try:
        if not harden_file(key):
            raise PermissionError("could not protect TLS private-key ACL")
    except Exception:
        os.remove(key)
        raise
    return cert, key


def rdp_client_ips():
    """Source IPs of the live RDP sessions (the people who should reach the panel)."""
    try:
        port = int(rdpm_config().get("rdp_port", 3389))
    except (TypeError, ValueError):
        port = 3389
    ips = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status != "ESTABLISHED" or not c.laddr or not c.raddr:
                continue
            if c.laddr.port == port and c.raddr.ip and not c.raddr.ip.startswith("127."):
                ips.add(c.raddr.ip)
    except Exception:
        pass
    return sorted(ips)


def default_allowed_ips():
    """Sensible allow-list: loopback + Tailscale + the live RDP client IPs."""
    allowed = {"127.0.0.1/32", "::1/128", "100.64.0.0/10"}
    for ip in local_ipv4s():
        allowed.add(ip + "/32")
    for ip in rdp_client_ips():
        allowed.add(ip + "/32")
    return sorted(allowed)


def firewall_apply(allowed, port):
    run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=%s" % RULE_NAME])
    remoteip = ",".join(allowed)
    rc, out = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule",
                       "name=%s" % RULE_NAME, "dir=in", "action=allow",
                       "protocol=TCP", "localport=%d" % int(port),
                       "remoteip=%s" % remoteip])
    return rc == 0, out


def firewall_remove():
    run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=%s" % RULE_NAME])


def restart_running_instance():
    """Stop the live server so the supervisor restarts it on the new bind."""
    try:
        pid = int(open(PID_FILE, encoding="ascii").read().strip())
    except (OSError, ValueError):
        return False
    try:
        p = psutil.Process(pid)
        if os.path.abspath(__file__).lower() in " ".join(p.cmdline()).lower():
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def remote_status():
    bind = STATE.get("bind", "127.0.0.1")
    remote = bind not in ("127.0.0.1", "::1", "localhost")
    port = STATE.get("port", 8399)
    scheme = "https" if remote else "http"
    urls = ["%s://127.0.0.1:%d/" % (scheme, port)]
    if remote:
        for ip in local_ipv4s():
            urls.append("%s://%s:%d/" % (scheme, ip, port))
        try:
            pub = external_ip()
        except Exception:
            pub = None
        if pub:
            urls.append("%s://%s:%d/" % (scheme, pub, port))
    urls = list(dict.fromkeys(urls))
    return {"remote": remote, "bind": bind, "port": port, "scheme": scheme,
            "allowed_ips": STATE.get("allowed_ips", []), "urls": urls}


def do_remote_enable(allowed=None):
    if IS_WIN and not is_admin():
        print("Remote mode requires an Administrator terminal.")
        return 1
    if not harden_private_storage():
        print("Could not protect the WebConsole directory ACL.")
        return 1
    try:
        cert, key = ensure_tls_cert()
    except Exception as e:
        print("Could not create the TLS certificate: %r" % e)
        return 1
    if allowed:
        raw = ",".join(allowed) if isinstance(allowed, (list, tuple)) else str(allowed)
        try:
            allowed = parse_allowed_ips(raw)
        except ValueError as e:
            print(e); return 1
    else:
        allowed = parse_allowed_ips(",".join(default_allowed_ips()))
    if not allowed:
        print("At least one allowed IP is required.")
        return 1
    previous = dict(STATE)
    STATE.update({"bind": "0.0.0.0", "port": PORT, "tls_cert": cert,
                  "tls_key": key, "allowed_ips": allowed})
    try:
        atomic_write(STATE_FILE, STATE)
        if not harden_file(STATE_FILE):
            raise PermissionError("could not protect state-file ACL")
    except Exception as e:
        STATE.clear(); STATE.update(previous)
        print("State update failed: %r" % e); return 1
    ok, out = firewall_apply(allowed, PORT)
    if not ok:
        restore_install_state(previous)
        print("Firewall setup failed; settings restored: " + out.strip()[:300]); return 1
    restart_running_instance()
    print("Remote mode enabled (https on 0.0.0.0:%d)." % PORT)
    print("Allowed: " + ", ".join(allowed))
    for u in remote_status()["urls"]:
        print("  " + u)
    return 0


def do_remote_disable():
    if IS_WIN and not is_admin():
        print("Remote mode requires an Administrator terminal.")
        return 1
    STATE.update({"bind": "127.0.0.1", "tls_cert": "", "tls_key": "",
                  "allowed_ips": []})
    atomic_write(STATE_FILE, STATE); harden_file(STATE_FILE)
    firewall_remove()
    restart_running_instance()
    print("Remote mode disabled; bind reset to 127.0.0.1.")
    return 0


def do_remote_allow(items, add=True):
    if IS_WIN and not is_admin():
        print("Remote mode requires an Administrator terminal.")
        return 1
    try:
        new = [str(x) for x in parse_allowed_ips(",".join(items))]
    except ValueError as e:
        print(e); return 1
    current = list(STATE.get("allowed_ips", []))
    if add:
        current = sorted(set(current) | set(new))
    else:
        current = sorted(set(current) - set(new))
    if not current:
        print("Refusing to leave an empty allow-list; use remote-disable instead.")
        return 1
    previous = dict(STATE)
    STATE["allowed_ips"] = current
    atomic_write(STATE_FILE, STATE)
    if not harden_file(STATE_FILE):
        restore_install_state(previous)
        print("Could not protect the state-file ACL.")
        return 1
    if STATE.get("bind") not in ("127.0.0.1", "::1", "localhost"):
        ok, out = firewall_apply(current, STATE.get("port", PORT))
        if not ok:
            restore_install_state(previous)
            print("Firewall setup failed; settings restored: " + out.strip()[:300])
            return 1
    restart_running_instance()
    print("Allowed IPs: " + ", ".join(current))
    return 0


def restore_install_state(previous):
    """Best-effort rollback for a failed install or upgrade."""
    STATE.clear(); STATE.update(previous)
    atomic_write(STATE_FILE, STATE)
    harden_file(STATE_FILE)
    run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule",
             "name=%s" % RULE_NAME])
    old_bind = previous.get("bind", "127.0.0.1")
    old_allowed = previous.get("allowed_ips", [])
    if old_bind not in ("127.0.0.1", "::1", "localhost") and old_allowed:
        run_cmd(["netsh", "advfirewall", "firewall", "add", "rule",
                 "name=%s" % RULE_NAME, "dir=in", "action=allow", "protocol=TCP",
                 "localport=%d" % int(previous.get("port", 8399)),
                 "remoteip=%s" % ",".join(old_allowed)])


def do_install(port, remote=False):
    global BIND, PORT
    if IS_WIN and not is_admin():
        print("Install requires an Administrator terminal.")
        return 1
    if not harden_private_storage():
        print("Could not protect the WebConsole directory ACL.")
        return 1
    previous = dict(STATE)
    if remote:
        cert = os.environ.get("RDPWC_TLS_CERT", STATE.get("tls_cert", ""))
        key = os.environ.get("RDPWC_TLS_KEY", STATE.get("tls_key", ""))
        try:
            allowed = parse_allowed_ips(os.environ.get(
                "RDPWC_ALLOWED_IPS", ",".join(STATE.get("allowed_ips", []))))
        except ValueError as e:
            print(e); return 1
        if not os.path.isfile(cert) or not os.path.isfile(key) or not allowed:
            print("Remote mode refused. It requires TLS files and an IP allow-list:")
            print("  set RDPWC_TLS_CERT=C:\\path\\cert.pem")
            print("  set RDPWC_TLS_KEY=C:\\path\\key.pem")
            print("  set RDPWC_ALLOWED_IPS=203.0.113.5/32")
            return 1
        STATE.update({"bind": "0.0.0.0", "port": port, "tls_cert": cert,
                      "tls_key": key, "allowed_ips": allowed})
        if not harden_file(key):
            print("Could not protect the TLS private-key ACL.")
            return 1
        BIND, PORT = "0.0.0.0", port
    else:
        STATE.update({"bind": "127.0.0.1", "port": port,
                      "tls_cert": "", "tls_key": "", "allowed_ips": []})
        BIND, PORT = "127.0.0.1", port
    try:
        atomic_write(STATE_FILE, STATE)
        if not harden_file(STATE_FILE):
            raise PermissionError("could not protect state-file ACL")
    except Exception as e:
        STATE.clear(); STATE.update(previous)
        print("State update failed: %r" % e)
        return 1
    print("[1/4] bind set to %s ..." % BIND)
    print("[2/4] firewall rule ...")
    run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=%s" % RULE_NAME])
    if remote:
        rc, out = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", "name=%s" % RULE_NAME,
                           "dir=in", "action=allow", "protocol=TCP", "localport=%d" % port,
                           "remoteip=%s" % ",".join(STATE["allowed_ips"])])
        if rc != 0:
            restore_install_state(previous)
            print("Firewall setup failed; settings restored: " + out.strip()[:300]); return 1
    else:
        rc, out = 0, "local-only; no firewall opening"
    print("      ", "OK" if rc == 0 else out.strip()[:120])
    print("[3/4] scheduled task at logon ...")
    py = sys.executable
    script = os.path.join(BASE_DIR, "RDPWebConsole.py")
    rc, out = run_cmd(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON", "/RL", "HIGHEST",
                       "/TR", '"%s" "%s" --run' % (py, script)])
    print("      ", "OK" if rc == 0 else out.strip()[:200])
    if rc != 0:
        if remote:
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule",
                     "name=%s" % RULE_NAME])
        restore_install_state(previous)
        print("Scheduled task setup failed; settings/firewall restored: " + out.strip()[:300]); return 1
    print("[4/4] done.")
    ip = external_ip() or "<YOUR_SERVER_IP>" if remote else "127.0.0.1"
    scheme = "https" if remote else "http"
    print("=" * 62)
    print("  CONSOLE: %s://%s:%d/" % (scheme, ip, PORT))
    print("  LOGIN TOKEN (store securely): %s" % TOKEN)
    print("=" * 62)
    print("  Token is entered on the login screen and is never placed in the URL.")
    return 0

def do_uninstall():
    was_remote = STATE.get("bind") not in ("127.0.0.1", "::1", "localhost")
    run_cmd(["schtasks", "/End", "/TN", TASK_NAME])
    try:
        pid = int(open(PID_FILE, encoding="ascii").read().strip())
        p = psutil.Process(pid)
        cmdline = " ".join(p.cmdline())
        script = os.path.abspath(__file__)
        if script.lower() in cmdline.lower():
            p.terminate()
            p.wait(timeout=10)
    except (OSError, ValueError, psutil.Error):
        pass
    rc1, out1 = run_cmd(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    rc2, out2 = run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=%s" % RULE_NAME])
    STATE.update({"bind": "127.0.0.1", "tls_cert": "", "tls_key": "",
                  "allowed_ips": []})
    atomic_write(STATE_FILE, STATE)
    harden_file(STATE_FILE)
    if rc1 != 0:
        print("task removal failed: " + out1[-300:])
    if rc2 != 0 and was_remote:
        print("firewall removal failed: " + out2[-300:])
    print("uninstall finished; bind reset to 127.0.0.1")
    return 0 if rc1 == 0 and (rc2 == 0 or not was_remote) else 1


_web_mutex = None


def acquire_instance_lock():
    global _web_mutex
    if not IS_WIN:
        return True
    name = "Global\\RDPWebConsole_" + hashlib.sha256(
        BASE_DIR.lower().encode()).hexdigest()[:20]
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k.CreateMutexW(None, False, name)
    if not handle:
        return False
    if k.GetLastError() == 183:
        k.CloseHandle(handle)
        return False
    _web_mutex = handle
    return True


def remote_security_config():
    cert = os.environ.get("RDPWC_TLS_CERT", STATE.get("tls_cert", ""))
    key = os.environ.get("RDPWC_TLS_KEY", STATE.get("tls_key", ""))
    allowed = STATE.get("allowed_ips", [])
    if BIND not in ("127.0.0.1", "::1", "localhost"):
        if not os.path.isfile(cert) or not os.path.isfile(key) or not allowed:
            raise RuntimeError("non-loopback bind requires TLS cert/key and allowed_ips")
    return cert, key


# ---------------------------------------------------------------- HTTP
def client_allowed(addr):
    try:
        ip = ipaddress.ip_address(addr)
        if BIND in ("127.0.0.1", "::1", "localhost"):
            return ip.is_loopback
        networks = [ipaddress.ip_network(x, strict=False)
                    for x in STATE.get("allowed_ips", [])]
        return any(ip in net for net in networks)
    except ValueError:
        return False


def login_rate_limited(addr):
    now = time.time()
    with _login_lock:
        dq = _login_attempts[addr]
        while dq and now - dq[0] > 300:
            dq.popleft()
        return len(dq) >= 10


def login_record_failure(addr):
    with _login_lock:
        _login_attempts[addr].append(time.time())


def login_clear_failures(addr):
    with _login_lock:
        _login_attempts.pop(addr, None)


def user_action_arguments(body):
    """Canonical arguments used for both confirmation and eventual dispatch."""
    op = str(body.get("op", ""))
    if op not in ("add", "enable", "disable", "delete", "password", "rename"):
        raise ValueError("invalid user operation")
    name = str(body.get("name", ""))
    value = str(body.get("value", ""))
    if not name or len(name) > 40 or len(value) > 64:
        raise ValueError("invalid user arguments")
    return {"op": op, "name": name, "value": value}


def user_confirmation_digest(args):
    """Bind a nonce to exact arguments without retaining plaintext passwords."""
    data = json.dumps(args, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(current_token().encode("utf-8"), data, hashlib.sha256).hexdigest()


def action_confirmation_digest(action, body):
    args = user_action_arguments(body) if action == "user" else confirmation_arguments(body)
    return user_confirmation_digest({"action": action, "arguments": args})


def operator_records():
    state = STATE if _NO_INIT else load_json(STATE_FILE, {})
    records = (state or {}).get("operators", {})
    if not isinstance(records, dict):
        return {}
    return {name: record for name, record in list(records.items())[:64]
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", name)
            and isinstance(record, dict)
            and re.fullmatch(r"[0-9a-f]{64}", str(record.get("token_sha256", "")))}


def authenticate_login(token):
    if hmac.compare_digest(str(token).encode("utf-8"), current_token().encode("utf-8")):
        return "owner", ""
    fingerprint = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    for name, record in operator_records().items():
        if isinstance(record, dict) and hmac.compare_digest(str(record.get("token_sha256", "")), fingerprint):
            return "operator:" + str(name), fingerprint
    return None, ""


def create_session(addr, actor="owner", credential_hash=""):
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with _session_lock:
        now = time.time()
        for key in [k for k, v in _sessions.items() if v["expires"] < now]:
            del _sessions[key]
        while len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["created"])
            del _sessions[oldest]
        _sessions[sid] = {"csrf": csrf, "created": now,
                          "expires": now + SESSION_TTL,
                          "addr": addr, "confirm": {}, "actor": actor,
                          "credential_hash": credential_hash}
    return sid, csrf


def verify_otp(otp, exp):
    """Atomically consume an unexpired signed login link once per server."""
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    now = time.time()
    if exp_i < now:
        return False
    want = hmac.new(current_token().encode("utf-8"), str(exp_i).encode("ascii"),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(otp).encode("utf-8"), want.encode("ascii")):
        return False
    with _otp_lock:
        for used in [key for key, expires in _used_otps.items() if expires < now]:
            del _used_otps[used]
        if want in _used_otps:
            return False
        _used_otps[want] = exp_i
        return True


def path_in_roots(path, roots):
    # Compare case-insensitively on Windows so a differently-cased drive or
    # folder is not rejected as "outside approved roots".
    target = os.path.normcase(path)
    for root in roots:
        try:
            if os.path.commonpath([target, os.path.normcase(root)]) == os.path.normcase(root):
                return True
        except ValueError:
            continue
    return False


class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(MAX_THREADS)
        self.tls_context = None
        if ":" in args[0][0]:
            self.address_family = socket.AF_INET6
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            if self.tls_context is not None:
                request.settimeout(15)
                try:
                    request = self.tls_context.wrap_socket(request, server_side=True)
                except (OSError, ssl.SSLError):
                    request.close()
                    return
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "RDPWebConsole/2.0"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *a): pass

    def _json(self, code, obj):
        self._finish_usage(code, obj)
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _finish_usage(self, code, obj):
        context = getattr(self, "_usage_context", None)
        if context is None:
            return
        self._usage_context = None
        status = "ok" if code < 400 and obj.get("ok") is not False and not obj.get("error") else (
            "failed" if code >= 500 or obj.get("ok") is False else "denied")
        try:
            append_event(USAGE_FILE, source="webconsole", actor=context["actor"],
                         action=context["action"], status=status, session=context.get("session", ""),
                         request_id=context["request_id"],
                         duration_ms=(time.monotonic() - context["started"]) * 1000)
        except Exception as exc:
            print(f"[audit] Usage recording failed: {type(exc).__name__}", file=sys.stderr)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if isinstance(self.connection, ssl.SSLSocket):
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; frame-src 'none'; "
                         "media-src 'none'; worker-src 'none'; manifest-src 'none'; "
                         "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                         "form-action 'self'")

    def _host_ok(self):
        """Reject DNS-rebinding style requests by validating the Host header.

        Loopback mode only accepts loopback names. Remote mode accepts IP
        literals plus any hostnames explicitly listed in state["server_name"],
        so an attacker-controlled domain cannot be used to reach the panel.
        """
        host = self.headers.get("Host", "").lower().strip()
        if host.startswith("["):
            name = host.split("]", 1)[0] + "]"
        else:
            name = host.split(":", 1)[0]
        if BIND in ("127.0.0.1", "::1", "localhost"):
            return name in ("127.0.0.1", "localhost", "[::1]")
        try:
            ipaddress.ip_address(name.strip("[]"))
            return True
        except ValueError:
            pass
        allowed_names = [n.strip().lower() for n in
                         str(STATE.get("server_name", "") or "").split(",") if n.strip()]
        return name in allowed_names

    def _session(self):
        current_token()  # A rotation in a separate CLI process revokes sessions.
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            sid = cookie.get("rdpwc_session").value
        except Exception:
            return None, None
        with _session_lock:
            sess = _sessions.get(sid)
            if not sess or sess["expires"] < time.time() \
                    or sess["addr"] != self.client_address[0]:
                _sessions.pop(sid, None)
                return None, None
            actor = sess.get("actor", "owner")
            if actor.startswith("operator:"):
                record = operator_records().get(actor.split(":", 1)[1], {})
                expected = record.get("token_sha256", "") if isinstance(record, dict) else ""
                if not expected or not hmac.compare_digest(str(expected), sess.get("credential_hash", "")):
                    _sessions.pop(sid, None)
                    return None, None
            sess["expires"] = time.time() + SESSION_TTL
            return sid, sess

    def _authed(self):
        return self._session()[1] is not None

    def _body(self):
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise ValueError("transfer encoding is not supported")
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            self.close_connection = True
            raise ValueError("invalid content length")
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            raise OverflowError("request body too large")
        raw = self.rfile.read(n)
        if len(raw) != n:
            self.close_connection = True
            raise ValueError("incomplete request body")
        body = json.loads(raw.decode("utf-8")) if n else {}
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        return body

    def do_GET(self):
        self._usage_context = None
        u = urlparse(self.path)
        if not self._host_ok(): return self._json(421, {"error": "invalid Host header"})
        if not client_allowed(self.client_address[0]):
            return self._json(403, {"error": "client IP not allowed"})
        if u.path in ("/", "/index.html"):
            qs = parse_qs(u.query)
            otp = (qs.get("otp") or [""])[0]
            exp = (qs.get("exp") or [""])[0]
            if otp and exp and verify_otp(otp, exp):
                # One-time auto-login: set the session cookie and drop the params.
                sid, _csrf = create_session(self.client_address[0])
                self.send_response(302)
                secure = "; Secure" if isinstance(self.connection, ssl.SSLSocket) else ""
                self.send_header("Set-Cookie",
                                 "rdpwc_session=%s; HttpOnly; SameSite=Strict; Path=/%s"
                                 % (sid, secure))
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self._security_headers(); self.end_headers()
                return
            try:
                with open(HTML_PATH, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._security_headers()
                self.end_headers(); self.wfile.write(body)
            except OSError as e:
                self._json(500, {"error": "UI file missing: %r" % e})
            return
        if u.path == "/health": return self._json(200, {"ok": True, "ts": time.time()})
        if u.path == "/api/session":
            _sid, sess = self._session()
            return self._json(200 if sess else 401,
                              {"ok": bool(sess), "csrf": sess.get("csrf") if sess else ""})
        if not self._authed(): return self._json(401, {"error": "authentication required"})
        if u.path == "/api/stats":
            with _lock: s = dict(LIVE)
            s["err"] = LAST_ERR
            return self._json(200, s)
        if u.path == "/api/history":
            return self._json(200, {"points": HIST[-1500:], "rdpmon": rdpm_history()[-1500:]})
        if u.path == "/api/security":
            cfg = {k: v for k, v in rdpm_config().items()
                   if not any(x in k.lower() for x in ("token", "secret", "password",
                                                       "passphrase", "key", "auth",
                                                       "credential", "private"))}
            return self._json(200, {"config": cfg, "blocked": rdpm_blocked(),
                                    "traffic": rdpm_traffic(), "sessions": rdp_sessions(),
                                    "rdp_ips": LIVE.get("rdp_ips", [])})
        if u.path == "/api/proc":
            pid = (parse_qs(u.query).get("pid") or ["0"])[0]
            try: return self._json(200, act_proc_detail(pid))
            except Exception as e: return self._json(500, {"error": repr(e)})
        if u.path == "/api/sysinfo": return self._json(200, act_sysinfo())
        if u.path == "/api/netstat": return self._json(200, {"items": act_netstat()})
        if u.path == "/api/services": return self._json(200, {"items": act_list_services()})
        if u.path == "/api/backup": return self._json(200, backup_info())
        if u.path == "/api/docs":
            try:
                with open(os.path.join(RDPDIR, "docs", "COMMANDS.md"),
                          encoding="utf-8", errors="replace") as f:
                    return self._json(200, {"markdown": f.read()})
            except OSError:
                return self._json(404, {"error": "documentation is not generated yet"})
        if u.path == "/api/rdp":
            ok, out = panel_request("rdp_status", timeout=10)
            return self._json(200 if ok else 503, out if isinstance(out, dict) else {"error": out})
        if u.path == "/api/settings":
            ok, out = panel_request("settings_get", timeout=15)
            return self._json(200 if ok else 503, out if isinstance(out, dict) else {"error": out})
        if u.path == "/api/traps":
            ok, out = panel_request("trap", {"op": "list"}, timeout=10)
            return self._json(200 if ok else 503, {"items": out} if ok else {"error": out})
        if u.path == "/api/automation":
            which = (parse_qs(u.query).get("list") or [""])[0]
            ok, out = panel_request("automation", {"list": which, "op": "list"}, timeout=10)
            return self._json(200 if ok else 503, {"items": out} if ok else {"error": out})
        if u.path == "/api/users":
            ok, out = panel_request("users_list", timeout=20)
            return self._json(200 if ok else 503,
                              {"items": out} if ok else {"error": out})
        if u.path == "/api/diag":
            qs = parse_qs(u.query)
            op = (qs.get("op") or [""])[0]
            arg = (qs.get("arg") or [""])[0]
            if op not in ("diagnose", "logstats", "logs", "firewall", "netstat",
                          "when", "ps", "bigfiles", "temp", "startup", "updates",
                          "sysinfo", "harden", "report", "logins", "botlog",
                          "configbackup", "dumps", "speedtest", "nettest"):
                return self._json(400, {"error": "invalid diagnostic"})
            ok, out = panel_request("diag", {"op": op, "arg": arg[:64]}, timeout=150)
            return self._json(200 if ok else 503, {"text": out} if ok else {"error": out})
        if u.path == "/api/audit":
            try:
                with open(AUDIT_FILE, encoding="utf-8") as f:
                    lines = collections.deque(f, maxlen=200)
                    items = [json.loads(x) for x in lines if x.strip()]
                return self._json(200, {"items": items})
            except FileNotFoundError: return self._json(200, {"items": []})
        if u.path == "/api/usage":
            return self._json(200, summarize(read_events(USAGE_FILE)))
        if u.path == "/api/file":
            if not DOWNLOADS_ENABLED:
                return self._json(403, {"error": "file downloads are disabled"})
            fp = (parse_qs(u.query).get("path") or [""])[0]
            fp = os.path.realpath(fp)
            roots = [os.path.realpath(os.path.expandvars(x))
                     for x in STATE.get("download_roots", [])]
            if not path_in_roots(fp, roots):
                return self._json(403, {"error": "path outside approved roots"})
            if not os.path.isfile(fp): return self._json(404, {"error": "not a file"})
            size = os.path.getsize(fp)
            if size > MAX_DOWNLOAD:
                return self._json(413, {"error": "file exceeds 50 MB limit"})
            audit("download", fp)
            # Once the response headers are sent we cannot emit a second status
            # line. On a mid-stream error just close the connection.
            try:
                handle = open(fp, "rb")
            except OSError as e:
                return self._json(500, {"error": repr(e)})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            safe_name = os.path.basename(fp).replace('"', "_")
            self.send_header("Content-Disposition", "attachment; filename=\"%s\"" % safe_name)
            self.send_header("Content-Length", str(size))
            self._security_headers(); self.end_headers()
            try:
                with handle:
                    while True:
                        chunk = handle.read(64 * 1024)
                        if not chunk: break
                        self.wfile.write(chunk)
            except OSError:
                self.close_connection = True
            return
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        self._usage_context = {"action": "login" if u.path == "/api/login" else "request",
                               "actor": "unauthenticated", "request_id": secrets.token_hex(16),
                               "started": time.monotonic()}
        if not self._host_ok(): return self._json(421, {"error": "invalid Host header"})
        if not client_allowed(self.client_address[0]):
            return self._json(403, {"error": "client IP not allowed"})
        try:
            body = self._body()
        except OverflowError:
            return self._json(413, {"error": "request body too large"})
        except Exception:
            return self._json(400, {"error": "invalid JSON"})
        if u.path == "/api/login":
            addr = self.client_address[0]
            if login_rate_limited(addr):
                return self._json(429, {"error": "too many login attempts"})
            actor, credential_hash = authenticate_login(body.get("token", ""))
            if actor is None:
                login_record_failure(addr)
                time.sleep(0.25)
                return self._json(401, {"error": "invalid token"})
            login_clear_failures(addr)
            sid, csrf = create_session(addr, actor, credential_hash)
            self._usage_context["actor"] = actor
            self._usage_context["session"] = hashlib.sha256(sid.encode()).hexdigest()[:16]
            self._finish_usage(200, {"ok": True})
            self.send_response(200)
            payload = json.dumps({"ok": True, "csrf": csrf}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            secure = "; Secure" if isinstance(self.connection, ssl.SSLSocket) else ""
            self.send_header("Set-Cookie", "rdpwc_session=%s; HttpOnly; SameSite=Strict; Path=/%s" % (sid, secure))
            self._security_headers(); self.end_headers(); self.wfile.write(payload)
            return
        sid, sess = self._session()
        if not sess: return self._json(401, {"error": "authentication required"})
        self._usage_context["actor"] = sess.get("actor", "owner")
        self._usage_context["session"] = hashlib.sha256(sid.encode()).hexdigest()[:16]
        if not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode("utf-8"),
                                   sess["csrf"].encode("utf-8")):
            return self._json(403, {"error": "CSRF check failed"})
        if u.path == "/api/logout":
            with _session_lock: _sessions.pop(sid, None)
            return self._json(200, {"ok": True})
        if u.path != "/api/action": return self._json(404, {"error": "not found"})
        act = str(body.get("action", ""))
        self._usage_context["action"] = audit_action(act, body)
        try:
            if act == "prepare":
                target = str(body.get("target", ""))
                if target not in CONFIRMED_ACTIONS:
                    return self._json(400, {"error": "invalid confirmation target"})
                try:
                    digest = action_confirmation_digest(target, body)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                nonce = secrets.token_urlsafe(24)
                with _session_lock:
                    now = time.time()
                    sess["confirm"] = {k: v for k, v in sess["confirm"].items()
                                       if v["expires"] > now}
                    full = len(sess["confirm"]) >= 16
                    if not full:
                        sess["confirm"][nonce] = {"target": target, "expires": now + 60,
                                                  "digest": digest}
                if full:
                    return self._json(429, {"error": "too many pending confirmations"})
                return self._json(200, {"ok": True, "nonce": nonce})
            if requires_confirmation(act, body):
                try:
                    digest = action_confirmation_digest(act, body)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                with _session_lock:
                    rec = sess["confirm"].pop(str(body.get("nonce", "")), None)
                if (not rec or rec["target"] != act or rec["expires"] < time.time()
                        or not hmac.compare_digest(rec.get("digest", ""), digest)):
                    return self._json(400, {"error": "fresh confirmation required"})
            if act == "kill":
                n, errs = act_kill(body.get("pids", [])); return self._json(200, {"ok": n > 0, "killed": n, "errors": errs})
            if act == "kill_app":
                n, errs = act_kill(body.get("pids", [])); return self._json(200, {"ok": n > 0, "killed": n, "errors": errs})
            if act == "clean_temp":
                files, freed = act_clean_temp(); return self._json(200, {"ok": True, "files": files, "freed": freed})
            if act == "msg":
                act_msg(str(body.get("text", ""))[:300]); return self._json(200, {"ok": True})
            if act == "logoff":
                ok, out = act_logoff(body.get("sid", "")); return self._json(200, {"ok": ok, "out": out})
            if act == "service":
                ok, out = act_service(body.get("name", ""), body.get("mode", "status"))
                return self._json(200, {"ok": ok, "out": out})
            if act == "run_command":
                ok, out = act_run_command(str(body.get("cmd", ""))[:500], body.get("timeout", 30))
                return self._json(200, {"ok": ok, "out": out})
            if act == "start_program":
                ok, out = act_start_program(str(body.get("path", ""))[:300], str(body.get("args", ""))[:200])
                return self._json(200, {"ok": ok, "out": out})
            if act == "screenshot":
                fp, err = act_screenshot()
                if err: return self._json(500, {"error": err})
                with open(fp, "rb") as f: b64 = base64.b64encode(f.read()).decode()
                return self._json(200, {"ok": True, "png": "data:image/png;base64," + b64, "path": fp})
            if act == "backup_now":
                ok, out = act_backup_now(); return self._json(200, {"ok": ok, "out": out})
            if act == "backup_gui":
                ok, out = act_backup_gui(); return self._json(200, {"ok": ok, "out": out})
            if act == "restore":
                ok, out = act_restore(body.get("name", "")); return self._json(200, {"ok": ok, "out": out})
            if act == "drill":
                ok, out = act_drill(); return self._json(200, {"ok": ok, "out": out})
            if act == "user":
                try:
                    args = user_action_arguments(body)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                ok, out = panel_request("user_action", args)
                audit("user", "%s %s -> %s" % (args["op"], args.get("name"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "rdp":
                op = str(body.get("op", ""))
                if op not in ("rdp_status", "rdp_allow_add", "rdp_allow_remove",
                              "rdp_allow_apply", "rdp_allow_clear", "lockdown", "panic"):
                    return self._json(400, {"error": "invalid operation"})
                args = {}
                if op in ("rdp_allow_add", "rdp_allow_remove"):
                    args["ip"] = str(body.get("ip", ""))[:64]
                if op in ("lockdown", "panic"):
                    args["mode"] = str(body.get("mode", "status"))[:16]
                ok, out = panel_request(op, args)
                audit("rdp", "%s %s -> %s" % (op, args, ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "settings_set":
                key = str(body.get("key", ""))[:32]
                value = str(body.get("value", ""))[:64]
                ok, out = panel_request("settings_set", {"key": key, "value": value,
                                                         "confirm": bool(body.get("confirm"))})
                audit("settings", "%s -> %s" % (key, ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "block_subnet":
                ok, out = panel_request("block_subnet",
                                        {"ip": str(body.get("ip", ""))[:64],
                                         "confirm": bool(body.get("confirm"))}, timeout=90)
                audit("block_subnet", "%s -> %s" % (body.get("ip"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "set_rdp_port":
                ok, out = panel_request("set_rdp_port",
                                        {"port": body.get("port"),
                                         "confirm": bool(body.get("confirm"))}, timeout=300)
                audit("set_rdp_port", "%s -> %s" % (body.get("port"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "mute":
                ok, out = panel_request("mute",
                                        {"minutes": body.get("minutes"),
                                         "off": bool(body.get("off"))}, timeout=10)
                audit("mute", "%s -> %s" % (body.get("minutes") or "off", ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "trap":
                ok, out = panel_request("trap",
                                        {"op": str(body.get("op", ""))[:12],
                                         "name": str(body.get("name", ""))[:40]}, timeout=10)
                audit("trap", "%s %s -> %s" % (body.get("op"), body.get("name"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "cancel_restart":
                ok, out = panel_request("cancel_restart", {}, timeout=20)
                audit("cancel_restart", "-> %s" % ok)
                return self._json(200, {"ok": ok, "out": out})
            if act == "automation":
                ok, out = panel_request("automation",
                                        {"list": str(body.get("list", ""))[:16],
                                         "op": str(body.get("op", ""))[:8],
                                         "name": str(body.get("name", ""))[:60],
                                         "ram_mb": body.get("ram_mb"),
                                         "run": str(body.get("run", ""))[:300]}, timeout=10)
                audit("automation", "%s %s %s -> %s"
                      % (body.get("list"), body.get("op"), body.get("name"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "test_alert":
                ok, out = panel_request("test_alert", {}, timeout=20)
                return self._json(200, {"ok": ok, "out": out})
            if act == "update_now":
                ok, out = panel_request("update_now",
                                        {"confirm": bool(body.get("confirm"))}, timeout=20)
                audit("update_now", "-> %s" % ok)
                return self._json(200, {"ok": ok, "out": out})
            if act == "exportlogs":
                ok, out = panel_request("exportlogs",
                                        {"scope": str(body.get("scope", "all"))[:16]}, timeout=20)
                audit("exportlogs", "%s -> %s" % (body.get("scope"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "send_file":
                ok, out = panel_request("send_file",
                                        {"path": str(body.get("path", ""))[:300]}, timeout=20)
                audit("send_file", "%s -> %s" % (body.get("path"), ok))
                return self._json(200, {"ok": ok, "out": out})
            if act == "block_ip":
                ok, out = block_ip(body.get("ip", "")); return self._json(200, {"ok": ok, "out": out})
            if act == "unblock_ip":
                ok, out = unblock_ip(body.get("ip", "")); return self._json(200, {"ok": ok, "out": out})
            if act in ("reboot", "shutdown"):
                return self._json(200, {"ok": act_reboot() if act == "reboot" else act_shutdown()})
            return self._json(400, {"error": "unknown action %r" % act})
        except Exception as e:
            return self._json(500, {"error": repr(e)})


# ---------------------------------------------------------------- main
def main():
    if sys.argv[1:2] and sys.argv[1] in ("operator-add", "operator-remove", "operator-list"):
        operation = sys.argv[1]
        records = STATE.setdefault("operators", {})
        if operation == "operator-list":
            print("\n".join(sorted(records)))
            return 0
        name = sys.argv[2] if len(sys.argv) == 3 else ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", name) or name == "owner":
            print("Use operator-add NAME or operator-remove NAME (1-40 ASCII letters/digits/_.-).")
            return 1
        if operation == "operator-add":
            if name in records or len(records) >= 64:
                print("Operator already exists or the 64-operator limit was reached.")
                return 1
            token = secrets.token_urlsafe(32)
            records[name] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "created": time.time()}
        else:
            if name not in records:
                print("Operator not found.")
                return 1
            del records[name]
        atomic_write(STATE_FILE, STATE)
        if not harden_file(STATE_FILE):
            print("Operator state was saved, but its ACL could not be protected; no credential is displayed.")
            return 1
        if operation == "operator-add":
            print("Store this personal administrator token securely: " + token)
        else:
            print("Operator removed; their sessions are revoked on the next request.")
        return 0
    if "--install" in sys.argv or "install" in sys.argv[1:2]:
        return do_install(PORT, remote=False)
    if "install-remote" in sys.argv[1:2]:
        return do_install(PORT, remote=True)
    if "uninstall" in sys.argv[1:2]:
        return do_uninstall()
    if "url" in sys.argv[1:2]:
        scheme = "http" if BIND in ("127.0.0.1", "::1", "localhost") else "https"
        host = "127.0.0.1" if scheme == "http" else (external_ip() or "<SERVER_IP>")
        print("%s://%s:%d/" % (scheme, host, PORT)); return 0
    if "token" in sys.argv[1:2]:
        print(current_token()); return 0
    if "rotate-token" in sys.argv[1:2]:
        new_token = secrets.token_urlsafe(32)
        STATE["token_enc"] = dpapi_protect(new_token)
        atomic_write(STATE_FILE, STATE); harden_file(STATE_FILE)
        _token_cache["mtime"] = 0.0
        _token_cache["value"] = new_token
        with _session_lock: _sessions.clear()
        print("New login token (store securely): " + new_token)
        return 0
    if "remote-enable" in sys.argv[1:2]:
        extra = sys.argv[2:]
        allowed = None
        if "--allow" in extra:
            allowed = [x for x in extra[extra.index("--allow") + 1:] if x]
        return do_remote_enable(allowed)
    if "remote-disable" in sys.argv[1:2]:
        return do_remote_disable()
    if "remote-status" in sys.argv[1:2]:
        print(json.dumps(remote_status())); return 0
    if "remote-allow-add" in sys.argv[1:2]:
        return do_remote_allow(sys.argv[2:], add=True)
    if "remote-allow-remove" in sys.argv[1:2]:
        return do_remote_allow(sys.argv[2:], add=False)
    if not acquire_instance_lock():
        print("RDPWebConsole is already running for this installation.")
        return 1
    if not harden_private_storage():
        print("Refusing to start: could not protect the WebConsole directory ACL.")
        return 1
    if not os.path.exists(HTML_PATH):
        open(HTML_PATH, "w", encoding="utf-8").write("<h1>RDPWebConsole</h1><p>UI file missing.</p>")
    threading.Thread(target=per_minute_job, daemon=True).start()
    def sampler():
        psutil.cpu_percent(interval=None); psutil.cpu_percent(interval=None, percpu=True)
        time.sleep(0.5)
        while True:
            sample_once(); time.sleep(2)
    threading.Thread(target=sampler, daemon=True).start()
    try:
        cert, key = remote_security_config()
    except RuntimeError as e:
        print("Refusing to start: %s" % e)
        return 1
    srv = LimitedThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    tls = BIND not in ("127.0.0.1", "::1", "localhost")
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        srv.tls_context = ctx
    disp = BIND if BIND in ("127.0.0.1", "localhost") else "[::1]" if BIND == "::1" else "<server-ip>"
    scheme = "https" if tls else "http"
    print("=" * 60)
    atomic_write(PID_FILE, os.getpid()); harden_file(PID_FILE)
    print(" RDPWebConsole v2 running")
    print(" console: %s://%s:%d/" % (scheme, disp, PORT))
    if BIND != "127.0.0.1":
        print(" remote access restricted by TLS + firewall/application IP allow-list")
    print(" bind=%s:%d | exec=%s" % (BIND, PORT, "on" if EXEC_ENABLED else "off"))
    print(" local autostart: python RDPWebConsole.py install")
    print("=" * 60)
    if BIND == "127.0.0.1" and IS_WIN:
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d/" % PORT)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        try: os.remove(PID_FILE)
        except OSError: pass
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
