# -*- coding: utf-8 -*-
"""
RDP Monitor - A comprehensive device monitoring tool Windows (Suitable for devices RDP) With Telegram

Features:
  - Set up the first run: Requests bot token Chat ID And keep them in config.json
  - Monitor the processor and RAM with graded alerts (Warning 50% / Danger 80% / Critical 95%)
  - Alert "The situation returned to normal" + Immediate alert when there is a sudden rise
  - Real-time internet consumption (/net) And measure speed (/speedtest)
  - Monitor disk space and alert you when it is close to full
  - Highest consuming processes (/top) And another graph 24 hours (/chart)
  - Daily report/Scheduled weekly + Order /report Immediate
  - Monitor a specific program by name (/watch)
  - Monitor sessions RDP Active and IP Callers + Alert upon entry/User logout
  - Control commands: /screenshot /exec /kill /download /restart /listusers /update
  - Receive files from Telegram and save them on the device automatically
  - Manual and automatic restart at a certain limit

Requirements:
  pip install psutil requests matplotlib pillow
"""

import copy
import difflib
import contextlib
import base64
import ctypes
import hashlib
import hmac
import html
import json
import os
import queue
import secrets
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import psutil
import requests
from safe_logging import redact as redact_log, scrub_file
from account_safety import serialized_account_action, serialized_user_command
from diagnostic_runtime import deadline_scope, remaining_timeout
from audit_store import append_event
from rdp_connectivity import COLLECT_PS, analyze as analyze_rdp_policy, format_report as format_rdp_policy
from bot_catalog import (build_menus, category_title, canonical_command, help_text,
                         telegram_menu, PAGE_ALIASES, OWNERS)
from resource_alerts import ResourceAlertPolicy, usage_level as resource_usage_level
from security_events import (canonical_ip, canonical_target, event_timestamp,
                             account_query, failed_query, protected_target, success_query, usable_source)

# Prefer IPv4 for outbound connections. Some hosts advertise an IPv6 address
# without a working IPv6 route, which makes requests hang until timeout.
try:
    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
        infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
        try:
            infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)
        except Exception:
            pass
        return infos

    socket.getaddrinfo = _ipv4_first
except Exception:
    pass

# Hide console windows for subcommands (powershell A black screen appeared every minute pythonw)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Comprehensive concealment: All subsystem commands (powershell/netsh/ping/qwinsta...) Without window
# - Treatment is required "Black screen jumps every 2 minutes" When operating with pythonw
_orig_sub_run = subprocess.run
_orig_sub_popen = subprocess.Popen


def _quiet_run(*args, **kwargs):
    kwargs.setdefault("creationflags", NO_WINDOW)
    timeout = remaining_timeout(kwargs.get("timeout"))
    if timeout is not None:
        kwargs["timeout"] = timeout
    return _orig_sub_run(*args, **kwargs)


def _quiet_popen(*args, **kwargs):
    kwargs.setdefault("creationflags", NO_WINDOW)
    return _orig_sub_popen(*args, **kwargs)


# Keep the standard module intact: asyncio subclasses subprocess.Popen on Windows.
from types import SimpleNamespace
subprocess = SimpleNamespace(**{name: getattr(subprocess, name) for name in dir(subprocess)
                               if not name.startswith("__")})
subprocess.run = _quiet_run
subprocess.Popen = _quiet_popen

try:
    import matplotlib
    matplotlib.use("Agg")
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ----------------------------- Settings -----------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.abspath(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
ALERT_QUEUE_FILE = os.path.join(BASE_DIR, "alert_queue.json")
FILE_QUEUE_FILE = os.path.join(BASE_DIR, "file_queue.json")
USAGE_FILE = os.path.join(BASE_DIR, "usage_audit.jsonl")
IMAGE_STATE_FILE = os.path.join(BASE_DIR, "image_state.json")

DEFAULT_CONFIG = {
    "telegram_token": "",            # Bot token from @BotFather
    "chat_id": "",                   # The Chat ID User’s own
    "send_backup_file": True,        # Send the finished backup archive via this bot (small files)
    "backup_file_max_mb": 45,        # Telegram Bot API upload limit is 50 MB
    # Limits of tiered alerts
    "cpu_alert_threshold": 50,       # Warning: Processor %
    "ram_alert_threshold": 50,       # Warning: rams %
    "danger_threshold": 80,          # Danger %
    "critical_threshold": 95,        # Critical %
    "alert_interval": 300,           # Alert period in seconds (5 Minutes)
    "spike_threshold": 30,           # Leap % Within a minute is a sudden spike
    "spike_cooldown": 600,           # Delay between spike alerts
    # Automatic restart
    "auto_restart_enabled": False,
    "auto_restart_cpu": 95,
    "auto_restart_ram": 95,
    "auto_restart_consecutive": 3,   # The number of consecutive minutes is over the limit
    "restart_delay_seconds": 30,
    "restart_cooldown": 900,
    # Discs
    "disk_threshold": 90,            # Alert when the disk is full %
    # Reports
    "daily_report_enabled": True,
    "daily_report_hour": 20,         # The hour 8 Evening
    "weekly_report_enabled": False,
    "weekly_report_day": 4,          # 0=Monday ... 4=Friday ... 6=Sunday
    "weekly_report_hour": 20,
    # network
    "speedtest_interval_hours": 0,   # 0 = Disabled, otherwise measure periodically every N hours
    # Monitor programs by name: [{"name": "chrome", "ram_mb": 3072}]
    "watch": [],
    # Control
    "exec_enabled": False,           # Allow an order /exec And/run (The most dangerous — Activate it
                                     # The moment of need /set exec on)
    "uploads_enabled": False,        # File reception is disabled by default; Activate it only when needed
    "upload_dir": "~/Downloads/RDPMonitor",
    "update_url": "",                # Direct link to a copy rdp_monitor.py New (https Only)
    "update_hash": "",                # Imprint SHA256 For the approved copy — /update Any non-matching file is rejected
    "user_management": False,        # Account management is disabled by default; Activate it only when needed
    "account_watch": True,           # Immediate alert upon any change in accounts (4720/4724/4725/4726...)
    # Sessions
    "session_alerts": True,          # Alert upon entry/User logout
    # Advanced security
    "instance_name": "",             # The name appears before each message (To distinguish multiple devices)
    "trusted_chat_ids": [],          # Additional Telegram accounts are allowed (legacy)
    "trusted_user_ids": [],          # Identifiers Telegram User ID Allowed to send orders
    "telegram_token_enc": "",        # The bot token is encrypted with DPAPI (Plain text is never written)
    "failed_login_alerts": True,     # Failed login attempts alert (breakthrough RDP)
    "failed_login_block": True,      # Ban IP Automatically in the firewall
    "failed_login_block_threshold": 10,  # Number of attempts before ban
    "failed_login_window": 15,       # Attempt counting window in minutes
    "failed_logon_types": "10",      # 10 = RDP Only (Safe). "3,10" Adds attempts NLA
                                     # Before authentication but including SMB Also (Risk of banning innocent people)
    "critical_alerts": True,         # Immediate alert of any critical event (Level 1) In the System and Applications logs
    "temp_threshold": 85,            # Heat alert °C
    "auto_lock_minutes": 0,          # Lock the session after inactivity (0 = Disabled)
    "auto_clean_enabled": False,     # Automatic weekly cleaning
    "auto_clean_day": 5,             # 0=Monday ... 5=Saturday
    "auto_clean_hour": 3,
    # RDP
    "rdp_port": 3389,                # outlet RDP Current (It changes with /setrdpport)
    "rdp_allowed_ips": [],           # Palace RDP On IP Specific (/rdpallow)
    "rdp_allow_active": False,       # Are the restriction rules activated?
    "rdp_allow_pre_active": False,   # Confinement status before locking (To continue after reboot)
    "rdpallow_disabled_rules": [],   # Broad rules of permission are invalidated by restrictions (Returned at clear)
    "pre_default_inbound": {},       # Original import policy before inventory (To undo)
    # Reliability and self-maintenance
    "muted_until": 0,                # Mutes regular notifications until this time (unix timestamp)
    "heartbeat_hours": 6,            # Message "It still works" Eat N hours (0 = Disabled)
    "keepalive": [],                 # Programs are automatically restarted: [{"name": "app.exe", "run": "Path"}]
    "rdp_watch": True,               # Outlet monitoring RDP: Alert + Restart the service if it stops
    "net_watch": True,               # Internet monitoring: Warning when cutting and returning
    "ping_target": "1.1.1.1",        # The target that checks to see the status of the Internet
    "update_check_hours": 24,        # Check for a newer version of update_url Eat N hours (0 = Disabled)
    "fw_guard": True,                # Firewall guarding: If it turns off, it activates it and notifies you
                                     # (All protection: Ban, confine, lock, panic - Depend on it)
    # Automatic locking against intrusion waves (Residential proxies are switched IP)
    "lockdown": False,               # Activate automatic lock
    "lockdown_limit": 30,            # Total failed attempts (Eat IP Combined) The one who works has the lock
    "lockdown_minutes": 60,          # Lock duration in minutes
    "auto_learn_ips": True,          # Learn IP Automatically log in RDP Successful (4624)
    "learn_for_lockdown": False,     # Login IP Learner in emergency lock automatically?
                                     # Default OK Manual Safer: Login success
                                     # It does not mean trust (Password theft = Reliable!) —
                                     # Activate it if IPAs a variable, you realize the trade-off
    "learned_ips": {},               # {ip: Last login success} - Educated whitelist
    "lockdown_until": 0,             # The expiry time of the current lock (0 = No lock)
    # Account for transferred data (The pendulum)
    "traffic_quota_gb": 0,           # Monthly quota in gigabytes (0 = Without share alert)
    "traffic_reset_day": 1,          # Quota reset day (Billing day) 1-28
    # Imaging the complete system (VHDX) And automatic upload
    "rclone_path": "",               # Path rclone.exe For automatic upload (Optional)
    "rclone_remote": "",             # Lifting remote such as gdrive:backups
    "image_delete_after": False,     # Delete the local copy after successful upload
    "image_enabled": False,          # System imaging is disabled by default; Heavy and delicate operation
    # Complete control and advanced protection
    "trap_users": [],                # Traps: Any attempt to log in with this name = Immediate permanent ban
    "subnetblock": False,            # Escalate the ban for a network /24 Complete
    "panic_active": False,           # Panic mode: RDP Completely closed (It remains after reboot)
    "new_ip_alerts": True,           # Alert upon successful entry from IP Never seen before
    "startup_report": False,         # Send a "Startup report" message each time the tool starts
    "baseline_alerts": False,        # Announce the learned-IP baseline on startup
    "rdphours": "",                  # Working hours RDP Like "9-23" (Empty = 24 hours)
    "rdpsched_blocked": False,       # Is a scheduling rule RDP Currently implemented?
    "selfheal_disk": False,          # Automatically clean up when the system disk is full 95%
    "svcwatch": [],                  # Services are monitored: [{"name": "W32Time"}] - If you stop, it will be repeated
}

config = {}
_config_lock = threading.Lock()

# ----------------------------- General condition -----------------------------

_net_speed = {"down": 0.0, "up": 0.0}
_last_net_time = 0.0
_last_net_counters = (0, 0)


_auto_streak = 0                   # Consecutive minutes above the auto-replay limit
_last_auto_check = 0.0
_last_auto_restart = 0.0

_disk_alerted = {}
_last_disk_check = 0.0

_watch_cooldown = {}
_last_watch_check = 0.0

_known_sessions = None
_last_session_check = 0.0

_history = []                      # [{"t": ts, "c": cpu, "r": ram}] Every minute
_last_history_append = 0.0
_last_history_save = 0.0

_last_speedtest = 0.0
_last_daily = None
_last_weekly = None

_failed_logins = {}                # {ip: {"times": [ts]}} Failed attempts
_seen_4625 = {}                    # {key: True} Failure events we read (Insert order)
_blocked = {}                      # {ip: ts} IP Blocked in firewall
_audit = []                        # Audit log
_session_locked = False
_last_lock_time = 0.0
_last_temp_check = 0.0
_last_temp_alert = 0.0
_last_failed_check = 0.0
_last_clean_day = None
_seen_critical = {}               # {key: True} Critical events we have read (Insert order)
_critical_baseline = False         # First reading of critical events = Reference point without alerts
_last_critical_check = 0.0
_last_heartbeat = 0.0              # Last pulse message
_keepalive_last = {}               # {name: ts} Last attempt to revive each program
_last_keepalive_check = 0.0
_rdp_down_since = None             # When did we notice that? RDP What he hears on his outlet
_last_rdp_check = 0.0
_last_rdp_restart = 0.0
_net_down_streak = 0               # Consecutive minutes in which the... ping
_last_net_watch = 0.0
_last_update_check = 0.0
_last_learn = 0.0                  # Last time we learned IP Success
_pre_lockdown_allow_active = None  # case rdp_allow_active Before locking (To undo)
_traffic = {}                      # {"YYYY-MM-DD": {"down": MB, "up": MB}}
_traffic_lock = threading.Lock()   # Guards _traffic against concurrent read/write
_last_traffic_counters = None      # (bytes_sent, bytes_recv) Last sample
_last_traffic_save = 0.0
_last_traffic_check = 0.0
_traffic_alerted = {}              # Quota alerts: {"YYYY-MM_50": True, ...}
_last_svcwatch_check = 0.0
_last_rdpsched_check = 0.0        # Last check to schedule hours RDP
_svcwatch_last = {}                # {name: ts} Last attempt to restart the service
_last_selfheal = 0.0               # Post self cleaning
_learn_alerts_ready = False        # First learn = Reference point without warning IP New
_seen_acct = {}                    # {key: True} Manage readable accounts events
_acct_baseline = False             # First reading of accounts events = Reference point

# ----------------------------- Imaging the complete system (VHDX) -----------------------------

DISK2VHD_URL = "https://download.sysinternals.com/files/Disk2vhd.zip"

_image_state = {                   # Status of the imaging process/Ongoing lifting
    "proc": None, "vhdx": None, "started": 0.0,
    "size_est": 0, "remote": None, "phase": None, "last_progress": 0.0,
}


class _RecoveredImageProcess:
    """Monitor PID After restarting RDP Monitor; He does not claim to know exit code The old one."""
    recovered = True

    def __init__(self, pid, created=None, executable=None):
        self.pid = int(pid)
        self.created = created
        self.executable = executable
        self.returncode = None

    def _process(self):
        if self.created is None or not self.executable:
            return None  # Legacy state cannot safely identify a recycled PID.
        p = psutil.Process(self.pid)
        if p.create_time() != self.created:
            return None
        exe = p.exe()
        if os.path.normcase(os.path.realpath(exe)) != \
                os.path.normcase(os.path.realpath(self.executable)):
            return None
        if os.path.basename(exe).lower() not in ("disk2vhd.exe", "disk2vhd64.exe"):
            return None
        return p

    def poll(self):
        try:
            if self._process() is not None:
                return None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        self.returncode = 1  # The original exit code is unknown, never success.
        return self.returncode

    def kill(self):
        p = self._process()
        if p is None:
            raise RuntimeError("The recovered imaging process no longer matches its saved identity")
        p.kill()


def _persist_image_state():
    data = {k: v for k, v in _image_state.items() if k != "proc"}
    proc = _image_state.get("proc")
    data["pid"] = getattr(proc, "pid", None)
    if proc is not None:
        try:
            if getattr(proc, "recovered", False):
                data["proc_created"] = proc.created
                data["proc_executable"] = proc.executable
            else:
                p = psutil.Process(proc.pid)
                data["proc_created"] = p.create_time()
                data["proc_executable"] = p.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            data["proc_created"] = None
            data["proc_executable"] = None
    try:
        _atomic_write_json(IMAGE_STATE_FILE, data, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[image] state save error: {e}")


def _find_rclone_upload_proc():
    """Return a psutil.Process for a running 'rclone copy' upload, or None."""
    try:
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                nm = (p.info.get("name") or "").lower()
                if not nm.startswith("rclone"):
                    continue
                cl = p.info.get("cmdline") or []
                if "copy" in cl:
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def _reattach_upload_watch(proc, path, remote):
    """Wait for a re-attached rclone upload to end, then report the result."""
    try:
        proc.wait()
    except Exception:
        pass
    name = os.path.basename(path or "image")
    remote = remote or config.get("rclone_remote") or ""
    ok, out = _rclone_run(["lsf", remote.rstrip("/") + "/" + name], timeout=120)
    if ok and out.strip():
        url = _rclone_link(remote, name)
        msg = ("[OK] <b>Upload complete</b>\n"
               "File: <code>" + esc(name) + "</code>\n"
               "To: <b>" + esc(remote) + "</b>")
        if url:
            msg += "\nShare link: " + esc(url)
        send_message(msg)
    else:
        send_message("[X] <b>Upload ended</b> but the file is not on the remote.\n"
                     "Check /rclone test and retry /image upload.")
    _image_state["phase"] = "done"
    _persist_image_state()


def recover_image_state():
    """Restores control Disk2vhd Or clearly reports a process that has been interrupted."""
    if not os.path.exists(IMAGE_STATE_FILE):
        return
    try:
        with open(IMAGE_STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        phase = saved.get("phase")
        if phase == "imaging" and saved.get("pid"):
            proc = _RecoveredImageProcess(saved["pid"], saved.get("proc_created"),
                                          saved.get("proc_executable"))
            if proc.poll() is None:
                _image_state.update(saved)
                _image_state["proc"] = proc
                threading.Thread(target=_image_watch, daemon=True).start()
                send_message("I regained practical control Disk2vhd That was working before restarting the tool.")
                return
        if phase == "uploading":
            proc = _find_rclone_upload_proc()
            if proc is not None:
                _image_state.update(saved)
                _image_state["phase"] = "uploading"
                _image_state["proc"] = proc
                _persist_image_state()
                threading.Thread(target=_reattach_upload_watch,
                                 args=(proc, saved.get("vhdx"), saved.get("remote")),
                                 daemon=True).start()
                send_message("<b>Upload re-attached</b>\n"
                             "An upload from before the restart is still running; "
                             "I will report when it finishes.")
                return
        if phase in ("imaging", "uploading"):
            _image_state.update(saved)
            _image_state["proc"] = None
            _image_state["phase"] = "done"
            _persist_image_state()
            what = "upload" if phase == "uploading" else "imaging"
            send_message("<b>Interrupted " + what + "</b>\n"
                         "The tool restarted while this job was running, so its result is "
                         "unknown.\nFile: <code>" + esc(str(saved.get("vhdx") or "unknown")) +
                         "</code>\nVerify it, then retry with /image " +
                         ("upload" if phase == "uploading" else "start") + ".")
    except Exception as e:
        print(f"[image] state recovery error: {e}")


def _is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _find_disk2vhd():
    """Looking for disk2vhd In the tool folder or PATH"""
    for name in ("disk2vhd64.exe", "disk2vhd.exe"):
        p = os.path.join(BASE_DIR, name)
        if os.path.isfile(p):
            return p
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for name in ("disk2vhd64.exe", "disk2vhd.exe"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def _download_disk2vhd():
    """He comes down Disk2vhd From the official Microsoft website (Sysinternals) And extract it into the tool folder"""
    import zipfile
    try:
        r = requests.get(DISK2VHD_URL, timeout=120)
        r.raise_for_status()
        zpath = os.path.join(BASE_DIR, "Disk2vhd.zip")
        with open(zpath, "wb") as f:
            f.write(r.content)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(BASE_DIR)
        os.remove(zpath)
        return _find_disk2vhd()
    except Exception as e:
        print(f"[image] disk2vhd download error: {e}")
        return None


def _pick_image_target(need_bytes):
    """Selects the most suitable disk to receive the image: Irregular with space, otherwise the largest space"""
    sys_drive = os.environ.get("SystemDrive", "C:").upper()
    candidates = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            candidates.append((part.mountpoint, part.device, u.free))
        except Exception:
            pass
    if not candidates:
        return os.path.expanduser("~"), 0
    for mp, dev, free in candidates:
        if not dev.upper().startswith(sys_drive) and free >= need_bytes:
            return mp, free
    mp, _dev, free = max(candidates, key=lambda x: x[2])
    return mp, free


def _fixed_volumes_used():
    """Total used bytes across fixed volumes, for the free-space estimate."""
    total = 0
    for part in psutil.disk_partitions(all=False):
        try:
            total += psutil.disk_usage(part.mountpoint).used
        except Exception:
            pass
    return total or psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").used


def image_progress_line():
    """Current shooting progress line"""
    st = _image_state
    try:
        target = st["vhdx"]
        stem = os.path.splitext(os.path.basename(target))[0].lower()
        done = sum(os.path.getsize(os.path.join(os.path.dirname(target), name))
                   for name in os.listdir(os.path.dirname(target))
                   if name.lower().endswith(".vhdx")
                   and (name.lower() == stem + ".vhdx"
                        or name.lower().startswith(stem + "-")))
    except (OSError, KeyError, TypeError):
        done = 0
    est = st.get("size_est") or 1
    pct = min(100.0, done / est * 100)
    elapsed = int(time.time() - st["started"])
    return (f"{pct:.0f}% ({format_size(done)} of ~{format_size(est)}) "
            f"- elapsed {format_duration(elapsed)}")


def image_start(remote=None):
    """Depicts the complete system VHDX And the system is working (Shadow Copy) He raises it later if he kicks it correctly"""
    if _image_state.get("phase") in ("imaging", "uploading"):
        send_message("In the process of filming/Upload is currently working - Status: /image")
        return
    if not _is_admin():
        send_message("[X] Photography requires administrator privileges - Run the tool as administrator (install.bat)")
        return
    vhdexe = _find_disk2vhd()
    if not vhdexe:
        send_message(" I didn’t find anything Disk2vhd - Download it now from the official Microsoft website...")
        vhdexe = _download_disk2vhd()
        if not vhdexe:
            send_message("[X] Download failed Disk2vhd (network?) - Download it manually:\n"
                         "https://download.sysinternals.com/files/Disk2vhd.zip\n"
                         "Unzip the files in the tool folder and then restore /image start")
            return
    sys_drive = os.environ.get("SystemDrive", "C:")
    used = _fixed_volumes_used()
    # Margin 5 GB: the image grows while imaging and Windows keeps writing to disk.
    need = used + 5 * 1024 ** 3
    out_dir, free = _pick_image_target(need)
    same_drive = out_dir[:2].upper() == sys_drive.upper()
    out_path = os.path.join(out_dir,
                            f"FULLSYSTEM_{datetime.now():%Y%m%d_%H%M%S_%f}.vhdx")
    if free < need:
        send_message(
            f"[X] There is not enough space for the image\n"
            f" Used on fixed volumes: {format_size(used)}\n"
            f" Free on {out_dir}: {format_size(free)}\n"
            "The image needs at least as much space as your data used.\n"
            "Free up space (/clean helps) or attach a second disk."
        )
        return
    if same_drive:
        send_message(
            "[WARN] No second disk with enough free space was found - the image "
            "will be written to the system disk.\n"
            "The free-space check passed, but keep Console access: if this disk "
            "fills up, Windows can become unreachable.")
    try:
        # Check signature Authenticode + Identity of the signer before operation — Code with permissions
        # Manager from the Internet: A valid signature alone is sufficient (Any signed file is valid
        # passes) — The signatory must be the same Microsoft/Sysinternals
        sig = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$s = Get-AuthenticodeSignature -LiteralPath '{_ps_quote(vhdexe)}'; "
             f"$sub = if ($s.SignerCertificate) {{ $s.SignerCertificate.Subject }} else {{ '' }}; "
             f"Write-Output ($s.Status.ToString() + '|' + $sub)"],
            capture_output=True, timeout=60, creationflags=NO_WINDOW)
        sig_out = _decode_out(sig.stdout).strip()
        status, _, subject = sig_out.partition("|")
        microsoft_signer = bool(re.search(
            r"(?:^|,\s*)CN=Microsoft Corporation(?:,|$)", subject,
            flags=re.I))
        if status.lower() != "valid" or not microsoft_signer:
            send_message("[X] Signature Disk2vhd Invalid or not signed "
                         "Microsoft/Sysinternals — I canceled filming and nothing happened\n"
                         f"Status: {esc(status)} | Signer: {esc(subject[:60])}")
            audit_record("System imaging was cancelled: Signature Disk2vhd Rejected")
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Disk2vhd's CLI needs a leading option; with none it prints usage and
        # hangs. "-c" copies volumes directly (VSS is unavailable on some hosts)
        # and "*" includes every volume, so the System Reserved / boot partition
        # is captured and the image boots on another VM.
        proc = subprocess.Popen([vhdexe, "-c", "*", out_path],
                                creationflags=flags,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        # Disk2vhd shows its usage dialog and hangs when arguments are rejected,
        # so detect an immediate exit instead of reporting a false "started".
        time.sleep(3)
        if proc.poll() is not None:
            send_message("[X] Disk2vhd exited immediately - imaging did not start "
                         "(arguments rejected). Nothing was written; check the log.")
            audit_record("System imaging failed to start (disk2vhd rejected args)")
            return
    except Exception as e:
        send_message(f"[X] Failed to start shooting: {e}")
        return
    _image_state.update({"proc": proc, "vhdx": out_path, "started": time.time(),
                         "size_est": used, "remote": remote,
                         "phase": "imaging", "last_progress": time.time()})
    _persist_image_state()
    audit_record(f"System imaging has begun: {out_path}")
    send_message(
        "<b>Imaging started</b>\n"
        "Data to image: " + format_size(used) + "\n"
        "Destination: <code>" + esc(out_path) + "</code>\n"
        "Free on destination: " + format_size(free) + "\n"
        "Windows keeps running during the copy.\n"
        "Progress is reported every 10 minutes; check anytime with /image status.\n"
        "Stop: /image stop"
    )
    threading.Thread(target=_image_watch, daemon=True).start()


def _image_watch():
    """Monitors the shooting process: Periodic progress + Completion → Auto upload"""
    while True:
        st = _image_state
        proc = st.get("proc")
        if st.get("phase") != "imaging" or not proc:
            return
        time.sleep(30)
        if st.get("phase") != "imaging":
            return
        if proc.poll() is not None:
            _image_finish()
            return
        now_ts = time.time()
        if now_ts - st.get("last_progress", 0) >= 600:
            st["last_progress"] = now_ts
            send_message("<b>Imaging</b> " + image_progress_line())


def _image_finish():
    """When filming is complete: Report + Auto upload if there is a destination"""
    st = _image_state
    proc = st.get("proc")
    path = st.get("vhdx")
    # Disk2vhd may append a physical-disk suffix. Only accept outputs with
    # this job's unique base name, created after this job started.
    paths = []
    if path:
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        directory = os.path.dirname(path)
        try:
            paths = [os.path.join(directory, name) for name in os.listdir(directory)
                     if name.lower().endswith(".vhdx")
                     and (name.lower() == stem + ".vhdx"
                          or name.lower().startswith(stem + "-"))
                     and os.path.getmtime(os.path.join(directory, name)) >= st.get("started", 0) - 2
                     and os.path.getsize(os.path.join(directory, name)) > 0]
        except OSError:
            paths = []
    st["vhdx_files"] = sorted(paths)
    if paths:
        path = paths[0]
        st["vhdx"] = path
    if getattr(proc, "recovered", False):
        st["phase"] = "done"
        _persist_image_state()
        send_message("<b>Imaging finished (recovered)</b>\n"
                     "The imaging process ended after a tool restart, so I cannot confirm "
                     "the exit code and will not auto-upload.\n"
                     "Verify the file, then upload it with /image upload:\n<code>"
                     + esc(str(path or "unknown")) + "</code>")
        return
    ok = proc is not None and proc.returncode == 0 and bool(paths)
    if not ok:
        st["phase"] = None
        _persist_image_state()
        audit_record("System imaging failed")
        send_message("[X] <b>Imaging failed</b> - see rdp_monitor.log for details.\n"
                     "Nothing was uploaded.")
        return
    size = sum(os.path.getsize(item) for item in paths)
    st["phase"] = "done"
    _persist_image_state()
    audit_record(f"System imaging is complete: {path} ({format_size(size)})")
    msg = ("[OK] <b>Imaging complete</b>\n"
           "Files: " + str(len(paths)) + "\n" +
           "\n".join("<code>" + esc(item) + "</code>" for item in paths) + "\n"
           "Size: " + format_size(size) + "\n"
           "Took: " + format_duration(time.time() - st["started"]))
    remote = st.get("remote") or config.get("rclone_remote")
    if remote:
        if _find_rclone():
            send_message(msg)
            threading.Thread(target=_upload_image_set, args=(paths, remote),
                              daemon=True).start()
            return
        msg += ("\n[WARN] rclone is not installed, so auto-upload is off.\n"
                "Set it up with /rclone install, then upload this file with /image upload.")
    send_message(msg)


def _find_rclone():
    """Looking for rclone: Saved path, tool folder, or PATH"""
    # Prefer the suite-managed copy before a saved absolute path.  A deployment
    # can move while the previous directory still exists (for rollback), and in
    # that case trusting config first silently keeps the live process coupled to
    # the old installation.
    local = os.path.abspath(os.path.join(BACKUP_DIR, "rclone", "rclone.exe"))
    if os.path.isfile(local):
        saved = config.get("rclone_path", "")
        try:
            same = saved and os.path.normcase(os.path.abspath(saved)) == os.path.normcase(local)
        except (OSError, TypeError, ValueError):
            same = False
        # Module imports used by tests or maintenance tools happen before
        # load_config().  Never persist that empty/default in-memory mapping;
        # normal runtime migration is allowed only after a real configuration
        # file has been loaded successfully.
        if not same and globals().get("CONFIG_LOAD_OK") is True:
            config["rclone_path"] = local
            try:
                save_config()
                register = globals().get("_rclone_register_config")
                if register:
                    register()
            except Exception as e:
                print("[rclone] local path migration warning: " + str(e))
        return local
    p = config.get("rclone_path", "")
    if p and os.path.isfile(p):
        return p
    for name in ("rclone.exe", "rclone"):
        p2 = os.path.join(BASE_DIR, name)
        if os.path.isfile(p2):
            return p2
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for name in ("rclone.exe", "rclone"):
            p2 = os.path.join(d, name)
            if os.path.isfile(p2):
                return p2
    return None


def _parse_rclone_size(tok):
    m = re.match(r"\s*([\d.]+)\s*([KMGTP]?i?B)", tok)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    mult = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4,
            "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4}
    return int(val * mult.get(unit, 1))


def _parse_rclone_stats(line):
    """Return (transferred_bytes, total_bytes, percent) from an rclone stats line."""
    m = re.search(
        r"([\d.]+\s*[KMGTP]?i?B)\s*/\s*([\d.]+\s*[KMGTP]?i?B)\s*[,\s]+(\d{1,3})%", line)
    if m:
        return (_parse_rclone_size(m.group(1)), _parse_rclone_size(m.group(2)),
                int(m.group(3)))
    m = re.search(r"(\d{1,3})%", line)
    if m:
        return None, None, int(m.group(1))
    return None, None, None


def _rclone_link(remote, filename):
    """Return a shareable link for an uploaded file, or ''."""
    full = remote.rstrip("/") + "/" + filename
    ok, out = _rclone_run(["link", full], timeout=60)
    if ok:
        for ln in out.splitlines():
            ln = ln.strip()
            if ln.startswith("http"):
                return ln
    return ""


def image_upload_chart():
    """Send a chart of uploaded GB over time for the running/finished upload."""
    samples = _image_state.get("upload_samples") or []
    if len(samples) < 2:
        send_message("Not enough progress data yet - try again in a few minutes.")
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        send_message("[X] Charts need matplotlib: " + esc(str(e)))
        return
    xs = [s[0] for s in samples]
    gbs = [(s[2] or 0) / (1024 ** 3) for s in samples]
    pcts = [s[1] for s in samples]
    name = os.path.basename(_image_state.get("vhdx") or "image")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(xs, gbs, color="#2563eb", linewidth=2, marker="o", markersize=3)
    ax.set_title("Upload progress - " + name)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Uploaded (GB)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = os.path.join(BASE_DIR, "upload_chart.png")
    fig.savefig(path, dpi=110)
    plt.close(fig)
    last = samples[-1]
    send_photo(path, "<b>Upload progress</b>\n"
                     f"{last[1]}% - {last[2] / (1024 ** 3):.2f} GB uploaded\n"
                     "To: " + esc(_image_state.get("remote") or ""))


def image_link(args):
    """Return a shareable link for an image already on the remote."""
    remote = config.get("rclone_remote")
    if not remote:
        send_message("No upload target set. Run /rclone set &lt;remote:path&gt; first.")
        return
    name = ""
    if args and os.path.isfile(args[0]):
        name = os.path.basename(args[0])
    elif args and args[0].isdigit():
        files = image_list_files()
        i = int(args[0]) - 1
        if 0 <= i < len(files):
            name = os.path.basename(files[i])
    else:
        st = _image_state.get("vhdx")
        name = os.path.basename(st) if st else ""
    if not name:
        send_message("Usage: /image link [n|path]  (see /image list)")
        return
    url = _rclone_link(remote, name)
    if url:
        send_message("Share link for <code>" + esc(name) + "</code>:\n" + esc(url))
    else:
        send_message("[X] No link. Is the file uploaded? Check /image status.")


def _verify_remote_image(path, remote):
    """Check that rclone reports the expected byte count at the destination."""
    target = remote.rstrip("/") + "/" + os.path.basename(path)
    ok, output = _rclone_run(["size", "--json", target], timeout=120)
    if not ok:
        return False
    try:
        result = json.loads(output)
        return result.get("count") == 1 and result.get("bytes") == os.path.getsize(path)
    except (ValueError, OSError, TypeError):
        return False


def _upload_image_set(paths, remote):
    """Upload every disk image before allowing local cleanup."""
    for path in paths:
        if not _upload_job(path, remote, delete_after=False, finalize_phase=False):
            _image_state["phase"] = "done"
            _persist_image_state()
            send_message("[X] The image set is incomplete on the remote. Local files were kept.")
            return
    if config.get("image_delete_after"):
        if not all(_verify_remote_image(path, remote) for path in paths):
            _image_state["phase"] = "done"
            _persist_image_state()
            send_message("[WARN] Remote image set verification failed. Local files were kept.")
            return
        for path in paths:
            try:
                os.remove(path)
            except OSError as e:
                send_message("[WARN] Could not delete <code>" + esc(path) + "</code>: " + esc(str(e)))
    _image_state["phase"] = "done"
    _persist_image_state()
    send_message("[OK] <b>System image set uploaded</b>\n"
                 f"Files: {len(paths)}\nDestination: <code>{esc(remote)}</code>")


def _upload_job(path, remote, delete_after=None, finalize_phase=True):
    """Upload a local image file to the rclone remote, reporting progress and result."""
    rc = _find_rclone()
    name = os.path.basename(path)
    if not rc:
        send_message("[X] <b>Upload not started</b> - rclone is not installed.\n"
                     "Install it with /rclone install, then retry /image upload.")
        if finalize_phase:
            _image_state["phase"] = "done"
            _persist_image_state()
        return False
    try:
        size = os.path.getsize(path)
    except OSError as e:
        send_message("[X] <b>Upload failed</b> - cannot read the file:\n"
                     + esc(name) + "\n" + esc(str(e)))
        if finalize_phase:
            _image_state["phase"] = "done"
            _persist_image_state()
        return False
    started = time.time()
    _image_state.update({"phase": "uploading", "vhdx": path, "remote": remote,
                         "upload_pct": 0, "upload_started": started,
                         "upload_detail": "", "upload_samples": []})
    _persist_image_state()
    audit_record("Upload started: %s -> %s" % (path, remote))
    send_message("[UP] <b>Upload started</b>\n"
                 "File: <code>" + esc(name) + "</code>\n"
                 "Size: " + format_size(size) + "\n"
                 "To: <b>" + esc(remote) + "</b>\n"
                 "I will report progress and the final result. Chart: /image chart")
    pct = 0
    out = ""
    samples = []
    logf = os.path.join(_rclone_dir(), "upload.log")
    try:
        open(logf, "w").close()
    except OSError:
        pass
    try:
        proc = subprocess.Popen(
            [rc, "--config", _rclone_conf_path(), "copy", path, remote,
             "--transfers", "4", "--stats", "15s", "--stats-one-line",
             "--log-file", logf, "--log-level", "INFO"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW)
        _image_state["proc"] = proc
        last_report = time.time()
        last_line = None
        while proc.poll() is None:
            time.sleep(5)
            try:
                with open(logf, "r", encoding="utf-8", errors="replace") as f:
                    logtext = f.read()
            except OSError:
                logtext = ""
            latest = None
            for ln in reversed(logtext.splitlines()):
                if "%" in ln and "/" in ln:
                    latest = ln.strip()
                    break
            if latest and latest != last_line:
                last_line = latest
                tr, _tot, p = _parse_rclone_stats(latest)
                if p is not None:
                    pct = p
                detail = re.sub(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d \S+\s*:\s*", "",
                                latest).strip()
                samples.append([round((time.time() - started) / 60.0, 2), pct, tr or 0])
                _image_state["upload_pct"] = pct
                _image_state["upload_detail"] = detail
                _image_state["upload_samples"] = samples[-3000:]
            if time.time() - last_report >= 300:
                last_report = time.time()
                send_message("[UP] <b>Uploading</b>\n" +
                             esc(_image_state.get("upload_detail") or (str(pct) + "%")) +
                             "\n" + esc(name) + " -> " + esc(remote) +
                             "\nChart: /image chart")
        time.sleep(1)
        rc_ok = (proc.returncode == 0)
        try:
            with open(logf, "r", encoding="utf-8", errors="replace") as f:
                out = f.read()
        except OSError:
            out = ""
    except Exception as e:
        send_message("[X] <b>Upload failed</b>\nFile: <code>" + esc(name) + "</code>\n"
                     "To: <b>" + esc(remote) + "</b>\nError: " + esc(str(e)))
        if finalize_phase:
            _image_state["phase"] = "done"
            _persist_image_state()
        return False
    dur = format_duration(time.time() - started)
    if rc_ok:
        audit_record("Upload complete: %s -> %s" % (path, remote))
        msg = ("[OK] <b>Upload complete</b>\n"
               "File: <code>" + esc(name) + "</code> (" + format_size(size) + ")\n"
               "To: <b>" + esc(remote) + "</b>\n"
               "Took: " + dur)
        link = _rclone_link(remote, name)
        if link:
            msg += "\nShare link: " + esc(link)
        if delete_after is None:
            delete_after = bool(config.get("image_delete_after"))
        if delete_after:
            if not _verify_remote_image(path, remote):
                send_message("[WARN] rclone returned success, but the remote file size "
                             "could not be verified. Local copy kept: <code>" +
                             esc(path) + "</code>")
                if finalize_phase:
                    _image_state["phase"] = "done"
                    _persist_image_state()
                return False
            try:
                os.remove(path)
                msg += "\nLocal copy deleted (image_delete_after is on)."
            except OSError as e:
                msg += "\nCould not delete the local copy: " + esc(str(e))
        send_message(msg)
    else:
        send_message("[X] <b>Upload failed</b>\n"
                     "File: <code>" + esc(name) + "</code>\n"
                     "To: <b>" + esc(remote) + "</b>\n"
                     "After " + dur + ". Reason:\n" + esc(out[-600:] or "(no details)"))
    if finalize_phase:
        _image_state["phase"] = "done"
        _persist_image_state()
    return rc_ok


def _image_search_roots():
    """Folders where a FULLSYSTEM image may live: tool dir, last target, drive roots."""
    roots = [BASE_DIR]
    st = _image_state.get("vhdx")
    if st:
        roots.append(os.path.dirname(st))
    for part in psutil.disk_partitions(all=False):
        roots.append(part.mountpoint)
    out, seen = [], set()
    for r in roots:
        if r and os.path.isdir(r):
            a = os.path.abspath(r)
            if a not in seen:
                seen.add(a)
                out.append(a)
    return out


def image_list_files():
    """Existing FULLSYSTEM_*.vhdx files, newest first."""
    found, seen = [], set()
    for root in _image_search_roots():
        try:
            for x in os.listdir(root):
                if x.lower().startswith("fullsystem_") and x.lower().endswith(".vhdx"):
                    p = os.path.join(root, x)
                    ap = os.path.abspath(p)
                    if ap not in seen:
                        seen.add(ap)
                        found.append(p)
        except OSError:
            pass
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def image_list_text():
    files = image_list_files()
    if not files:
        return ("<b>System images</b>\nNone found.\nCreate one with /image start.")
    lines = ["<b>System images</b> (newest first)"]
    for i, p in enumerate(files, 1):
        try:
            size = format_size(os.path.getsize(p))
            when = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size, when = "?", "?"
        lines.append(f"{i}. {esc(os.path.basename(p))} - {size} - {when}")
        lines.append("   <code>" + esc(p) + "</code>")
    lines.append("")
    lines.append("Upload one: /image upload 1   (or /image upload &lt;full-path&gt;)")
    return "\n".join(lines)


def image_upload(args):
    """Upload an existing image (no new image is created)."""
    remote = config.get("rclone_remote")
    if not remote:
        send_message("[X] No upload target set. Run /rclone set &lt;remote:path&gt; first.")
        return
    if not _find_rclone():
        send_message("[X] rclone is not installed. Run /rclone install first.")
        return
    if _image_state.get("phase") in ("imaging", "uploading"):
        send_message("[X] A job is already running. Check /image status.")
        return
    files = image_list_files()
    path = None
    if args:
        a = args[0]
        if a.isdigit() and 1 <= int(a) <= len(files):
            path = files[int(a) - 1]
        elif os.path.isfile(a):
            path = a
        else:
            send_message("[X] Not found: " + esc(a) + "\nSee /image list")
            return
    elif files:
        path = files[0]
    if not path:
        send_message("[X] No image found. Create one with /image start.")
        return
    _image_state["vhdx"] = path
    _image_state["remote"] = remote
    _image_state["phase"] = "uploading"
    _persist_image_state()
    audit_record("Upload existing image: " + path + " -> " + remote)
    threading.Thread(target=_upload_job, args=(path, remote), daemon=True).start()


def _confirm_image_upload(path, remote, size):
    if (not os.path.isfile(path) or os.path.getsize(path) != size
            or config.get("rclone_remote") != remote):
        send_message("[X] The image or destination changed. Review /image upload again.")
        return
    image_upload([path])


# ----------------------------- rclone setup from chat -----------------------------
# Lets the user install rclone and create cloud remotes entirely from Telegram,
# without touching the machine. Remotes live in one shared rclone.conf so the
# monitor and the SYSTEM backup worker both see them.

RCLONE_URL = "https://downloads.rclone.org/v1.74.4/rclone-v1.74.4-windows-amd64.zip"
RCLONE_SHA256 = "ef097ef9de37a57feb7d9f9c7afb34148ad3c65be8025f1d8f7f521554a701ea"

# Remote types that need a browser OAuth sign-in; create these with a token.
RCLONE_OAUTH_TYPES = {
    "drive", "googlephotos", "onedrive", "dropbox", "box", "pcloud",
    "yandex", "sharefile", "jottacloud", "premiumizeme", "zoho", "hidrive",
}


def _rclone_dir():
    return os.path.join(BACKUP_DIR, "rclone")


def _rclone_conf_path():
    d = _rclone_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "rclone.conf")
    if not os.path.exists(p):
        try:
            open(p, "a", encoding="utf-8").close()
        except OSError:
            pass
    return p


def _rclone_exe():
    exe = _find_rclone()
    if exe:
        return exe
    local = os.path.join(_rclone_dir(), "rclone.exe")
    return local if os.path.isfile(local) else None


def _rclone_run(args, timeout=120):
    """Run rclone against the shared config. Returns (ok, combined output)."""
    exe = _rclone_exe()
    if not exe:
        return False, "rclone is not installed - run /rclone install first"
    try:
        r = subprocess.run([exe, "--config", _rclone_conf_path()] + list(args),
                           capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        out = (_decode_out(r.stdout) + "\n" + _decode_out(r.stderr)).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "rclone timed out"
    except Exception as e:
        return False, repr(e)


def _rclone_version():
    ok, out = _rclone_run(["version"], timeout=30)
    return out.splitlines()[0].strip() if (ok and out) else ""


def _rclone_remotes():
    ok, out = _rclone_run(["listremotes"], timeout=60)
    if not ok:
        raise RuntimeError("Could not load rclone remotes: " + redact_log(out)[:300])
    return [ln.strip() for ln in out.splitlines()
            if re.fullmatch(r"[A-Za-z0-9_.\-]+:", ln.strip())]


def _rclone_register_config():
    """Point the backup worker at the same rclone.conf the monitor uses."""
    try:
        cm, cfg = _backup_cfg()
        cfg.setdefault("cloud", {})["rclone_config"] = _rclone_conf_path()
        cm.save_config(cfg)
    except Exception:
        pass


def rclone_status_text():
    exe = _rclone_exe()
    lines = ["<b>rclone cloud setup</b>"]
    if not exe:
        lines.append("Status: <b>not installed</b>")
        lines.append("Install it from here: /rclone install")
    else:
        lines.append("Status: installed")
        lines.append("Version: " + esc(_rclone_version() or "unknown"))
        lines.append("Path: <code>" + esc(exe) + "</code>")
        try:
            remotes = _rclone_remotes()
            lines.append("Remotes: " + (esc(", ".join(remotes)) if remotes else "(none)"))
        except RuntimeError as exc:
            lines.append(esc(str(exc)) + "\nUse My remotes to retry; saved remotes were not changed.")
    target = config.get("rclone_remote") or ""
    lines.append("Image upload target: " + (esc(target) if target else "(not set)"))
    lines.append("")
    lines.append("Choose an action below. Common providers need no typed commands.")
    return "\n".join(lines)


def _rclone_confirm(text, fn, args=()):
    """Review a guided rclone mutation, then execute it once."""
    pid = pend_store({"fn": fn, "args": tuple(args)})
    send_buttons(text, [[("Confirm", "cf:" + pid), ("Cancel", "cx:" + pid)],
                        [("Back to rclone", "rc:menu")]])


def _rclone_start_install():
    threading.Thread(target=rclone_install, daemon=True).start()


def _rclone_start_authorize(name, rtype):
    threading.Thread(target=rclone_authorize, args=(name, rtype), daemon=True).start()


def rclone_menu():
    """Button-first rclone setup for the common providers and operations."""
    rows = [[("Install / repair", "rc:install"), ("My remotes", "rc:list")],
            [("Google Drive", "rc:gdrive"), ("OneDrive", "rc:onedrive")],
            [("Dropbox", "rc:dropbox"), ("Advanced providers", "rc:advanced")],
            [("Cloud backup targets", "cmd:/cloud"), ("Home", "menu:root")]]
    send_buttons(rclone_status_text(), rows)


def rclone_advanced_menu():
    send_buttons(
        "<b>Advanced rclone providers</b>\n"
        "Only credentials still need to be typed; navigation, testing, target "
        "selection, and removal use buttons.\n\n"
        "OAuth token from another device:\n"
        "<code>/rclone token &lt;name&gt; &lt;type&gt; &lt;json&gt;</code>\n\n"
        "S3 / B2 / Wasabi / MinIO / SFTP / FTP / WebDAV:\n"
        "<code>/rclone add &lt;name&gt; &lt;type&gt; key=value ...</code>\n\n"
        "Private Google client:\n"
        "<code>/rclone client gdrive &lt;client_id&gt; &lt;client_secret&gt;</code>",
        [[("My remotes", "rc:list"), ("Back", "rc:menu")]])


def rclone_remotes_menu():
    try:
        remotes = _rclone_remotes()
    except RuntimeError as exc:
        return send_buttons(esc(str(exc)) + "\nSaved remotes were not changed.",
                            [[("Retry", "rc:list"), ("Back", "rc:menu")]])
    if not remotes:
        return send_buttons(
            "<b>rclone remotes</b>\nNone yet. Choose a provider to create one.",
            [[("Google Drive", "rc:gdrive"), ("OneDrive", "rc:onedrive")],
             [("Dropbox", "rc:dropbox"), ("Back", "rc:menu")]])
    rows = []
    for remote in remotes:
        pid = pend_store({"rclone_remote_card": remote})
        rows.append([(remote, "rr:" + pid)])
    rows.append([("Back", "rc:menu")])
    send_buttons("<b>rclone remotes</b>\nChoose one to test, use, or remove.", rows)


def rclone_remote_card(remote):
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+:", remote or ""):
        return send_message("[X] Invalid rclone remote.")
    name = remote[:-1]
    current = config.get("rclone_remote") or ""
    destination = current if current.split(":", 1)[0] == name else remote + "RDPMonitor-Images"
    test_pid = pend_store({"fn": rclone_test, "args": ([name],)})
    use_pid = pend_store({"rclone_use_review": destination})
    del_pid = pend_store({"rclone_delete_review": name})
    text = ("<b>" + esc(remote) + "</b>\n"
            + ("Current image target: <code>" + esc(current) + "</code>\n" if current else "")
            + "Choose an action.")
    send_buttons(text,
                 [[("Test connection", "sc:" + test_pid),
                   ("Use for images", "rs:" + use_pid)],
                  [("Remove", "rd:" + del_pid), ("Back", "rc:list")]])


def rclone_guided_callback(data):
    """Handle short callback identifiers; Telegram limits callback data to 64 bytes."""
    if data == "rc:menu":
        return rclone_menu()
    if data == "rc:list":
        return rclone_remotes_menu()
    if data == "rc:advanced":
        return rclone_advanced_menu()
    if data == "rc:install":
        return _rclone_confirm("Install or repair the suite-managed rclone copy?",
                               _rclone_start_install)
    providers = {"rc:gdrive": ("gdrive", "drive", "Google Drive"),
                 "rc:onedrive": ("onedrive", "onedrive", "OneDrive"),
                 "rc:dropbox": ("dropbox", "dropbox", "Dropbox")}
    if data in providers:
        name, rtype, label = providers[data]
        return _rclone_confirm("Start guided sign-in for <b>" + esc(label) + "</b>?",
                               _rclone_start_authorize, (name, rtype))
    if data.startswith("rr:"):
        pending = pend_take(data[3:])
        remote = pending.get("rclone_remote_card") if pending else None
        return rclone_remote_card(remote) if remote else send_message("This button expired. Open /rclone again.")
    if data.startswith("rs:"):
        pending = pend_take(data[3:])
        destination = pending.get("rclone_use_review") if pending else None
        if not destination:
            return send_message("This button expired. Open /rclone again.")
        return _rclone_confirm("Use <code>" + esc(destination) + "</code> for image uploads?",
                               rclone_set, ([destination],))
    if data.startswith("rd:"):
        pending = pend_take(data[3:])
        name = pending.get("rclone_delete_review") if pending else None
        return rclone_del([name]) if name else send_message("This button expired. Open /rclone again.")


def rclone_install():
    exe = _rclone_exe()
    if exe and os.path.isfile(exe):
        send_message("[OK] rclone is already installed:\n<code>" + esc(exe) + "</code>")
        return
    send_message("Downloading rclone (about 20 MB)...")
    try:
        import io
        import zipfile
        r = requests.get(RCLONE_URL, timeout=300)
        r.raise_for_status()
        digest = hashlib.sha256(r.content).hexdigest()
        if not hmac.compare_digest(digest, RCLONE_SHA256):
            send_message("[X] rclone archive checksum mismatch. Nothing was installed.")
            return
        os.makedirs(_rclone_dir(), exist_ok=True)
        target = os.path.join(_rclone_dir(), "rclone.exe")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            member = next((n for n in z.namelist()
                           if n.lower().endswith("rclone.exe")), None)
            if not member:
                send_message("[X] rclone.exe was not found in the downloaded archive.")
                return
            with open(target, "wb") as f:
                f.write(z.read(member))
        config["rclone_path"] = target
        save_config()
        _rclone_conf_path()
        _rclone_register_config()
        audit_record("rclone installed: " + target)
        send_message("[OK] rclone installed.\n" + esc(_rclone_version()) +
                     "\nPath: <code>" + esc(target) + "</code>")
        rclone_menu()
    except Exception as e:
        send_message("[X] rclone download failed: " + esc(str(e)))


def _rclone_kv(pairs):
    """Turn key=value tokens into the alternating list rclone config expects."""
    kv = []
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            kv += [k, v]
    return kv


def rclone_add(args):
    """args: <name> <type> key=value ...  (non-interactive remotes)."""
    args = [a for a in args if a.lower() != "confirm"]
    if len(args) < 2:
        send_message("Usage: /rclone add &lt;name&gt; &lt;type&gt; key=value ...\n"
                     "Example: /rclone add myb2 b2 account=ID key=SECRET")
        return
    name, rtype = args[0], args[1]
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", name):
        send_message("[X] Invalid remote name.")
        return
    if rtype.lower() in RCLONE_OAUTH_TYPES:
        send_message("[WARN] <b>" + esc(rtype) + "</b> needs a browser sign-in.\n"
                     "On any device run <code>rclone authorize \"" + esc(rtype) +
                     "\"</code>, then paste the token here:\n"
                     "/rclone token " + esc(name) + " " + esc(rtype) + " &lt;json&gt;")
        return
    kv = _rclone_kv(args[2:])
    if not kv:
        send_message("[X] Add at least one key=value, e.g. account=ID key=SECRET")
        return
    ok, out = _rclone_run(["config", "create", name, rtype] + kv, timeout=120)
    audit_record("rclone remote created: " + name + " (" + rtype + ")")
    if ok:
        send_message("[OK] Remote <b>" + esc(name) + "</b> created.\n" + esc(out[-300:]))
    else:
        send_message("[X] Could not create remote:\n" + esc(out[-500:]))


def rclone_token(args):
    """args: <name> <type> <token-json>  (OAuth remotes / service accounts)."""
    args = [a for a in args if a.lower() != "confirm"]
    if len(args) < 3:
        send_message("Usage: /rclone token &lt;name&gt; &lt;type&gt; &lt;json&gt;\n"
                     "Get the JSON on any device with: rclone authorize \"&lt;type&gt;\"")
        return
    name, rtype = args[0], args[1]
    token = " ".join(args[2:]).strip()
    m = re.search(r"\{.*\}", token, flags=re.S)
    if not m:
        send_message("[X] Paste the JSON token printed by <code>rclone authorize</code>.")
        return
    token = m.group(0)
    ok, out = _rclone_run(["config", "create", name, rtype, "token", token], timeout=120)
    audit_record("rclone remote created from token: " + name + " (" + rtype + ")")
    if ok:
        send_message("[OK] Remote <b>" + esc(name) + "</b> created from token.")
    else:
        send_message("[X] Could not create remote:\n" + esc(out[-500:]))


def rclone_client(args):
    """args: <name> <client_id> <client_secret> - set your own Google OAuth client."""
    args = [a for a in args if a.lower() != "confirm"]
    if len(args) < 3:
        send_message(
            "<b>Use your own Google client_id (one time, ~5 min)</b>\n"
            "rclone's shared client_id is retired during 2026. Google has no API to "
            "create OAuth clients, so this part is manual - everything else is automatic.\n\n"
            "1. Create a project: https://console.cloud.google.com/projectcreate\n"
            "2. Enable the Drive API: "
            "https://console.cloud.google.com/apis/library/drive.googleapis.com\n"
            "3. OAuth consent screen (External; add your email as a Test user): "
            "https://console.cloud.google.com/apis/credentials/consent\n"
            "4. Credentials > Create credentials > OAuth client ID > "
            "Application type: <b>Desktop app</b>\n"
            "5. Copy the Client ID and Client secret, then send:\n"
            "<code>/rclone client gdrive &lt;client_id&gt; &lt;client_secret&gt;</code>\n"
            "6. Sign in again: /rclone gdrive\n\n"
            "No Google console at all? Use an S3-compatible cloud instead "
            "(Backblaze B2, Wasabi, MinIO): /rclone add myb2 b2 account=ID key=SECRET")
        return
    name, cid, secret = args[0], args[1], args[2]
    ok, out = _rclone_run(["config", "update", name,
                           "client_id", cid, "client_secret", secret], timeout=60)
    audit_record("rclone client_id set for: " + name)
    if ok:
        send_message("[OK] Client ID set for <b>" + esc(name) + "</b>.\n"
                     "Now sign in again: /rclone gdrive")
    else:
        send_message("[X] Could not update:\n" + esc(out[-400:]))


def rclone_authorize(name, rtype):
    """Guided browser sign-in on the machine; captures the token automatically."""
    exe = _rclone_exe()
    if not exe:
        send_message("[X] rclone is not installed. Run /rclone install first.")
        return
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", name):
        send_message("[X] Invalid remote name.")
        return
    send_message("<b>Sign-in started for '" + esc(name) + "' (" + esc(rtype) + ")</b>\n"
                 "A browser window should open on the machine. Sign in and click Allow.\n"
                 "If nothing opens, I will send a link you can open on the machine.")
    try:
        proc = subprocess.Popen([exe, "authorize", rtype],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
    except Exception as e:
        send_message("[X] Could not start sign-in: " + esc(str(e)))
        return
    lines = []

    def _reader():
        try:
            for ln in proc.stdout:
                lines.append(ln)
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()
    sent_link = False
    start = time.time()
    while proc.poll() is None:
        if time.time() - start > 600:
            try:
                proc.kill()
            except Exception:
                pass
            break
        if not sent_link:
            for ln in list(lines):
                if "following link" in ln.lower():
                    link = ln.split("link:", 1)[-1].strip()
                    if link:
                        send_message("<b>Open this link on the machine to sign in:</b>\n"
                                     + esc(link) + "\n(It only works on the machine "
                                     "itself, e.g. via RDP.)")
                        sent_link = True
                    break
        time.sleep(1)
    time.sleep(1)
    out = "".join(lines)
    m = re.search(r"\{.*\}", out, flags=re.S)
    if not m:
        send_message("[X] Sign-in was not completed. Run /rclone gdrive again.")
        return
    ok, o2 = _rclone_run(["config", "create", name, rtype, "token", m.group(0)],
                         timeout=120)
    if ok:
        audit_record("rclone remote created via sign-in: " + name + " (" + rtype + ")")
        send_message("[OK] Remote <b>" + esc(name) + "</b> created.")
        rclone_remote_card(name + ":")
    else:
        send_message("[X] Sign-in succeeded but saving the remote failed:\n"
                     + esc(o2[-400:]))


def rclone_gdrive(args):
    rclone_authorize(args[0] if args else "gdrive", "drive")


def rclone_test(args):
    remote = args[0] if args else (config.get("rclone_remote") or "")
    if not remote:
        send_message("Usage: /rclone test &lt;remote&gt;")
        return
    target = remote if remote.endswith(":") else remote.split(":")[0] + ":"
    ok, out = _rclone_run(["lsd", target], timeout=60)
    if ok:
        send_message("[OK] " + esc(target) + " reachable.\n" + esc(out[:400] or "(empty)"))
    else:
        send_message("[X] " + esc(target) + " failed:\n" + esc(out[:500]))


def rclone_set(args):
    if not args:
        send_message("Usage: /rclone set &lt;remote:path&gt;\nExample: /rclone set myb2:VPS-Images")
        return
    remote = args[0]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\s]*", remote):
        send_message("[X] Use a destination such as myremote:Images.")
        return
    config["rclone_remote"] = remote
    save_config()
    audit_record("rclone image target set: " + remote)
    send_message("[OK] /image will upload to <b>" + esc(remote) + "</b>.")
    rclone_remote_card(remote.split(":", 1)[0] + ":")


def rclone_del(args):
    if not args:
        send_message("Usage: /rclone del &lt;name&gt; confirm")
        return
    name = args[0]
    if not any(a.lower() == "confirm" for a in args[1:]):
        btns = confirm_buttons("/rclone del " + name)
        if btns:
            send_buttons("Remove remote <b>" + esc(name) + "</b>?", btns)
        else:
            send_message("Add confirm: /rclone del " + esc(name) + " confirm")
        return
    ok, out = _rclone_run(["config", "delete", name], timeout=60)
    audit_record("rclone remote deleted: " + name)
    if ok:
        send_message("[OK] Remote removed.")
        rclone_remotes_menu()
    else:
        send_message("[X] " + esc(out[:300]))


_state_lock = threading.Lock()     # Lock the writing of state files (history/audit/blocked)
_busy_checks = set()               # Tests are running now - Prevents overlapping of two parallel copies
_busy_lock = threading.Lock()


def _check_start(name):
    """True If we start the examination now - False If a copy of it is working (Its cycle is longer than scheduling)"""
    with _busy_lock:
        if name in _busy_checks:
            return False
        _busy_checks.add(name)
        return True


def _check_end(name):
    with _busy_lock:
        _busy_checks.discard(name)

RDP_STATE_WORDS = {"active", "disc", "conn", "idle", "Active", "Online", "Cut", "Inactive"}
AR_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_instance_mutex = None


def _instance_mutex_name():
    """Fixed name for each installed instance, with no port occupation TCP Or conflict with other programs."""
    install_id = hashlib.sha256(BASE_DIR.lower().encode("utf-8")).hexdigest()[:20]
    return "Global\\RDPMonitor_" + install_id


def acquire_instance_lock():
    """Lock Windows mutex Real: A second copy cannot choose an alternative port and start."""
    global _instance_mutex
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, _instance_mutex_name())
        if not handle:
            print("[lock] CreateMutexW failed")
            return False
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _instance_mutex = handle
        return True
    except Exception as e:
        print(f"[lock] mutex error: {e}")
        return False


# ----------------------------- Settings: Save/Download -----------------------------

# ----------------------------- Token encryption (DPAPI) -----------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    blob = _DATA_BLOB(len(data), ptr)
    blob._buf = buf  # Prevent memory from being released before the call finishes
    return blob


def dpapi_protect(plain, machine=None):
    """User DPAPI by default; startup hosting uses machine DPAPI plus private ACLs."""
    in_blob = _dpapi_blob(plain.encode("utf-8"))
    out = _DATA_BLOB()
    if machine is None:
        machine = os.path.isfile(os.path.join(BASE_DIR, "control", "service.json"))
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 4 if machine else 0, ctypes.byref(out))
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return base64.b64encode(
            ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def dpapi_unprotect(b64):
    """Decrypt a user- or machine-scoped DPAPI blob on this device."""
    raw = base64.b64decode(b64)
    in_blob = _dpapi_blob(raw)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


_acl_warned = {"config": False, "dir": False}


def _harden_config_acl(path=None):
    """Reducing powers config.json On Administrators/SYSTEM Only (Best effort)"""
    try:
        r = subprocess.run(
            ["icacls", path or CONFIG_FILE, "/inheritance:r",
             "/grant:r", "*S-1-5-32-544:F", "*S-1-5-18:F"],
            capture_output=True, timeout=15, creationflags=NO_WINDOW)
        if r.returncode != 0 and not _acl_warned["config"]:
            _acl_warned["config"] = True
            print("[security] WARNING: could not restrict config.json permissions (icacls failed)")
    except Exception as e:
        if not _acl_warned["config"]:
            _acl_warned["config"] = True
            print(f"[security] WARNING: config.json ACL hardening error: {e}")


_acl_last = 0.0


def _harden_dir_acl():
    """Locks the tool folder on Administrators/SYSTEM (Writing) AndUsers (Read and execute only)
    - It was a group BUILTIN Users You write in the folder and the tool runs with administrator privileges:
      Local user captures file requests.py Or psutil.py Python loads it on boot
      = Complete escalation of local powers"""
    try:
        r = subprocess.run(
            ["icacls", BASE_DIR, "/inheritance:r",
             "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
             "*S-1-5-32-545:(OI)(CI)RX"],
            capture_output=True, timeout=15, creationflags=NO_WINDOW)
        if r.returncode != 0 and not _acl_warned["dir"]:
            _acl_warned["dir"] = True
            print("[security] WARNING: could not restrict the tool folder permissions (icacls failed)")
    except Exception as e:
        if not _acl_warned["dir"]:
            _acl_warned["dir"] = True
            print(f"[security] WARNING: tool folder ACL hardening error: {e}")


def _clamp_config_int(key, low, high):
    try:
        config[key] = max(low, min(high, int(config.get(key, low))))
    except (TypeError, ValueError):
        config[key] = int(DEFAULT_CONFIG[key])


def _normalize_config():
    """Security limits also apply to config.json Manually modified or coming from an old version."""
    for key in ("cpu_alert_threshold", "ram_alert_threshold",
                "danger_threshold", "critical_threshold", "spike_threshold"):
        _clamp_config_int(key, 1, 100)
    _clamp_config_int("disk_threshold", 10, 99)
    _clamp_config_int("alert_interval", 30, 86400)
    _clamp_config_int("auto_restart_cpu", 50, 100)
    _clamp_config_int("auto_restart_ram", 50, 100)
    _clamp_config_int("auto_restart_consecutive", 1, 60)
    _clamp_config_int("failed_login_block_threshold", 1, 100)
    _clamp_config_int("lockdown_minutes", 1, 1440)
    _clamp_config_int("temp_threshold", 40, 120)
    _clamp_config_int("failed_login_window", 1, 1440)
    _clamp_config_int("weekly_report_day", 0, 6)
    _clamp_config_int("auto_clean_day", 0, 6)
    _clamp_config_int("auto_clean_hour", 0, 23)
    _clamp_config_int("daily_report_hour", 0, 23)
    _clamp_config_int("weekly_report_hour", 0, 23)
    _clamp_config_int("heartbeat_hours", 0, 720)
    _clamp_config_int("update_check_hours", 0, 720)
    _clamp_config_int("speedtest_interval_hours", 0, 720)
    _clamp_config_int("auto_lock_minutes", 0, 1440)
    if str(config.get("failed_logon_types")) not in ("10", "3,10", "10,3"):
        config["failed_logon_types"] = "10"


def load_config():
    global config, CONFIG_LOAD_OK
    saved = {}
    CONFIG_LOAD_OK = False
    # We read the main one first, and if it is damaged, we return to the backup copy .bak
    for path in (CONFIG_FILE, CONFIG_FILE + ".bak"):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    candidate = json.load(f)
                if not isinstance(candidate, dict):
                    raise ValueError("configuration must be a JSON object")
                saved = candidate
                CONFIG_LOAD_OK = True
                break
            except Exception:
                continue  # Corrupt file - We try the next one
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(saved)
    _normalize_config()
    # Token migration to crypto: Existing plaintext from an older version is encrypted and deleted
    if config.get("telegram_token_enc"):
        try:
            config["telegram_token"] = dpapi_unprotect(
                config["telegram_token_enc"])
        except Exception:
            config["telegram_token"] = ""   # Device/Different user - We request the token again
            print("[config] token decryption failed - setup required")
    elif config.get("telegram_token"):
        try:
            config["telegram_token_enc"] = dpapi_protect(
                config["telegram_token"])
            print("[config] plaintext token migrated to DPAPI encryption")
        except Exception:
            pass


def save_config():
    """Atomic conservation: We write to a temporary file and then replace - A power outage corrupts the file
    - The explicit token is never written to disk (encryption DPAPI Only)"""
    with _config_lock:
        tmp = CONFIG_FILE + ".tmp"
        try:
            # dict(config) is a single C-level copy, so it cannot observe a
            # concurrent insert from another thread mid-iteration.
            snapshot = dict(config)
            persist = {k: v for k, v in snapshot.items()
                       if k != "telegram_token"}
            if snapshot.get("telegram_token"):
                # If setup/migration could not encrypt, fail without discarding
                # the only credential or replacing the previous configuration.
                persist["telegram_token_enc"] = dpapi_protect(snapshot["telegram_token"])
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(persist, f, indent=2, ensure_ascii=False)
            if os.path.exists(CONFIG_FILE):
                bak = CONFIG_FILE + ".bak"
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        previous = json.load(f)
                except (OSError, ValueError):
                    previous = None
                if isinstance(previous, dict):
                    token = previous.pop("telegram_token", "")
                    if token:
                        previous["telegram_token_enc"] = dpapi_protect(token)
                    if not _atomic_write_json(bak, previous, indent=2, ensure_ascii=False):
                        raise OSError("could not persist configuration backup")
                    _harden_config_acl(bak)
            os.replace(tmp, CONFIG_FILE)
            # os.replace Creates a new file that inherits the folder’s permissions - We?re shrinking it again
            # After each replacement without dilution: The ten minute window was leaving the file
            # Readable for Users After the second save, it is included
            _harden_config_acl()
            if snapshot.get("telegram_token"):
                config["telegram_token_enc"] = persist["telegram_token_enc"]
            return True
        except Exception as e:
            print(f"[config] save error: {e}")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


_OEM_CP = ""


def _oem_cp():
    """encoding OEM For console (net.exe And qwinsta.exe And cmd.exe They issue it)
    - Mostly in Arabic cp720 - Unscrew UTF-8 It distorts Arabic usernames"""
    global _OEM_CP
    if not _OEM_CP:
        try:
            _OEM_CP = f"cp_{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            _OEM_CP = "cp437"
    return _OEM_CP


def _decode_out(b):
    """Decode Windows command output into correct console encoding"""
    if not b:
        return ""
    try:
        return b.decode(_oem_cp(), "replace")
    except Exception:
        return b.decode("utf-8", "replace")


def _atomic_write_json(path, data, **json_kwargs):
    """Atomic writing of state files: Temporary file + os.replace
    - Direct writing would corrupt the file if the power was cut off while writing
      (The tool checks the ban history/Complete audit silently)"""
    with _state_lock:
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, **json_kwargs)
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"[state] save error ({os.path.basename(path)}): {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False


def _has_console():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


LOG_FILE = os.path.join(BASE_DIR, "rdp_monitor.log")


class _TeeWriter:
    """Directs all outputs print To the console (If any) And log file with time
    - Resolves the problem of errors disappearing when running with pythonw Without window"""

    def __init__(self, original):
        self.original = original
        self._lock = threading.Lock()

    def write(self, s):
        original_length = len(s or "")
        s = redact_log(s or "")
        if s and s.strip():
            try:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with self._lock:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{stamp}] {s.rstrip()}\n")
                # Rotate the record: If he grows older than 512KB We save a copy .old And we start again
                if os.path.getsize(LOG_FILE) > 512 * 1024:
                    older = LOG_FILE + ".old"
                    if os.path.exists(older):
                        os.remove(older)
                    os.replace(LOG_FILE, older)
            except Exception:
                pass
        orig = self.original
        if orig is not None:
            try:
                orig.write(s)
                orig.flush()
            except Exception:
                pass
        return original_length

    def flush(self):
        try:
            if self.original is not None:
                self.original.flush()
        except Exception:
            pass


def _show_setup_required():
    """When operating without a window (pythonw) We explain the setup steps with a text message and file"""
    instructions = (
        "The tool is now running without a window and is not configured yet.\n\n"
        "Setup steps (Once):\n"
        "1) Open CMD In the tool folder\n"
        "2) Job: python rdp_monitor.py\n"
        "3) Enter the bot token and the Chat ID\n\n"
        "Then work install.bat For always running in the background."
    )
    try:
        with open(os.path.join(BASE_DIR, "SETUP_REQUIRED.txt"), "w",
                  encoding="utf-8") as f:
            f.write(instructions)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, instructions, "RDP Monitor - Setup required", 0x40000)
    except Exception:
        pass
    sys.exit(1)


def first_time_setup():
    """Requests setup data from the user upon first startup"""
    if not _has_console():
        _show_setup_required()
    print("=" * 60)
    print("  Welcome to RDP Monitor - first-time setup")
    print("=" * 60)
    print()
    print("1) Create a bot via @BotFather on Telegram and copy the Token")
    print("2) Send any message to your bot, then get your Chat ID from @userinfobot")
    print("   The token is stored encrypted (Windows DPAPI) - never in plaintext.")
    print()

    try:
        while not config.get("telegram_token"):
            token = input("Enter bot token: ").strip()
            try:
                r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
                data = r.json()
                if data.get("ok"):
                    print(f"   token OK - bot: @{data['result'].get('username', '?')}")
                    config["telegram_token"] = token
                    try:
                        config["telegram_token_enc"] = dpapi_protect(token)
                        config["telegram_token"] = token  # By memory only - It is not saved
                    except Exception as e:
                        print(f"   encryption failed: {e}")
                    break
                print("   invalid token, try again")
            except Exception as e:
                print(f"   telegram connection failed: {e}")

        while not config.get("chat_id"):
            chat_id = input("Enter Chat ID: ").strip()
            if chat_id.lstrip("-").isdigit():
                config["chat_id"] = chat_id
                if chat_id.startswith("-"):
                    print("   [!] A negative ID is a GROUP: alerts go there, but")
                    print("       ONLY personal User IDs can send commands -")
                    print("       group members (including you) cannot run /allow.")
                    # Without this step, the device remains without any controller after setup!
                    while True:
                        uid = input("Enter YOUR personal Telegram User ID "
                                    "(@userinfobot) - required for group setup: ").strip()
                        if uid.isdigit() and int(uid) > 0:
                            config["trusted_user_ids"] = [uid]
                            print(f"   OK - user {uid} can control the bot")
                            break
                        print("   must be a positive personal User ID")
                break
            print("   Chat ID must be a number (negative for groups)")
    except (EOFError, OSError):
        _show_setup_required()

    save_config()
    _harden_config_acl()
    print()
    print(f"Saved config to: {CONFIG_FILE} (token encrypted)")
    print()


# ----------------------------- Telegram -----------------------------

def tg_api(method, **params):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config['telegram_token']}/{method}",
            json=params, timeout=15)
        return r.json()
    except Exception as e:
        print(f"[telegram] error in {method}: {e}")
        return {"ok": False}


def _allowed_user_ids():
    """All user IDs allowed to send commands:
    Main chat owner + Trusted list (+ chat ids Old for compatibility)"""
    ids = []
    if config.get("chat_id"):
        ids.append(str(config["chat_id"]))
    for t in (config.get("trusted_user_ids") or []):
        s = str(t)
        if s not in ids:
            ids.append(s)
    for t in (config.get("trusted_chat_ids") or []):
        s = str(t)
        if s not in ids:
            ids.append(s)
    return ids


def _alert_targets():
    """All chats are allowed: Main + Trusted accounts"""
    return _allowed_user_ids()


def _tag():
    """Prefix the device name before each message"""
    name = config.get("instance_name")
    return f"[{name}] " if name else ""


# ----------------------------- Queue pending alerts -----------------------------
# Permanent queue on disk: Restart the tool or Windows do not lose text alerts.
_alert_queue = deque(maxlen=500)
_file_queue = deque(maxlen=50)
_alert_q_lock = threading.Lock()


def _persist_alert_queue_locked():
    try:
        _atomic_write_json(ALERT_QUEUE_FILE, list(_alert_queue),
                           ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[alert-queue] save error: {e}")


def _persist_file_queue_locked():
    try:
        _atomic_write_json(FILE_QUEUE_FILE, list(_file_queue),
                           ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[file-queue] save error: {e}")


def load_alert_queue():
    with _alert_q_lock:
        _alert_queue.clear()
        try:
            if os.path.exists(ALERT_QUEUE_FILE):
                with open(ALERT_QUEUE_FILE, "r", encoding="utf-8") as f:
                    rows = json.load(f)
                now = time.time()
                for row in rows[-500:]:
                    if isinstance(row, list) and len(row) == 3 \
                            and now - float(row[0]) <= 86400:
                        _alert_queue.append((float(row[0]), str(row[1]),
                                             str(row[2])))
        except Exception as e:
            print(f"[alert-queue] load error: {e}")
        _persist_alert_queue_locked()
        _file_queue.clear()
        try:
            if os.path.exists(FILE_QUEUE_FILE):
                with open(FILE_QUEUE_FILE, "r", encoding="utf-8") as f:
                    rows = json.load(f)
                now = time.time()
                for row in rows[-50:]:
                    if isinstance(row, list) and len(row) in (5, 6) \
                            and now - float(row[0]) <= 86400:
                        _file_queue.append((float(row[0]), str(row[1]),
                                            str(row[2]), str(row[3]),
                                            str(row[4]), row[5] is True if len(row) == 6 else False))
        except Exception as e:
            print(f"[file-queue] load error: {e}")
        _persist_file_queue_locked()


def _queue_alert(chat, text):
    with _alert_q_lock:
        _alert_queue.append((time.time(), chat, text))
        _persist_alert_queue_locked()


def _queue_file(kind, chat, path, caption, cleanup=False):
    with _alert_q_lock:
        _file_queue.append((time.time(), kind, chat, path, caption or "", bool(cleanup)))
        _persist_file_queue_locked()


def _cleanup_queued_temp(path):
    """Delete a generated file after delivery, but only inside the temp folder."""
    try:
        with _alert_q_lock:
            if any(os.path.normcase(os.path.abspath(row[3])) ==
                   os.path.normcase(os.path.abspath(path)) for row in _file_queue):
                return
            tmp_root = os.path.realpath(tempfile.gettempdir())
            real = os.path.realpath(path)
            if os.path.commonpath([tmp_root, real]) == tmp_root and os.path.isfile(real):
                os.remove(real)
    except Exception:
        pass


def _send_file_once(kind, chat, path, caption):
    if not os.path.isfile(path):
        return None
    field = "photo" if kind == "photo" else "document"
    method = "sendPhoto" if kind == "photo" else "sendDocument"
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{config['telegram_token']}/{method}",
                data={"chat_id": chat, "caption": caption,
                      "parse_mode": "HTML"},
                files={field: (os.path.basename(path), f)}, timeout=180)
        try:
            return bool(r.ok and r.json().get("ok"))
        except Exception:
            return False
    except Exception as e:
        print(f"[telegram] {kind} send error: {e}")
        return False


def _drain_alert_queue():
    while True:
        time.sleep(60)
        while True:
            with _alert_q_lock:
                while _alert_queue and time.time() - _alert_queue[0][0] > 86400:
                    _alert_queue.popleft()
                    _persist_alert_queue_locked()
                if not _alert_queue:
                    break
                ts, chat, text = _alert_queue[0]
            res = tg_api("sendMessage", chat_id=chat, text=text[:3900])
            if not res.get("ok"):
                break
            with _alert_q_lock:
                if _alert_queue and _alert_queue[0] == (ts, chat, text):
                    _alert_queue.popleft()
                    _persist_alert_queue_locked()
        while True:
            with _alert_q_lock:
                while _file_queue and time.time() - _file_queue[0][0] > 86400:
                    _file_queue.popleft()
                    _persist_file_queue_locked()
                if not _file_queue:
                    break
                item = _file_queue[0]
            ts, kind, chat, path, caption, cleanup = item
            sent = _send_file_once(kind, chat, path, caption)
            if sent is False:
                break
            with _alert_q_lock:
                if _file_queue and _file_queue[0] == item:
                    _file_queue.popleft()
                    _persist_file_queue_locked()
            if sent is None:
                _queue_alert(chat, f"[X] The file could not be resubmitted because it no longer exists: {path}")
            elif sent and cleanup:
                _cleanup_queued_temp(path)


# When the WebConsole panel asks for a read-only report, the bot's own
# formatting helpers are redirected into this buffer instead of Telegram.
_CAPTURE = threading.local()


def _capture_begin():
    _CAPTURE.lines = []


def _capture_end():
    lines = getattr(_CAPTURE, "lines", None)
    _CAPTURE.lines = None
    return "\n".join(lines or [])


def _capture_add(text):
    lines = getattr(_CAPTURE, "lines", None)
    if lines is not None:
        lines.append(_strip_tags(str(text)).replace("\u200f", ""))
        return True
    return False


def send_message(text):
    if _capture_add(text):
        return
    text = _tag() + text
    text = _fix_rtl(text)  # Unifying the direction of all Arabic lines in all tool messages
    # Split long messages (Telegram limit 4096 distorted) - Otherwise the transmission fails silently
    chunks = []
    rest = text
    while len(rest) > 3900:
        cut = rest.rfind("\n", 2500, 3900)  # Divide at the end of a line if possible
        if cut == -1:
            cut = 3900
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    chunks.append(rest)
    for chat in _alert_targets():
        for chunk in chunks:
            res = tg_api("sendMessage", chat_id=chat, text=chunk,
                         parse_mode="HTML")
            if res.get("ok"):
                continue
            # Net outage/Telegram? Store to send when you return - Don’t miss alerts
            plain = _strip_tags(chunk) if "<" in chunk else chunk
            if "<" in chunk:
                res = tg_api("sendMessage", chat_id=chat, text=plain)
            if not res.get("ok"):
                _queue_alert(chat, plain)


def _strip_tags(text):
    """He removes tags HTML From the text - For places that are sent without analysis HTML"""
    return re.sub(r"</?[a-zA-Z][^>]*>", "", text)


RLM = "\u200f"  # Right turn sign-left

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def _fix_rtl(text):
    """Central processor of direction: Every line in Arabic begins with a marker RTL
    - It is prohibited to mix numbers and English with the Arabic position in Telegram
    - Excludes blocks <pre> (Digital trend tables LTR)"""
    parts = re.split(r"(<pre>.*?</pre>)", text, flags=re.DOTALL)
    out = []
    for part in parts:
        if part.startswith("<pre>"):
            out.append(part)
            continue
        lines = []
        for ln in part.split("\n"):
            if _ARABIC_RE.search(ln) and not ln.startswith(RLM):
                ln = RLM + ln
            lines.append(ln)
        out.append("\n".join(lines))
    return "".join(out)


def rtl(text):
    """Forces direction RTL On the line - It is prohibited to mix numbers and English with Arabic"""
    return RLM + text


def esc(text):
    """Smuggling typefaces HTML For dynamic content (Process names, event messages...)"""
    return html.escape(str(text), quote=False)


def send_plain(text):
    """Send without HTML (Important for command output that may contain < >)
    - It automatically removes tags even if they leak into the text, and the transmission fails and is stored in the queue"""
    if _capture_add(text):
        return
    text = _tag() + _strip_tags(text)
    text = _fix_rtl(text)
    for chat in _alert_targets():
        for i in range(0, len(text), 3900):
            res = tg_api("sendMessage", chat_id=chat, text=text[i:i + 3900])
            if not res.get("ok"):
                _queue_alert(chat, text[i:i + 3900])


def send_buttons(text, rows):
    """Message with buttons inline - rows = [[(Text_button, callback_data), ...], ...]
    - When transmission fails (interruption): The text enters the notification queue (No buttons —
      It is worse to receive the text than to lose it all, and the button alerts are the most important texts)"""
    if _capture_add(text):
        return
    plain = _strip_tags(text)
    text = _tag() + _fix_rtl(text)
    markup = {"inline_keyboard": [
        [{"text": t, "callback_data": d} for t, d in row] for row in rows]}
    for chat in _alert_targets():
        res = tg_api("sendMessage", chat_id=chat, text=text,
                     parse_mode="HTML", reply_markup=markup)
        if not res.get("ok"):
            res = tg_api("sendMessage", chat_id=chat, text=plain,
                         reply_markup=markup)
        if not res.get("ok"):
            _queue_alert(chat, plain)


# ----------------------------- Queue of deferred buttons (Confirm/Deny) -----------------------------
# Telegram limit 64 byte on callback_data: The entire command is stored in memory and the button holds only its identifier
_pending = {}                      # {id: {"cmd": Text} Or {"fn": function, "args": tuple}}
_pend_seq = 0
_pend_lock = threading.Lock()
PENDING_TTL = 1800                 # Confirm button expired: 30 Minute


def pend_store(payload):
    """Stores a deferred command and returns a short identifier for the button - Neglects the old expired one"""
    global _pend_seq
    with _pend_lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if now - v["t"] > PENDING_TTL]:
            del _pending[k]
        if len(_pending) > 300:
            for k in sorted(_pending, key=lambda k: _pending[k]["t"])[:100]:
                del _pending[k]
        # Find a free 4-hex id instead of blindly wrapping modulo 65536, which
        # could overwrite a live pending confirmation.
        for _ in range(65536):
            _pend_seq = (_pend_seq + 1) % 65536
            pid = format(_pend_seq, "04x")
            if pid not in _pending:
                break
        payload["t"] = now
        _pending[pid] = payload
    return pid


def pend_take(pid):
    """Consume a live deferred action once; expired buttons never execute."""
    with _pend_lock:
        payload = _pending.pop(pid, None)
        if payload is None or time.time() - payload["t"] >= PENDING_TTL:
            return None
        return payload


def confirm_buttons(cmdline):
    """Confirmation buttons are ready for any command, no matter how long it takes — The user confirms with the click of a button instead of retyping
    - The command is stored in memory and the button holds only its identifier (Telegram limit 64 byte)
    - The button works once and then it’s over 30 Minute — Then he announces the expiration instead of doing something wrong"""
    pid = pend_store({"cmd": cmdline.strip()})
    return [[("Confirm - execute", "cf:" + pid),
             ("Cancel - do nothing", "cx:" + pid)]]


def handle_pending(pid):
    """The delayed order is executed after pressing Confirm — It works from the command queue"""
    p = pend_take(pid)
    if not p:
        send_message("The confirmation button has expired (30 Minute) — Resend the command.\n"
                     "Confirm button expired — send the command again.")
        return
    if "cmd" in p:
        handle_command(p["cmd"] + " confirm")
    else:
        try:
            p["fn"](*p.get("args", ()))
        except Exception as e:
            send_message(f"[X] Error executing the action: {e}")


# ----------------------------- Unified suite: WebConsole + Backup -----------------------------
# The monitor bot is the single Telegram interface. It exposes the browser
# panel and drives the isolated SYSTEM backup worker through a fixed-path
# control file, then relays the backup result back to chat.

SUITE_ROOT = BASE_DIR
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
BACKUP_CONTROL_DIR = os.path.join(BACKUP_DIR, "control")
BACKUP_REQUEST = os.path.join(BACKUP_CONTROL_DIR, "request.json")
BACKUP_STATUS = os.path.join(BACKUP_CONTROL_DIR, "status.json")
BACKUP_PROGRESS = os.path.join(BACKUP_CONTROL_DIR, "progress.json")
BACKUP_RESULT = os.path.join(BACKUP_CONTROL_DIR, "last_result.json")
BACKUP_LAST_RUN = os.path.join(BACKUP_DIR, "logs", "last_run.json")
BACKUP_LOCAL_DIR = os.path.join(BACKUP_DIR, "local_backups")
WEBCONSOLE_STATE = os.path.join(BASE_DIR, "webconsole", "webconsole_state.json")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def webconsole_port():
    try:
        return int(_read_json(WEBCONSOLE_STATE, {}).get("port", 8399))
    except (TypeError, ValueError):
        return 8399


def webconsole_bind():
    return str(_read_json(WEBCONSOLE_STATE, {}).get("bind", "127.0.0.1"))


def webconsole_scheme():
    return "https" if webconsole_bind() not in ("127.0.0.1", "::1", "localhost") else "http"


def webconsole_url(host="127.0.0.1"):
    return f"{webconsole_scheme()}://{host}:{webconsole_port()}/"


def panel_hosts():
    """Detected hosts for the panel URL so it works on any machine/RDP."""
    hosts = [("Local", "127.0.0.1")]
    if webconsole_bind() in ("127.0.0.1", "::1", "localhost"):
        return hosts  # remote access is not enabled
    seen = set()
    try:
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if getattr(a, "family", None) == socket.AF_INET and getattr(a, "address", ""):
                    if not a.address.startswith("127.") and a.address not in seen:
                        seen.add(a.address)
                        hosts.append((name, a.address))
    except Exception:
        pass
    try:
        import urllib.request
        ext = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode().strip()
        if ext and ext not in seen:
            hosts.append(("External", ext))
    except Exception:
        pass
    return hosts


def panel_login_url(host):
    """One-time auto-login link: valid ~10 minutes, no permanent token in the URL."""
    tok = webconsole_token()
    if not tok:
        return None
    exp = str(int(time.time()) + 600)
    otp = hmac.new(tok.encode("utf-8"), exp.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{webconsole_scheme()}://{host}:{webconsole_port()}/?exp={exp}&otp={otp}"


def _mk_button(label, value):
    value = str(value)
    if value.startswith("http"):
        return {"text": label, "url": value}
    return {"text": label, "callback_data": value}


def send_url_buttons(text, rows):
    """Inline keyboard that can mix URL buttons and callback buttons."""
    plain = _strip_tags(text)
    text = _tag() + _fix_rtl(text)
    markup = {"inline_keyboard": [[_mk_button(t, v) for t, v in row] for row in rows]}
    for chat in _alert_targets():
        res = tg_api("sendMessage", chat_id=chat, text=text, parse_mode="HTML", reply_markup=markup)
        if not res.get("ok"):
            res = tg_api("sendMessage", chat_id=chat, text=plain, reply_markup=markup)
        if not res.get("ok"):
            _queue_alert(chat, plain)


def webconsole_token():
    """Read the panel login token (same user session, so DPAPI user scope works)."""
    st = _read_json(WEBCONSOLE_STATE, {})
    enc = st.get("token_enc")
    if not enc:
        return None
    try:
        return dpapi_unprotect(enc)
    except Exception:
        return None


def send_panel_info():
    if not webconsole_token():
        send_message("No panel token stored yet. Start the WebConsole first.")
        return
    local_only = webconsole_bind() in ("127.0.0.1", "::1", "localhost")
    rows = []
    for label, host in panel_hosts()[:4]:
        if local_only and host not in ("127.0.0.1", "localhost", "::1"):
            continue
        address = "[" + host + "]" if ":" in host else host
        u = f"{webconsole_scheme()}://{address}:{webconsole_port()}/"
        rows.append([(f"Open {label} ({host})", u)])
    rows.append([("Show login token", "panel:token"), ("Panel status", "run:/panelstatus")])
    rows.append([("Direct IP:port access", "cmd:/panelremote direct"),
                 ("Access settings", "cmd:/panelremote")])
    note = ("Open an HTTPS link, then enter your login token on the sign-in screen. "
            "Remote settings are saved across restarts. A self-signed certificate "
            "may show a browser warning. External reachability depends on the provider firewall."
            if not local_only else
            "Local-only panel (open it inside the RDP session). Choose Direct IP:port "
            "access below to enable HTTPS from outside without an extra app.")
    send_url_buttons("<b>WebConsole panel</b>\n" + note, rows)


def send_panel_token():
    tok = webconsole_token()
    if not tok:
        send_message("No panel token found. Start the WebConsole, then try again.")
        return
    audit_record("Panel token revealed")
    send_message("<b>WebConsole login token</b>\n"
                 f"<code>{esc(tok)}</code>\n"
                 "Keep it private — it grants full control of the panel.")


def send_panel_status():
    url = webconsole_url()
    up = False
    try:
        import ssl as _ssl
        import urllib.request
        ctx = _ssl._create_unverified_context()
        with urllib.request.urlopen(url + "health", timeout=3, context=ctx) as r:
            up = bool(json.loads(r.read().decode()).get("ok"))
    except Exception:
        up = False
    send_message("<b>Panel status</b>\n"
                 f"URL: <code>{esc(url)}</code>\n"
                 f"Reachable: {'yes' if up else 'no'}\n"
                 f"Token stored: {'yes' if webconsole_token() else 'no'}")


def _run_webconsole_cli(cli_args, timeout=90):
    """Run the WebConsole CLI (remote mode, cert, allow-list) as this user."""
    wc = os.path.join(BASE_DIR, "webconsole", "RDPWebConsole.py")
    try:
        r = subprocess.run([sys.executable, wc] + cli_args, capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        out = (_decode_out(r.stdout) + _decode_out(r.stderr)).strip()
        return r.returncode, out
    except Exception as e:
        return 1, repr(e)


def panel_remote(arg=""):
    """Turn the WebConsole remote (HTTPS on 0.0.0.0) mode on or off."""
    parts = (arg or "").strip().split()
    verb = parts[0].lower() if parts else "on"
    if verb in ("on", "enable", "start"):
        rc, out = _run_webconsole_cli(["remote-enable"])
    elif verb in ("direct", "open", "any", "public"):
        rc, out = _run_webconsole_cli(["remote-enable", "--allow", "0.0.0.0/0"])
    elif verb in ("off", "disable", "stop"):
        rc, out = _run_webconsole_cli(["remote-disable"])
    elif verb == "status":
        rc, out = _run_webconsole_cli(["remote-status"])
    elif verb in ("allow", "add") and len(parts) > 1:
        rc, out = _run_webconsole_cli(["remote-allow-add"] + parts[1:])
    elif verb in ("deny", "remove") and len(parts) > 1:
        rc, out = _run_webconsole_cli(["remote-allow-remove"] + parts[1:])
    else:
        send_message("Usage: /panelremote [direct | on | off | status | allow <ip> | deny <ip>]\n"
                     "direct = HTTPS by IP:port from any IPv4 address; on = restricted HTTPS.")
        return
    audit_record("Panel remote %s -> rc=%s" % (arg or "on", rc))
    if rc == 0 and verb in ("on", "enable", "start", "direct", "open", "any", "public"):
        send_message("Remote access enabled — the panel now listens on 0.0.0.0 over HTTPS.")
        time.sleep(4)  # let the supervisor restart the WebConsole on the new bind
        send_panel_info()
        return
    head = "Panel remote" if rc == 0 else "Panel remote failed"
    send_message(f"<b>{head}</b>\n<pre>{esc(out[-1200:] or 'no output')}</pre>")


def queue_backup_request():
    """Queue one validated manual backup for the SYSTEM worker."""
    os.makedirs(BACKUP_CONTROL_DIR, exist_ok=True)
    lock_path = BACKUP_REQUEST + ".lock"
    try:
        if os.path.exists(lock_path) and time.time() - os.path.getmtime(lock_path) > 120:
            os.remove(lock_path)
    except OSError:
        pass
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False, "another backup request is being queued"
    try:
        if os.path.exists(BACKUP_REQUEST):
            existing = _read_json(BACKUP_REQUEST, {})
            if time.time() - float(existing.get("created", 0) or 0) > 3600:
                try:
                    os.remove(BACKUP_REQUEST)
                except OSError:
                    pass
        if os.path.exists(BACKUP_REQUEST):
            return False, "a backup request is already pending"
        rid = os.urandom(9).hex()
        if not _atomic_write_json(BACKUP_REQUEST, {"version": 1, "id": rid, "action": "backup",
                                                  "created": time.time(), "requested_by": "telegram"}):
            return False, "could not persist the backup request"
        audit_record("Backup requested from Telegram")
        return True, rid
    finally:
        os.close(fd)
        try:
            os.remove(lock_path)
        except OSError:
            pass


def backup_status_text():
    worker = _read_json(BACKUP_STATUS, {})
    last = _read_json(BACKUP_LAST_RUN, {})
    bcfg = _read_json(os.path.join(BACKUP_DIR, "config.json"), {})
    items = []
    try:
        for name in sorted(os.listdir(BACKUP_LOCAL_DIR), reverse=True):
            p = os.path.join(BACKUP_LOCAL_DIR, name)
            if name.startswith("Backup_") and os.path.isfile(p):
                items.append((name, os.path.getsize(p)))
            if len(items) >= 5:
                break
    except OSError:
        pass
    sched = bcfg.get("schedule", {})
    lines = ["<b>Backup status</b>",
             f"Worker: <b>{esc(str(worker.get('state', 'unknown')))}</b> — "
             f"{esc(str(worker.get('message', '')))}"]
    if last.get("last_success"):
        lines.append(f"Last success: {esc(str(last['last_success']))}")
    if last.get("summary"):
        lines.append(esc(str(last["summary"])[:200]))
    if not sched.get("enabled"):
        schedule_label = "disabled"
    elif sched.get("mode") == "interval":
        schedule_label = f"every {sched.get('interval_hours', '?')} hours"
    elif sched.get("mode") == "times":
        schedule_label = "at " + ", ".join(sched.get("times") or [])
    else:
        schedule_label = f"daily at {sched.get('time', '03:00')}"
    lines.append("Schedule: " + esc(schedule_label))
    source_count = len((bcfg.get("backup") or {}).get("sources") or [])
    lines.append(f"Sources: {source_count}")
    if sched.get("enabled") and not source_count:
        lines.append("[WARN] Setup incomplete: add a backup source with /backsrc add.")
    if items:
        lines.append("")
        lines.append("Local archives:")
        lines += [f"• {esc(n)} — {format_size(s)}" for n, s in items]
    return "\n".join(lines)


def backup_list_text():
    items = []
    try:
        for name in sorted(os.listdir(BACKUP_LOCAL_DIR), reverse=True):
            p = os.path.join(BACKUP_LOCAL_DIR, name)
            if name.startswith("Backup_") and os.path.isfile(p):
                items.append((name, os.path.getsize(p), os.path.getmtime(p)))
            if len(items) >= 15:
                break
    except OSError:
        pass
    if not items:
        return "No local backup archives found."
    lines = ["<b>Local backups</b>"]
    for name, size, mtime in items:
        when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• {esc(name)}\n  {format_size(size)} — {when}")
    return "\n".join(lines)


def _suite_backup_module(name):
    """Import a module from backup/app (restore, config_manager) on demand."""
    import importlib
    path = os.path.join(BACKUP_DIR, "app")
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def suite_restore(archive_name, dest_root=None):
    """Restore one archive into an isolated folder. Returns (result, error)."""
    try:
        restore_mod = _suite_backup_module("restore")
        config_manager = _suite_backup_module("config_manager")
        cfg = config_manager.load_config()
        pw = (cfg.get("backup", {}).get("archive_password") or "").strip()
        b = next((x for x in restore_mod.list_backups() if x["name"] == archive_name), None)
        if not b:
            return None, "archive not found"
        # A fresh, unique folder per restore so a repeat never overwrites.
        dest = dest_root or restore_mod.new_restore_dir(
            os.path.join(SUITE_ROOT, "restore"), archive_name)
        res = restore_mod.restore_archive(b["path"], dest, password=pw)
        audit_record("Restore: %s -> %s (%s)" % (archive_name, dest, res.get("status")))
        return res, None
    except Exception as e:
        return None, repr(e)


def suite_drill():
    """Run a restore drill of the newest archive. Returns (result, error)."""
    try:
        restore_mod = _suite_backup_module("restore")
        config_manager = _suite_backup_module("config_manager")
        cfg = config_manager.load_config()
        dest = (cfg.get("restore_drill", {}) or {}).get("dest", "")
        res = restore_mod.run_drill(cfg, dest, log=lambda *a, **k: None)
        audit_record("Restore drill: %s" % res.get("status"))
        return res, None
    except Exception as e:
        return None, repr(e)


# ----------------------------- Panel control channel (RDP security) -----------------------------
MONITOR_CONTROL_DIR = os.path.join(SUITE_ROOT, "control")
MONITOR_REQUEST = os.path.join(MONITOR_CONTROL_DIR, "request.json")
MONITOR_RESULT = os.path.join(MONITOR_CONTROL_DIR, "result.json")


def api_rdp_status():
    load_blocked()
    return {
        "port": int(config.get("rdp_port", 3389)),
        "allow_active": bool(config.get("rdp_allow_active")),
        "lockdown": lockdown_active(),
        "panic": bool(config.get("panic_active")),
        "allowed_ips": [str(i) for i in (config.get("rdp_allowed_ips") or [])],
        "blocked_count": len(_blocked),
    }


def api_rdp_allow_add(ip):
    ip = str(ip).strip()
    if not _valid_ip(ip):
        return False, "invalid IP"
    ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
    if ip in ips:
        return True, "already in the list"
    ips.append(ip)
    config["rdp_allowed_ips"] = ips
    save_config()
    if config.get("rdp_allow_active") or lockdown_active():
        apply_rdp_allow(lockdown_ips() if lockdown_active() else ips)
    audit_record("Panel: allow-list add " + ip)
    return True, "added " + ip


def api_rdp_allow_remove(ip):
    ip = str(ip).strip()
    ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
    if ip not in ips:
        return False, "not in the list"
    ips.remove(ip)
    config["rdp_allowed_ips"] = ips
    save_config()
    if lockdown_active():
        apply_rdp_allow(lockdown_ips())
    elif config.get("rdp_allow_active"):
        apply_rdp_allow(ips)
    audit_record("Panel: allow-list remove " + ip)
    return True, "removed " + ip


def api_rdp_allow_apply():
    ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
    if not ips:
        return False, "the allow-list is empty"
    if not apply_rdp_allow(ips):
        return False, _allow_fail_info or "failed to apply the restriction"
    config["rdp_allow_active"] = True
    save_config()
    audit_record("Panel: allow-list applied")
    return True, "RDP is now restricted to the allow-list"


def api_rdp_allow_clear():
    if lockdown_active():
        return False, "a lockdown is active; release it first"
    if not apply_rdp_allow([]):
        return False, "allow-list release failed; recorded restriction retained; inspect /firewall"
    config["rdp_allow_active"] = False
    config["rdp_allowed_ips"] = []
    save_config()
    audit_record("Panel: allow-list cleared")
    return True, "restriction cleared (RDP is open to any IP)"


def api_lockdown(mode):
    if mode == "on":
        ok = lockdown_start(manual=True)
        return (bool(ok), "lockdown started" if ok else "could not start the lockdown")
    if mode == "off":
        ok = lockdown_release()
        return bool(ok), "lockdown released" if ok else "lockdown release failed; inspect firewall"
    return True, "lockdown is active" if lockdown_active() else "no lockdown"


def api_panic(mode):
    if mode == "on":
        panic_on()
        ok = bool(config.get("panic_active"))
        return ok, "panic mode activated (RDP closed)" if ok else "panic activation failed"
    if mode == "off":
        panic_off()
        ok = not config.get("panic_active")
        return ok, "panic mode released" if ok else "panic release could not be verified"
    return True, "panic mode is active" if config.get("panic_active") else "panic mode is off"


def _valid_user_name(name):
    return bool(re.fullmatch(r"[A-Za-z0-9_.\- ]{1,40}", str(name or "")))


def api_users_list():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$ErrorActionPreference='Stop'; Get-LocalUser | Select-Object Name,Enabled,LastLogon | "
                            "ConvertTo-Json -Compress"],
                           capture_output=True, timeout=40, creationflags=NO_WINDOW)
        out = _decode_out(r.stdout)
        if r.returncode != 0:
            return False, "Windows user query failed. Retry; no accounts were changed."
    except Exception as exc:
        return False, "Windows user query failed: " + redact_log(str(exc))[:200]
    items = []
    try:
        data = json.loads(out) if out.strip() else []
        if data is None:
            data = []
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or any(not isinstance(i, dict) or not i.get("Name") for i in data):
            raise ValueError("invalid user response")
        for i in data:
            items.append({"name": i.get("Name"), "enabled": bool(i.get("Enabled")),
                          "last": i.get("LastLogon")})
    except Exception:
        return False, "Windows returned an invalid user list. Retry; no accounts were changed."
    return True, items


@serialized_account_action
def api_user_action(action, name, value=""):
    if not config.get("user_management", False):
        return False, "user management is disabled"
    name = str(name or "").strip()
    if not _valid_user_name(name):
        return False, "invalid user name"
    if action not in ("enable", "disable", "delete", "password", "rename", "add"):
        return False, "unknown action"
    if action in ("delete", "disable", "password"):
        allowed, warning = last_admin_guard(name)
        if not allowed:
            return False, _panel_text(warning)
    if action in ("add", "password"):
        weak = _password_weak(str(value))
        if weak:
            return False, "weak password: " + weak
    q = _ps_quote(name)
    if action == "enable":
        ok = ps_ok(f"Enable-LocalUser -Name '{q}' -ErrorAction Stop")
    elif action == "disable":
        ok = ps_ok(f"Disable-LocalUser -Name '{q}' -ErrorAction Stop")
    elif action == "delete":
        ok = ps_ok(f"Remove-LocalUser -Name '{q}' -ErrorAction Stop")
    elif action == "password":
        ok = ps_ok("$p=ConvertTo-SecureString '" + _ps_quote(str(value)) +
                   "' -AsPlainText -Force; Set-LocalUser -Name '" + q +
                   "' -Password $p -ErrorAction Stop")
    elif action == "rename":
        if not _valid_user_name(value):
            return False, "invalid new name"
        ok = ps_ok(f"Rename-LocalUser -Name '{q}' -NewName '{_ps_quote(str(value))}' -ErrorAction Stop")
    elif action == "add":
        ok = ps_ok("$p=ConvertTo-SecureString '" + _ps_quote(str(value)) +
                   "' -AsPlainText -Force; New-LocalUser -Name '" + q +
                   "' -Password $p -ErrorAction Stop")
    else:
        return False, "unknown action"
    audit_record("Panel user %s: %s" % (action, name))
    return ok, ("done" if ok else "failed")


def _panel_text(value):
    """Plain text for the panel: drop HTML tags and RTL markers."""
    return _strip_tags(str(value)).replace("\u200f", "")


# A config key is a credential if its name contains one of these fragments or
# ends in "_key"/is exactly "key". /configbackup (bot + panel) must never return
# such values in the clear - not just the Telegram token.
_SENSITIVE_KEY_HINTS = (
    "token", "secret", "password", "passphrase", "pwd", "credential",
    "webhook", "private", "apikey", "api_key", "api_hash", "authorization", "connection_string",
)
_SENSITIVE_KEY_RE = re.compile(r"(^|_)key$", re.IGNORECASE)


def _is_sensitive_key(name):
    text = str(name).lower()
    if any(hint in text for hint in _SENSITIVE_KEY_HINTS):
        return True
    return bool(_SENSITIVE_KEY_RE.search(text))


def _mask_secret(key, value):
    """Match upstream credential masking for strings, containers and numbers."""
    if value is None or value == "":
        return value
    if isinstance(value, str) and str(key).lower() == "telegram_token":
        return "***" + value[-4:]
    return "***redacted***"


def _redact_config(data):
    """Deep copy a config value with every credential masked for /configbackup."""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            if _is_sensitive_key(key):
                masked[key] = _mask_secret(key, value)
            else:
                masked[key] = _redact_config(value)
        return masked
    if isinstance(data, list):
        return [_redact_config(item) for item in data]
    return data


# The panel waits 150s for /api/diag, and the monitor services one request at a
# time, so a slow job must not hold the mailbox longer than this. A job that
# overruns holds its capacity slot until it exits; further jobs are rejected.
_PANEL_JOB_DEADLINE = 90
_PANEL_JOB_SLOTS = threading.BoundedSemaphore(1)


def _run_captured_job(fn, deadline=None):
    """Bound the response wait and admit at most one running captured job.

    Same _capture_begin/_capture_end behaviour as the inline jobs, but on a
    worker thread so a hung job cannot block the serialized monitor mailbox.
    """
    if deadline is None:
        deadline = _PANEL_JOB_DEADLINE
    slots = _PANEL_JOB_SLOTS
    if not slots.acquire(blocking=False):
        return False, "Diagnostics busy: a job is already running; try again after it finishes."
    box = {}

    def worker():
        try:
            _capture_begin()
            with deadline_scope(deadline):
                box["result"] = fn()
        except Exception as exc:  # surfaced to the panel as text
            box["error"] = repr(exc)
        finally:
            try:
                box["out"] = _capture_end()
            finally:
                slots.release()

    try:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
    except BaseException:
        slots.release()
        raise
    thread.join(deadline)
    if thread.is_alive():
        return False, ("the job did not finish within %d seconds; it is still "
                       "running on the machine, try again shortly" % deadline)
    if "error" in box:
        return False, box["error"]
    result = box.get("result")
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
        return result
    return True, box.get("out") or "(no result)"


def api_diag(op, arg=""):
    return _run_captured_job(lambda: _api_diag_inline(op, arg))


def _api_diag_inline(op, arg=""):
    """Read-only diagnostics for the WebConsole panel, reusing the bot reports."""
    op = str(op or "").strip().lower()
    arg = str(arg or "").strip()
    if op == "diagnose":
        hours = int(arg) * 24 if arg.isdigit() and 1 <= int(arg) <= 30 else 24
        return True, _panel_text(diagnose_report(hours))
    if op == "logstats":
        days = int(arg) if arg.isdigit() and 1 <= int(arg) <= 30 else 7
        return True, _panel_text(logstats_report(days))
    if op == "logs":
        hours, level = 24, "error"
        parts = arg.split()
        if parts and parts[0].isdigit() and 1 <= int(parts[0]) <= 30:
            hours = int(parts[0]) * 24
        if len(parts) >= 2 and parts[1].lower() in LOG_LEVELS:
            level = parts[1].lower()
        total, lines = fetch_system_logs(hours, LOG_LEVELS[level])
        if total is None:
            return False, "could not read the event log (try an administrator account)"
        head = "System log: %s, level %s, %d matching events" % (arg or "24 hours", level, total)
        return True, head + "\n" + ("\n".join(lines[:40]) if lines else "(no events at this level)")
    if op == "firewall":
        report = get_firewall_report()
        return report["status"] == "external_verification_required", format_rdp_policy(report)
    if op == "netstat":
        return True, _panel_text(format_netstat())
    if op == "when":
        metric, threshold = "cpu", 80
        for a in arg.split():
            if a.lower() in ("cpu", "ram"):
                metric = a.lower()
            elif a.isdigit():
                threshold = int(a)
        return True, _panel_text(when_report(metric, threshold))
    if op == "ps":
        if not arg:
            return False, "provide a process name, for example: chrome"
        return True, _panel_text(ps_detail(arg))
    jobs = {
        "bigfiles": bigfiles_job,
        "temp": temp_job,
        "startup": startup_job,
        "updates": updates_job,
        "sysinfo": _sysinfo_job,
        "harden": lambda: harden_report(False),
        "speedtest": lambda: speedtest_job(silent=True),
    }
    if op in jobs:
        _capture_begin()
        try:
            value = jobs[op]()
        except Exception as e:
            _capture_end()
            return False, repr(e)
        return True, _capture_end() or (_panel_text(value) if value is not None else "(no output)")
    if op == "report":
        midnight = datetime.now().replace(hour=0, minute=0, second=0,
                                          microsecond=0).timestamp()
        s = stats_since(midnight)
        if not s:
            return True, "Daily report: not enough data collected yet."
        lines = ["Daily report — %s" % datetime.now().strftime("%Y-%m-%d"),
                 "  CPU: average %.0f%% / peak %.0f%%" % (s["cpu_avg"], s["cpu_max"]),
                 "  RAM: average %.0f%% / peak %.0f%%" % (s["ram_avg"], s["ram_max"]),
                 "  Samples: %d" % s["points"]]
        rec = _traffic.get(datetime.now().strftime("%Y-%m-%d"))
        if rec:
            lines.append("  Data today: DL %.2f GB | UL %.2f GB"
                         % (rec["down"] / 1024.0, rec["up"] / 1024.0))
        return True, "\n".join(lines)
    if op == "logins":
        n = int(arg) if arg.isdigit() and 1 <= int(arg) <= 30 else 10
        _capture_begin()
        try:
            _logins_job(n)
        except Exception as e:
            _capture_end()
            return False, repr(e)
        return True, _capture_end() or "(no logins recorded)"
    if op == "botlog":
        if not os.path.isfile(LOG_FILE):
            return True, "No log file yet."
        with open(LOG_FILE, "rb") as f:
            if os.path.getsize(LOG_FILE) > 40 * 1024:
                f.seek(-40 * 1024, 2)
            data = f.read()
        return True, data.decode("utf-8", "replace")
    if op == "configbackup":
        return True, json.dumps(_redact_config(config), indent=2, ensure_ascii=False)
    if op == "dumps":
        dumps = _crash_dumps()
        if not dumps:
            return True, "No recent crash dump files (that is a good thing)."
        out = ["Recent crash dumps:"]
        for path, size, mtime in dumps[:10]:
            out.append("  %s  %s  %s" % (
                datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                format_size(size), path))
        return True, "\n".join(out)
    if op == "nettest":
        parts = arg.split()
        if not parts:
            return False, "provide a host, for example: 1.1.1.1"
        _capture_begin()
        try:
            nettest_job(parts[0])
        except Exception as e:
            _capture_end()
            return False, repr(e)
        return True, _capture_end() or "(no result)"
    return False, "unknown diagnostic %r" % op


def _dispatch_panel(action, args):
    if action == "block_ip":
        return block_ip(args.get("ip", ""))
    if action == "unblock_ip":
        ok = unblock_ip(args.get("ip", ""))
        return ok, "rule removal verified" if ok else "rule removal could not be verified; tracking retained"
    if action == "users_list":
        return api_users_list()
    if action == "diag":
        return api_diag(args.get("op", ""), args.get("arg", ""))
    if action == "user_action":
        return api_user_action(args.get("op", ""), args.get("name", ""), args.get("value", ""))
    if action == "rdp_status":
        return True, api_rdp_status()
    if action == "rdp_allow_add":
        return api_rdp_allow_add(args.get("ip", ""))
    if action == "rdp_allow_remove":
        return api_rdp_allow_remove(args.get("ip", ""))
    if action == "rdp_allow_apply":
        return api_rdp_allow_apply()
    if action == "rdp_allow_clear":
        return api_rdp_allow_clear()
    if action == "lockdown":
        return api_lockdown(args.get("mode", "status"))
    if action == "panic":
        return api_panic(args.get("mode", "status"))
    if action == "settings_get":
        return True, {"groups": settings_snapshot()}
    if action == "settings_set":
        key = str(args.get("key", ""))
        value = str(args.get("value", ""))
        if (key.lower() in SET_ENABLE_CONFIRM and value.lower() == "on"
                and not config.get(SET_ENABLE_CONFIRM[key.lower()])
                and not args.get("confirm")):
            return False, "confirmation required for " + key
        return apply_setting(key, value)
    if action == "block_subnet":
        if not args.get("confirm"):
            return False, "confirmation required"
        return block_subnet(str(args.get("ip", "")))
    if action == "set_rdp_port":
        if not args.get("confirm"):
            return False, "confirmation required"
        try:
            port = int(args.get("port"))
        except (TypeError, ValueError):
            return False, "invalid port"
        current = int(config.get("rdp_port", 3389))
        if not (1024 <= port <= 65535):
            return False, "port must be between 1024 and 65535"
        if port == current:
            return False, "that is already the current port"
        res = change_rdp_port(port)
        if res.get("busy"):
            return False, "port %d is busy; nothing changed" % port
        if not res.get("reg"):
            return False, "registry change failed; nothing changed"
        if not res.get("listen"):
            return False, "new port did not listen; rolled back to %d" % current
        return True, "RDP now listens on %d - reconnect to IP:%d" % (port, port)
    if action == "mute":
        if args.get("off"):
            config["muted_until"] = 0
            save_config()
            return True, "alerts unmuted"
        try:
            minutes = int(args.get("minutes"))
        except (TypeError, ValueError):
            return False, "invalid duration"
        secs = max(60, min(minutes * 60, 7 * 24 * 3600))
        config["muted_until"] = time.time() + secs
        save_config()
        return True, "alerts muted for " + format_duration(secs)
    if action == "trap":
        op = str(args.get("op", "list"))
        traps = [str(t) for t in (config.get("trap_users") or [])]
        if op == "list":
            return True, traps
        name = str(args.get("name", "")).strip()
        if not name or len(name) > 40:
            return False, "invalid name"
        if op == "add":
            if name.lower() not in [t.lower() for t in traps]:
                traps.append(name)
                config["trap_users"] = traps
                save_config()
            return True, "trap added: " + name
        if op == "del":
            traps = [t for t in traps if t.lower() != name.lower()]
            config["trap_users"] = traps
            save_config()
            return True, "trap removed: " + name
        return False, "unknown trap operation"
    if action == "cancel_restart":
        try:
            subprocess.run(["shutdown", "/a"], check=True,
                           capture_output=True, timeout=15, creationflags=NO_WINDOW)
            return True, "scheduled restart cancelled"
        except Exception as e:
            return False, "nothing to cancel (%s)" % e
    if action == "automation":
        which = str(args.get("list", ""))
        if which not in ("watch", "keepalive", "svcwatch"):
            return False, "unknown list"
        items = [dict(x) for x in (config.get(which) or [])]
        op = str(args.get("op", "list"))
        if op == "list":
            return True, items
        name = str(args.get("name", "")).strip()
        if not name or len(name) > 60:
            return False, "invalid name"
        if op == "add":
            if which == "watch":
                try:
                    mb = max(64, min(1048576, int(args.get("ram_mb"))))
                except (TypeError, ValueError):
                    mb = 3072
                items = [x for x in items
                         if str(x.get("name", "")).lower() != name.lower()]
                items.append({"name": name, "ram_mb": mb})
            elif which == "keepalive":
                run = str(args.get("run", "")).strip()
                if run and not config.get("exec_enabled"):
                    return False, "a custom run command needs /set exec on"
                items = [x for x in items
                         if str(x.get("name", "")).lower() != name.lower()]
                entry = {"name": name}
                if run:
                    entry["run"] = run
                items.append(entry)
            else:
                if not any(str(x.get("name", "")).lower() == name.lower()
                           for x in items):
                    items.append({"name": name})
            config[which] = items
            save_config()
            return True, "added " + name
        if op == "del":
            items = [x for x in items
                     if str(x.get("name", "")).lower() != name.lower()]
            config[which] = items
            save_config()
            return True, "removed " + name
        return False, "unknown operation"
    if action == "test_alert":
        send_message("[OK] Test message from the WebConsole panel - the alert channel works.")
        return True, "test message sent to the configured chat"
    if action == "update_now":
        if not args.get("confirm"):
            return False, "confirmation required"
        url = str(config.get("update_url") or "")
        hsh = str(config.get("update_hash") or "")
        if not url.startswith("https://") or not re.fullmatch(r"[0-9a-fA-F]{64}", hsh):
            return False, "self-update is not configured (set update_url and update_hash)"
        threading.Thread(target=update_self, daemon=True).start()
        return True, "update started; the monitor restarts when it finishes"
    if action == "exportlogs":
        scope = str(args.get("scope", "all")).lower()
        if scope not in ("all", "system", "application"):
            scope = "all"
        threading.Thread(target=export_logs_job, args=(scope,), daemon=True).start()
        return True, "export started; the ZIP will arrive in Telegram"
    if action == "send_file":
        path = os.path.expanduser(os.path.expandvars(str(args.get("path", ""))))
        if not path or not os.path.isfile(path):
            return False, "file not found"
        try:
            if os.path.getsize(path) > 45 * 1024 * 1024:
                return False, "file is larger than the 45 MB Telegram limit"
        except OSError:
            return False, "file not readable"
        send_document(path, "File requested from the WebConsole panel")
        return True, "file queued to Telegram"
    return False, "unknown action"


def monitor_control_loop():
    """Execute panel requests (RDP security) in the monitor process."""
    os.makedirs(MONITOR_CONTROL_DIR, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    reads = ThreadPoolExecutor(max_workers=4, thread_name_prefix="panel-read")
    writes = ThreadPoolExecutor(max_workers=1, thread_name_prefix="panel-write")
    pending = set()
    while True:
        try:
            pending = {job for job in pending if not job.done()}
            # Per-request files let unrelated reads proceed while a slow query runs.
            for name in sorted(os.listdir(MONITOR_CONTROL_DIR)):
                if len(pending) >= 24:
                    break
                if not re.fullmatch(r"request-[a-f0-9]{32}\.json", name):
                    continue
                path = os.path.join(MONITOR_CONTROL_DIR, name)
                claimed = path + ".processing"
                try:
                    os.replace(path, claimed)
                except OSError:
                    continue
                with open(claimed, encoding="utf-8") as stream:
                    req = json.load(stream)
                pool = reads if _panel_read_request(req) else writes
                pending.add(pool.submit(_process_panel_request, req, claimed))
            if not os.path.isfile(MONITOR_REQUEST):
                time.sleep(0.05)
                continue
            claimed = MONITOR_REQUEST + ".processing"
            try:
                os.replace(MONITOR_REQUEST, claimed)
            except OSError:
                time.sleep(1)
                continue
            rid = ""
            try:
                with open(claimed, "r", encoding="utf-8") as f:
                    req = json.load(f)
                rid = str(req.get("id", ""))
                ok, out = _dispatch_panel(str(req.get("action", "")), req.get("args") or {})
            finally:
                try:
                    os.remove(claimed)
                except OSError:
                    pass
            if isinstance(out, (dict, list)):
                out_val = out
            else:
                out_val = str(out)
                if len(out_val) > 200000:
                    out_val = out_val[:200000] + "\n… (truncated)"
            _atomic_write_json(MONITOR_RESULT, {"id": rid, "ok": bool(ok),
                                                "out": out_val,
                                                "t": time.time()})
        except Exception as e:
            try:
                _atomic_write_json(MONITOR_RESULT, {"id": "", "ok": False,
                                                    "out": repr(e), "t": time.time()})
            except Exception:
                pass
        time.sleep(0.05)


def _panel_read_request(req):
    action, args = req.get("action"), req.get("args") or {}
    return (action in {"users_list", "settings_get", "rdp_status"}
            or action in {"trap", "automation"} and args.get("op") == "list")


def _process_panel_request(req, claimed):
    rid = str(req.get("id", ""))
    try:
        if not re.fullmatch(r"[a-f0-9]{32}", rid):
            return
        if time.time() >= float(req.get("expires", 0)):
            return  # Never execute an action after its caller timed out.
        try:
            ok, out = _dispatch_panel(str(req.get("action", "")), req.get("args") or {})
        except Exception as exc:
            ok, out = False, redact_log(repr(exc))
        if time.time() < float(req["expires"]):
            _atomic_write_json(os.path.join(MONITOR_CONTROL_DIR, "result-" + rid + ".json"),
                               {"id": rid, "ok": bool(ok), "out": out})
    finally:
        try:
            os.remove(claimed)
        except OSError:
            pass


def restore_list_text():
    try:
        restore_mod = _suite_backup_module("restore")
        items = restore_mod.list_backups()
    except Exception:
        items = []
    if not items:
        return "No local backup archives found."
    lines = ["<b>Restore — local archives</b>",
             "Use: <code>/restore &lt;name&gt;</code>"]
    for b in items[:15]:
        when = datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• {esc(b['name'])}\n  {format_size(b['size'])} — {when}")
    return "\n".join(lines)


def tg_send_tracked(text):
    """Send a message and return its id so it can be edited later."""
    targets = _alert_targets()
    if not targets:
        return None
    chat = targets[0]
    res = tg_api("sendMessage", chat_id=chat, text=_tag() + _fix_rtl(text),
                 parse_mode="HTML")
    if not res.get("ok"):
        res = tg_api("sendMessage", chat_id=chat, text=_strip_tags(text))
    return res.get("result", {}).get("message_id") if res.get("ok") else None


def tg_edit_tracked(msg_id, text):
    targets = _alert_targets()
    if not targets or not msg_id:
        return
    tg_api("editMessageText", chat_id=targets[0], message_id=msg_id,
           text=_tag() + _fix_rtl(text), parse_mode="HTML")


def _progress_bar(pct):
    filled = max(0, min(20, int(20 * pct / 100)))
    return "█" * filled + "░" * (20 - filled)


def backup_progress_text():
    p = _read_json(BACKUP_PROGRESS, {})
    state = p.get("state", "unknown")
    pct = int(p.get("percent", 0) or 0)
    msg = _strip_tags(str(p.get("message", "")))[:120]
    low = msg.lower()
    if state == "done":
        head = "<b>Backup finished</b>"
    elif state == "error":
        head = "<b>Backup failed</b>"
    elif "upload" in low:
        head = "<b>Cloud upload</b>"
    else:
        head = "<b>Backup in progress</b>"
    bar = _progress_bar(pct)
    return f"{head}\n<pre>{bar}  {pct:>3}%\n{msg}</pre>"


def backup_result_text():
    """Structured result block for the last backup, or None if unavailable."""
    r = _read_json(BACKUP_RESULT, {})
    if not r:
        return None
    ok = r.get("status") == "ok"
    kind = r.get("kind", "")
    kind_label = "manual" if kind == "manual" else ("scheduled" if kind else "")
    suffix = f" ({kind_label})" if kind_label else ""
    head = ("<b>Backup complete</b>" if ok else "<b>Backup finished with warnings</b>") + suffix
    lines = [
        f"{r.get('archive', '')}",
        f"{r.get('size_mb', 0)} MB • {r.get('files', 0)} files",
        f"Encryption: {'AES' if r.get('encrypted') else 'none'}",
        f"VSS: {r.get('vss', 'off')}",
        f"Verified: {'yes' if r.get('verified') else 'no'}",
    ]
    if r.get("errors"):
        lines.append(f"Unreadable files: {r['errors']}")
    if r.get("missing"):
        lines.append(f"Missing sources: {r['missing']}")
    # Delivery is done by THIS unified bot, not the retired backup bot, so the
    # status is derived from this bot's settings and the archive size.
    send_enabled = bool(config.get("send_backup_file", True))
    max_mb = float(config.get("backup_file_max_mb", 45) or 45)
    size_mb = float(r.get("size_mb", 0) or 0)
    if not send_enabled:
        tg = "disabled"
    elif size_mb > max_mb:
        tg = f"skipped (over {max_mb:.0f} MB bot limit)"
    else:
        tg = "sending via this bot"
    lines.append(f"Telegram: {tg}")
    if not r.get("cloud_enabled"):
        lines.append("Cloud: not enabled")
    else:
        lines.append(f"Cloud: {r.get('cloud_ok', 0)} ok / {r.get('cloud_fail', 0)} failed")
    lines.append(f"{r.get('time', '')}")
    for remote, link in (r.get("links") or {}).items():
        lines.append(f"Link: {remote} {link}")
    tail = r.get("log_tail") or []
    if tail:
        lines.append("")
        lines.append("Log:")
        lines.extend(str(x)[:120] for x in tail)
    return head + "\n<pre>" + esc("\n".join(lines)) + "</pre>"


def backup_live_loop():
    """Edit a single chat message with live backup progress."""
    live_id = None
    was_running = False
    while True:
        try:
            p = _read_json(BACKUP_PROGRESS, {})
            state = p.get("state")
            if state == "running":
                text = backup_progress_text()
                if live_id is None:
                    live_id = tg_send_tracked(text)
                else:
                    tg_edit_tracked(live_id, text)
                was_running = True
            elif was_running and state in ("done", "error", "idle"):
                tg_edit_tracked(live_id, backup_progress_text())
                live_id = None
                was_running = False
        except Exception:
            pass
        time.sleep(4)


def _backup_cfg():
    """Load (config_manager, cfg) for the backup component."""
    cm = _suite_backup_module("config_manager")
    return cm, cm.load_config()


def backsources_list_text():
    try:
        _cm, cfg = _backup_cfg()
    except Exception as e:
        return "Backup configuration unavailable: " + esc(str(e))
    sources = [str(s) for s in (cfg.get("backup", {}).get("sources") or [])]
    if not sources:
        return ("<b>Backup sources</b>\nNo sources configured.\n"
                "Add one with /backsrc add &lt;path&gt; or /backsrc browse.")
    lines = ["<b>Backup sources</b>"]
    for i, s in enumerate(sources, 1):
        mark = "" if os.path.exists(s) else ""
        lines.append(f"{i}. {mark} <code>{esc(s)}</code>")
    lines.append("\nAdd: /backsrc add &lt;path&gt;\nRemove: /backsrc remove &lt;index|path&gt;\n"
                 "Browse: /backsrc browse")
    return "\n".join(lines)


def backsources_add(path):
    try:
        cm, cfg = _backup_cfg()
    except Exception as e:
        return "Backup configuration unavailable: " + esc(str(e))
    path = os.path.abspath(os.path.expandvars(str(path).strip().strip('"')))
    if not os.path.exists(path):
        return f"Path does not exist: <code>{esc(path)}</code>"
    sources = [str(s) for s in (cfg.get("backup", {}).get("sources") or [])]
    if path in sources:
        return f"Already configured: <code>{esc(path)}</code>"
    sources.append(path)
    cfg.setdefault("backup", {})["sources"] = sources
    cm.save_config(cfg)
    audit_record("Backup source added: " + path)
    return f"Added backup source:\n<code>{esc(path)}</code>\nTotal: {len(sources)}"


def backsources_remove(token):
    try:
        cm, cfg = _backup_cfg()
    except Exception as e:
        return "Backup configuration unavailable: " + esc(str(e))
    sources = [str(s) for s in (cfg.get("backup", {}).get("sources") or [])]
    if not sources:
        return "No sources configured."
    removed = None
    token = str(token).strip()
    if token.isdigit():
        idx = int(token)
        if 1 <= idx <= len(sources):
            removed = sources.pop(idx - 1)
    else:
        p = os.path.abspath(os.path.expandvars(token.strip('"')))
        if p in sources:
            sources.remove(p)
            removed = p
    if not removed:
        return "Not found. Use /backsrc list to see the indexes."
    cfg.setdefault("backup", {})["sources"] = sources
    cm.save_config(cfg)
    audit_record("Backup source removed: " + removed)
    return f"Removed:\n<code>{esc(removed)}</code>\nRemaining: {len(sources)}"


def _backsrc_sources():
    try:
        _cm, cfg = _backup_cfg()
        return [str(s) for s in (cfg.get("backup", {}).get("sources") or [])]
    except Exception:
        return []


def _bs_button(args):
    return "bs:" + pend_store({"fn": _backsrc_nav, "args": args})


def _backsrc_nav(path, action="nav", page=0):
    if action == "add":
        send_message(backsources_add(path))
    elif action == "remove":
        send_message(backsources_remove(path))
    else:
        backsources_browse(path, page)


def _list_drives():
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = letter + ":\\"
        if os.path.exists(root):
            drives.append(root)
    return drives


def _breadcrumb(path):
    """Return up to 4 (label, target) crumbs from the root to the current folder."""
    cur = os.path.abspath(path)
    parts = []
    while True:
        parent = os.path.dirname(cur.rstrip("\\/"))
        if not parent or parent == cur:
            parts.append((cur, cur))
            break
        parts.append((os.path.basename(cur) or cur, cur))
        cur = parent
        if len(parts) >= 8:
            break
    parts.reverse()
    out = []
    for label, target in parts[-4:]:
        if len(label) > 14:
            label = label[:12] + ".."
        out.append((label, target))
    return out


def backsources_browse(path=None, page=0):
    """Desktop-style folder/file browser with breadcrumbs, paging and add/remove."""
    if not path:
        path = os.path.expanduser("~")
    path = os.path.abspath(os.path.expandvars(str(path).strip('"')))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        path = os.path.expanduser("~")
    try:
        entries = sorted(os.listdir(path))
    except OSError as e:
        send_message(f"Cannot list <code>{esc(path)}</code>: {esc(str(e))}")
        return
    dirs = [e for e in entries
            if os.path.isdir(os.path.join(path, e)) and not e.startswith(("$", "."))]
    files = [e for e in entries
             if os.path.isfile(os.path.join(path, e)) and not e.startswith(("$", "."))]
    items = [("DIR", d) for d in dirs] + [("FILE", f) for f in files]
    per_page = 20
    pages = max(1, (len(items) + per_page - 1) // per_page)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = max(0, min(page, pages - 1))
    chunk = items[page * per_page:(page + 1) * per_page]
    configured = set(_backsrc_sources())

    parent = os.path.dirname(path.rstrip("\\/")) or path
    rows = [
        [("Up", _bs_button((parent, "nav", 0))),
         ("Home", "run:/backsrc browse"),
         ("Drives", "run:/backsrc drives")],
    ]
    crumbs = _breadcrumb(path)
    if crumbs:
        rows.append([(label, _bs_button((target, "nav", 0))) for label, target in crumbs])

    for i in range(0, len(chunk), 2):
        row = []
        for kind, name in chunk[i:i + 2]:
            full = os.path.join(path, name)
            if kind == "DIR":
                action = "nav"
            else:
                action = "remove" if full in configured else "add"
            mark = "* " if full in configured else ""
            label = ("DIR  " if kind == "DIR" else "FILE ") + mark + name[:22]
            row.append((label, _bs_button((full, action, 0))))
        rows.append(row)

    if pages > 1:
        rows.append([("Prev", _bs_button((path, "nav", page - 1))),
                     (f"page {page + 1}/{pages}", _bs_button((path, "nav", page))),
                     ("Next", _bs_button((path, "nav", page + 1)))])

    if path in configured:
        rows.append([("Remove this folder", _bs_button((path, "remove", 0)))])
    else:
        rows.append([("Add this folder", _bs_button((path, "add", 0)))])

    text = ("<b>Browse</b>\n"
            f"<pre>{esc(path)}\n"
            f"folders {len(dirs)}  files {len(files)}  page {page + 1}/{pages}</pre>\n"
            "Tap a folder to open, a file to add/remove. * = already added.")
    send_buttons(text, rows)


def backsources_drives():
    drives = _list_drives()
    if not drives:
        send_message("No drives detected.")
        return
    rows = [[(d, _bs_button((d, "nav", 0)))] for d in drives]
    send_buttons("<b>Drives</b>", rows)


def backup_schedule_text():
    try:
        _cm, cfg = _backup_cfg()
    except Exception as e:
        return "Backup configuration unavailable: " + esc(str(e))
    s = cfg.get("schedule", {})
    mode = s.get("mode", "daily")
    lines = ["Backup schedule",
             f"Enabled: {'yes' if s.get('enabled', True) else 'no'}",
             f"Mode: {mode}"]
    if mode == "interval":
        lines.append(f"Every {s.get('interval_hours', 6)} hours")
    elif mode == "times":
        lines.append("Times: " + (", ".join(s.get("times") or []) or "(none)"))
    else:
        lines.append(f"Daily at {s.get('time', '03:00')}")
    lines.append(f"Retries: {s.get('retry_count', 3)} every {s.get('retry_delay_minutes', 10)} min")
    lines.append("")
    lines.append("Set: /backupschedule daily HH:MM | interval HOURS | times HH:MM,HH:MM | on | off")
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def backup_schedule_set(args):
    try:
        cm, cfg = _backup_cfg()
    except Exception as e:
        return "Backup configuration unavailable: " + esc(str(e))
    s = cfg.setdefault("schedule", {})
    sub = (args[0] if args else "").lower()
    if sub in ("on", "off"):
        s["enabled"] = (sub == "on")
    elif sub == "daily" and len(args) >= 2 and re.fullmatch(r"\d{1,2}:\d{2}", args[1]):
        hh, mm = map(int, args[1].split(":"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return "Invalid time"
        s["mode"] = "daily"
        s["time"] = f"{hh:02d}:{mm:02d}"
    elif sub == "interval" and len(args) >= 2 and args[1].isdigit():
        s["mode"] = "interval"
        s["interval_hours"] = max(1, min(168, int(args[1])))
    elif sub == "times" and len(args) >= 2:
        times = []
        for t in args[1].split(","):
            t = t.strip()
            if not re.fullmatch(r"\d{1,2}:\d{2}", t):
                return "Invalid time: " + esc(t)
            hh, mm = map(int, t.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                return "Invalid time: " + esc(t)
            times.append(f"{hh:02d}:{mm:02d}")
        s["mode"] = "times"
        s["times"] = times
    else:
        return ("Usage:\n/backupschedule\n/backupschedule on|off\n"
                "/backupschedule daily HH:MM\n/backupschedule interval HOURS\n"
                "/backupschedule times HH:MM,HH:MM")
    cm.save_config(cfg)
    audit_record("Backup schedule updated")
    return backup_schedule_text()


def _cloud_state():
    cm, cfg = _backup_cfg()
    cur = [str(r) for r in (cfg.get("cloud", {}).get("remotes") or [])]
    try:
        cloud = _suite_backup_module("cloud_uploader")
        cloud.configure(cfg)
        remotes = cloud.list_remotes()
    except Exception:
        remotes = []
    return cm, cfg, cur, remotes


def _cloud_btn(args):
    return "cl:" + pend_store({"fn": _cloud_nav, "args": args})


def _cloud_nav(remote, action):
    cm, cfg, cur, _remotes = _cloud_state()
    r = remote if remote.endswith(":") else (remote + ":" if remote else "")
    if action == "add" and r and r not in cur:
        cur.append(r)
    elif action == "remove" and r in cur:
        cur.remove(r)
    elif action == "clear":
        pid = pend_store({"fn": _cloud_clear_confirm, "args": (list(cur),)})
        send_buttons("[WARN] Remove all backup cloud destinations? New backups will have no cloud copy.",
                     [[("Confirm clear", "cf:" + pid),
                       ("Cancel", "cx:" + pid)]])
        return
    cfg.setdefault("cloud", {})["remotes"] = cur
    cm.save_config(cfg)
    audit_record("Cloud destinations updated: " + (", ".join(cur) or "(none)"))
    cloud_menu()


def _cloud_clear_confirm(expected):
    cm, cfg, cur, _remotes = _cloud_state()
    if cur != expected:
        send_message("[X] Cloud destinations changed. Review /cloud again.")
        return
    cfg.setdefault("cloud", {})["remotes"] = []
    cm.save_config(cfg)
    audit_record("Cloud destinations cleared")
    cloud_menu()


def cloud_menu():
    cm, cfg, cur, remotes = _cloud_state()
    lines = ["Cloud destinations", "Enabled: " + (", ".join(cur) if cur else "(none)")]
    if not remotes:
        lines.append("No rclone remotes found. Create one with: rclone config")
    else:
        lines.append("Existing remotes: " + ", ".join(remotes))
    lines.append("")
    lines.append("Tap a remote to enable/disable it. * = enabled.")
    rows = []
    for r in remotes[:12]:
        mark = "* " if r in cur else ""
        action = "remove" if r in cur else "add"
        rows.append([(mark + r, _cloud_btn((r, action)))])
    if cur:
        rows.append([("Clear all", _cloud_btn(("", "clear")))])
    rows.append([("Test connection", "run:/cloud test")])
    send_buttons("<pre>" + esc("\n".join(lines)) + "</pre>", rows)


def cloud_test():
    cm, cfg, cur, _remotes = _cloud_state()
    if not cur:
        send_message("No cloud destinations enabled. Use /cloud to pick one.")
        return
    cu = _suite_backup_module("cloud_uploader")
    lines = ["Cloud test"]
    for r in cur:
        target = r if r.endswith(":") else r + ":"
        ok, out = cu._run(["lsd", target], timeout=60)
        lines.append(f"{target} : {'OK' if ok else 'FAILED'}")
        if not ok:
            lines.append("   " + (out or "")[:150])
    send_message("<pre>" + esc("\n".join(lines)) + "</pre>")


def _sched_btn(args):
    return "sc:" + pend_store({"fn": _sched_nav, "args": args})


def _sched_nav(mode, value):
    if mode == "off":
        send_buttons("Disable automatic backups? Manual backups remain available.",
                     confirm_buttons("/backupschedule off"))
        return
    send_message(backup_schedule_set([mode, value] if value else [mode]))
    schedule_menu()


def schedule_menu():
    rows = [
        [("Daily 03:00", _sched_btn(("daily", "03:00"))),
         ("Daily 12:00", _sched_btn(("daily", "12:00")))],
        [("Every 6h", _sched_btn(("interval", "6"))),
         ("Every 4h", _sched_btn(("interval", "4"))),
         ("Every 1h", _sched_btn(("interval", "1")))],
        [("Times 03:00,15:00", _sched_btn(("times", "03:00,15:00")))],
        [("Enable", _sched_btn(("on", ""))), ("Disable", _sched_btn(("off", "")))],
        [("Custom daily HH:MM", "run:/backupschedule custom")],
    ]
    send_buttons(backup_schedule_text(), rows)


class _ProgressFile:
    """File wrapper that reports upload percentage while requests reads it."""

    def __init__(self, f, total, cb):
        self._f = f
        self._total = total
        self._cb = cb
        self._sent = 0
        self._last = -1

    def __len__(self):
        return self._total

    def read(self, size=-1):
        data = self._f.read(size)
        self._sent += len(data)
        if self._total:
            pct = int(self._sent * 100 / self._total)
            if pct != self._last:
                self._last = pct
                try:
                    self._cb(pct)
                except Exception:
                    pass
        return data

    def seek(self, *a):
        return self._f.seek(*a)

    def tell(self):
        return self._f.tell()


def _send_document_progress(chat, path, caption, progress_cb):
    if not os.path.isfile(path):
        return None
    total = os.path.getsize(path)
    try:
        with open(path, "rb") as f:
            obj = _ProgressFile(f, total, progress_cb)
            r = requests.post(
                f"https://api.telegram.org/bot{config['telegram_token']}/sendDocument",
                data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                files={"document": (os.path.basename(path), obj)}, timeout=1800)
        try:
            return bool(r.ok and r.json().get("ok"))
        except Exception:
            return False
    except Exception as e:
        print(f"[telegram] document send error: {e}")
        return False


_backup_sent_archive = None


def send_backup_archive(archive_path):
    """Send a finished backup archive through the unified bot (small files only)."""
    global _backup_sent_archive
    if not config.get("send_backup_file", True):
        return
    if not archive_path or not os.path.isfile(archive_path):
        return
    if archive_path == _backup_sent_archive:
        return
    size_mb = os.path.getsize(archive_path) / 1048576
    max_mb = float(config.get("backup_file_max_mb", 45) or 45)
    targets = _alert_targets()
    if not targets:
        return
    if size_mb > max_mb:
        send_message(f"The archive is {size_mb:.1f} MB (over the {max_mb:.0f} MB bot limit). "
                     "Download it from the panel or use the cloud link.")
        _backup_sent_archive = archive_path
        return
    chat = targets[0]

    def send_text(pct):
        return ("<b>Sending backup archive</b>\n"
                f"<pre>{_progress_bar(pct)}  {pct:>3}%\n{size_mb:.1f} MB</pre>")

    live = tg_send_tracked(send_text(0))

    def cb(pct):
        tg_edit_tracked(live, send_text(pct))

    ok = _send_document_progress(chat, archive_path, _tag() + "Backup archive", cb)
    if ok:
        tg_edit_tracked(live, f"<b>Archive sent</b>\n<pre>{os.path.basename(archive_path)}\n"
                              f"{size_mb:.1f} MB</pre>")
    else:
        tg_edit_tracked(live, "<b>Could not send the archive</b>\n"
                              "Download it from the panel.")
    _backup_sent_archive = archive_path


def backup_relay_loop():
    """Relay backup completions through the unified bot (the backup bot is retired)."""
    path, offset = None, None
    while True:
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            new_path = os.path.join(BACKUP_DIR, "logs", f"backup_{day}.log")
            if new_path != path:
                path, offset = new_path, None
            if os.path.exists(path):
                size = os.path.getsize(path)
                if offset is None:
                    offset = size
                elif size < offset:
                    offset = 0
                if size > offset:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        chunk = f.read()
                    offset = size
                    low = chunk.lower()
                    if "job finished" in low or "backup finished" in low:
                        text = backup_result_text()
                        if text:
                            send_message(text)
                        else:
                            last = _read_json(BACKUP_LAST_RUN, {})
                            send_message("<b>Backup finished</b>\n"
                                         + esc(str(last.get("summary", ""))[:250]))
                        try:
                            lb = os.path.join(BACKUP_DIR, "local_backups")
                            zips = sorted((os.path.join(lb, x) for x in os.listdir(lb)
                                           if x.startswith("Backup_") and x.endswith(".zip")),
                                          key=os.path.getmtime, reverse=True)
                            if zips:
                                send_backup_archive(zips[0])
                        except OSError:
                            pass
                    elif "backup failed" in low or "failed to create the archive" in low:
                        send_message("<b>Backup failed</b> — send /backupstatus for details")
                    elif "restore drill passed" in low:
                        send_message("<b>Restore drill passed</b> — the latest backup "
                                     "restored and verified.")
                    elif "restore drill failed" in low:
                        send_message("<b>Restore drill FAILED</b> — the latest backup "
                                     "could not be restored/verified.")
        except Exception:
            pass
        time.sleep(5)


# ----------------------------- List of buttons (/menu) -----------------------------

MENU_PAGES = build_menus()

# command -> (what it does in detail, usage, needs confirm?)
COMMAND_INFO = {
    "/view": ("Full live report: CPU %, RAM % and GB used, network speed "
              "up/down right now, disk usage with free space, active login "
              "sessions count, and machine uptime. Reads information only - "
              "changes nothing.", "/view", False),
    "/top": ("Lists the 10 processes consuming the most CPU and the 10 using "
             "the most RAM right now, with PID, memory and CPU per process. "
             "Use it to find what is loading the machine.", "/top", False),
    "/chart": ("Generates a graph image of CPU and RAM over the last 24 hours "
               "(one sample per minute) and sends it as a photo.",
               "/chart", False),
    "/report": ("Today's report: average and peak CPU/RAM since midnight with "
                "the chart, plus today's transferred data. The same report is "
                "sent automatically every day at the configured hour.",
                "/report", False),
    "/temp": ("Reads CPU temperature via WMI and GPU via nvidia-smi. Many "
              "VPS machines expose no sensors - in that case it says so.",
              "/temp", False),
    "/net": ("Current download/upload speed, plus total data transferred "
             "since the machine booted.", "/net", False),
    "/traffic": ("Bandwidth accounting: today, the current billing cycle, "
                 "quota bar, all-time total, and a daily table. Counted "
                 "machine-wide (all users), persisted in traffic.json.",
                 "/traffic", False),
    "/speedtest": ("Measures real internet speed via Cloudflare (~20 seconds): "
                   "ping, download and upload Mbps.", "/speedtest", False),
    "/rdp": ("Lists active RDP sessions (user, session, state, ID) and every "
             "remote IP currently connected to the RDP port via netstat.",
             "/rdp", False),
    "/logins": ("Last successful RDP logins from the Security event log: time, "
                "username, source IP. Use it after any suspicion - it shows "
                "who actually got in.", "/logins", False),
    "/listusers": ("Lists all local Windows accounts and marks which ones are "
                   "administrators.", "/listusers", False),
    "/bigfiles": ("Scans the system drive and lists the 20 largest files with "
                  "their full paths. Use it when the disk is full. The scan "
                  "can take a few minutes.", "/bigfiles", False),
    "/netstat": ("All active TCP connections (local -> remote with owning "
                 "process) and all listening ports, marked local-only vs "
                 "open-to-network. Reveals backdoors and unexpected listeners.",
                 "/netstat", False),
    "/firewall": ("Diagnoses effective RDP firewall policy, client-logon allow rules, "
                  "broad inbound blocks, policy sources, listener and NLA. External access remains unverified.",
                  "/firewall", False),
    "/sysinfo": ("System card: Windows version, CPU model, RAM size and "
                 "pressure, pagefile usage, uptime, and whether a reboot is "
                 "pending (from Windows Update).", "/sysinfo", False),
    "/startup": ("Inventory of autostart entries: registry Run keys and "
                 "non-Microsoft scheduled tasks. Anything unfamiliar here is "
                 "a classic malware persistence spot.", "/startup", False),
    "/updates": ("Queries Windows Update: number of pending updates with "
                 "titles, and whether a reboot is pending.",
                 "/updates", False),
    "/audit": ("Last commands executed via the bot, files sent, and rejected "
               "unauthorized access attempts.", "/audit", False),
    "/blocklist": ("Every IP the tool blocked in Windows Firewall and when.",
                   "/blocklist", False),
    "/block": ("Blocks an IP immediately in Windows Firewall (all protocols, "
               "permanent until /unblock). Double-check it is not your own IP.",
               "/block <ip> confirm", True),
    "/blocksubnet": ("Blocks the whole /24 network of an IP (256 addresses) - "
                     "for rotating proxies attacking from the same range.",
                     "/blocksubnet <ip> confirm", True),
    "/whitelist": ("The RDP allow list: manual IPs plus IPs learned "
                   "automatically from successful logins (last 14 days). "
                   "Used by lockdown.", "/whitelist", False),
    "/botlog": ("Sends the tail of the tool's own log file (rdp_monitor.log) "
                "- use it when the tool itself misbehaves.", "/botlog", False),
    "/clean": ("Deletes files older than 24h from TEMP folders and empties "
               "the Recycle Bin, then reports how much space was freed. "
               "Locked files are skipped safely.", "/clean", False),
    "/exec": ("Runs an arbitrary CMD command on the machine with admin rights "
              "and returns full output. THE most dangerous command - anyone "
              "with your Telegram controls the whole machine. Keep it off "
              "(/set exec off) when not needed.",
              "/exec <command> confirm", True),
    "/kill": ("Force-kills every process matching the name (all instances). "
              "Unsaved work in those programs is lost.",
              "/kill chrome confirm", True),
    "/run": ("Launches a program on the machine (like typing it in Run box).",
             "/run notepad confirm", True),
    "/download": ("Sends a file from the machine to this chat (up to 45MB, "
                  "Telegram's limit).", "/download C:\\path\\file", False),
    "/logoff": ("Forces a user's RDP session to end immediately. Programs "
                "running in that session close without saving.",
                "/logoff <name> confirm", True),
    "/adduser": ("Creates a local Windows account: /adduser name password for "
                 "a normal user with RDP access, or add 'admin' to make it an "
                 "administrator. The password stays visible in chat history - "
                 "change it later if the chat is shared.",
                 "/adduser <name> <password> [admin] confirm", True),
    "/disableuser": ("Disables an account (cannot log in) without deleting "
                     "anything - reversible with /enableuser.",
                     "/disableuser <name> confirm", True),
    "/enableuser": ("Re-enables a disabled account.", "/enableuser <name> confirm", True),
    "/deluser": ("Deletes a local account permanently. Refuses to remove the "
                 "last administrator.", "/deluser <name> confirm", True),
    "/setrdpport": ("Wizard to change the RDP port: edits the registry, opens "
                    "the new port in the firewall, blocks the old one, "
                    "restarts the RDP service. Your current RDP connection "
                    "DROPS the moment it applies - reconnect to IP:newport.",
                    "/setrdpport <port> confirm", True),
    "/rdpallow": ("Restricts RDP to specific IPs only: allow rule for the "
                  "list + block rule for everyone else. Danger of locking "
                  "yourself out - make sure your IP is in the list first.",
                  "/rdpallow add|del|apply|clear", True),
    "/lockdown": ("Emergency lock: instantly restricts RDP to the whitelist "
                  "and blocks any new IP on first attempt. Auto-expires.",
                  "/lockdown on|off|now|release", True),
    "/panic": ("Closes the RDP port ENTIRELY at firewall level and blocks all "
               "previous attackers. Stays closed across reboots until you "
               "send /panic off. You will not be able to connect either!",
               "/panic on|off", True),
    "/harden": ("Audits RDP hardening: NLA enabled, account lockout policy, "
                "Administrator account renamed. '/harden fix' auto-fixes the "
                "first two (needs confirm).", "/harden [fix] confirm", False),
    "/restart": ("Restarts the machine after a 30-second warning window "
                 "(cancelable with /cancel_restart).",
                 "/restart confirm", True),
    "/shutdown": ("Powers the machine OFF after 30 seconds (cancel with "
                  "/cancel_restart).", "/shutdown confirm", True),
    "/mute": ("Silences non-critical alerts (usage, disk, temp, sessions) for "
              "a period. Security and critical alerts always arrive.",
              "/mute 3h | /mute off", False),
    "/image": ("System image attempt: captures selected volumes into one or more "
               "VHDX files while Windows runs. Verify the complete file set and "
               "test a restore in a VM before relying on it. Needs free "
               "space equal to the used space; if no second disk is present the "
               "image is written to the system disk. Optionally uploads via rclone.",
               "/image start|list|upload|status|progress|stop", False),
    "/set": ("Detailed settings guide with current values and examples.",
             "/set", False),
    "/status": ("Current value of every setting in one message.",
                "/status", False),
    "/panel": ("WebConsole panel: shows the local URL and a button to reveal "
               "the login token on demand.", "/panel", False),
    "/panelstatus": ("Checks whether the WebConsole is reachable and whether a "
                     "login token is stored.", "/panelstatus", False),
    "/paneltoken": ("Reveals the current WebConsole login token in chat.",
                    "/paneltoken", False),
    "/panelremote": ("Turns remote access to the WebConsole panel on or off. "
                     "On enables HTTPS on 0.0.0.0 with a self-signed certificate "
                     "and a firewall/IP allow-list (loopback + Tailscale + this "
                     "host). open allows any IP; allow/deny edit the list.",
                     "/panelremote direct|on|off|status|allow <ip>|deny <ip>", False),
    "/backup": ("Queues a manual backup on the isolated SYSTEM worker. It "
                "reports here when it finishes.", "/backup", False),
    "/backupstatus": ("Backup worker state, last successful run, schedule, and "
                      "recent archives.", "/backupstatus", False),
    "/backuplist": ("Lists the local backup archives with size and time.",
                    "/backuplist", False),
    "/backsrc": ("Manage what gets backed up: list sources, add or remove a "
                 "file/folder, or browse with a desktop-style file browser "
                 "(drives, breadcrumbs, folders and files, paging).",
                 "/backsrc list | add <path> | remove <index|path> | browse [path] | drives",
                 False),
    "/backupprogress": ("Shows the live progress of a running backup "
                        "(percentage, phase, name).", "/backupprogress", False),
    "/restorelist": ("Lists the local archives available to restore.",
                     "/restorelist", False),
    "/restore": ("Restores one archive into an isolated folder under the suite "
                 "and verifies the restored files. It never overwrites the "
                 "original paths.", "/restore <archive-name>", True),
    "/drill": ("Restores the newest archive into an isolated folder and verifies "
               "it, then removes the copy. A restore test, not just a CRC check.",
               "/drill", True),
    "/start": ("Opens the main button menu.", "/start", False),
    "/menu": ("Shows the interactive button menu.", "/menu", False),
    "/noop": ("Cancels a pending action (used by the Cancel buttons).", "/noop", False),
    "/diagnose": ("Analyzes recent System/Application error events and explains likely causes.",
                  "/diagnose [days]", False),
    "/logstats": ("Groups system log events by source for the last N days.",
                  "/logstats [days]", False),
    "/exportlogs": ("Exports the last 7 days of System/Application error events to a ZIP and sends it.",
                    "/exportlogs [all|system|application]", False),
    "/dumps": ("Sends the newest Windows crash dump (minidump) file.", "/dumps", False),
    "/screenshot": ("Captures the interactive desktop and sends it.", "/screenshot", False),
    "/msg": ("Shows a message on the logged-in desktop.", "/msg <text>", False),
    "/ps": ("Shows details for processes matching a name.", "/ps <name>", False),
    "/when": ("Reports when CPU or RAM last exceeded a threshold, from saved history.",
              "/when [cpu|ram] [percent]", False),
    "/nettest": ("Tests connectivity and latency to a host.", "/nettest <host>", False),
    "/test": ("Sends a test message to confirm the bot can reach you.", "/test", False),
    "/token": ("Reveals the WebConsole login token.", "/token", False),
    "/configbackup": ("Sends a copy of the configuration with secrets hidden.",
                      "/configbackup", False),
    "/cancel_restart": ("Cancels a scheduled restart/shutdown inside the cancel window.",
                        "/cancel_restart", False),
    "/update": ("Self-updates from the configured HTTPS URL and SHA-256 fingerprint.",
                "/update", True),
    "/unblock": ("Removes a firewall block for an IP.", "/unblock <ip>", True),
    "/allow": ("Manage trusted Telegram user IDs allowed to control the device.",
               "/allow list | add <id> | del <id>", False),
    "/trap": ("Trap usernames: ban an IP immediately on any login attempt using those names.",
              "/trap list | add <name> | del <name>", False),
    "/svc": ("Restarts a Windows service (with confirmation).", "/svc restart <name>", True),
    "/watch": ("Alerts when a program exceeds a RAM limit.",
               "/watch list | add <name> <MB> | del <name>", False),
    "/renameuser": ("Renames a local Windows account.", "/renameuser <old> <new>", True),
    "/getlog": ("Shows the bot's recent log; alias of /botlog.", "/getlog", False),
    "/keepalive": ("Lists or manages programs restarted automatically when they stop.",
                   "/keepalive list|add|del", False),
    "/svcwatch": ("Lists or manages Windows services restarted automatically when they stop.",
                  "/svcwatch list|add|del", False),
    "/help": ("This reference.", "/help", False),
    "/docs": ("Documentation database: what runs behind each command, its effect, "
              "and troubleshooting. /docs shows the index; /docs <command> shows one card.",
              "/docs [command]", False),
    "/backupschedule": ("View or change the automatic backup schedule: daily at a time, "
                        "every N hours, or several specific times.",
                        "/backupschedule [daily HH:MM | interval HOURS | times HH:MM,HH:MM | on | off]",
                        False),
    "/cloud": ("Choose the cloud destinations from your existing rclone remotes "
               "(enable/disable with buttons) and test the connection.",
               "/cloud | /cloud test", False),
    "/rclone": ("Set up cloud upload entirely from chat: install rclone, create "
                "remotes (S3/B2/Wasabi/SFTP/WebDAV directly; Google Drive, OneDrive, "
                "Dropbox with a pasted token), list/test them, and choose where "
                "/image uploads. Stored in one config the SYSTEM worker also uses.",
                "/rclone [install|gdrive|auth|client|add|token|list|test|set|del]", False),
}

# Pairing rule: every command must be explained in COMMAND_INFO and classified
# here as a WebConsole panel action or "bot-only". A new command must be added
# to BOTH (help + this map), and to the WebConsole when a panel action is named.
PANEL_COVERAGE = {
    "/view": "live", "/top": "apps", "/chart": "charts", "/net": "live",
    "/rdp": "sec", "/netstat": "tools", "/sysinfo": "tools", "/screenshot": "tools",
    "/exec": "tools", "/kill": "live", "/run": "tools", "/download": "file",
    "/logoff": "live", "/restart": "ctl", "/shutdown": "ctl", "/clean": "ctl",
    "/msg": "ctl", "/audit": "sec", "/blocklist": "sec", "/block": "sec",
    "/unblock": "sec", "/traffic": "sec", "/svc": "tools",
    "/panel": "panel", "/panelstatus": "panel", "/paneltoken": "panel",
    "/panelremote": "panel", "/token": "panel",
    "/backup": "backup", "/backupstatus": "backup", "/backuplist": "backup",
    "/backsrc": "backup", "/backupprogress": "backup",
    "/restorelist": "backup", "/restore": "backup", "/drill": "backup",
    "/backupschedule": "backup", "/cloud": "backup", "/rclone": "panel",
    "/ps": "diagnostics", "/when": "diagnostics",
    "/report": "diagnostics", "/temp": "diagnostics", "/speedtest": "diagnostics",
    "/logins": "diagnostics", "/bigfiles": "diagnostics",
    "/startup": "diagnostics", "/updates": "diagnostics", "/image": "bot-only",
    "/listusers": "users", "/adduser": "users",
    "/disableuser": "users", "/enableuser": "users", "/deluser": "users",
    "/renameuser": "users", "/mute": "ctl", "/set": "settings",
    "/status": "settings", "/blocksubnet": "rdpsec", "/whitelist": "bot-only",
    "/rdpallow": "rdpsec", "/lockdown": "rdpsec", "/panic": "rdpsec",
    "/harden": "diagnostics", "/setrdpport": "rdpsec", "/firewall": "diagnostics",
    "/botlog": "diagnostics", "/diagnose": "diagnostics",
    "/logstats": "diagnostics", "/exportlogs": "diagnostics", "/dumps": "diagnostics",
    "/watch": "automation", "/keepalive": "automation", "/svcwatch": "automation",
    "/trap": "sec", "/allow": "bot-only", "/update": "ctl",
    "/configbackup": "diagnostics", "/cancel_restart": "ctl",
    "/nettest": "diagnostics", "/test": "ctl", "/noop": "bot-only",
    "/start": "bot-only", "/menu": "bot-only", "/help": "bot-only",
    "/docs": "docs",
}

# Documentation database: for key commands, what runs behind them, the effect,
# and troubleshooting. Commands without an entry fall back to COMMAND_INFO text.
COMMAND_BACKEND = {
    "/setrdpport": (
        "Registry PortNumber (HKLM\\...\\WinStations\\RDP-Tcp) + New-NetFirewallRule for the "
        "new port + Restart-Service TermService, then a listener check.",
        "RDP listens on the new port; the old port is blocked only after the new one verifies.",
        "If no listener appears it rolls back automatically. Check admin rights, port conflicts, "
        "and update the provider firewall/port-forwarding."),
    "/rdpallow": (
        "Windows Firewall allow rules (RDPMonitor RDP Allow List TCP/UDP) plus profile inbound "
        "policy, disabling broad allow rules.",
        "RDP is restricted to the listed IPs only.",
        "On failure it restores the previous rules. Verify with /firewall and from a provider console."),
    "/lockdown": (
        "apply_rdp_allow(lockdown_ips()) with a timed window; auto-releases when the timer expires.",
        "RDP is limited to trusted IPs for the lockdown duration; new attempts are banned.",
        "Make sure your current IP is trusted first; end early with /lockdown release."),
    "/panic": (
        "New-NetFirewallRule block on the RDP port (RDPMonitor PANIC).",
        "RDP is closed for everyone.",
        "You must reach the machine another way; /panic off reopens it."),
    "/block": (
        "netsh advfirewall firewall add rule (RDPMonitor Block <ip>) remoteip=<ip>.",
        "All inbound traffic from that IP is blocked.",
        "Verify with /blocklist; remove with /unblock."),
    "/blocksubnet": (
        "netsh advfirewall firewall add rule blocking the /24 network of the IP.",
        "Every address in that /24 is blocked.",
        "Confirm the network is not yours; remove with /unblock on the /24 entry."),
    "/unblock": (
        "netsh advfirewall firewall delete rule + Get-NetFirewallRule verification.",
        "The block rule is removed and the IP is dropped from blocked.json.",
        "If the rule remains, the IP stays tracked; retry or check permissions."),
    "/harden": (
        "Checks NLA, account lockout policy, and administrator posture; optional fix applies the changes.",
        "Hardens RDP authentication and account policy.",
        "Re-run to verify; review each finding before applying fixes."),
    "/firewall": (
        "netsh advfirewall show allprofiles + Get-NetFirewallRule summaries.",
        "Reports firewall profile state and RDP-related rules (read-only).",
        "No changes are made."),
    "/backup": (
        "Writes a control request; the SYSTEM worker runs create_backup + cloud upload + delivery.",
        "A ZIP archive is created, verified, uploaded to the cloud, and a link is reported.",
        "Check /backupstatus and the worker log; add sources with /backsrc."),
    "/backsrc": (
        "Edits backup/config.json sources; the worker reloads it before the next run.",
        "Adds or removes files/folders from the backup set.",
        "Missing sources abort the backup (fail closed)."),
    "/restore": (
        "Extracts the archive into a new folder and verifies each file by size and CRC.",
        "Files are restored to an isolated folder (never over the originals).",
        "A missing/invalid manifest aborts; a non-empty destination is refused."),
    "/drill": (
        "Restores the newest archive into a temp folder, verifies it, then removes it.",
        "Proves the latest backup is restorable.",
        "If it fails, inspect the archive and its manifest."),
    "/exec": (
        "subprocess shell command on the machine (only when exec is enabled).",
        "Runs a real command as the tool's account.",
        "Enable with /set exec on; add confirm; output is returned."),
    "/run": (
        "subprocess.Popen of the given executable (only when exec is enabled).",
        "Starts the program in the interactive session.",
        "Provide a full path; detached from the tool."),
    "/kill": (
        "psutil Process.kill() for the given PIDs.",
        "Terminates the processes.",
        "Protected PIDs (0, 4, the tool itself) are refused."),
    "/screenshot": (
        "PIL ImageGrab of the interactive desktop.",
        "A PNG of the current screen is sent.",
        "Fails if the session is locked or Pillow is missing."),
    "/clean": (
        "Deletes TEMP files older than 24h and empties the recycle bin.",
        "Frees disk space.",
        "Locked files are skipped."),
    "/logoff": (
        "logoff <session-id>.",
        "Ends that Windows/RDP session.",
        "Confirm the session id from /rdp first."),
    "/restart": (
        "shutdown /r with a short delay and a cancel window.",
        "Reboots the machine.",
        "Cancel with /cancel_restart inside the window."),
    "/shutdown": (
        "shutdown /s with a short delay and a cancel window.",
        "Powers off the machine.",
        "Cancel with /cancel_restart inside the window."),
    "/msg": (
        "msg * <text> to the interactive session.",
        "Shows a popup message on the desktop.",
        "Needs an active interactive session."),
    "/svc": (
        "Restart-Service -Force for the given service.",
        "The service restarts (dependents briefly stop).",
        "Use the exact service name; needs admin rights."),
}


# Detailed per-command documents: ordered steps with the EXACT backend commands.
# Used by /docs <command> and by docs/COMMANDS.md. Commands without an entry fall
# back to COMMAND_BACKEND (one line) and then COMMAND_INFO.
COMMAND_DOCS = {
    "/setrdpport": {
        "summary": "Changes the RDP listening port, opens it, verifies it, and closes the old port.",
        "steps": [
            ("Check the new port is free",
             "psutil.net_connections() scan for a LISTEN socket on the new port"),
            ("Set the registry port",
             "Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name PortNumber -Value <port> -Type DWord -ErrorAction Stop"),
            ("Open the new port in the firewall",
             "New-NetFirewallRule -DisplayName 'RDPMonitor RDP <port>' -Direction Inbound -LocalPort <port> -Protocol TCP -Action Allow -ErrorAction Stop"),
            ("Restart the RDP service",
             "Restart-Service TermService -Force -ErrorAction Stop"),
            ("Verify the listener belongs to TermService",
             "Get-CimInstance Win32_Service -Filter \"Name='TermService'\" (ProcessId) + psutil listener check on the new port"),
            ("Close the old port (only after verification)",
             "Disable-NetFirewallRule -DisplayGroup 'Remote Desktop'; netsh advfirewall firewall delete rule name=\"RDPMonitor Old RDP Port Block\"; netsh advfirewall firewall add rule name=\"RDPMonitor Old RDP Port Block\" dir=in action=block protocol=TCP localport=<old>"),
            ("Rollback on failure",
             "Set-ItemProperty PortNumber=<old>; Restart-Service TermService; netsh advfirewall firewall delete rule name=\"RDPMonitor RDP <new>\""),
        ],
        "effect": "RDP listens on the new port; the old port is blocked only after the new one verifies.",
        "output": "\"New port: <port> (verified listening)\" or a rollback notice.",
        "troubleshoot": "No listener -> it rolls back; check admin rights, port conflicts, and update provider firewall/port-forwarding. Keep a console session open.",
        "related": ["/rdp", "/rdpallow", "/firewall"],
    },
    "/rdpallow": {
        "summary": "Restricts RDP to a list of allowed IPs (default-deny for everyone else).",
        "steps": [
            ("Create staging allow rules (TCP + UDP)",
             "netsh advfirewall firewall add rule name=\"RDPMonitor RDP Allow Staging TCP|UDP\" dir=in action=allow protocol=TCP|UDP localport=<port> remoteip=<ip1,ip2,...>"),
            ("Rename staging rules to the final names",
             "Set-NetFirewallRule -DisplayName 'RDPMonitor RDP Allow Staging TCP' -NewDisplayName 'RDPMonitor RDP Allow List TCP' (and UDP)"),
            ("Scan for broad allow rules that bypass the list",
             "Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow ... (reads address/service filters)"),
            ("Disable those broad rules",
             "Disable-NetFirewallRule -Name <rule-id> (saved so they can be re-enabled)"),
            ("Set the profile default inbound action to Block",
             "Set-NetFirewallProfile -Profile '<profile>' -DefaultInboundAction Block"),
            ("Remove the old general RDP rule",
             "netsh advfirewall firewall delete rule name=\"RDPMonitor RDP <port>\""),
            ("Rollback on failure",
             "Enable-NetFirewallRule for saved rules; Set-NetFirewallProfile -DefaultInboundAction Allow; delete the allow rules"),
        ],
        "effect": "RDP is reachable only from the listed IPs.",
        "output": "\"RDP is now restricted to the allow-list\".",
        "troubleshoot": "If it fails it restores the previous rules. Verify with /firewall and from a provider console; never apply without your current IP in the list.",
        "related": ["/whitelist", "/lockdown", "/firewall"],
    },
    "/lockdown": {
        "summary": "Temporary strict lockdown: RDP limited to trusted IPs for a set time.",
        "steps": [
            ("Learn recent successful IPs",
             "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624;StartTime=$st}"),
            ("Apply the trusted allow-list",
             "apply_rdp_allow(lockdown_ips()) -> same netsh/Set-NetFirewallProfile steps as /rdpallow"),
            ("Set the expiry",
             "config.lockdown_until = now + minutes (auto-released by the monitor loop)"),
        ],
        "effect": "RDP is limited to trusted IPs; new attempts are banned on the first try.",
        "output": "\"The lock worked\" with the trusted IP count.",
        "troubleshoot": "Ensure your current IP is trusted first. End early with /lockdown release.",
        "related": ["/rdpallow", "/panic", "/whitelist"],
    },
    "/panic": {
        "summary": "Emergency: closes RDP completely for everyone.",
        "steps": [
            ("Block every IP that failed to log in",
             "block_ip(ip) for each -> netsh advfirewall firewall add rule name=\"RDPMonitor Block <ip>\" dir=in action=block remoteip=<ip>"),
            ("Create a block rule on the RDP port",
             "New-NetFirewallRule -DisplayName 'RDPMonitor PANIC' -Direction Inbound -Protocol TCP -LocalPort <port> -Action Block -ErrorAction Stop"),
            ("Verify the rule exists",
             "(Get-NetFirewallRule -DisplayName 'RDPMonitor PANIC').Count"),
        ],
        "effect": "RDP is closed for all sources.",
        "output": "\"Panic mode is activated!\" or an explicit failure notice.",
        "troubleshoot": "You must reach the machine another way. /panic off deletes the rule and re-verifies.",
        "related": ["/rdpallow", "/lockdown", "/firewall"],
    },
    "/harden": {
        "summary": "Checks and optionally fixes RDP authentication and account policy.",
        "steps": [
            ("Check Network Level Authentication",
             "Get-ItemProperty 'HKLM:\\System\\...\\WinStations\\RDP-Tcp' -Name UserAuthentication"),
            ("Check account lockout policy",
             "net accounts"),
            ("Check administrator accounts",
             "Get-LocalGroupMember -Group Administrators"),
            ("Apply fixes (only with 'fix')",
             "Set-ItemProperty UserAuthentication=1; net accounts /lockoutthreshold:<n>"),
        ],
        "effect": "Hardens RDP authentication and account lockout.",
        "output": "A findings list; 'fix' applies the changes.",
        "troubleshoot": "Review each finding before applying; re-run to verify.",
        "related": ["/rdp", "/rdpallow", "/firewall"],
    },
    "/firewall": {
        "summary": "Read-only RDP connectivity diagnosis using effective ActiveStore policy.",
        "steps": [
            ("Effective policy",
             "Get-NetFirewallProfile -PolicyStore ActiveStore; Get-NetFirewallRule -PolicyStore ActiveStore -TracePolicyStore -Direction Inbound"),
            ("RDP endpoints",
             "Read RDP registry port, TermService and TCP listeners; inspect rule port/address/application/service filters"),
        ],
        "effect": "No changes; a report only.",
        "output": "Local issues, potential RDP TCP allows, broad/conditional blocks, policy origin and external-verification requirement.",
        "troubleshoot": "Shadow is not a client-logon allow. Unknown/GroupPolicy/sandbox blocks are never disabled automatically. Verify the actual address/port from an authorized independent host.",
        "related": ["/rdpallow", "/harden"],
    },
    "/block": {
        "summary": "Permanently blocks one IP in Windows Firewall.",
        "steps": [
            ("Add the block rule",
             "netsh advfirewall firewall add rule name=\"RDPMonitor Block <ip>\" dir=in action=block remoteip=<ip>"),
            ("Record it",
             "blocked.json[<ip>] = now"),
        ],
        "effect": "All inbound traffic from that IP is rejected.",
        "output": "\"Banned <ip> in the firewall\".",
        "troubleshoot": "Confirm it is not your own IP. Remove with /unblock.",
        "related": ["/blocksubnet", "/unblock", "/blocklist"],
    },
    "/blocksubnet": {
        "summary": "Blocks the whole /24 network of an IP.",
        "steps": [
            ("Add the subnet block rule",
             "netsh advfirewall firewall add rule name=\"RDPMonitor Block <net>.0/24\" dir=in action=block remoteip=<net>.0/24"),
        ],
        "effect": "Every address in that /24 is rejected.",
        "output": "\"Banned <net>.0/24 (network)\".",
        "troubleshoot": "Confirm the network is not yours; remove with /unblock on the /24 entry.",
        "related": ["/block", "/unblock"],
    },
    "/unblock": {
        "summary": "Removes a firewall block for an IP and verifies it is gone.",
        "steps": [
            ("Delete the rule",
             "netsh advfirewall firewall delete rule name=\"RDPMonitor Block <ip>\""),
            ("Verify",
             "(Get-NetFirewallRule -DisplayName 'RDPMonitor Block <ip>').Count"),
            ("Update state",
             "blocked.json.pop(<ip>) only if the rule is gone"),
        ],
        "effect": "The IP can reach the machine again.",
        "output": "\"The ban has been lifted\" or a failure notice.",
        "troubleshoot": "If the rule remains, the IP stays tracked; retry or check permissions.",
        "related": ["/block", "/blocklist"],
    },
    "/backup": {
        "summary": "Runs a backup now: archive, verify, upload to cloud, and report a link.",
        "steps": [
            ("Queue the request",
             "write backup/control/request.json"),
            ("SYSTEM worker picks it up",
             "create_backup(): collect files, zip (AES if password), verify CRC, write manifest"),
            ("Upload to the cloud",
             "rclone copy <archive> <remote>:VPS-Backups --stats-one-line"),
            ("Create a share link",
             "rclone link <remote>:VPS-Backups/<archive>"),
            ("Deliver",
             "Telegram message + link; local retention keeps 3 copies"),
        ],
        "effect": "A verified archive exists locally, is uploaded, and a link is sent.",
        "output": "A structured result (archive, size, encryption, cloud, link).",
        "troubleshoot": "Check /backupstatus and the worker log; add sources with /backsrc.",
        "related": ["/backupstatus", "/backsrc", "/restore"],
    },
    "/restore": {
        "summary": "Restores one archive into a new isolated folder and verifies it.",
        "steps": [
            ("Refuse an unsafe destination",
             "destination must be new/empty with no reparse points"),
            ("Extract",
             "zip extract into the isolated folder (zip-slip protected)"),
            ("Verify",
             "each manifest entry: exists, size matches, CRC matches the manifest"),
        ],
        "effect": "Files are restored to an isolated folder; originals are untouched.",
        "output": "\"restored N files, verified M manifest entries\".",
        "troubleshoot": "A missing/invalid manifest aborts; a non-empty destination is refused.",
        "related": ["/restorelist", "/drill", "/backuplist"],
    },
    "/drill": {
        "summary": "Restore drill: restores the newest archive, verifies it, then removes the copy.",
        "steps": [
            ("Pick the newest archive",
             "backup/local_backups newest Backup_*.zip"),
            ("Restore + verify",
             "same steps as /restore"),
            ("Clean up",
             "remove the temporary restore folder unless keep=true"),
        ],
        "effect": "Proves the latest backup can actually be restored.",
        "output": "\"Restore drill passed\" or a failure with the reason.",
        "troubleshoot": "If it fails, inspect the archive and manifest.",
        "related": ["/restore", "/restorelist", "/backupstatus"],
    },
    "/exec": {
        "summary": "Runs a shell command on the machine (only when exec is enabled).",
        "steps": [
            ("Gate",
             "config.exec_enabled must be true (/set exec on)"),
            ("Confirm",
             "the command must include 'confirm'"),
            ("Run",
             "subprocess.run(cmd, shell=True, capture_output=True)"),
        ],
        "effect": "A real command runs as the tool's account.",
        "output": "The command output (tail).",
        "troubleshoot": "Disabled by default; enable with /set exec on. Avoid interactive commands.",
        "related": ["/run", "/kill", "/set"],
    },
    "/run": {
        "summary": "Starts an executable in the interactive session.",
        "steps": [
            ("Gate", "config.exec_enabled must be true"),
            ("Start", "subprocess.Popen([path] + args, shell=False)"),
        ],
        "effect": "The program starts detached.",
        "output": "\"started\" or an error.",
        "troubleshoot": "Provide a full path; check it is not blocked.",
        "related": ["/exec", "/kill"],
    },
    "/kill": {
        "summary": "Terminates processes by PID.",
        "steps": [
            ("Guard", "refuse PIDs 0, 4, and the tool itself"),
            ("Kill", "psutil.Process(pid).kill()"),
        ],
        "effect": "The processes end.",
        "output": "The count killed and any errors.",
        "troubleshoot": "Confirm the PID from /top or /view first.",
        "related": ["/top", "/ps"],
    },
    "/screenshot": {
        "summary": "Captures the interactive desktop.",
        "steps": [("Capture", "PIL ImageGrab.grab(all_screens=True)"), ("Send", "sendPhoto")],
        "effect": "A PNG of the current screen is sent.",
        "output": "The image, or a failure notice.",
        "troubleshoot": "Fails if the session is locked or Pillow is missing.",
        "related": ["/view"],
    },
    "/msg": {
        "summary": "Shows a popup message on the desktop.",
        "steps": [("Send", "msg * <text>")],
        "effect": "A message box appears for signed-in users.",
        "output": "Delivered (no text output).",
        "troubleshoot": "Needs an active interactive session.",
        "related": ["/screenshot"],
    },
    "/logoff": {
        "summary": "Logs off a Windows/RDP session.",
        "steps": [("Log off", "logoff <session-id>")],
        "effect": "That session ends.",
        "output": "\"done\" or an error.",
        "troubleshoot": "Confirm the session id from /rdp first.",
        "related": ["/rdp", "/listusers"],
    },
    "/restart": {
        "summary": "Reboots the machine with a cancel window.",
        "steps": [("Schedule", "shutdown /r /t 5")],
        "effect": "The machine reboots.",
        "output": "A confirmation.",
        "troubleshoot": "Cancel with /cancel_restart inside the window.",
        "related": ["/shutdown", "/cancel_restart"],
    },
    "/shutdown": {
        "summary": "Powers off the machine with a cancel window.",
        "steps": [("Schedule", "shutdown /s /t 5")],
        "effect": "The machine powers off.",
        "output": "A confirmation.",
        "troubleshoot": "Cancel with /cancel_restart inside the window.",
        "related": ["/restart", "/cancel_restart"],
    },
    "/cancel_restart": {
        "summary": "Cancels a pending restart/shutdown.",
        "steps": [("Abort", "shutdown /a")],
        "effect": "The pending shutdown is cancelled.",
        "output": "A confirmation.",
        "troubleshoot": "Only works inside the cancel window.",
        "related": ["/restart", "/shutdown"],
    },
    "/clean": {
        "summary": "Cleans old TEMP files and the recycle bin.",
        "steps": [
            ("Delete old TEMP files",
             "os.unlink() for files older than 24h in %TEMP% and C:\\Windows\\Temp"),
            ("Empty the recycle bin",
             "Clear-RecycleBin -Force"),
        ],
        "effect": "Frees disk space.",
        "output": "Files removed and space freed.",
        "troubleshoot": "Locked files are skipped.",
        "related": ["/bigfiles", "/view"],
    },
    "/svc": {
        "summary": "Restarts a Windows service.",
        "steps": [("Restart", "Restart-Service -Name <name> -Force -ErrorAction Stop")],
        "effect": "The service restarts (dependents briefly stop).",
        "output": "\"The service has been restarted\" or an error.",
        "troubleshoot": "Use the exact service name; needs admin rights.",
        "related": ["/startup"],
    },
    "/listusers": {
        "summary": "Lists local Windows accounts.",
        "steps": [("Enumerate", "Get-LocalUser")],
        "effect": "Read-only.",
        "output": "A user table.",
        "troubleshoot": "Run from an administrator account.",
        "related": ["/adduser", "/logins"],
    },
    "/adduser": {
        "summary": "Creates a local account and adds it to a group.",
        "steps": [
            ("Create", "New-LocalUser -Name <n> -Password (Read-Host -AsSecureString)"),
            ("Add to group", "Add-LocalGroupMember -Group <g> -Member <n>"),
        ],
        "effect": "A new local account exists.",
        "output": "\"created\" or an error.",
        "troubleshoot": "Requires user management enabled (/set users on).",
        "related": ["/deluser", "/listusers"],
    },
    "/deluser": {
        "summary": "Deletes a local account.",
        "steps": [("Delete", "Remove-LocalUser -Name <n>")],
        "effect": "The account is removed.",
        "output": "\"deleted\" or an error.",
        "troubleshoot": "The profile folder remains on disk.",
        "related": ["/adduser", "/listusers"],
    },
    "/disableuser": {
        "summary": "Disables a local account.",
        "steps": [("Disable", "Disable-LocalUser -Name <n>")],
        "effect": "The account cannot sign in.",
        "output": "\"disabled\" or an error.",
        "troubleshoot": "Re-enable with /enableuser.",
        "related": ["/enableuser", "/listusers"],
    },
    "/enableuser": {
        "summary": "Enables a local account.",
        "steps": [("Enable", "Enable-LocalUser -Name <n>")],
        "effect": "The account can sign in again.",
        "output": "\"enabled\" or an error.",
        "troubleshoot": "Pair with /disableuser.",
        "related": ["/disableuser", "/listusers"],
    },
    "/renameuser": {
        "summary": "Renames a local account.",
        "steps": [("Rename", "Rename-LocalUser -Name <old> -NewName <new> -ErrorAction Stop")],
        "effect": "The account name changes; profile folder keeps the old name.",
        "output": "\"Renamed: <old> -> <new>\".",
        "troubleshoot": "Fails if the new name is taken.",
        "related": ["/listusers"],
    },
    "/diagnose": {
        "summary": "Analyzes recent System/Application error events and explains causes.",
        "steps": [("Query", "Get-WinEvent -FilterHashtable @{LogName='System'|'Application'; Level=@(1,2); StartTime=$st}")],
        "effect": "Read-only analysis.",
        "output": "A grouped diagnosis.",
        "troubleshoot": "Run from an administrator account.",
        "related": ["/logstats", "/dumps"],
    },
    "/logstats": {
        "summary": "Groups system log events by source for N days.",
        "steps": [("Query", "Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$st} | Group-Object ProviderName")],
        "effect": "Read-only.",
        "output": "Counts per source.",
        "troubleshoot": "Use a longer window for rare errors.",
        "related": ["/diagnose"],
    },
    "/exportlogs": {
        "summary": "Exports the last 7 days of error events to a ZIP and sends it.",
        "steps": [
            ("Export each log",
             "wevtutil epl <log> <out>.evtx /q:\"*[System[(Level=1 or Level=2) and TimeCreated[timediff(@SystemTime) <= <ms>]]]\" /ow:true"),
            ("Compress",
             "Compress-Archive -Path <files> -DestinationPath <zip>"),
        ],
        "effect": "A ZIP of .evtx files is produced and sent.",
        "output": "The archive (<= 45 MB).",
        "troubleshoot": "Try /exportlogs system if the combined size is too large.",
        "related": ["/dumps", "/botlog"],
    },
    "/dumps": {
        "summary": "Sends the newest Windows crash dump.",
        "steps": [("Find", "C:\\Windows\\Minidump newest .dmp"), ("Send", "sendDocument")],
        "effect": "The dump file is sent.",
        "output": "The file, or \"no recent dumps\".",
        "troubleshoot": "Files over 45 MB are not sent; the path is reported instead.",
        "related": ["/diagnose"],
    },
    "/watch": {
        "summary": "Alerts when a program exceeds a RAM limit.",
        "steps": [("Sample", "psutil process memory per matching name each cycle")],
        "effect": "A warning when the limit is exceeded (cooldown 10 min).",
        "output": "The program and its current RAM.",
        "troubleshoot": "Use /watch add <name> <MB>.",
        "related": ["/top"],
    },
    "/rdp": {
        "summary": "Shows active RDP sessions and remote IPs.",
        "steps": [
            ("Sessions", "qwinsta"),
            ("Recent logins", "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624;StartTime=$st}"),
        ],
        "effect": "Read-only.",
        "output": "Sessions and caller IPs.",
        "troubleshoot": "Combine with /blocklist for banned callers.",
        "related": ["/logins", "/blocklist"],
    },
    "/token": {
        "summary": "Reveals the WebConsole login token.",
        "steps": [("Read", "webconsole_state.json token_enc -> DPAPI unprotect")],
        "effect": "The panel login token is sent.",
        "output": "The token (keep it private).",
        "troubleshoot": "Rotate with the panel rotate-token command if leaked.",
        "related": ["/panel", "/paneltoken"],
    },
    "/configbackup": {
        "summary": "Sends a copy of the configuration with secrets hidden.",
        "steps": [("Redact", "remove credential fields by key name (any type)"), ("Send", "sendDocument")],
        "effect": "A redacted config copy is sent.",
        "output": "The JSON file.",
        "troubleshoot": "Secrets are never included.",
        "related": ["/status"],
    },
    # ---- Monitoring (read-only) ----
    "/view": {
        "summary": "Live snapshot of CPU, RAM, network, disks, sessions, and uptime.",
        "steps": [("Sample", "psutil.cpu_percent(), virtual_memory(), net_io_counters(), disk_usage(), boot_time()")],
        "effect": "Read-only.",
        "output": "A formatted report.",
        "troubleshoot": "Values are point-in-time samples.",
        "related": ["/top", "/chart"],
    },
    "/top": {
        "summary": "Top processes by CPU and by RAM.",
        "steps": [("Enumerate", "psutil.process_iter() with cpu_percent and memory_info")],
        "effect": "Read-only.",
        "output": "A ranked process list with PIDs.",
        "troubleshoot": "First sample of a new process may read 0%.",
        "related": ["/kill", "/ps"],
    },
    "/chart": {
        "summary": "Graph image of CPU/RAM over the last 24 hours.",
        "steps": [("Render", "matplotlib from history.json")],
        "effect": "Read-only.",
        "output": "A PNG chart.",
        "troubleshoot": "Needs matplotlib installed.",
        "related": ["/report", "/view"],
    },
    "/report": {
        "summary": "Today's averages and peaks.",
        "steps": [("Aggregate", "history.json for today")],
        "effect": "Read-only.",
        "output": "Averages and peaks.",
        "troubleshoot": "History builds up over time.",
        "related": ["/chart"],
    },
    "/temp": {
        "summary": "CPU/GPU temperature when sensors are available.",
        "steps": [("Read", "WMI/OpenHardwareMonitor sensors via PowerShell")],
        "effect": "Read-only.",
        "output": "Temperature readings.",
        "troubleshoot": "Many VMs expose no sensors.",
        "related": ["/view"],
    },
    "/net": {
        "summary": "Current download/upload speed and totals since boot.",
        "steps": [("Sample", "psutil.net_io_counters() delta")],
        "effect": "Read-only.",
        "output": "Speed and totals.",
        "troubleshoot": "Speed is an average over the last interval.",
        "related": ["/speedtest", "/traffic"],
    },
    "/speedtest": {
        "summary": "Real internet speed test.",
        "steps": [("Download/upload", "HTTP transfer to Cloudflare endpoints")],
        "effect": "Read-only.",
        "output": "Mbps down/up and latency.",
        "troubleshoot": "Consumes bandwidth; run sparingly.",
        "related": ["/net", "/nettest"],
    },
    "/traffic": {
        "summary": "Bandwidth accounting: today, billing cycle, quota, daily table.",
        "steps": [("Aggregate", "traffic.json counters")],
        "effect": "Read-only.",
        "output": "Totals and a daily table.",
        "troubleshoot": "Quota alerts are configured with /set traffic.",
        "related": ["/net"],
    },
    "/sysinfo": {
        "summary": "OS, hardware, pagefile, pending reboot.",
        "steps": [("Collect", "platform + psutil + Get-CimInstance")],
        "effect": "Read-only.",
        "output": "System details.",
        "troubleshoot": "Pending-reboot reads the registry.",
        "related": ["/startup"],
    },
    "/netstat": {
        "summary": "Active connections and listening ports with the owning process.",
        "steps": [("Enumerate", "psutil.net_connections(kind='tcp')")],
        "effect": "Read-only.",
        "output": "A connection table.",
        "troubleshoot": "May need admin rights for all PIDs.",
        "related": ["/rdp", "/firewall"],
    },
    "/startup": {
        "summary": "Autostart inventory: Run keys and non-Microsoft scheduled tasks.",
        "steps": [("Read", "registry Run keys + Get-ScheduledTask")],
        "effect": "Read-only.",
        "output": "A startup list.",
        "troubleshoot": "Compare against expected entries.",
        "related": ["/sysinfo"],
    },
    "/updates": {
        "summary": "Pending Windows updates and reboot flag.",
        "steps": [("Query", "Windows Update COM API / USOClient")],
        "effect": "Read-only.",
        "output": "A pending-update list.",
        "troubleshoot": "Can be slow on first run.",
        "related": ["/sysinfo"],
    },
    "/bigfiles": {
        "summary": "20 largest files on the system drive.",
        "steps": [("Scan", "walk the system drive and sort by size")],
        "effect": "Read-only.",
        "output": "A largest-files list.",
        "troubleshoot": "Excludes protected system paths.",
        "related": ["/clean"],
    },
    "/ps": {
        "summary": "Details for processes matching a name.",
        "steps": [("Match", "psutil process_iter by name"), ("Detail", "exe, cmdline, user, cpu, memory")],
        "effect": "Read-only.",
        "output": "Process details.",
        "troubleshoot": "Use a distinctive name.",
        "related": ["/top", "/kill"],
    },
    "/when": {
        "summary": "When CPU/RAM last exceeded a threshold.",
        "steps": [("Analyze", "history.json thresholds")],
        "effect": "Read-only.",
        "output": "Timestamps above the threshold.",
        "troubleshoot": "Needs accumulated history.",
        "related": ["/chart", "/report"],
    },
    "/botlog": {
        "summary": "The tool's own recent log.",
        "steps": [("Read", "rdp_monitor.log tail")],
        "effect": "Read-only.",
        "output": "Recent log lines.",
        "troubleshoot": "Rotate if it grows large.",
        "related": ["/diagnose"],
    },
    "/audit": {
        "summary": "Recent accepted and rejected actions.",
        "steps": [("Read", "audit.json tail")],
        "effect": "Read-only.",
        "output": "An action history.",
        "troubleshoot": "Records commands and blocks.",
        "related": ["/blocklist"],
    },
    "/blocklist": {
        "summary": "IPs currently blocked in the firewall.",
        "steps": [("Read", "blocked.json")],
        "effect": "Read-only.",
        "output": "Blocked IPs with timestamps.",
        "troubleshoot": "Remove with /unblock.",
        "related": ["/block", "/unblock"],
    },
    "/status": {
        "summary": "Current value of every setting.",
        "steps": [("Read", "config.json")],
        "effect": "Read-only.",
        "output": "A settings summary.",
        "troubleshoot": "Change values with /set.",
        "related": ["/set"],
    },
    "/set": {
        "summary": "Detailed settings guide and value changes.",
        "steps": [("Update", "config[key] = value; save_config()")],
        "effect": "The setting changes immediately.",
        "output": "A confirmation.",
        "troubleshoot": "Use /set with no args for the guide.",
        "related": ["/status"],
    },
    "/mute": {
        "summary": "Silences non-critical alerts for a period.",
        "steps": [("Set", "config.mute_until = now + duration")],
        "effect": "Routine alerts pause; security alerts continue.",
        "output": "A confirmation.",
        "troubleshoot": "/mute off restores alerts.",
        "related": ["/status"],
    },
    "/nettest": {
        "summary": "Connectivity and latency to a host.",
        "steps": [("Test", "TCP connect / ping to the host")],
        "effect": "Read-only.",
        "output": "Reachability and latency.",
        "troubleshoot": "Use a hostname or IP.",
        "related": ["/net", "/speedtest"],
    },
    "/test": {
        "summary": "Sends a test message to verify the alert channel.",
        "steps": [("Send", "sendMessage to the configured chat")],
        "effect": "A test message arrives.",
        "output": "The test message.",
        "troubleshoot": "If it fails, check the token and chat id.",
        "related": ["/status"],
    },
    "/update": {
        "summary": "Self-update from the configured HTTPS URL and SHA-256.",
        "steps": [("Download", "HTTPS GET update_url"), ("Verify", "SHA-256 matches update_hash"), ("Apply", "replace the script")],
        "effect": "The tool updates to the new version.",
        "output": "A success or failure notice.",
        "troubleshoot": "Requires HTTPS and a matching hash; disabled by default.",
        "related": ["/status"],
    },
    "/allow": {
        "summary": "Manage extra trusted Telegram user IDs.",
        "steps": [("Update", "config.trusted_user_ids add/del")],
        "effect": "Those IDs may control the device.",
        "output": "The updated list.",
        "troubleshoot": "Groups are not inherited; use private chat IDs.",
        "related": ["/status"],
    },
    "/trap": {
        "summary": "Honeypot usernames: any login attempt bans the IP.",
        "steps": [("Update", "config.trap_users add/del")],
        "effect": "The first attempt with that name blocks the IP.",
        "output": "The trap list.",
        "troubleshoot": "Use names no real user has.",
        "related": ["/blocklist"],
    },
    "/whitelist": {
        "summary": "The RDP allow-list (manual + learned IPs).",
        "steps": [("Read", "config.rdp_allowed_ips + learned_ips")],
        "effect": "Read-only view; apply with /rdpallow.",
        "output": "The allow-list.",
        "troubleshoot": "Learned IPs are used only during lockdown if enabled.",
        "related": ["/rdpallow", "/lockdown"],
    },
    "/image": {
        "summary": "System image with disk2vhd: captures the volumes while Windows "
                   "runs; disk2vhd may create one VHDX per physical disk.",
        "steps": [("Run", "disk2vhd.exe -c * <file.vhdx>"),
                  ("Upload", "rclone copy of the VHDX file(s)")],
        "effect": "One VHDX per physical disk is produced (needs free space equal "
                  "to used space).",
        "output": "Progress and the file(s).",
        "troubleshoot": "Mount on Hyper-V/Azure directly; for KVM/Proxmox run "
                        "qemu-img convert -f vhdx -O qcow2. Needs admin rights.",
        "related": ["/backup"],
    },
    "/download": {
        "summary": "Sends a file from the machine (up to 45 MB).",
        "steps": [("Read", "open the path"), ("Send", "sendDocument")],
        "effect": "The file is sent to the chat.",
        "output": "The file.",
        "troubleshoot": "Paths outside approved roots may be refused.",
        "related": ["/configbackup"],
    },
    "/logins": {
        "summary": "Successful remote-interactive RDP logins from the last three days (up to 5,000 events scanned).",
        "steps": [("Query", "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624}")],
        "effect": "Read-only.",
        "output": "UTC event time, domain/account, source IP and event record ID.",
        "troubleshoot": "Needs Security log read permission and successful Logon auditing. Query failure is reported separately from an empty result.",
        "related": ["/rdp", "/blocklist"],
    },
    "/panel": {
        "summary": "Shows the WebConsole URL and a token button.",
        "steps": [("Read", "webconsole_state.json port")],
        "effect": "Read-only.",
        "output": "The URL and a Get-token button.",
        "troubleshoot": "Local-only unless remote mode is configured.",
        "related": ["/paneltoken", "/panelstatus"],
    },
    "/panelstatus": {
        "summary": "Checks whether the WebConsole is reachable.",
        "steps": [("Probe", "HTTP GET /health on 127.0.0.1:<port>")],
        "effect": "Read-only.",
        "output": "Reachable yes/no and token stored.",
        "troubleshoot": "If down, check the RDPSuite task.",
        "related": ["/panel"],
    },
    "/paneltoken": {
        "summary": "Reveals the WebConsole login token.",
        "steps": [("Read", "token_enc -> DPAPI unprotect")],
        "effect": "The token is sent.",
        "output": "The token.",
        "troubleshoot": "Rotate if leaked.",
        "related": ["/panel"],
    },
    "/panelremote": {
        "summary": "Turns remote access to the panel on or off.",
        "steps": [("Generate", "self-signed TLS cert -> webconsole/tls/panel.crt.pem"),
                  ("Set", "webconsole_state.json bind=0.0.0.0 + allowed_ips"),
                  ("Firewall", "netsh advfirewall add rule remoteip=<allow-list>"),
                  ("Restart", "supervisor rebinds the WebConsole on 0.0.0.0:8399")],
        "effect": "The panel answers on https://<host-ip>:8399/ for allowed IPs only.",
        "output": "Enabled/disabled and the reachable URLs.",
        "troubleshoot": "on allows loopback + Tailscale 100.64.0.0/10 + this host; "
                        "use allow <ip> for more, open for any IP, off to revert.",
        "related": ["/panel", "/panelstatus"],
    },
    "/backupstatus": {
        "summary": "Worker state, last run, schedule, recent archives.",
        "steps": [("Read", "control/status.json + logs/last_run.json + local_backups")],
        "effect": "Read-only.",
        "output": "A status summary.",
        "troubleshoot": "Use /backupschedule to change timing.",
        "related": ["/backup", "/backupschedule"],
    },
    "/backuplist": {
        "summary": "Local backup archives with size and time.",
        "steps": [("List", "backup/local_backups")],
        "effect": "Read-only.",
        "output": "An archive list.",
        "troubleshoot": "Restore with /restore.",
        "related": ["/restorelist", "/restore"],
    },
    "/backsrc": {
        "summary": "Manage what gets backed up (add/remove/browse).",
        "steps": [("Update", "backup/config.json backup.sources"), ("Reload", "worker reloads config before the next run")],
        "effect": "The backup set changes.",
        "output": "The updated source list.",
        "troubleshoot": "Missing sources abort the backup (fail closed).",
        "related": ["/backup", "/backupstatus"],
    },
    "/backupprogress": {
        "summary": "Live progress of a running backup.",
        "steps": [("Read", "control/progress.json")],
        "effect": "Read-only.",
        "output": "Percent, phase, and message.",
        "troubleshoot": "Updated during compression and cloud upload.",
        "related": ["/backup"],
    },
    "/backupschedule": {
        "summary": "View or change the automatic backup schedule.",
        "steps": [("Update", "backup/config.json schedule (mode/time/interval/times)")],
        "effect": "The worker applies the new schedule within seconds.",
        "output": "The current schedule with buttons.",
        "troubleshoot": "Modes: daily HH:MM, interval HOURS, times HH:MM,HH:MM.",
        "related": ["/backupstatus"],
    },
    "/cloud": {
        "summary": "Choose cloud destinations from existing rclone remotes and test them.",
        "steps": [("List", "rclone listremotes"), ("Update", "backup/config.json cloud.remotes"), ("Test", "rclone lsd <remote>")],
        "effect": "Selected remotes receive each backup.",
        "output": "The destination list with toggle buttons.",
        "troubleshoot": "Create remotes with rclone config; the worker uses the stored rclone.conf.",
        "related": ["/backup", "/backupstatus"],
    },
    "/rclone": {
        "summary": "Cloud (rclone) setup from chat: install, create remotes, test, set target.",
        "steps": [("Install", "download rclone-current-windows-amd64.zip -> backup/rclone/rclone.exe"),
                  ("Google Drive", "/rclone gdrive runs rclone authorize drive and saves the token"),
                  ("OAuth other", "/rclone auth <name> <type> for onedrive/dropbox"),
                  ("Non-OAuth", "rclone --config backup/rclone/rclone.conf config create <name> <type> key value ..."),
                  ("Target", "config.rclone_remote = <remote:path>")],
        "effect": "Remotes live in backup/rclone/rclone.conf, shared with the SYSTEM worker.",
        "output": "The remote list, a test result, or the active upload target.",
        "troubleshoot": "OAuth types (drive/onedrive/dropbox) need a token from "
                        "rclone authorize on any device.",
        "related": ["/image", "/cloud"],
    },
    "/restorelist": {
        "summary": "Archives available to restore.",
        "steps": [("List", "backup/local_backups")],
        "effect": "Read-only.",
        "output": "An archive list.",
        "troubleshoot": "Restore with /restore <name>.",
        "related": ["/restore", "/drill"],
    },
    "/help": {
        "summary": "The full command reference.",
        "steps": [("Render", "HELP_TEXT")],
        "effect": "Read-only.",
        "output": "The reference.",
        "troubleshoot": "Use /docs <command> for details.",
        "related": ["/docs"],
    },
    "/docs": {
        "summary": "The documentation database (index and per-command documents).",
        "steps": [("Render", "COMMAND_INFO + COMMAND_DOCS + PANEL_COVERAGE")],
        "effect": "Read-only.",
        "output": "An index or a full document.",
        "troubleshoot": "Generated to docs/COMMANDS.md too.",
        "related": ["/help"],
    },
    "/menu": {
        "summary": "The interactive button menu.",
        "steps": [("Render", "MENU_PAGES")],
        "effect": "Read-only.",
        "output": "The menu.",
        "troubleshoot": "Tap a section to expand it.",
        "related": ["/help"],
    },
    "/start": {
        "summary": "Opens the main menu.",
        "steps": [("Render", "MENU_PAGES['root']")],
        "effect": "Read-only.",
        "output": "The main menu.",
        "troubleshoot": "Same as /menu.",
        "related": ["/menu"],
    },
    "/noop": {
        "summary": "Cancels a pending action.",
        "steps": [("No-op", "nothing is executed")],
        "effect": "The pending action is dropped.",
        "output": "A cancellation notice.",
        "troubleshoot": "Used by Cancel buttons.",
        "related": [],
    },
}


def _command_section(cmd):
    return category_title(cmd)


def docs_index_text():
    by_section = {}
    for cmd in sorted(COMMAND_INFO):
        by_section.setdefault(_command_section(cmd), []).append(cmd)
    lines = ["<b>Command reference</b>", "Use: /docs &lt;command&gt;"]
    for section in sorted(by_section):
        lines.append("")
        lines.append(f"<b>{esc(section)}</b>")
        lines.append("  " + "  ".join(by_section[section]))
    return "\n".join(lines)


def docs_card_text(cmd):
    cmd = cmd if cmd.startswith("/") else "/" + cmd
    info = COMMAND_INFO.get(cmd)
    if not info:
        return f"Unknown command: {esc(cmd)}. Send /docs for the list."
    desc, usage, dangerous = info
    doc = COMMAND_DOCS.get(cmd)
    lines = [f"{cmd}   [{_command_section(cmd)}]",
             f"Usage: {usage}",
             f"Panel: {PANEL_COVERAGE.get(cmd, 'bot-only')}"]
    if dangerous:
        lines.append("Risk: dangerous (confirmation required)")
    lines.append("")
    if doc:
        lines.append(f"What it does: {doc['summary']}")
        lines.append("")
        lines.append("Steps (backend commands):")
        for i, (title, backend) in enumerate(doc["steps"], 1):
            lines.append(f"  {i}. {title}")
            lines.append(f"     {backend}")
        lines.append("")
        lines.append(f"Effect: {doc['effect']}")
        lines.append(f"Output: {doc['output']}")
        lines.append(f"Troubleshoot: {doc['troubleshoot']}")
        if doc.get("related"):
            lines.append("Related: " + " ".join(doc["related"]))
    else:
        lines.append(f"What it does: {desc}")
        backend = COMMAND_BACKEND.get(cmd)
        if backend:
            lines.append(f"Backend: {backend[0]}")
            lines.append(f"Effect: {backend[1]}")
            lines.append(f"Troubleshoot: {backend[2]}")
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def generate_docs_file():
    """Write docs/COMMANDS.md from the same source used by /docs."""
    try:
        path = os.path.join(SUITE_ROOT, "docs", "COMMANDS.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out = ["# RDP Suite - Command reference", ""]
        by_section = {}
        for cmd in sorted(COMMAND_INFO):
            by_section.setdefault(_command_section(cmd), []).append(cmd)
        for section in sorted(by_section):
            out.append(f"## {section}")
            out.append("")
            for cmd in by_section[section]:
                desc, usage, dangerous = COMMAND_INFO[cmd]
                out.append(f"### {cmd}")
                out.append(f"- Purpose: {desc}")
                out.append(f"- Usage: `{usage}`")
                out.append(f"- Panel: {PANEL_COVERAGE.get(cmd, 'bot-only')}")
                if dangerous:
                    out.append("- Risk: dangerous (confirmation required)")
                doc = COMMAND_DOCS.get(cmd)
                if doc:
                    out.append("")
                    out.append(f"**What it does:** {doc['summary']}")
                    out.append("")
                    out.append("**Steps (backend commands):**")
                    for i, (title, backend) in enumerate(doc["steps"], 1):
                        out.append(f"{i}. {title}")
                        out.append("   ```")
                        out.append(f"   {backend}")
                        out.append("   ```")
                    out.append("")
                    out.append(f"**Effect:** {doc['effect']}")
                    out.append(f"**Output:** {doc['output']}")
                    out.append(f"**Troubleshoot:** {doc['troubleshoot']}")
                    if doc.get("related"):
                        out.append("**Related:** " + " ".join(doc["related"]))
                else:
                    backend = COMMAND_BACKEND.get(cmd)
                    if backend:
                        out.append(f"- Backend: {backend[0]}")
                        out.append(f"- Effect: {backend[1]}")
                        out.append(f"- Troubleshoot: {backend[2]}")
                out.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        return path
    except Exception:
        return None


def show_menu_page(page):
    """Sends a page from a list of buttons"""
    page = PAGE_ALIASES.get(page, page)
    title, items = MENU_PAGES.get(page) or MENU_PAGES["root"]
    rows = [[(lbl, cb) for lbl, cb in items[i:i + 2]]
            for i in range(0, len(items), 2)]
    if page != "root":
        rows.append([(" Home", "menu:root")])
    send_buttons(title, rows)



def setrdpport_wizard():
    """Port Change Wizard RDP Cardigans: Choose a port ← Confirm or cancel — Without writing"""
    current = int(config.get("rdp_port", 3389))
    ports = [p for p in (44389, 33890, 13389) if p != current]
    rows = [[(str(p), "run:/setrdpport " + str(p)) for p in ports[i:i + 2]]
            for i in range(0, len(ports), 2)]
    rows.append([("[X] Cancel — We don’t change anything", "run:/noop")])
    send_buttons(
        rtl(" <b>Port Change Wizard RDP</b>") + "\n"
        + rtl(f"Current port: ({current})") + "\n\n"
        + rtl("Choose the new port — Then confirm [OK] Or cancel [X]:") + "\n"
        + rtl("[WARN] The connection is cut off the moment the application reconnects IP:port_New") + "\n"
        + rtl(" Dedicated port? Write: /setrdpport No"), rows)


READ_ONLY_COMMANDS = {
    "/view", "/top", "/chart", "/report", "/temp", "/net", "/traffic",
    "/speedtest", "/rdp", "/logins", "/listusers", "/screenshot",
    "/bigfiles", "/netstat", "/firewall", "/sysinfo", "/startup",
    "/updates", "/audit", "/blocklist", "/botlog", "/status", "/test",
    "/panelstatus", "/backupstatus", "/backuplist", "/restorelist",
    "/backupprogress", "/diagnose", "/logstats", "/dumps", "/docs", "/help", "/menu",
}


def show_command_info(cmdline):
    """Opening a card never executes an action. Review, then run or confirm."""
    parts = cmdline.strip().split()
    if not parts:
        return
    cmd = canonical_command(parts[0].lower().split("@")[0])
    args = [part for part in parts[1:] if part.lower() != "confirm"]
    command = " ".join([cmd] + args)
    if cmd not in COMMAND_INFO:
        return send_message("Unknown command. Open /menu for the command list.")
    desc, usage, dangerous = COMMAND_INFO[cmd]
    doc = COMMAND_DOCS.get(cmd, {})
    text = (f"<b>{esc(cmd)}</b> ? {esc(_command_section(cmd))}\n"
            f"{esc(desc)}\n\nUsage:\n<code>{esc(usage)}</code>")
    if doc.get("effect"):
        text += "\n\nEffect: " + esc(doc["effect"])
    needs_confirmation = dangerous or cmd not in READ_ONLY_COMMANDS or bool(args)
    if needs_confirmation:
        text += "\n\nReview the target and effect. Confirming may change this device or its access."
    rows = []
    if not any(mark in command for mark in ("<", ">", "|")):
        text += "\n\nSelected: <code>" + esc(command) + "</code>"
        if needs_confirmation:
            rows.extend(confirm_buttons(command))
        else:
            pid = pend_store({"reviewed_command": command})
            rows.append([("Run command", "rv:" + pid)])
    if cmd == "/setrdpport" and not args:
        rows.append([("Choose a port", "port:wizard")])
    if cmd == "/panic" and not args:
        rows.append([("Review panic ON", "cmd:/panic on"), ("Review panic OFF", "cmd:/panic off")])
    if cmd == "/lockdown" and not args:
        rows.append([("Review lockdown NOW", "cmd:/lockdown now")])
    if cmd == "/rdpallow" and not args:
        rows.append([("Review allowlist apply", "cmd:/rdpallow apply")])
    if cmd == "/panelremote" and not args:
        text += "\n\nHTTPS access settings persist across restarts. Choose who can connect."
        rows.extend([
            [("Enable restricted HTTPS", "cmd:/panelremote on"),
             ("Direct IP:port access", "cmd:/panelremote direct")],
            [("Connection status", "cmd:/panelremote status"),
             ("Disable remote access", "cmd:/panelremote off")],
        ])
    rows.append([("Back to category", "menu:" + OWNERS[cmd]), ("Home", "menu:root")])
    send_buttons(text, rows)


def handle_run_callback(cmdline):
    """Old run buttons also enter review; no embedded confirm can bypass it."""
    return show_command_info(cmdline)


def handle_reviewed_command(pid):
    pending = pend_take(pid)
    command = pending.get("reviewed_command") if pending else None
    if not command:
        return send_message("This Run button expired or was already used. Open the command again.")
    handle_command(command)


def handle_menu_callback(data):
    """Executed by pressing a button: List/Order details/Direct implementation"""
    if data.startswith("menu:"):
        show_menu_page(data[5:])
    elif data.startswith("cmd:"):
        show_command_info(data[4:])
    elif data == "panel:token":
        send_panel_token()
    elif (data.startswith("rc:") or data.startswith("rr:")
          or data.startswith("rs:") or data.startswith("rd:")):
        rclone_guided_callback(data)
    elif data.startswith("bs:") or data.startswith("cl:") or data.startswith("sc:"):
        p = pend_take(data[3:])
        if p and p.get("fn"):
            try:
                p["fn"](*p.get("args", ()))
            except Exception as e:
                send_message(f"[X] {esc(str(e))}")
    elif data == "port:wizard":
        setrdpport_wizard()
    elif data.startswith("rv:"):
        handle_reviewed_command(data[3:])
    elif data.startswith("run:"):
        handle_run_callback(data[4:])


def send_photo(path, caption=None, *, cleanup=False):
    """Send a photo; True means the caller must retain it for queued retries."""
    caption = _tag() + (caption or "")
    queued = False
    for chat in _alert_targets():
        if not _send_file_once("photo", chat, path, caption):
            _queue_file("photo", chat, path, caption, cleanup)
            queued = True
    return queued


def send_document(path, caption=None, *, cleanup=False):
    """Send a file to every target. Returns True if any target was queued for retry."""
    caption = _tag() + (caption or "")
    queued = False
    for chat in _alert_targets():
        if not _send_file_once("document", chat, path, caption):
            _queue_file("document", chat, path, caption, cleanup)
            queued = True
    return queued


def tg_download_file(file_id):
    """Download a file sent by the user to the bot (Telegram limit 20MB)"""
    try:
        info = tg_api("getFile", file_id=file_id)
        fp = (info.get("result") or {}).get("file_path")
        if not fp:
            return None
        r = requests.get(
            f"https://api.telegram.org/file/bot{config['telegram_token']}/{fp}",
            timeout=120)
        return r.content if r.ok else None
    except Exception as e:
        print(f"[telegram] file download error: {e}")
        return None


# ----------------------------- Measurements -----------------------------

def get_usage():
    """You come back (Processor ratio, RAM ratio, user ratio GBTotal GB)"""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    used_gb = (mem.total - mem.available) / (1024 ** 3)
    total_gb = mem.total / (1024 ** 3)
    return cpu, mem.percent, used_gb, total_gb


def update_net_speed():
    """Current network speed is calculated from the difference of meters - Each monitoring session is called"""
    global _last_net_time, _last_net_counters
    c = psutil.net_io_counters()
    now = time.time()
    if _last_net_time and now > _last_net_time:
        dt = now - _last_net_time
        _net_speed["down"] = max(0.0, (c.bytes_recv - _last_net_counters[1]) * 8 / dt / 1e6)
        _net_speed["up"] = max(0.0, (c.bytes_sent - _last_net_counters[0]) * 8 / dt / 1e6)
    _last_net_time = now
    _last_net_counters = (c.bytes_sent, c.bytes_recv)


def get_disks():
    """You come back [(Letter, Usage rate, remaining GB, Total GB)]"""
    res = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            res.append((part.device, u.percent,
                        (u.total - u.used) / (1024 ** 3), u.total / 1024 ** 3))
        except Exception:
            pass
    return res


def get_top_processes(n=10):
    """You come back (higher n By processor, higher n In Ramat): [(name, pid, cpu, mem_mb)]"""
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            p.cpu_percent(None)  # Account configuration
            procs.append(p)
        except Exception:
            pass
    time.sleep(0.5)
    items = []
    for p in procs:
        try:
            mi = p.info.get('memory_info')
            items.append((p.info.get('name') or '?', p.info['pid'],
                          p.cpu_percent(None),
                          (mi.rss / (1024 ** 2)) if mi else 0.0))
        except Exception:
            pass
    top_cpu = sorted(items, key=lambda x: -x[2])[:n]
    top_ram = sorted(items, key=lambda x: -x[3])[:n]
    return top_cpu, top_ram


def get_rdp_sessions(strict=False):
    """Active user sessions: qwinsta If available, otherwise psutil.users()"""
    # method 1: qwinsta (Available on Windows Pro It gives the session status and number)
    try:
        try:
            query_result = subprocess.run(["qwinsta"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
            raw = query_result.stdout
        except FileNotFoundError:
            query_result = subprocess.run(["query", "session"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
            raw = query_result.stdout
        if query_result.returncode != 0 or (strict and not _decode_out(raw).strip()):
            raise RuntimeError("session snapshot unavailable")
        sessions = []
        for line in _decode_out(raw).splitlines():
            toks = line.split()
            state_idx = None
            for i, t in enumerate(toks):
                if t.lower() in RDP_STATE_WORDS or t in RDP_STATE_WORDS:
                    state_idx = i
                    break
            if state_idx is None or state_idx < 2:
                continue
            user = toks[state_idx - 2]
            if not user or user.startswith(("rdp-tcp", "console", "service", ">")):
                continue
            sessions.append({
                "session": toks[0].lstrip(">"),
                "user": user,
                "id": toks[state_idx - 1],
                "state": toks[state_idx],
            })
        return sessions
    except FileNotFoundError:
        if strict:
            raise
    except Exception as e:
        if strict:
            raise
        print(f"[sessions] qwinsta error: {e}")

    # method 2 (Alternative for Windows Home): psutil.users()
    sessions = []
    for u in psutil.users():
        term = u.terminal or "console"
        state = "RDP" if "rdp" in term.lower() else "Active"
        sessions.append({"session": term, "user": u.name, "id": "", "state": state})
    return sessions


def _net_names(out):
    """Extracting names from outputs net user / net localgroup (One or two line breaks)"""
    lines = out.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("---"):
            start = i
            break
    if start is None:
        return []
    names = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if not s or s.startswith("---") \
                or "command" in s.lower() or "Order" in s:
            break
        names.extend(s.split())
    return names


# ----------------------------- User management -----------------------------

INVALID_USER_CHARS = set('/\\[]":;|<>+=,?*')


def valid_username(name):
    """Basic username verification (Windows rules)"""
    return (1 <= len(name) <= 20
            and not name.startswith("-")
            and not any(c in INVALID_USER_CHARS for c in name)
            and name.strip() == name
            and name not in (".", ".."))


def run_net(args, timeout=25):
    """Executing an order net And return (Result code, text) - Without shell This means no command injection"""
    try:
        r = subprocess.run(["net"] + args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        out = _decode_out(r.stdout)
        err = _decode_out(r.stderr)
        text = (out + "\n" + err).strip()
        return r.returncode, text
    except Exception as e:
        return -1, str(e)


def _find_local_group(*keywords):
    """Searches the device’s groups for a group whose name contains one of the words"""
    rc, out = run_net(["localgroup"])
    if rc != 0:
        return None
    for g in _net_names(out):
        g = g.lstrip("*")  # The group list displays names with a prefix *
        gl = g.lower()
        for kw in keywords:
            if kw in gl:
                return g
    return None


def add_to_group(user, common_names, keywords):
    """Adds a user to a group (Try common names and then research) - He comes back (Group name, success?)"""
    for g in common_names:
        rc, _ = run_net(["localgroup", g, user, "/add"])
        if rc == 0:
            return g, True
    g = _find_local_group(*keywords)
    if g:
        rc, _ = run_net(["localgroup", g, user, "/add"])
        if rc == 0:
            return g, True
    return None, False


def get_rdp_ips():
    """Addresses IP Currently connected to a port RDP Cross netstat"""
    rdp_port = str(config.get("rdp_port", 3389))
    ips = []
    try:
        raw = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, timeout=15, creationflags=NO_WINDOW).stdout
        out = _decode_out(raw)
        for line in out.splitlines():
            toks = line.split()
            if len(toks) >= 4 and toks[0] == "TCP" \
                    and toks[1].endswith(":" + rdp_port) \
                    and toks[3] == "ESTABLISHED":
                ip = toks[2].rsplit(":", 1)[0].strip("[]")
                if ip and ip not in ips:
                    ips.append(ip)
    except Exception as e:
        print(f"[netstat] error: {e}")
    return ips


def get_local_users():
    """Local user accounts + Distinguishing supervisors: [(name, is_admin)]"""
    names = []
    try:
        out = subprocess.run(["net", "user"], capture_output=True, timeout=15, creationflags=NO_WINDOW)\
            .stdout
        names = _net_names(_decode_out(out))
    except Exception as e:
        print(f"[users] error: {e}")

    admins = set()
    try:
        r = subprocess.run(["net", "localgroup", "administrators"],
                           capture_output=True, timeout=15, creationflags=NO_WINDOW)
        if r.returncode == 0:
            admins.update(_net_names(_decode_out(r.stdout)))
    except Exception:
        pass

    admins_lower = {a.lower() for a in admins}
    return [(u, u.lower() in admins_lower) for u in names]


def run_speedtest():
    """Measure internet speed via Cloudflare: (ping ms, Download Mbps, Raise Mbps)"""
    t0 = time.time()
    requests.get("https://speed.cloudflare.com/__down?bytes=1000", timeout=remaining_timeout(15))
    ping_ms = (time.time() - t0) * 1000

    t0 = time.time()
    r = requests.get("https://speed.cloudflare.com/__down?bytes=25000000", timeout=remaining_timeout(120))
    dl_secs = max(0.001, time.time() - t0)
    down_mbps = len(r.content) * 8 / dl_secs / 1e6

    payload = b"0" * 8_000_000
    t0 = time.time()
    requests.post("https://speed.cloudflare.com/__up", data=payload, timeout=remaining_timeout(120))
    ul_secs = max(0.001, time.time() - t0)
    up_mbps = len(payload) * 8 / ul_secs / 1e6

    return ping_ms, down_mbps, up_mbps


# ----------------------------- Consumption record -----------------------------

def load_history():
    global _history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                _history = json.load(f)
            cutoff = time.time() - 8 * 24 * 3600  # We keep 8 Weekly reporting days
            _history = [h for h in _history if h.get("t", 0) >= cutoff]
    except Exception:
        _history = []


def save_history():
    _atomic_write_json(HISTORY_FILE, _history)


def append_history(cpu, ram):
    _history.append({"t": time.time(), "c": round(cpu, 1), "r": round(ram, 1)})
    max_pts = 8 * 24 * 60  # 8 Sample days every minute
    if len(_history) > max_pts:
        del _history[:len(_history) - max_pts]


def stats_since(ts):
    """Consumption statistics from a certain time
    - .get With default: Bad point/The old formula was silently breaking the daily report"""
    pts = [h for h in _history
           if h.get("t", 0) >= ts and isinstance(h.get("c"), (int, float))
           and isinstance(h.get("r"), (int, float))]
    if not pts:
        return None
    cpus = [h["c"] for h in pts]
    rams = [h["r"] for h in pts]
    n = len(pts)
    return {
        "points": n,
        "cpu_avg": sum(cpus) / n, "cpu_max": max(cpus),
        "ram_avg": sum(rams) / n, "ram_max": max(rams),
    }


# ----------------------------- Chart -----------------------------

def make_chart(hours=24):
    """Plots another consumption N hours and returns the image path or None"""
    if not HAS_MATPLOTLIB or len(_history) < 2:
        return None
    import matplotlib.pyplot as plt
    now = time.time()
    pts = [h for h in _history if h["t"] >= now - hours * 3600]
    if len(pts) < 2:
        return None

    ts = [datetime.fromtimestamp(h["t"]) for h in pts]
    cpus = [h["c"] for h in pts]
    rams = [h["r"] for h in pts]

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
    ax.plot(ts, cpus, label="CPU %", color="#e74c3c", linewidth=1.4)
    ax.plot(ts, rams, label="RAM %", color="#3498db", linewidth=1.4)
    ax.axhline(config["cpu_alert_threshold"], color="gray",
               linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axhline(config["critical_threshold"], color="red",
               linestyle="--", linewidth=0.8, alpha=0.4)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Percent %")
    ax.set_title(f"CPU / RAM - last {hours}h")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()

    path = os.path.join(tempfile.gettempdir(),
                        f"rdp_monitor_chart_{time.time_ns()}.png")
    fig.savefig(path)
    plt.close(fig)
    return path


# ----------------------------- Scheduled reports -----------------------------

def send_daily_report():
    midnight = datetime.now().replace(hour=0, minute=0, second=0,
                                      microsecond=0).timestamp()
    s = stats_since(midnight)
    if not s:
        send_message(" Daily report: There is not enough data yet.")
        return
    traffic_line = ""
    rec = _traffic.get(datetime.now().strftime("%Y-%m-%d"))
    if rec:
        traffic_line = (f"\n Data today: DL  {rec['down'] / 1024:.2f} GB "
                        f"| UL  {rec['up'] / 1024:.2f} GB")
    txt = (
        f"<b>Daily report</b> - {datetime.now():%Y-%m-%d}\n"
        f" Processor: Average {s['cpu_avg']:.0f}% / higher {s['cpu_max']:.0f}%\n"
        f" rams: Average {s['ram_avg']:.0f}% / higher {s['ram_max']:.0f}%\n"
        f" Number of measurements: {s['points']}" + traffic_line
    )
    chart = make_chart(24)
    if chart:
        send_photo(chart, txt)
    else:
        send_message(txt)


def send_weekly_report():
    week_ago = time.time() - 7 * 24 * 3600
    s = stats_since(week_ago)
    if not s:
        send_message(" Weekly report: There is not enough data yet.")
        return
    try:
        extra = "\n\n" + logstats_summary()
    except Exception:
        extra = ""
    send_message(
        f"<b>Weekly report</b>\n"
        f" Processor: Average {s['cpu_avg']:.0f}% / higher {s['cpu_max']:.0f}%\n"
        f" rams: Average {s['ram_avg']:.0f}% / higher {s['ram_max']:.0f}%\n"
        f" Number of measurements: {s['points']}" + extra
    )


# ----------------------------- Text reports -----------------------------

def format_uptime():
    secs = int(time.time() - psutil.boot_time())
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}h {m}m"


def format_report():
    cpu, ram_pct, used_gb, total_gb = get_usage()
    disks = get_disks()
    disk_line = ""
    if disks:
        dev, pct, free, _total = disks[0]
        disk_line = f" disk {dev} : {pct:.0f}% (remaining {free:.0f} GB)\n"
    return (
        rtl("<b>Consumption report</b>") + "\n"
        + rtl(f" Processor (CPU): <b>{cpu:.1f}%</b>") + "\n"
        + rtl(f" rams (RAM): <b>{ram_pct:.1f}%</b>") + "\n"
        + rtl(f"User: {used_gb:.2f} GB Who {total_gb:.2f} GB") + "\n"
        + rtl(f" network: DL  {_net_speed['down']:.1f} | UL  {_net_speed['up']:.1f} Mbps") + "\n"
        + rtl(disk_line.strip()) + "\n"
        + rtl(f" Active users: {len(psutil.users())}") + "\n"
        + rtl(f" Duration of operation: {format_uptime()}")
    )


def format_net_report():
    c = psutil.net_io_counters()
    return (
        rtl("<b>Use the network</b>") + "\n"
        + rtl(f"DL  Download now: <b>{_net_speed['down']:.2f} Mbps</b>") + "\n"
        + rtl(f"UL  Upload now: <b>{_net_speed['up']:.2f} Mbps</b>") + "\n"
        + rtl(" Since turning on the device:") + "\n"
        + rtl(f"He arrived: {c.bytes_recv / 1024 ** 3:.2f} GB") + "\n"
        + rtl(f"He came out: {c.bytes_sent / 1024 ** 3:.2f} GB")
    )


def format_top_report():
    top_cpu, top_ram = get_top_processes(10)
    lines = ["<b>Highest consuming processes</b>", "",
             " <b>Depending on the processor:</b>", "<pre>"]
    for i, (name, pid, cpu, mem) in enumerate(top_cpu, 1):
        lines.append(esc(f"{i:2}. {name[:26]:26} {cpu:5.1f}% {mem:6.0f} MB"))
    lines.append("</pre>\n <b>According to the rams:</b>\n<pre>")
    for i, (name, pid, cpu, mem) in enumerate(top_ram, 1):
        lines.append(esc(f"{i:2}. {name[:26]:26} {mem / 1024:5.2f} GB {cpu:5.1f}%"))
    lines.append("</pre>")
    return "\n".join(lines)


def format_rdp_report():
    sess = get_rdp_sessions()
    ips = get_rdp_ips()
    lines = ["<b>Sessions RDP Active</b>", ""]
    if sess:
        lines.append("<pre>")
        for s in sess:
            lines.append(esc(f"{s['user'][:20]:20} {s['state'][:10]:10} ID {s['id']}"))
        lines.append("</pre>")
    else:
        lines.append("There are currently no user sessions registered")
    if ips:
        lines.append(f"\n <b>IPs connected to a port RDP ({config.get('rdp_port', 3389)}):</b>\n<pre>")
        for ip in ips:
            lines.append(esc(ip))
        lines.append("</pre>")
    return "\n".join(lines)


PS_LOCAL_USERS_DETAIL = (
    "$ErrorActionPreference='Stop'; $admins=@{}; "
    "try { Get-LocalGroup -SID 'S-1-5-32-544' -ErrorAction Stop | "
    "Get-LocalGroupMember -ErrorAction Stop | "
    "ForEach-Object { $admins[$_.Name.Split('\\')[-1].ToLower()] = $true } } catch { throw } "
    "Get-LocalUser | ForEach-Object { "
    "$a = if ($admins.ContainsKey($_.Name.ToLower())) { 1 } else { 0 }; "
    "$pls = if ($_.PasswordLastSet) { $_.PasswordLastSet.ToString('yyyy-MM-dd') } else { '-' }; "
    "$pex = if ($_.PasswordExpires) { $_.PasswordExpires.ToString('yyyy-MM-dd') } else { 'never' }; "
    "$ll = if ($_.LastLogon) { $_.LastLogon.ToString('yyyy-MM-dd') } else { '-' }; "
    "Write-Output ($_.Name + '|' + [int][bool]$_.Enabled + '|' + $a + '|' + $pls + '|' + $pex + '|' + $ll) "
    "}"
)


def _local_users_detail(strict=False):
    """Accounts details: [{name, enabled, admin, pwlastset, pwexpires, lastlogon}]
    - Cross Get-LocalUser (More accurate than net user): Status and password dates"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            PS_LOCAL_USERS_DETAIL],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if strict and r.returncode != 0:
            raise RuntimeError("Windows account inventory failed")
        users = []
        for ln in _decode_out(r.stdout).splitlines():
            parts = ln.strip().split("|")
            if len(parts) != 6:
                if strict and ln.strip():
                    raise RuntimeError("invalid Windows account inventory")
                continue
            if strict and (not parts[0] or parts[1] not in ("0", "1")
                           or parts[2] not in ("0", "1")):
                raise RuntimeError("incomplete Windows account inventory")
            users.append({
                "name": parts[0], "enabled": parts[1] == "1",
                "admin": parts[2] == "1", "pwlastset": parts[3],
                "pwexpires": parts[4], "lastlogon": parts[5],
            })
        if users:
            return users
        if strict:
            raise RuntimeError("Windows account inventory is empty")
    except Exception as e:
        if strict:
            raise
        print(f"[users-detail] error: {e}")
    # Precaution: Who net user No details
    return [{"name": n, "enabled": True, "admin": a,
             "pwlastset": "-", "pwexpires": "-", "lastlogon": "-"}
            for n, a in get_local_users()]


def _password_weak(pw):
    """Check password strength locally before Windows rejects it - Due to weakness or None"""
    if len(pw) < 8:
        return ("less than 8 Typefaces / less than 8 characters")
    if not re.search(r"[A-Za-z]", pw):
        return "There are no letters in it / no letters"
    if not re.search(r"[0-9]", pw):
        return "There is no number in it / no digit"
    if not re.search(r"[^A-Za-z0-9]", pw):
        return "There is no symbol in it / no symbol"
    return None


def last_admin_guard(name):
    """Deletion is prohibited/Disable/Change the password of the last activated admin = Protect yourself from being locked out of your device
    - He comes back (Allowed?, warning message or None)"""
    try:
        users = _local_users_detail(strict=True)
        target = next((u for u in users
                       if u["name"].lower() == name.lower()), None)
        if target is None:
            return False, "Cannot verify the target account; no change was made."
        admins = [u for u in users if u["admin"] and u["enabled"]]
        if target["admin"] and target["enabled"] and len(admins) <= 1:
            return False, (
                f" <b>{esc(name)}</b> He is the only active administrator on the device!\n"
                f" <b>{esc(name)}</b> is the ONLY enabled administrator!\n\n"
                "Executing the order will permanently lock you out.\n"
                "Create a second first supervisor: /adduser backup Admin@123 admin\n\n"
                "Running this would lock you out. Create a second admin first.")
        me = os.environ.get("USERNAME", "")
        if me and target["name"].lower() == me.lower():
            return True, rtl("[WARN] Pay attention: This is an account of your current session! "
                             "If the session is closed, you will need a second login method.\n"
                             "[WARN] This is your current session's account — "
                             "make sure you have another way in.")
        return True, None
    except Exception:
        return False, "Cannot verify administrator safety; no change was made. Try again when account inventory is available."


def format_users_report():
    """Accounts report: Status, moderation and password dates"""
    users = _local_users_detail()
    if not users:
        return "[X] I couldn’t read the user list"
    users.sort(key=lambda u: (not u["admin"], u["name"].lower()))
    lines = [rtl("<b>User accounts on the device / Local accounts</b>\n")]
    for u in users:
        state = "" if u["enabled"] else " Disabled"
        role = " Supervisor" if u["admin"] else ""
        lines.append(
            rtl(f"{role} <b>{esc(u['name'])}</b> — {state}") + "\n"
            + rtl(f"    Password changed: {u['pwlastset']} · "
                  f"It ends: {u['pwexpires']} · Last entry: {u['lastlogon']}"))
    lines.append("\n" + rtl("Management: /adduser /disableuser /enableuser "
                            "/deluser /renameuser"))
    return "\n".join(lines)


# ----------------------------- Procedures -----------------------------

def do_restart(reason, auto=False):
    """Perform a reboot with user notification"""
    delay = int(config.get("restart_delay_seconds", 30))
    kind = "Automatic restart" if auto else "Manual restart"
    send_message(
        f"[WARN] <b>{kind}</b>\n"
        f"The reason: {reason}\n"
        f"The device will then reboot {delay} Again.\n"
        f"To cancel send /cancel_restart During this period."
    )
    try:
        subprocess.run(
            ["shutdown", "/r", "/t", str(delay), "/c", f"RDP Monitor: {reason}"],
            check=True, creationflags=NO_WINDOW)
        return True
    except Exception as e:
        send_message(f"[X] Failed to perform restart: {e}")
        return False


def cancel_restart():
    try:
        subprocess.run(["shutdown", "/a"], check=True, creationflags=NO_WINDOW)
        send_message("[OK] The scheduled restart has been cancelled.")
        return True
    except Exception as e:
        send_message(f"There is no scheduled reboot to cancel ({e})")
        return False


def kill_by_name(name):
    """End processes with exactly matching name (With or without .exe)
    - It was a partial match: /kill py He was killing python.exe And pythonw.exe Together"""
    target = name.lower()
    candidates = {target}
    if not target.endswith(".exe"):
        candidates.add(target + ".exe")
    killed = []
    me = os.path.basename(sys.executable or "").lower()
    for p in psutil.process_iter(['name']):
        pname = (p.info.get('name') or '').lower()
        if pname in candidates:
            if pname == me or pname == "pythonw.exe":
                continue  # Don’t kill the tool itself
            try:
                p.kill()
                killed.append(f"{p.info['name']} (PID {p.pid})")
            except psutil.Error:
                pass
    return killed


def exec_command(cmd):
    """Run a command CMD Returns the result as text"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=30, creationflags=NO_WINDOW)

        def dec(b):
            # cmd.exe Exported with encryption OEM For console (cp437/cp720...) - Andutf-8 Finally, just in case
            for enc in (_oem_cp(), "utf-8", "cp1256"):
                try:
                    return b.decode(enc)
                except UnicodeDecodeError:
                    continue
                except LookupError:
                    continue
            return b.decode("utf-8", "replace")

        out = dec(r.stdout)
        err = dec(r.stderr)
        text = (out + "\n" + err).strip() or "(no output)"
        if len(text) > 3500:
            text = text[:3500] + "\n... (It has been truncated)"
        return f"Command: {cmd}\n\nOutput:\n{text}"
    except subprocess.TimeoutExpired:
        return f"Command: {cmd}\n\nTimed out after 30 seconds and was terminated."
    except Exception as e:
        return f"Command: {cmd}\n\nError: {e}"


def take_screenshot():
    """A screenshot of the device (All screens)"""
    try:
        from PIL import ImageGrab
        path = os.path.join(tempfile.gettempdir(),
                            f"rdm_screenshot_{int(time.time())}.png")
        img = ImageGrab.grab(all_screens=True)
        img.save(path)
        return path
    except Exception as e:
        print(f"[screenshot] error: {e}")
        return None


def restart_program():
    """Restart the tool itself"""
    if getattr(sys, "frozen", False):
        target = [sys.executable]
    else:
        target = [sys.executable, SCRIPT_PATH]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(target, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(0)


def update_self():
    """Download a new copy of update_url Replace the tool and restart it"""
    url = config.get("update_url", "")
    if not url:
        send_message("[X] You did not specify the update link. Edit update_url In config.json\n"
                     "Or send: /set update https://example.com/rdp_monitor.py")
        return
    send_message("Loading the update...")
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        code = r.text
        compile(code, "rdp_monitor_new.py", "exec")  # Check the validity of the code before replacing
    except Exception as e:
        send_message(f"[X] The update failed to download (Nothing has been changed): {e}")
        return

    # Imprint SHA256: Without pre-installing the fingerprint we do nothing — Coderemote Executed with administrator powers
    new_hash = hashlib.sha256(r.content).hexdigest()
    pinned = (config.get("update_hash") or "").lower()
    if pinned and new_hash != pinned:
        send_message("[X] I refused to update: The fingerprint of the new file does not match the fingerprint "
                     "Installed with /set updatehash — Did the file change after I disabled it?\n"
                     f"Fingerprint of the downloaded copy: <code>{new_hash}</code>")
        return
    if not pinned:
        send_message("Fingerprint of the new version (SHA256):\n"
                     f"<code>{new_hash}</code>\n\n"
                     "Review the code first, then fingerprint and update it:\n"
                     f"<code>/set updatehash {new_hash}</code>\n"
                     "<code>/update</code>")
        return

    try:
        new_path = SCRIPT_PATH + ".new"
        bak_path = SCRIPT_PATH + ".bak"
        with open(new_path, "wb") as f:
            # byte as downloaded — Writing a text was a change BOM And the ends of the lines
            # The update check keeps saying "The versions are different" Without end
            f.write(r.content)
        if os.path.exists(bak_path):
            os.remove(bak_path)
        if os.path.exists(SCRIPT_PATH):
            os.replace(SCRIPT_PATH, bak_path)
        os.replace(new_path, SCRIPT_PATH)
    except Exception as e:
        send_message(f"[X] File replacement failed: {e}")
        return

    send_message("[OK] Updated successfully. The tool will now restart...")
    time.sleep(2)
    restart_program()


def handle_incoming_file(msg):
    """Save a file/An image sent by the user to the bot on the device"""
    if not config.get("uploads_enabled"):
        send_message("Receiving files is disabled. Activate it with /set uploads on")
        return
    doc = msg.get("document")
    photo = msg.get("photo")
    if doc:
        file_id = doc["file_id"]
        fname = os.path.basename(doc.get("file_name") or f"file_{int(time.time())}")
        fsize = doc.get("file_size") or 0
    elif photo:
        best = max(photo, key=lambda p: p.get("width", 0))
        file_id = best["file_id"]
        fname = f"photo_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        fsize = best.get("file_size") or 0
    else:
        return
    if fsize > 20 * 1024 * 1024:
        send_message("[X] File size is greater than 20MB (This is Telegram’s limit for downloading bots).")
        return
    send_message("Downloading file...")
    data = tg_download_file(file_id)
    if not data:
        send_message("[X] File download failed.")
        return
    updir = os.path.expanduser(config["upload_dir"])
    os.makedirs(updir, exist_ok=True)
    dest = os.path.join(updir, fname)
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(dest):
        dest = f"{base}_{n}{ext}"
        n += 1
    try:
        with open(dest, "wb") as f:
            f.write(data)
    except Exception as e:
        send_message(f"[X] Failed to save file: {e}")
        return
    send_message(f"[OK] The file has been saved:\n{dest}\nSize: {len(data) / 1048576:.2f} MB")


# ----------------------------- Additional safety and maintenance -----------------------------

AUDIT_FILE = os.path.join(BASE_DIR, "audit.json")
_legacy_audit_lock = threading.RLock()
BLOCKED_FILE = os.path.join(BASE_DIR, "blocked.json")


def load_audit():
    global _audit
    try:
        if os.path.exists(AUDIT_FILE):
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                _audit = json.load(f)
    except Exception:
        _audit = []


def audit_record(entry):
    with _legacy_audit_lock:
        _audit.append({"t": time.time(), "e": entry})
        if len(_audit) > 300:
            del _audit[:len(_audit) - 300]
        _atomic_write_json(AUDIT_FILE, _audit, ensure_ascii=False)


def format_size(n):
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024:.0f} KB"


def get_temps():
    """Temperature reading: Trans processor WMI And I decided NVIDIA Cross nvidia-smi"""
    temps = {}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
             "-ErrorAction Stop | Measure-Object -Property CurrentTemperature -Maximum).Maximum"],
            capture_output=True, timeout=20, creationflags=NO_WINDOW)
        temps["CPU"] = float(r.stdout.decode().strip()) / 10.0 - 273.15
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=15, creationflags=NO_WINDOW)
        temps["GPU"] = float(r.stdout.decode().split()[0])
    except Exception:
        pass
    return temps


def temps_report_message(temps):
    if not temps:
        return (" I could not read the temperature on this device.\n"
                "What is sensitive about it? WMI Available and what’s in it nvidia-smi (Card NVIDIA).\n"
                "For full readings, pin it LibreHardwareMonitor Then try again.")
    lines = ["<b>Temperature reading</b>"]
    for k, v in sorted(temps.items()):
        mark = "" if v >= config.get("temp_threshold", 85) else ""
        lines.append(f"{mark} {k}: {v:.0f}°C")
    return "\n".join(lines)


def temp_job():
    send_message(temps_report_message(get_temps()))


def idle_seconds():
    """How many seconds have passed since the last press?/User movement"""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return max(0.0, (ctypes.windll.kernel32.GetTickCount()
                             - lii.dwTime) / 1000.0)
    except Exception:
        pass
    return 0.0


def lock_session():
    try:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"],
                       capture_output=True, timeout=15, creationflags=NO_WINDOW)
        return True
    except Exception:
        return False


def show_message_box(text):
    """A pop-up message on the device screen"""
    def _show():
        try:
            import ctypes
            # MB_SETFOREGROUND | MB_TOPMOST | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, text, "RDP Monitor", 0x50040)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()


def clean_temp_files(max_age_hours=24):
    """Clean files TEMP Older than a day + Recycle Bin - Returns the size of the editor"""
    freed = 0
    cutoff = time.time() - max_age_hours * 3600
    win_temp = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")
    for d in {tempfile.gettempdir(), win_temp}:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d, topdown=False):
            for f in files:
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    if st.st_mtime < cutoff:
                        freed += st.st_size
                        os.remove(p)
                except OSError:
                    pass
            for dd in dirs:
                p = os.path.join(root, dd)
                try:
                    if not os.listdir(p):
                        os.rmdir(p)
                except OSError:
                    pass
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=90, creationflags=NO_WINDOW)
    except Exception:
        pass
    return freed


def _failed_logon_ps():
    return failed_query(config.get("failed_login_window", 15), config.get("failed_logon_types", "10"))


def load_blocked():
    global _blocked
    try:
        if os.path.exists(BLOCKED_FILE):
            with open(BLOCKED_FILE, "r", encoding="utf-8") as f:
                _blocked = json.load(f)
    except Exception:
        _blocked = {}


def save_blocked():
    if not _atomic_write_json(BLOCKED_FILE, _blocked, ensure_ascii=False, indent=1):
        raise OSError("blocked.json could not be saved")


@contextlib.contextmanager
def _blocked_file_guard():
    """Cross-process mutex shared with the optional hardened WebConsole."""
    handle = None
    acquired = False
    try:
        name = "Global\\RDPMonitorBlocked_" + hashlib.sha256(
            BASE_DIR.lower().encode()).hexdigest()[:20]
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise TimeoutError("blocked.json lock creation failed")
        wait = kernel32.WaitForSingleObject(handle, 15000)
        # WAIT_OBJECT_0 (0) and WAIT_ABANDONED (0x80) both grant ownership.
        if wait not in (0, 0x80):
            raise TimeoutError("blocked.json lock timeout")
        acquired = True
        yield
    finally:
        if handle:
            if acquired:
                ctypes.windll.kernel32.ReleaseMutex(handle)
            ctypes.windll.kernel32.CloseHandle(handle)


def _valid_ip(ip):
    return canonical_ip(ip) is not None


def _netsh(args):
    """Implementation netsh Returning error text - Failure was swallowed silently, he says 'Administrator powers'
    For any mysterious error"""
    try:
        r = subprocess.run(["netsh"] + args, capture_output=True, timeout=30,
                           creationflags=NO_WINDOW)
        err = (_decode_out(r.stderr).strip()
               or _decode_out(r.stdout).strip())[:160]
        return r.returncode == 0, err
    except Exception as e:
        return False, str(e)[:160]


def _firewall_rule_count(name):
    try:
        script = ("$ErrorActionPreference='Stop'; $rules=@(Get-NetFirewallRule -ErrorAction Stop | "
                  "Where-Object { $_.DisplayName -eq '" + _ps_quote(name) + "' }); Write-Output $rules.Count")
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                capture_output=True, timeout=60, creationflags=NO_WINDOW)
        text = _decode_out(result.stdout).strip()
        return int(text) if result.returncode == 0 and text.isdigit() else None
    except Exception:
        return None


def _add_block_target(target):
    if protected_target(target, config.get("rdp_allowed_ips", [])):
        return False, "refused: target contains a trusted management, loopback or unsafe address"
    try:
        with _blocked_file_guard():
            load_blocked()
            if target in _blocked:
                count = _firewall_rule_count("RDPMonitor Block " + target)
                if count is None:
                    return False, "cannot verify existing firewall rule"
                if count > 0:
                    return True, "exists"
            previous = dict(_blocked)
            ok, error = _netsh(["advfirewall", "firewall", "add", "rule",
                                f"name=RDPMonitor Block {target}", "dir=in", "action=block", f"remoteip={target}"])
            if not ok:
                return False, error or "firewall rule creation failed"
            _blocked[target] = time.time()
            try:
                save_blocked()
            except Exception:
                _blocked.clear()
                _blocked.update(previous)
                rolled_back, _ = _netsh(["advfirewall", "firewall", "delete", "rule", f"name=RDPMonitor Block {target}"])
                return False, ("tracking write failed; new firewall rule rolled back" if rolled_back else
                               "tracking write and rollback failed; inspect firewall manually")
            return True, "added"
    except TimeoutError:
        return False, "block list is busy (lock timeout)"


def block_ip(ip):
    ip = canonical_ip(ip)
    return _add_block_target(ip) if ip else (False, "invalid IP")


def unblock_ip(ip):
    target = canonical_target(ip)
    if not target:
        return False
    with _blocked_file_guard():
        load_blocked()
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name=RDPMonitor Block {target}"])
        count = _firewall_rule_count("RDPMonitor Block " + target)
        if count != 0:
            return False
        previous = dict(_blocked)
        _blocked.pop(target, None)
        try:
            save_blocked()
        except Exception:
            _blocked.clear()
            _blocked.update(previous)
            return False
        return True


def check_failed_logons():
    """Reads login failure events (4625) It alerts and blocks intruders
    - Interference gate: The scan may take longer than the scheduling cycle (60 Again)"""
    if not _check_start("failed_logons"):
        return
    try:
        _check_failed_logons_impl()
    finally:
        _check_end("failed_logons")


def _check_failed_logons_impl():
    global _seen_4625
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _failed_logon_ps()],
                           capture_output=True, timeout=90, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Security event query failed; no protection state was changed")
    except Exception as exc:
        print(f"[failed-logons] {exc}")
        return
    now = time.time()
    window_min = max(1, int(config.get("failed_login_window", 15)))
    window = window_min * 60
    # Event time, not polling time, determines the failure window.
    _seen_4625 = {key: stamp for key, stamp in _seen_4625.items()
                  if isinstance(stamp, (float, int)) and not isinstance(stamp, bool)
                  and now - window <= stamp <= now + 60}
    new_by_ip = {}
    for line in _decode_out(r.stdout).splitlines():
        parts = line.strip().split("|")
        if len(parts) not in (3, 4):
            continue
        user, raw_ip, stamp = parts[:3]
        ip = usable_source(raw_ip)
        event_time = event_timestamp(stamp)
        if not ip or event_time is None or not now - window <= event_time <= now + 60:
            continue
        key = "record:" + parts[3] if len(parts) == 4 and parts[3].isdigit() else f"{user}|{ip}|{stamp}"
        if key in _seen_4625:
            continue
        _seen_4625[key] = event_time
        info = new_by_ip.setdefault(ip, {"users": set(), "times": []})
        info["users"].add(user)
        info["times"].append(event_time)
    if len(_seen_4625) > 50000:
        _seen_4625 = dict(sorted(_seen_4625.items(), key=lambda item: (
            item[1], int(item[0][7:]) if item[0].startswith("record:") else 0))[-50000:])
    for ip, entry in list(_failed_logins.items()):
        entry["times"] = [t for t in entry["times"] if now - window <= t <= now + 60]
        if not entry["times"]:
            _failed_logins.pop(ip, None)
    if not new_by_ip:
        return
    traps = {str(name).casefold() for name in config.get("trap_users", [])}
    threshold = 1 if lockdown_active() else max(1, int(config.get("failed_login_block_threshold", 10)))
    lines = ["<b>Failed RDP login attempts</b>", f"Event window: {window_min} minutes (UTC event timestamps)."]
    for ip, info in new_by_ip.items():
        entry = _failed_logins.setdefault(ip, {"times": []})
        entry["times"].extend(info["times"])
        total = len(entry["times"])
        latest = datetime.fromtimestamp(max(info["times"]), timezone.utc).isoformat(timespec="seconds")
        lines.append(f"Account: {esc(', '.join(sorted(info['users'])))} | Source: {esc(ip)} | Attempts: {total} | Latest: {latest}")
        protected = protected_target(ip, config.get("rdp_allowed_ips", []))
        trap = any(name.casefold() in traps for name in info["users"])
        if protected:
            lines.append("  Trusted management address: alerted, never automatically blocked.")
            continue
        already = ip in _blocked
        if not already and (trap or (config.get("failed_login_block") and total >= threshold)):
            ok, status = block_ip(ip)
            lines.append("  IP blocked." if ok else "  Block failed: " + esc(status))
            already = ok
        if already and config.get("subnetblock", False) and (trap or config.get("failed_login_block")):
            ok, status = block_subnet(ip)
            if ok and status == "added":
                lines.append("  Explicit subnet policy: /24 blocked.")
    audit_record("Failed RDP attempts: " + "; ".join(f"{ip} x{len(info['times'])}" for ip, info in new_by_ip.items()))
    total_all = sum(len(e["times"]) for ip, e in _failed_logins.items()
                    if not protected_target(ip, config.get("rdp_allowed_ips", [])))
    if config.get("lockdown") and not lockdown_active() and total_all >= int(config.get("lockdown_limit", 30)):
        lockdown_start()
    rows = []
    for ip in list(new_by_ip)[:3]:
        if not protected_target(ip, config.get("rdp_allowed_ips", [])):
            rows.append([(f"Review {ip}", f"cmd:/block {ip}")])
    rows.append([("Review lockdown", "cmd:/lockdown"), ("Recent logins", "cmd:/logins")])
    if config.get("failed_login_alerts", True) or any(name.casefold() in traps for info in new_by_ip.values() for name in info["users"]):
        send_buttons("\n".join(lines), rows)


# ----------------------------- Whitelist and auto lock -----------------------------

PS_SUCCESS_LOGON = success_query(14)


def learn_successful_ips():
    global _learn_alerts_ready
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", PS_SUCCESS_LOGON],
                                capture_output=True, timeout=120, creationflags=NO_WINDOW)
        if result.returncode != 0:
            raise RuntimeError("Security login query failed; learned history was preserved")
    except Exception as exc:
        print(f"[learn] {exc}")
        return None
    learned = dict(config.get("learned_ips") or {})
    now = time.time()
    new_ips = set()
    for line in _decode_out(result.stdout).splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3:
            continue
        ip = usable_source(parts[0])
        stamp = event_timestamp(parts[2])
        if not ip or stamp is None or not now - 14*86400 <= stamp <= now + 60:
            continue
        if ip not in learned:
            new_ips.add(ip)
        previous = learned.get(ip)
        previous_time = previous.get("t", 0) if isinstance(previous, dict) else 0
        if not isinstance(previous_time, (int, float)):
            previous_time = 0
        if stamp >= previous_time:
            learned[ip] = {"t": stamp, "u": parts[1]}
    learned = {ip: item for ip, item in learned.items() if isinstance(item, dict)
               and isinstance(item.get("t"), (float, int)) and now - 14*86400 <= item["t"] <= now+60}
    config["learned_ips"] = learned
    save_config()
    if new_ips and _learn_alerts_ready and config.get("new_ip_alerts", True):
        rows = [f"? {esc(ip)} | {esc(learned[ip]['u'])} | "
                + datetime.fromtimestamp(learned[ip]['t'], tz=timezone.utc).isoformat()
                for ip in sorted(new_ips) if ip in learned]
        send_buttons("<b>New successful RDP source observed</b>\nSource | account | Windows event time (UTC)\n"
                     + "\n".join(rows[:10]),
                     [[("Review recent logins", "cmd:/logins"), ("Review panic", "cmd:/panic")]])
    _learn_alerts_ready = True
    return len(new_ips)


def lockdown_active():
    """Is the auto lock working now?"""
    try:
        return time.time() < float(config.get("lockdown_until", 0) or 0)
    except Exception:
        return False


def lockdown_ips():
    """IP Allowed while locked: Manual approval, educated only when you choose it.
    Current contact does not mean trust: An attacker may be online the moment the lock is initiated."""
    ips = []
    sources = (
        [str(i) for i in (config.get("rdp_allowed_ips") or [])],
        [ip for ip, v in (config.get("learned_ips") or {}).items()
         if config.get("learn_for_lockdown", False)
         and time.time() - (v["t"] if isinstance(v, dict) else v) <= 14 * 86400],
    )
    for src in sources:
        for ip in src:
            if _valid_ip(ip) and ip not in ips:
                ips.append(ip)
    return ips


def lockdown_start(minutes=None, manual=False):
    """fall short RDP Whitelist immediately - Manual or automatic when a wave breaks"""
    global _pre_lockdown_allow_active
    minutes = int(minutes or config.get("lockdown_minutes", 60))
    learned_new = learn_successful_ips()
    ips = lockdown_ips()
    if not ips:
        send_message("[X] I couldn’t operate the lock: There is nothing in it IP Reliable, known\n"
                     "Add your device manually first: /whitelist add IP-Your device\n"
                     "(Also check administrator permissions for automatic learning to work)")
        return False
    _pre_lockdown_allow_active = bool(config.get("rdp_allow_active"))
    # We save the state before locking in the settings (It was only in memory — Restart
    # She was forgetting her, as release cancels your permanent confinement to him)
    config["rdp_allow_pre_active"] = _pre_lockdown_allow_active
    save_config()
    if not apply_rdp_allow(ips):
        send_message("[X] Failed to apply lock (Check administrator permissions)")
        return False
    config["lockdown_until"] = time.time() + minutes * 60
    config["rdp_allow_active"] = True
    save_config()
    audit_record("Safety lock: " + ("Manual" if manual else "Auto")
                 + f" - {len(ips)} IP Allowed for a period of time {minutes} Minute")
    send_buttons(
        rtl(f"<b>The lock worked {'(Manual)' if manual else '(Automatically - Breakthrough wave)'}</b>") + "\n"
        + rtl(f"RDP Now limited to {len(ips)} IP Reliable for duration {format_duration(minutes * 60)}") + "\n"
        + rtl(f"Learn {learned_new or 0} IP New from successful logins") + "\n"
        + rtl("During lock: Yes IP A new person tries to enter and is banned on the first attempt"),
        [[("Whitelist", "run:/whitelist"),
          ("Release early", "run:/lockdown release")]])
    return True


def lockdown_release(auto=False):
    """End the lock and revert the pre-lock firewall rules
    - We return the actual state before locking: If the restriction was not activated, we will not activate it
      (It was applying permission rules even if they were not enabled before the lock)"""
    global _pre_lockdown_allow_active
    manual_ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
    was_active = bool(config.get("rdp_allow_pre_active",
                                 _pre_lockdown_allow_active))
    if was_active and not manual_ips:
        send_message("[X] Lockdown release refused: the previous allow-list is empty. Review /rdpallow.")
        return False
    if not apply_rdp_allow(manual_ips if was_active else []):
        send_message("[X] Lockdown release failed; recorded lockdown state retained. Review /firewall before retrying.")
        return False
    config["rdp_allow_active"] = was_active
    config["lockdown_until"] = 0
    config["rdp_allow_pre_active"] = False
    _pre_lockdown_allow_active = None
    save_config()
    audit_record("Security lock expired" + (" (Auto)" if auto else " (Manual)"))
    send_message((" <b>The lock ended automatically</b> - " if auto else " <b>I lifted the lock</b> - ")
                 + "The firewall is back to before the lock")
    return True


def ps_ok(ps, timeout=90):
    """Executes an order PowerShell Whether it was successful or not"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


# ----------------------------- Monitor account management events -----------------------------

PS_ACCOUNT_EVENTS = account_query()


ACCT_EVENT_INFO = {
    "4720": ("", "A new account has been created", "Account created"),
    "4722": ("", "A disabled account has been activated", "Account enabled"),
    "4724": ("", "Account password has been zeroed", "Password reset"),
    "4725": ("", "Account has been disabled", "Account disabled"),
    "4726": ("", "Account deleted", "Account deleted"),
    "4728": ("", "Added a member to a security group", "Member added to global group"),
    "4732": ("", "A member has been added to a local group", "Member added to local group"),
}


def check_account_events():
    """Monitors account changes outside the tool (From Windows itself): Create/Delete/Disable/
    Traffic whistle/Add to supervisors — The malicious back account is exposed immediately"""
    if not _check_start("account_events"):
        return
    try:
        _check_account_events_impl()
    finally:
        _check_end("account_events")


def _check_account_events_impl():
    global _seen_acct, _acct_baseline
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            PS_ACCOUNT_EVENTS],
                           capture_output=True, timeout=90, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Security account query failed; baseline preserved")
    except Exception as e:
        print(f"[acct-events] error: {e}")
        return
    rows = []
    for ln in _decode_out(r.stdout).splitlines():
        parts = ln.strip().split("|")
        if len(parts) != 7:
            continue
        rows.append(parts)
    if not _acct_baseline:
        _acct_baseline = True
        _seen_acct = {"|".join(row): True for row in rows}
        return
    new = []
    for eid, member, group, subj, ts, record, sid in rows:
        key = "|".join((eid, member, group, subj, ts, record, sid))
        if key not in _seen_acct:
            _seen_acct[key] = True
            new.append((eid, member, group, subj, ts, record, sid))
    if len(_seen_acct) > 2000:
        _seen_acct = dict(list(_seen_acct.items())[-1000:])
    if not new:
        return
    # Sensitive: any new account, or adding a member to an administrator group.
    # 4720 carries no group field, so creation is always treated as sensitive.
    sensitive = [n for n in new
                 if n[0] == "4720"
                 or (n[0] in ("4728", "4732")
                     and (n[6] == "S-1-5-32-544" or "admin" in (n[2] or "").lower()))]
    prefix = " <b>Change to device accounts!</b>" if sensitive \
        else " <b>Activity on accounts</b>"
    lines = [rtl(prefix)]
    for eid, member, group, subj, ts, record, sid in new:
        icon, ar, en = ACCT_EVENT_INFO.get(eid, ("•", "Account event", "Account event"))
        detail = f"{member}" + (f" → {group}" if group != "-" else "")
        lines.append(rtl(f"{icon} {ar} / {en}\n"
                         f"    <b>{esc(detail)}</b> — By {esc(subj)} — {esc(ts)} UTC — record {esc(record)}"))
    if sensitive:
        lines.append(rtl("[WARN] If you weren’t the one who did it — Review the list of buttons or think of PANIC"))
    audit_record("Accounts events: "
                 + "; ".join(f"#{e}:{m}" for e, m, _g, _s, _t, _r, _sid in new[:5]))
    if sensitive:
        send_buttons("\n".join(lines),
                     [[("List users", "run:/listusers"),
                       ("Logins", "run:/logins")],
                      [("PANIC - close RDP", "run:/panic on confirm")]])
    else:
        send_buttons("\n".join(lines),
                     [[("List users", "run:/listusers")]])


def account_events_loop():
    """Periodic check of account management events (Every minute)"""
    while True:
        if config.get("account_watch", True):
            check_account_events()
        time.sleep(60)


def change_rdp_port(new_port):
    """Change port RDP Safely — Each step is conditional on the success of the one before it:
    registry ← Firewall ← Reset service ← Confirm listening on new
    - The old port is closed only after ensuring that the new port is actually listening
    - That is, failure = Automatic rollback of old port (He could have blocked all the outlets for you)"""
    old_port = int(config.get("rdp_port", 3389))
    res = {"reg": False, "fw": False, "old": None, "svc": None,
           "listen": False, "allow": None, "busy": False}

    reg_path = ("'HKLM:\\System\\CurrentControlSet\\Control\\Terminal "
                "Server\\WinStations\\RDP-Tcp'")

    # 0) The new port must be empty before anything else — Another program he listens to was
    #    It is read later as a listener RDP The change is considered successful and then the old one is closed to you!
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr \
                    and c.laddr.port == new_port:
                res["busy"] = True
                return res
    except Exception:
        pass

    # 1) Registry first — If we fail, we don’t touch anything at all
    if not ps_ok(f"Set-ItemProperty -Path {reg_path} "
                 f"-Name PortNumber -Value {new_port} -Type DWord -ErrorAction Stop"):
        return res
    res["reg"] = True

    # 2) Open the new port in the firewall — If it fails, return the registry
    if not ps_ok(f"New-NetFirewallRule -DisplayName 'RDPMonitor RDP {new_port}' "
                 f"-Direction Inbound -LocalPort {new_port} -Protocol TCP "
                 "-Action Allow -ErrorAction Stop", timeout=60):
        ps_ok(f"Set-ItemProperty -Path {reg_path} "
              f"-Name PortNumber -Value {old_port} -Type DWord -ErrorAction Stop")
        return res
    res["fw"] = True

    # 3) Restart the service to listen on the new one
    res["svc"] = ps_ok("Restart-Service TermService -Force -ErrorAction Stop",
                       timeout=90)

    # 4) Wait for a listener on the new port — And it must be him PID Service RDP Herself
    #    (A listener of a strange program on the outlet does not consider it a success)
    rsvc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Service -Filter \"Name='TermService'\").ProcessId"],
        capture_output=True, timeout=60, creationflags=NO_WINDOW)
    try:
        term_pid = int(_decode_out(rsvc.stdout).strip() or 0)
    except ValueError:
        term_pid = 0
    listen_pid = None
    for _ in range(15):
        time.sleep(2)
        try:
            for c in psutil.net_connections(kind="tcp"):
                if c.status == psutil.CONN_LISTEN and c.laddr \
                        and c.laddr.port == new_port:
                    listen_pid = c.pid
                    break
        except Exception:
            pass
        if listen_pid is not None:
            break
    if term_pid and listen_pid == term_pid:
        res["listen"] = True
    elif listen_pid and not term_pid:
        # We couldn’t read PID Service — We accept svchost As a regression indicator only
        try:
            res["listen"] = \
                psutil.Process(listen_pid).name().lower() == "svchost.exe"
        except Exception:
            res["listen"] = False

    if not res["listen"]:
        print(f"[rdpport] listener check failed "
              f"(listen_pid={listen_pid}, termsvc_pid={term_pid}) - rolling back")
        ps_ok(f"Set-ItemProperty -Path {reg_path} "
              f"-Name PortNumber -Value {old_port} -Type DWord -ErrorAction Stop")
        ps_ok("Restart-Service TermService -Force -ErrorAction Stop", timeout=90)
        # Remove the allow rule for the port we just tried, otherwise it stays
        # open to the world even though the change was rolled back.
        _netsh(["advfirewall", "firewall", "delete", "rule",
                f"name=RDPMonitor RDP {new_port}"])
        res["fw"] = False
        return res

    # 5) Only now — After confirming the new — Close the old port
    if old_port != new_port:
        ps_ok("Disable-NetFirewallRule -DisplayGroup 'Remote Desktop' "
              "-ErrorAction SilentlyContinue", timeout=60)
        ps_ok("Disable-NetFirewallRule -DisplayGroup 'Remote desktop' "
              "-ErrorAction SilentlyContinue", timeout=60)
        _netsh(["advfirewall", "firewall", "delete", "rule",
                "name=RDPMonitor Old RDP Port Block"])
        ok, _err = _netsh(["advfirewall", "firewall", "add", "rule",
                           "name=RDPMonitor Old RDP Port Block", "dir=in",
                           "action=block", "protocol=TCP",
                           f"localport={old_port}"])
        res["old"] = ok

    # 6) Save the setting + Reapply the restriction IP On the new port
    #    (The restriction rules remained on the old port, so the new one remained open to the world)
    config["rdp_port"] = new_port
    save_config()
    if config.get("rdp_allow_active") or lockdown_active():
        # During lock: Manual, learned only when activated learn_for_lockdown
        # (The application reset was manual read only — If the lock depends on the learners
        #  The new port remains open to the world and the settings say "Forbidden"!)
        ips = lockdown_ips() if lockdown_active() \
            else [str(i) for i in (config.get("rdp_allowed_ips") or [])]
        if ips:
            res["allow"] = apply_rdp_allow(ips)
    return res


RDP_ALLOW_RULE = "RDPMonitor RDP Allow List"      # legacy v4.3 name
RDP_ALLOW_TCP_RULE = "RDPMonitor RDP Allow List TCP"
RDP_ALLOW_UDP_RULE = "RDPMonitor RDP Allow List UDP"
RDP_STAGE_TCP_RULE = "RDPMonitor RDP Allow Staging TCP"
RDP_STAGE_UDP_RULE = "RDPMonitor RDP Allow Staging UDP"
RDP_BLOCK_RULE = "RDPMonitor RDP Block Others"   # Old name - Cleans up upon reapplication
_allow_fail_info = ""                            # Another reason for the failure of the inventory (For messages)


def _ps_quote(value):
    """PowerShell single-quoted literal content."""
    return str(value).replace("'", "''")


def _scan_broad_rules(port, trusted):
    """He comes back IDs Rules that may allow movement RDP Off the list, without modifying the system.

    Rules TermService Andsvchost Prepare rules RDP Actual and not excluded. Restrictive rules
    With service/Other program do not apply to TermService, so it is left and its name appears for review.
    Editing is done later rule by rule in order to keep a record rollback Before moving on to the next.
    """
    ps = (
        "$ErrorActionPreference='Stop'; $port='" + str(port) + "'; "
        "$mine=@('" + RDP_ALLOW_RULE + "','" + RDP_ALLOW_TCP_RULE +
        "','" + RDP_ALLOW_UDP_RULE + "','" + RDP_STAGE_TCP_RULE +
        "','" + RDP_STAGE_UDP_RULE + "'); "
        "$trust=@(" + ",".join(f"'{i}'" for i in trusted) + "); "
        "$out=@(); $warn=@(); "
        "Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow "
        "-ErrorAction Stop | "
        "Where-Object { $mine -notcontains $_.DisplayName } | ForEach-Object { "
        "$pf = $_ | Get-NetFirewallPortFilter -ErrorAction Stop; "
        "if ($pf) { $hit = $false; $protOk = $false; "
        "if (-not $pf.Protocol -or $pf.Protocol -eq 'Any') { $protOk = $true } "
        "elseif (@('TCP','UDP','6','17') -contains [string]$pf.Protocol) { $protOk = $true }; "
        "if ($protOk) { "
        "if (@($pf.LocalPort) -contains $port) { $hit = $true } "
        "elseif (@($pf.LocalPort) -contains 'Any') { $hit = $true } "
        "else { foreach ($lp in @($pf.LocalPort)) { "
        "if ($lp -match '^(\\d+)-(\\d+)$') { "
        "if ($port -ge [int]$Matches[1] -and $port -le [int]$Matches[2]) "
        "{ $hit = $true } } } } }; "
        "if ($hit) { "
        "$scoped = $false; $rdpScoped = $false; "
        "$apf = $_ | Get-NetFirewallApplicationFilter -ErrorAction Stop; "
        "if ($apf -and $apf.Program -and $apf.Program -ne 'Any') { "
        "$scoped = $true; if ($apf.Program -match '(?i)(\\\\svchost\\.exe$|^System$)') "
        "{ $rdpScoped = $true } }; "
        "$svf = $_ | Get-NetFirewallServiceFilter -ErrorAction Stop; "
        "if ($svf -and $svf.Service -and $svf.Service -ne 'Any') { "
        "$scoped = $true; if ($svf.Service -eq 'TermService') { $rdpScoped = $true } }; "
        "if ($scoped -and -not $rdpScoped) { $warn += $_.DisplayName } else { "
        "$af = $_ | Get-NetFirewallAddressFilter -ErrorAction Stop; "
        "$broad = $false; "
        "if (-not $af) { $broad = $true } else { "
        "foreach ($ra in @($af.RemoteAddress)) { "
        "if ($ra -and ($trust -notcontains $ra)) { $broad = $true } } }; "
        "if ($broad) { $out += $_.Name } } } } }; "
        "[ordered]@{disable=@($out);warnings=@($warn)} | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=240, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(_decode_out(r.stderr).strip() or "PowerShell failed")
        data = json.loads(_decode_out(r.stdout).strip())
        ids = data.get("disable") or []
        warns = data.get("warnings") or []
        if isinstance(ids, str):
            ids = [ids]
        if isinstance(warns, str):
            warns = [warns]
        return [str(x) for x in ids], [str(x) for x in warns]
    except Exception as e:
        print(f"[rdpallow] scan error: {e}")
        return None, None


def _set_rule_enabled(rule_id, enabled):
    rid = _ps_quote(rule_id)
    verb = "Enable" if enabled else "Disable"
    expected = "True" if enabled else "False"
    return ps_ok(
        f"${{ErrorActionPreference}}='Stop'; {verb}-NetFirewallRule -Name '{rid}'; "
        f"$r=Get-NetFirewallRule -Name '{rid}'; "
        f"if ($r.Enabled.ToString() -ne '{expected}') {{ exit 1 }}", timeout=60)


def _enable_saved_rule(rule_id):
    """Repeats rule ID New, supported DisplayName Store from older versions."""
    rid = _ps_quote(rule_id)
    return ps_ok(
        "$ErrorActionPreference='Stop'; "
        f"$r=Get-NetFirewallRule -Name '{rid}' -ErrorAction SilentlyContinue; "
        f"if (-not $r) {{$r=Get-NetFirewallRule -DisplayName '{rid}' "
        "-ErrorAction SilentlyContinue}; if (-not $r) {exit 1}; "
        "$r | Enable-NetFirewallRule -ErrorAction Stop", timeout=60)


def _delete_allow_rules(port):
    names = (RDP_ALLOW_RULE, RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE,
             RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE, RDP_BLOCK_RULE,
             f"RDPMonitor RDP {port}")
    for name in names:
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name={name}"])


def _delete_trusted_rules():
    for name in (RDP_ALLOW_RULE, RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE,
                 RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE, RDP_BLOCK_RULE):
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name={name}"])


def _create_general_rdp_rule(port):
    _netsh(["advfirewall", "firewall", "delete", "rule",
            f"name=RDPMonitor RDP {port}"])
    ok, err = _netsh(["advfirewall", "firewall", "add", "rule",
                      f"name=RDPMonitor RDP {port}", "dir=in", "action=allow",
                      "protocol=TCP", f"localport={port}"])
    return ok, err


def _create_trusted_rules(port, ips):
    # Create staging Firstly, while the old rules are still effective: There is no access gap.
    for stale in (RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE):
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name={stale}"])
    created = []
    for name, protocol in ((RDP_STAGE_TCP_RULE, "TCP"),
                           (RDP_STAGE_UDP_RULE, "UDP")):
        ok, err = _netsh(["advfirewall", "firewall", "add", "rule",
                          f"name={name}", "dir=in", "action=allow",
                          f"protocol={protocol}", f"localport={port}",
                          "remoteip=" + ",".join(ips)])
        if not ok:
            for made in created:
                _netsh(["advfirewall", "firewall", "delete", "rule",
                        f"name={made}"])
            return False, err
        created.append(name)
    for old in (RDP_ALLOW_RULE, RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE,
                RDP_BLOCK_RULE):
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name={old}"])
    for staging, final in ((RDP_STAGE_TCP_RULE, RDP_ALLOW_TCP_RULE),
                           (RDP_STAGE_UDP_RULE, RDP_ALLOW_UDP_RULE)):
        if not ps_ok(f"Set-NetFirewallRule -DisplayName '{staging}' "
                     f"-NewDisplayName '{final}' -ErrorAction Stop", timeout=60):
            for name in (RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE,
                         RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE):
                _netsh(["advfirewall", "firewall", "delete", "rule",
                        f"name={name}"])
            return False, "The trusted allow rule name could not be installed"
    return True, ""


def _rollback_rdp_allow(port, disabled_now, changed_profiles):
    saved = list(config.get("rdpallow_disabled_rules") or [])
    for rid in disabled_now:
        if _enable_saved_rule(rid) and rid in saved:
            saved.remove(rid)
    config["rdpallow_disabled_rules"] = saved
    pre = dict(config.get("pre_default_inbound") or {})
    for prof in changed_profiles:
        original = pre.get(prof, "Allow")
        if ps_ok(f"Set-NetFirewallProfile -Profile '{_ps_quote(prof)}' "
                 f"-DefaultInboundAction {original} -ErrorAction Stop", timeout=60):
            pre.pop(prof, None)
    config["pre_default_inbound"] = pre
    _delete_allow_rules(port)
    fallback_ok, _ = _create_general_rdp_rule(port)
    save_config()
    return fallback_ok


def apply_rdp_allow(ips):
    """Application transactional To limit RDP With TCP AndUDP And he scored rollback Permanent."""
    global _allow_fail_info
    _allow_fail_info = ""
    if any(canonical_ip(ip) is None for ip in ips):
        _allow_fail_info = "invalid allow-list address; firewall unchanged"
        return False
    ips = list(dict.fromkeys(canonical_ip(ip) for ip in ips))
    port = int(config.get("rdp_port", 3389))
    if not ips:
        _delete_allow_rules(port)
        counts = [_firewall_rule_count(name) for name in
                  (RDP_ALLOW_RULE, RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE,
                   RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE, RDP_BLOCK_RULE)]
        if any(count != 0 for count in counts):
            _allow_fail_info = "allow-list rule removal could not be verified"
            return False
        ok, _ = _create_general_rdp_rule(port)
        all_ok = ok
        remaining = []
        for rname in (config.get("rdpallow_disabled_rules") or []):
            if not _enable_saved_rule(rname):
                remaining.append(rname)
                all_ok = False
        config["rdpallow_disabled_rules"] = remaining
        pre_remaining = {}
        for prof, act in (config.get("pre_default_inbound") or {}).items():
            if not ps_ok(f"Set-NetFirewallProfile -Profile '{_ps_quote(prof)}' "
                         f"-DefaultInboundAction {act} -ErrorAction Stop", timeout=60):
                pre_remaining[prof] = act
                all_ok = False
        config["pre_default_inbound"] = pre_remaining
        save_config()
        return all_ok

    # staging Created before old rules are deleted; We do not create an access gap during the update.
    ok, err = _create_trusted_rules(port, ips)
    if not ok:
        print(f"[rdpallow] allow rule error: {err}")
        _allow_fail_info = err
        # Staging failed before the old rules were removed, so the previous
        # state is intact. Never open RDP to the world as a fallback here.
        return False
    _netsh(["advfirewall", "firewall", "delete", "rule",
            f"name=RDPMonitor RDP {port}"])

    candidates, scoped_warns = _scan_broad_rules(port, trusted=ips)
    if candidates is None:
        _allow_fail_info = "Broad bases scanning failed (PowerShell)"
        _rollback_rdp_allow(port, [], [])
        return False

    disabled_now = []
    saved = list(config.get("rdpallow_disabled_rules") or [])
    for rid in candidates:
        if not _set_rule_enabled(rid, False):
            _allow_fail_info = "Unable to disable broad permission rule: " + rid
            _rollback_rdp_allow(port, disabled_now, [])
            return False
        disabled_now.append(rid)
        if rid not in saved:
            saved.append(rid)
        config["rdpallow_disabled_rules"] = saved
        save_config()  # Register rollback After each change, not after the payment has finished

    leftover, _w = _scan_broad_rules(port, trusted=ips)
    if leftover is None:
        leftover = ["<verification failed>"]
    if leftover:
        print(f"[rdpallow] verification failed, leftovers: {leftover}")
        _allow_fail_info = "Broad rules of tolerance have not been broken: " + ", ".join(leftover[:5])
        _rollback_rdp_allow(port, disabled_now, [])
        return False

    if scoped_warns:
        send_message(rtl("<b>Accuracy alert:</b> Allow rules are restricted to a specific program "
                         "Or another service on the same port has not changed: "
                         + esc(", ".join(scoped_warns[:5]))
                         + " — Review it manually: /firewall"))

    ps_pol = ("$o=@(); Get-NetFirewallProfile | ForEach-Object { "
              "if ($_.DefaultInboundAction -eq 'Allow') { "
              "$o += ($_.Name) } }; Write-Output ($o -join '|')")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_pol],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(_decode_out(r.stderr).strip())
        allow_profiles = [x for x in _decode_out(r.stdout).strip().split("|") if x]
    except Exception as e:
        _allow_fail_info = "Unable to read firewall policy: " + str(e)[:120]
        _rollback_rdp_allow(port, disabled_now, [])
        return False
    changed_profiles = []
    if allow_profiles:
        pre = dict(config.get("pre_default_inbound") or {})
        for prof in allow_profiles:
            pre[prof] = "Allow"
            config["pre_default_inbound"] = pre
            save_config()
            if not ps_ok(f"Set-NetFirewallProfile -Profile '{_ps_quote(prof)}' "
                         "-DefaultInboundAction Block -ErrorAction Stop", timeout=60):
                _allow_fail_info = "Unable to convert inbound policy to Block: " + prof
                _rollback_rdp_allow(port, disabled_now, changed_profiles)
                return False
            changed_profiles.append(prof)
        send_message(rtl("<b>Important note:</b> The default inbound policy was "
                         "Allow On: " + ", ".join(allow_profiles) + " — I turned it over "
                         "Block Otherwise, the limitation has no meaning. At /rdpallow clear You come back "
                         "As it was. Check your ports: /firewall"))
    save_config()
    return True


def _confirm_rdp_allow(expected_ips, expected_lockdown):
    """Apply only the allow-list shown on the confirmation prompt."""
    if (list(config.get("rdp_allowed_ips") or []) != expected_ips
            or lockdown_active() != expected_lockdown):
        send_message("[X] The RDP allow-list changed. Review it and request /rdpallow apply again.")
        return
    handle_command("/rdpallow apply confirm")


LOG_LEVELS = {"error": (1, 2), "warning": (3,), "all": (1, 2, 3)}


def fetch_system_logs(hours, levels, limit=30):
    """Reads a log System Who Event Viewer: He comes back (Total number or None, lines of events)"""
    lvl = ",".join(str(x) for x in levels)
    ps = (
        "$st=(Get-Date).AddHours(-" + str(hours) + "); "
        "$e=@(Get-WinEvent -FilterHashtable @{LogName='System'; "
        "Level=@(" + lvl + "); StartTime=$st} -MaxEvents 1000 "
        "-ErrorAction SilentlyContinue); "
        "Write-Output ('TOTAL:' + $e.Count); "
        "$e | Select-Object -First " + str(limit) + " | ForEach-Object { "
        "$msg = $_.Message; if (-not $msg) { $msg = '(no message)' }; "
        "$msg = $msg -replace '\\r?\\n', ' '; "
        "if ($msg.Length -gt 90) { $msg = $msg.Substring(0, 90) }; "
        "Write-Output ($_.TimeCreated.ToString('MM-dd HH:mm') + ' | L' "
        "+ $_.Level + ' | ' + $_.ProviderName + ' | #' + $_.Id + ' | ' + $msg) }"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except Exception:
        return None, []
    total = None
    lines = []
    for ln in _decode_out(r.stdout).splitlines():
        ln = ln.strip()
        if ln.startswith("TOTAL:"):
            try:
                total = int(ln.split(":", 1)[1])
            except ValueError:
                total = 0
        elif ln:
            lines.append(ln)
    return total, lines


def get_firewall_report():
    """Read effective RDP policy without changing rules or probing external hosts."""
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", COLLECT_PS],
                                capture_output=True, timeout=120, creationflags=NO_WINDOW)
        if result.returncode != 0:
            raise RuntimeError("effective policy query failed")
        return analyze_rdp_policy(json.loads(_decode_out(result.stdout)))
    except Exception:
        return analyze_rdp_policy({})


def format_netstat():
    """Active communications + Open ports with the name of the owner program"""
    try:
        conns = psutil.net_connections(kind="tcp")
    except Exception as e:
        return f"[X] I couldn’t read the communications: {e}"

    def pname(pid):
        if not pid:
            return "?"
        try:
            return psutil.Process(pid).name()
        except Exception:
            return "?"

    est = [c for c in conns if c.status == psutil.CONN_ESTABLISHED and c.raddr]
    lst = {}
    for c in conns:
        if c.status == psutil.CONN_LISTEN and c.laddr:
            key = (c.laddr.ip, c.laddr.port)
            known = lst.get(key, "?")
            cur = pname(c.pid)
            # We keep the known name - The unknown name does not match the one before it
            if known == "?" and cur != "?":
                lst[key] = cur
            elif key not in lst:
                lst[key] = cur

    lines = [" <b>Active communications (ESTABLISHED)</b>", "<pre>"]
    if est:
        for c in est[:25]:
            lines.append(esc(f"{c.laddr.ip}:{c.laddr.port} -> "
                             f"{c.raddr.ip}:{c.raddr.port} [{pname(c.pid)}]"))
        if len(est) > 25:
            lines.append(esc(f"... And {len(est) - 25} Another connection"))
    else:
        lines.append("There is no")
    lines.append("</pre>\n <b>Open ports (LISTEN)</b>\n<pre>")
    open_count = 0
    for (ip, port), name in sorted(lst.items(), key=lambda x: x[0][1]):
        if open_count >= 25:
            lines.append(esc(f"... And {len(lst) - open_count} Another port"))
            break
        scope = "Local only" if ip.startswith("127.") else "Open on the network [WARN]"
        lines.append(esc(f"{ip}:{port} [{name}] ") + scope)
        open_count += 1
    lines.append("</pre>")
    return "\n".join(lines)


def rename_local_user(old, new):
    """Rename a local account via Rename-LocalUser"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Rename-LocalUser -Name '{old}' -NewName '{new}' -ErrorAction Stop"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW)
        err = _decode_out(r.stderr).strip()
        return r.returncode == 0, err
    except Exception as e:
        return False, str(e)


# ----------------------------- Diagnostics of system logs -----------------------------

EVENT_EXPLANATIONS = {
    # (Source in small print, Event number): (Icon, The reason for the event and the proposed action)
    ("kernel-power", 41): ("", "Unexpected shutdown: The device turned off or froze without turning it off properly "
                                 "(Loss of power, complete freeze, or power outage)"),
    ("eventlog", 6008): ("", "The previous suspension was unexpected: The system subsequently records the extinguishing process"),
    ("bugcheck", 1001): ("", "Blue screen BSOD: The system has completely collapsed - See files Minidump With /dumps"),
    ("disk", 7): ("", "A read operation failed/Write to disk: Possibility of bad sectors"),
    ("disk", 11): ("", "The disk definition encountered an error: The disk may be failing - Take a backup"),
    ("disk", 153): ("", "Input error/Eject to disk: Possible bad sectors - chkdsk And a backup copy immediately"),
    ("ntfs", 55): ("", "File system corruption NTFS: Run chkdsk /f On the disk mentioned in the message"),
    ("whea-logger", 18): ("", "Strict hardware error (WHEA): Processor problem/Ram/Motherboard - Monitor the temperature and secure the parts"),
    ("whea-logger", 19): ("", "Corrected hardware error (WHEA): An early sign of a hardware problem - Watch for repetition"),
    ("whea-logger", 20): ("", "Hardware error (WHEA): Processor or memory related crash"),
    ("service control manager", 7031): ("", "Service collapsed: It ended suddenly and then tried again - Her name is in the letter"),
    ("service control manager", 7034): ("", "Service ended suddenly: If the same service is repeated, it is unstable"),
    ("application error", 1000): ("", "Program collapse: Unhandled exception Close the application - His name is in the message"),
    ("application error", 1002): ("", "The program freezes and stops responding (Hang) - Repeating the same program means a problem with it"),
    (".net runtime", 1026): ("", "Application crash .NET: Unhandled exception within the application"),
    ("application error", 1018): ("", "Application crash .NET"),
}

# Template PowerShell To withdraw critical events/Errors from my log System AndApplication
# {M} = time window in minutes, {LV} = Event levels (1 = Just embarrassed, 1,2 = Critical + Error)
PS_DIAG_EVENTS = (
    "$st=(Get-Date).AddMinutes(-{M}); "
    "foreach ($log in @('System','Application')) { "
    "$e=Get-WinEvent -FilterHashtable @{LogName=$log; Level=@({LV}); StartTime=$st} "
    "-MaxEvents 500 -ErrorAction SilentlyContinue; "
    "foreach ($x in $e) { "
    "$m=$x.Message; if (-not $m) { $m='(no message)' }; "
    "$m=($m -replace '\\r?\\n', ' ') -replace '\\|', '/'; "
    "if ($m.Length -gt 120) { $m=$m.Substring(0,120) }; "
    "Write-Output ($log+'|'+$x.ProviderName+'|'+$x.Id+'|'"
    "+$x.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')+'|'+$m) } }"
)


def fetch_diagnosis_events(minutes, levels="1,2"):
    """Collects system events: He comes back [(Record, source, number, time, message)] Or None When you fail"""
    ps = PS_DIAG_EVENTS.replace("{M}", str(minutes)).replace("{LV}", levels)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=180, creationflags=NO_WINDOW)
    except Exception as e:
        print(f"[diagnosis] error: {e}")
        return None
    events = []
    for ln in _decode_out(r.stdout).splitlines():
        parts = ln.strip().split("|", 4)
        if len(parts) == 5 and parts[2].isdigit():
            events.append((parts[0], parts[1], int(parts[2]), parts[3], parts[4]))
    return events


def explain_event(provider, eid):
    """Explains the cause of an event from the dictionary: He comes back (Icon, explanation)"""
    p = (provider or "").lower().replace("microsoft-windows-", "")
    hit = EVENT_EXPLANATIONS.get((p, eid))
    if hit:
        return hit
    # Matched with family: Source names vary between versions of Windows, but the family is fixed
    if eid == 1001 or "bugcheck" in p:
        return ("", "Blue screen BSOD: The system collapsed - See files Minidump With /dumps")
    if "whea" in p:
        return ("", "Hardware error (WHEA): Indicator of a processor problem/Ram/Motherboard")
    if p in ("disk", "ntfs", "volmgr", "volsnap", "storahci", "stornvme") \
            or "disk" in p:
        return ("", "Disk problem/Storage: Review the text of the message and think about it chkdsk And a backup copy")
    if "kernel-power" in p:
        return ("", "Energy problem/Unexpected shutdown")
    if "service control" in p:
        return ("", "System service problem: The name of the service in the message")
    return ("", f"Error from source {provider} - See the text of the message")


def _crash_categories(group_keys):
    """Categorizes a group of events (Source, number) into categories of general problems arranged by priority"""
    cats = set()
    for prov, eid in group_keys:
        p = (prov or "").lower().replace("microsoft-windows-", "")
        if eid == 1001 or "bugcheck" in p:
            cats.add("bsod")
        elif eid == 41 or "kernel-power" in p or (p == "eventlog" and eid == 6008):
            cats.add("power")
        elif p in ("disk", "ntfs", "volmgr", "storahci", "stornvme") or "disk" in p:
            cats.add("disk")
        elif "whea" in p:
            cats.add("hw")
        elif "service control" in p:
            cats.add("svc")
        else:
            cats.add("app")
    ADVICE = {
        "bsod": ("", "Blue screen recorded - Top priority: Export files with /dumps And check the reason"),
        "power": ("", "Unexpected shutdown - Check power and freeze before anything"),
        "disk": ("", "Disk errors - Second priority: Back up immediately then chkdsk"),
        "hw": ("", "Hardware errors WHEA - Monitor temperature, install parts, and update drivers"),
        "svc": ("", "System services crash - Select the service from the event details above"),
        "app": ("", "Programs collapse - Annoying but usually does not threaten system stability"),
    }
    res = []
    for c in ("bsod", "power", "disk", "hw", "svc", "app"):
        if c in cats:
            res.append(ADVICE[c])
    return res


def diagnose_report(hours=24):
    """Diagnostic report: Collects errors, explains the reason for each one, and gives a summary of priorities"""
    events = fetch_diagnosis_events(hours * 60)
    if events is None:
        return "[X] Failed to read logs (Try from a manager account)"
    if not events:
        return (f"[OK] <b>Diagnosis</b> - Another {hours} hours\n"
                "There are no critical events or errors. The system is clean ")
    groups = {}
    for log, prov, eid, ts, msg in events:
        g = groups.setdefault((prov, eid),
                              {"n": 0, "last": ts, "msg": msg, "log": log})
        g["n"] += 1
        g["last"] = ts
    lines = [rtl(f"<b>Error diagnosis</b> — Another {hours} hours ({len(events)} It happened)"), ""]
    rows, reasons = [], []
    for (prov, eid), g in sorted(groups.items(),
                                 key=lambda kv: -kv[1]["n"])[:15]:
        icon, why = explain_event(prov, eid)
        rows.append(f"{prov[:30]} #{eid} x{g['n']}  {g['last']}")
        reasons.append((icon, why, prov, eid, g))
    lines.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    for icon, why, prov, eid, g in reasons[:8]:
        lines.append(rtl(f"{icon} <b>{esc(prov)}</b> #{eid} — {esc(why)}"))
    verdicts = _crash_categories(groups.keys())
    if verdicts:
        lines.append("")
        lines.append(rtl("━━ <b>Conclusion and priorities</b> ━━"))
        for icon, advice in verdicts:
            lines.append(rtl(f"{icon} {advice}"))
    return "\n".join(lines)


def logstats_report(days=7):
    """The components of the system that produce the most errors over a period"""
    events = fetch_diagnosis_events(days * 24 * 60)
    if events is None:
        return "[X] Failed to read logs (Try from a manager account)"
    if not events:
        return f" Another {days} days: There are no errors at all "
    counts = {}
    for _log, prov, eid, _ts, _msg in events:
        counts[(prov, eid)] = counts.get((prov, eid), 0) + 1
    lines = [rtl(f" <b>Components of problems</b> — Another {days} days ({len(events)} Error)"),
             "",
             "<pre>"]
    for (prov, eid), n in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
        icon, _why = explain_event(prov, eid)
        lines.append(esc(f"{icon} {prov[:32]} #{eid} x{n}"))
    lines.append("</pre>")
    return "\n".join(lines)


def logstats_summary(days=7, top=3):
    """Short version for scheduled reports - Returns text or empty text"""
    events = fetch_diagnosis_events(days * 24 * 60)
    if not events:
        return ""
    counts = {}
    for _log, prov, eid, _ts, _msg in events:
        counts[(prov, eid)] = counts.get((prov, eid), 0) + 1
    parts = [f"{prov} #{eid} ×{n}" for (prov, eid), n
             in sorted(counts.items(), key=lambda kv: -kv[1])[:top]]
    return " Most sources of errors this week: " + " · ".join(parts)


def check_critical_events():
    """Immediate alert of any critical event (Level 1) New in System and Applications logs
    - Interference gate: The scan may take longer than the scheduling cycle"""
    if not _check_start("critical_events"):
        return
    try:
        _check_critical_events_impl()
    finally:
        _check_end("critical_events")


def _check_critical_events_impl():
    global _seen_critical, _critical_baseline
    events = fetch_diagnosis_events(3, levels="1")
    if events is None:
        return
    def _ev_key(ev):
        # Include the full timestamp and a message slice so events that share a
        # provider/id are not suppressed across years or repeated incidents.
        return f"{ev[0]}|{ev[1]}|{ev[2]}|{ev[3]}|{ev[4][:60]}"
    if not _critical_baseline:
        _critical_baseline = True
        _seen_critical = {_ev_key(ev): True for ev in events}
        return
    new = []
    for ev in events:
        key = _ev_key(ev)
        if key not in _seen_critical:
            _seen_critical[key] = True
            new.append(ev)
    if len(_seen_critical) > 1000:
        # dict Listed in order: We grab the newest and effectively throw away the oldest (It was set In no order)
        _seen_critical = dict(list(_seen_critical.items())[-500:])
    if not new:
        return
    if len(new) > 5:
        # A flood of events: We summarize instead of flooding the chat
        send_buttons(f" You register {len(new)} A critical event occurred during the last minutes!\n"
                     "Press the button to analyze the full reason:",
                     [[("Diagnose now", "run:/diagnose")]])
        return
    lines = [rtl("<b>CRITICAL SYSTEM EVENT</b>")]
    for log, prov, eid, ts, msg in new:
        icon, why = explain_event(prov, eid)
        lines.append(rtl(f"\n{icon} <b>{esc(prov)}</b> #{eid} at {ts} ({log} log)"))
        lines.append(rtl(f"Likely cause: {esc(why)}"))
        lines.append(esc(msg[:120]))
    audit_record("Critical event: "
                 + "; ".join(f"{p} #{e}" for _l, p, e, _t, _m in new))
    send_buttons("\n".join(lines),
                 [[("Diagnose", "run:/diagnose"),
                   ("Crash dumps", "run:/dumps")]])


PS_SHUTDOWN_HISTORY = (
    "$st=(Get-Date).AddHours(-24); "
    "$e=Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$st} "
    "-MaxEvents 400 -ErrorAction SilentlyContinue | "
    "Where-Object { $_.Id -in @(41,6008,1001,1074) }; "
    "foreach ($x in $e) { "
    "$m=$x.Message; if (-not $m) { $m='' }; "
    "$m=($m -replace '\\r?\\n', ' ') -replace '\\|', '/'; "
    "if ($m.Length -gt 100) { $m=$m.Substring(0,100) }; "
    "Write-Output ($x.Id+'|'+$x.TimeCreated.ToString('MM-dd HH:mm')+'|'+$m) }"
)


def _crash_dumps(max_age_days=30):
    """Recent crash dump files: [(Path, size, modification time)]"""
    dumps = []
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    locations = [os.path.join(sysroot, "Minidump"),
                 os.path.join(sysroot, "MEMORY.DMP"),
                 os.path.join(sysroot, "LiveKernelReports")]
    cutoff = time.time() - max_age_days * 86400
    for loc in locations:
        if os.path.isfile(loc):
            try:
                st = os.stat(loc)
                if st.st_mtime >= cutoff:
                    dumps.append((loc, st.st_size, st.st_mtime))
            except OSError:
                pass
        elif os.path.isdir(loc):
            for f in os.listdir(loc):
                if not f.lower().endswith(".dmp"):
                    continue
                fp = os.path.join(loc, f)
                try:
                    st = os.stat(fp)
                    if st.st_mtime >= cutoff:
                        dumps.append((fp, st.st_size, st.st_mtime))
                except OSError:
                    pass
    return sorted(dumps, key=lambda d: -d[2])


def boot_report():
    """Startup report: Is the last fire extinguished properly? Blue screen? Dump files?"""
    if not config.get("startup_report", False):
        return
    unexpected, bsod, clean = [], [], []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            PS_SHUTDOWN_HISTORY],
                           capture_output=True, timeout=120, creationflags=NO_WINDOW)
        for ln in _decode_out(r.stdout).splitlines():
            parts = ln.split("|", 2)
            if len(parts) < 2 or not parts[0].strip().isdigit():
                continue
            eid, ts = parts[0].strip(), parts[1].strip()
            if eid in ("41", "6008"):
                unexpected.append(ts)
            elif eid == "1001":
                bsod.append(ts)
            elif eid == "1074":
                clean.append(parts[2][:80] if len(parts) > 2 else "")
    except Exception as e:
        print(f"[boot-report] error: {e}")
        return

    lines = ["<b>Startup report</b>"]
    if bsod:
        lines.append(f" Blue screen recorded: {', '.join(bsod[:3])} "
                     "- See the dump files below")
    elif unexpected:
        lines.append(f" The latest shutdown was unexpected (Register {unexpected[0]}) - "
                     "Loss of power or freezing")
    elif clean:
        lines.append(f"[OK] The last extinguishing was fine ({clean[0][:60]})")
    else:
        lines.append("[OK] There are no indicators of a blue screen or an unexpected shutdown during 24 hours")

    dumps = _crash_dumps()
    if dumps:
        lines.append("\n Recent crash dump files:")
        for path, size, mtime in dumps[:3]:
            when = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            lines.append(f"• {os.path.basename(path)} - {format_size(size)} - {when}")
        lines.append("Send /dumps To download and analyze the latest file")
    send_message("\n".join(lines))


def export_logs_job(scope="all"):
    """Export post errors 7 Days of my record System/Application To zip And send it to chat"""
    zip_path = None
    queued = False
    tmpdir = tempfile.mkdtemp(prefix="rdpm_logs_")
    try:
        ms = 7 * 24 * 3600 * 10000000  # 7 Days in units 100 ns (Language wevtutil)
        q = ("*[System[(Level=1 or Level=2) and "
             "TimeCreated[timediff(@SystemTime) <= %d]]]" % ms)
        logs = ["System", "Application"] if scope == "all" else [scope.capitalize()]
        files = []
        for log in logs:
            out = os.path.join(tmpdir, f"{log}_errors_7d.evtx")
            try:
                r = subprocess.run(["wevtutil", "epl", log, out, f"/q:{q}",
                                    "/ow:true"],
                                   capture_output=True, timeout=300, creationflags=NO_WINDOW)
                if r.returncode == 0 and os.path.exists(out):
                    files.append(out)
            except Exception as e:
                print(f"[export] {log} error: {e}")
        if not files:
            send_message("[X] Failed to export records (Try from a manager account)")
            return
        zip_path = os.path.join(tempfile.gettempdir(),
                                f"rdpm_logs_{int(time.time())}.zip")
        ps = ("Compress-Archive -Path '"
              + "','".join(files) + "' -DestinationPath '"
              + zip_path + "' -Force")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=180, creationflags=NO_WINDOW)
        if not os.path.exists(zip_path):
            send_message("[X] Compression of log files failed")
            return
        size = os.path.getsize(zip_path)
        if size > 45 * 1024 * 1024:
            send_message(f"[X] Export volume {format_size(size)} More than enough "
                         "Telegram 45MB - Try /exportlogs system")
            return
        queued = send_document(zip_path,
                               f" Error logs - Another 7 days ({format_size(size)})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        # Keep the archive when it was queued for retry; deleting it here would
        # make the queued resend fail with "file no longer exists".
        if zip_path and not queued:
            try:
                os.remove(zip_path)
            except OSError:
                pass


# ----------------------------- Reliability: Pulse, revival, monitoring RDP And the Internet -----------------------------

def check_keepalive():
    """Plays back programs recorded in /keepalive If you close + Alert"""
    for w in (config.get("keepalive") or []):
        name = (w.get("name") or "").lower()
        if not name:
            continue
        found = False
        for p in psutil.process_iter(['name']):
            try:
                if (p.info.get('name') or '').lower() == name:
                    found = True
                    break
            except Exception:
                pass
        if found:
            continue
        # Deadline 5 Minutes between attempts at revival - We prevent a continuous failover loop
        now_ts = time.time()
        if now_ts - _keepalive_last.get(name, 0) < 300:
            continue
        _keepalive_last[name] = now_ts
        if len(_keepalive_last) > 200:
            for k in [k for k, t in _keepalive_last.items() if now_ts - t > 86400]:
                _keepalive_last.pop(k, None)
        # Custom order = shell With manager powers: Portal /exec It applies literally
        # (It was the only way left to execute orders with /exec And/run Disabled)
        if w.get("run") and not config.get("exec_enabled"):
            send_message(rtl(f"Revival went beyond {w['name']}: Custom run command "
                             "Requires activation /set exec on"))
            continue
        run = w.get("run") or w["name"]
        try:
            if w.get("run"):
                # An operating command written by the owner himself in his settings (He may need shell) — Intentional and reliable
                subprocess.Popen(run, shell=True, creationflags=NO_WINDOW)
            else:
                try:
                    os.startfile(run)  # None shell — Which opens the door to orders
                except OSError:
                    subprocess.Popen([run], creationflags=NO_WINDOW)
            send_message(f"Program <b>{w['name']}</b> It was locked - It turned on automatically")
        except Exception as e:
            print(f"[keepalive] start error: {e}")
            send_message(f"[X] Program <b>{w['name']}</b> It’s locked and I can’t turn it on "
                         f"({e})\nSee the run command: /keepalive add Name path")


def _rdp_registry_port():
    """Reads port RDP Real from the registry (Trusted source) - None If reading fails"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Terminal Server"
                r"\WinStations\RDP-Tcp") as k:
            val, _t = winreg.QueryValueEx(k, "PortNumber")
            return int(val)
    except Exception:
        return None


def check_rdp_service():
    """He makes sure that RDP He hears it on his real port (From the registry, not from settings):
    - If the settings differ from the registry, we will correct them automatically without warning
      (The old setting was causing false alarm every 15 minutes and restart the service properly!)
    - If the service really doesn’t listen: Alert after 2 minutes + Restart"""
    global _rdp_down_since, _last_rdp_restart
    reg_port = _rdp_registry_port()
    cfg_port = int(config.get("rdp_port", 3389))
    port = reg_port or cfg_port
    # Automatic sync: The settings were saying 3389 And reality 44389 = Permanent false alarm
    if reg_port and cfg_port != reg_port:
        config["rdp_port"] = reg_port
        save_config()
        send_message(rtl(
            f"outlet RDP In the registry it is <b>{reg_port}</b> It was in the settings "
            f"<b>{cfg_port}</b> — Settings fixed automatically (Without any actual error)"))
    listening = False
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                listening = True
                break
    except Exception as e:
        print(f"[rdp-watch] error: {e}")
        return
    if listening:
        if _rdp_down_since:
            _rdp_down_since = None
            send_message(f"[OK] Service RDP You are back listening on the port {port}")
        return
    now_ts = time.time()
    if _rdp_down_since is None:
        _rdp_down_since = now_ts
    if now_ts - _rdp_down_since < 120:
        return  # Two consecutive minutes before any action - We avoid false alarms
    if now_ts - _last_rdp_restart < 900:
        return  # Try to restart all 15 1 minute max
    _last_rdp_restart = now_ts
    send_buttons(
        rtl("<b>RDP SERVICE DOWN</b>") + "\n"
        + rtl(f"Not listening on port ({port}) - if this continues you lose remote access") + "\n"
        + rtl("Attempting to restart the service automatically..."),
        [[("RDP status", "run:/rdp"),
          ("Restart service now", "run:/svc restart TermService")]])
    if ps_ok("Restart-Service TermService -Force -ErrorAction Stop", timeout=60):
        send_message(rtl("RDP service restarted - verify you can connect"))
    else:
        send_message(rtl("Failed to restart the RDP service (check admin rights) - "
                         "the machine may need manual intervention"))


_last_allow_sync = 0.0


def check_rdp_allow_sync():
    """Ensures that the rules are limited RDP In the firewall associated with the current port:
    - Changing the port was leaving the permission rules/Blocking on the old port
      The new port remains open to the world despite the activation of the restriction! (A vulnerability we actually discovered)"""
    if not config.get("rdp_allow_active") and not lockdown_active():
        return
    # During lock we only sync the actual approved list
    ips = lockdown_ips() if lockdown_active() \
        else [str(i) for i in (config.get("rdp_allowed_ips") or [])]
    if not ips:
        return
    port = _rdp_registry_port() or int(config.get("rdp_port", 3389))
    ps = ("$r = Get-NetFirewallRule -DisplayName "
          "'RDPMonitor RDP Allow List TCP' -ErrorAction SilentlyContinue; "
          "if ($r) { ($r | Get-NetFirewallPortFilter).LocalPort } "
          "else { Write-Output 'MISSING' }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60,
                           creationflags=NO_WINDOW)
        out = _decode_out(r.stdout).strip()
    except Exception:
        return
    if out == str(port):
        return  # Everything is in sync
    if apply_rdp_allow(ips):
        send_message(rtl(
            f" <b>Limitation rules RDP It was on the wrong port!</b>\n"
            f"It was: {out or 'Missing'} — Supposedly: {port}\n"
            f"I have now reapplied it to the correct port"))
        audit_record(f"Reapply inventory RDP On the port {port} (It was: {out})")


def _ping_ok(target):
    """try ping One - Returns whether it was successful or not"""
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", "3000", target],
                           capture_output=True, timeout=10, creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def check_internet():
    """Internet monitoring: Alert after two minutes interruption + Warning when returning"""
    global _net_down_streak
    target = config.get("ping_target", "1.1.1.1")
    if _ping_ok(target):
        if _net_down_streak >= 2:
            send_message(f"[OK] <b>I got the internet back</b> (It was cut off "
                         f"{_net_down_streak} About a minute)")
        _net_down_streak = 0
    else:
        _net_down_streak += 1
        if _net_down_streak == 2:
            send_message(f" <b>The Internet is cut off on the device</b>\n"
                         f"ping {target} Failed 2 minutes ago\n"
                         "The device is working but without internet")


_last_fw_check = 0.0


def check_firewall_guard():
    """Firewall guarding - We discovered the actual incident: The wall was completely matted
    All the blocks, mats, and locks were 'On paper':
    - If the firewall file is turned off: Ensures that the port is RDP It has a permission rule, activates it, and informs you"""
    if not _check_start("fw_guard"):
        return
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$ErrorActionPreference='Stop'; Get-NetFirewallProfile -PolicyStore ActiveStore | ForEach-Object { "
                            "Write-Output ($_.Name + '|' + $_.Enabled.ToString()) }"],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("firewall profile query failed")
        off = []
        for ln in _decode_out(r.stdout).splitlines():
            parts = ln.strip().split("|")
            if len(parts) == 2 and parts[1].lower() == "false":
                off.append(parts[0])
        if not off:
            return
        diagnosis = get_firewall_report()
        if diagnosis["status"] in ("inconclusive", "blockers_found") or diagnosis.get("activation_blockers"):
            send_message("[X] Firewall guard paused: effective RDP policy is unknown or contains broad inbound blocks. "
                         "Review /firewall from the provider console; no policy was changed.")
            return
        # Safety first: Make sure that RDP It delivers — But there is no broad rule that breaks the restrictions!
        # (The guard was creating a general tolerance rule even if the restriction was enabled = It opens RDP To the world)
        port = _rdp_registry_port() or int(config.get("rdp_port", 3389))
        if config.get("rdp_allow_active"):
            # A restriction is configured. Never fall back to a general allow rule
            # (that would open RDP to the world). If we cannot reapply it, leave
            # the firewall exactly as it is and alert the operator.
            ips = lockdown_ips() if lockdown_active() \
                else [str(i) for i in (config.get("rdp_allowed_ips") or [])]
            if not ips:
                send_message(rtl("Firewall guard skipped: the IP allow-list is enabled but empty. "
                                 "Fix it first: /rdpallow add IP then /rdpallow apply confirm"))
                return
            if not apply_rdp_allow(ips):
                send_message(rtl("Firewall guard aborted: the IP allow-list could not be reapplied, "
                                 "so the firewall was left unchanged (RDP was NOT opened to the world). "
                                 "Fix it: /rdpallow apply confirm"))
                return
        else:
            access_ready, err = _create_general_rdp_rule(port)
            if not access_ready:
                send_message(rtl("[X] I did not activate the firewall because creating an access rule "
                                 "RDP Reliable failure. Fix the wall powers first.")
                             + (f"\n{esc(err)}" if err else ""))
                return
        ok, err = _netsh(["advfirewall", "set", "allprofiles", "state", "on"])
        if not ok:
            send_message(f"[X] Firewall activation failed: {esc(err)}")
            return
        audit_record("Firewall guarding: Activate dead files: " + ", ".join(off))
        send_buttons(
            rtl("<b>The firewall was off!</b>") + "\n"
            + rtl(f"Matte files: {esc(', '.join(off))}") + "\n"
            + rtl("All prohibition and restriction rules were not implemented — Activate them now automatically") + "\n"
            + rtl("Make sure your connection RDP It works, check the ports: /firewall"),
            [[("Firewall report", "run:/firewall"),
              ("Blocklist", "run:/blocklist")]])
    except Exception as e:
        print(f"[fw-guard] error: {e}")
    finally:
        _check_end("fw_guard")


def check_update_available():
    """Compares version on update_url In the current version - If you disagree, he will alert you (Without installation)
    - We compare the bytes of the file as is: Reading the text was unifying CRLF→LF
      The comparison always becomes different and the warning is repeated endlessly"""
    url = config.get("update_url", "")
    if not url:
        return
    try:
        r = requests.get(url, timeout=60)
        new_hash = hashlib.md5(r.content).hexdigest()
    except Exception as e:
        print(f"[update-check] error: {e}")
        return
    try:
        with open(SCRIPT_PATH, "rb") as f:
            cur_hash = hashlib.md5(f.read()).hexdigest()
    except Exception:
        return
    if new_hash != cur_hash:
        send_message("UL  <b>There is a new update for the tool</b> on the specified link.\n"
                     "Review your changes first, then submit /update To install.\n"
                     "To stop the scan: /set updatecheck 0")


# ----------------------------- Account for transferred data -----------------------------

TRAFFIC_FILE = os.path.join(BASE_DIR, "traffic.json")


def load_traffic():
    """Holds daily count + Last sample counters — Turning the tool off and on doubles the count
    (It was the first sample after all restart It re-adds every byte of the device’s boot)"""
    global _traffic, _last_traffic_counters
    try:
        if os.path.exists(TRAFFIC_FILE):
            with open(TRAFFIC_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            return
        if isinstance(data, dict) and "days" in data:
            _traffic = data.get("days") or {}
            last = data.get("last")
            # Boot ID: Pre-reboot system counters are worthless with
            # New boot even if it is larger than the saved one (An account shortage was occurring)
            if data.get("boot") == psutil.boot_time() \
                    and isinstance(last, (list, tuple)) and len(last) == 2:
                _last_traffic_counters = (last[0], last[1])
        else:
            _traffic = data  # Old formula: Dictionary of days directly
    except Exception:
        _traffic = {}


def save_traffic():
    """Atomic conservation - A power outage does not waste the daily count nor the last sample counters"""
    try:
        tmp = TRAFFIC_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"days": _traffic, "boot": psutil.boot_time(),
                       "last": list(_last_traffic_counters or [])}, f)
        os.replace(tmp, TRAFFIC_FILE)
    except Exception as e:
        print(f"[traffic] save error: {e}")


def traffic_job():
    """Collects the bytes transferred since the last sample and adds them to the day’s count - Every cycle is monitored"""
    global _last_traffic_counters, _last_traffic_save, _last_traffic_check
    c = psutil.net_io_counters()
    if _last_traffic_counters:
        d_sent = c.bytes_sent - _last_traffic_counters[0]
        d_recv = c.bytes_recv - _last_traffic_counters[1]
        # If the meters decrease, the device will be restarted - We are counting from the start of take-off
        if d_sent < 0:
            d_sent = c.bytes_sent
        if d_recv < 0:
            d_recv = c.bytes_recv
    else:
        # First run of the tool on this installation only (After the first save, the counters are saved
        # In traffic.json Restarting the tool will continue without delay)
        d_sent = c.bytes_sent
        d_recv = c.bytes_recv
    day = datetime.now().strftime("%Y-%m-%d")
    with _traffic_lock:
        rec = _traffic.setdefault(day, {"down": 0.0, "up": 0.0})
        rec["down"] += d_recv / (1024 ** 2)   # MB
        rec["up"] += d_sent / (1024 ** 2)
        # Cleaning: We keep 95 day
        if len(_traffic) > 95:
            cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            for k in list(_traffic.keys()):
                if k < cutoff:
                    del _traffic[k]
    _last_traffic_counters = (c.bytes_sent, c.bytes_recv)
    now_ts = time.time()
    if now_ts - _last_traffic_save >= 300:
        _last_traffic_save = now_ts
        save_traffic()
        check_traffic_quota()
    _last_traffic_check = now_ts


def quota_window_start():
    """The beginning of the current billing cycle based on the day of the return (The default is the first of the month)"""
    day = min(max(int(config.get("traffic_reset_day", 1) or 1), 1), 28)
    now = datetime.now()
    if now.day >= day:
        return datetime(now.year, now.month, day)
    prev = datetime(now.year, now.month, 1) - timedelta(days=1)
    return datetime(prev.year, prev.month, day)


def traffic_since(start_dt):
    """Total (Download, upload) In megabytes since a certain date"""
    start_str = start_dt.strftime("%Y-%m-%d")
    down = up = 0.0
    with _traffic_lock:
        snapshot = dict(_traffic)
    for day, rec in snapshot.items():
        if day >= start_str:
            down += rec.get("down", 0)
            up += rec.get("up", 0)
    return down, up


def check_traffic_quota():
    """Monthly quota alerts: 50% / 80% / 95%"""
    quota = float(config.get("traffic_quota_gb", 0) or 0)
    if quota <= 0:
        return
    down, up = traffic_since(quota_window_start())
    used_gb = (down + up) / 1024
    pct = used_gb / quota * 100
    month_key = quota_window_start().strftime("%Y-%m")
    for level, mark in ((50, ""), (80, ""), (95, "")):
        key = f"{month_key}_{level}"
        if pct >= level and not _traffic_alerted.get(key):
            _traffic_alerted[key] = True
            if len(_traffic_alerted) > 36:
                # Keep only the most recent quota-alert markers.
                for k in sorted(_traffic_alerted)[:-24]:
                    _traffic_alerted.pop(k, None)
            send_message(
                f"{mark} <b>Data consumption alert</b>\n"
                f"Consumed {used_gb:.1f} GB of share {quota:.0f} GB "
                f"({pct:.0f}%) In the current billing cycle\n"
                "Detail: /traffic"
            )


def traffic_report(days=7):
    """Transferred data report: Today, current session, class, and days breakdown"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [rtl("<b>Account for transferred data</b>"), ""]
    with _traffic_lock:
        snapshot = dict(_traffic)
    rec = snapshot.get(today)
    if rec:
        lines.append(rtl(f" Today: <b>{(rec['down'] + rec['up']) / 1024:.2f} GB</b> "
                         f"(Download {rec['down'] / 1024:.2f} | Raise {rec['up'] / 1024:.2f})"))
    else:
        lines.append(" Today: No data has been transferred yet (Or the tool has started now)")
    start = quota_window_start()
    down, up = traffic_since(start)
    lines.append(rtl(f" Billing cycle (since {start:%m-%d}): "
                     f"<b>{(down + up) / 1024:.2f} GB</b> "
                     f"(Download {down / 1024:.2f} | Raise {up / 1024:.2f})"))
    quota = float(config.get("traffic_quota_gb", 0) or 0)
    if quota > 0:
        used = (down + up) / 1024
        pct = min(100.0, used / quota * 100)
        bars = int(pct // 5)
        lines.append(rtl(f" The share: {used:.2f} Who {quota:.0f} GB"))
        lines.append("" * bars + "" * (20 - bars) + f" {pct:.0f}%")
    else:
        lines.append(rtl("There is no specific quota — Select it: /set traffic 500"))
    all_down = sum(r.get("down", 0) for r in snapshot.values())
    all_up = sum(r.get("up", 0) for r in snapshot.values())
    lines.append(rtl(f" Since installation: <b>{(all_down + all_up) / 1024:.2f} GB</b> "
                     f"(Download {all_down / 1024:.2f} | Raise {all_up / 1024:.2f})"))
    lines.append("")
    lines.append(rtl(f" Another {days} days:"))
    rows = []
    for i in range(days):
        day_dt = datetime.now() - timedelta(days=i)
        r = snapshot.get(day_dt.strftime("%Y-%m-%d"))
        if r:
            rows.append(f"{day_dt:%m-%d}   {(r['down'] + r['up']) / 1024:7.2f} GB"
                        f"   DL {r['down'] / 1024:6.2f}  UL {r['up'] / 1024:6.2f}")
        else:
            rows.append(f"{day_dt:%m-%d}      -")
    lines.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    lines.append(rtl("Ranking: History | Total | Download | Raise"))
    return "\n".join(lines)


# ----------------------------- Complete control and advanced diagnostics -----------------------------

PANIC_RULE = "RDPMonitor PANIC"
SCHED_RULE = "RDPMonitor Schedule"


def block_subnet(ip):
    ip = canonical_ip(ip)
    if not ip or ":" in ip:
        return False, "requires IPv4"
    return _add_block_target(canonical_target(ip + "/24"))


def _panic_rule_exists():
    count = _firewall_rule_count(PANIC_RULE)
    return count is not None and count > 0


def panic_on():
    """Panic mode: Close RDP Totally + Block all previous attempters"""
    if config.get("panic_active"):
        send_message(rtl("Panic mode is already on — /panic off To stop"))
        return
    blocked_now = []
    for ip in list(_failed_logins.keys()):
        bok, _st = block_ip(ip)
        if bok:
            blocked_now.append(ip)
    port = int(config.get("rdp_port", 3389))
    ok = ps_ok(f"New-NetFirewallRule -DisplayName '{PANIC_RULE}' -Direction Inbound "
               f"-Protocol TCP -LocalPort {port} -Action Block -ErrorAction Stop",
               timeout=60)
    if not ok:
        ok = _panic_rule_exists()
    if not ok:
        # The status is recorded and success is announced only if the rule actually exists
        audit_record("Failed to activate panic mode - The closing rule has not been established")
        send_message(rtl("[X] Failed to create shutdown rule — Panic mode <b>Not activated</b>. "
                         "Check administrator permissions"))
        return
    config["panic_active"] = True
    save_config()
    audit_record("Panic mode is activated")
    send_message(
        rtl("<b>Panic mode is activated!</b>") + "\n"
        + rtl(f"RDP Completely closed on the port ({port}) — Login via RDP Impossible now") + "\n"
        + rtl(f"Blocked {len(blocked_now)} IP From previous attempts") + "\n"
        + rtl("Return: /panic off"))


def panic_off():
    """End panic mode: Open RDP Again"""
    if not config.get("panic_active"):
        send_message(rtl("There is no panic mode activated"))
        return
    _netsh(["advfirewall", "firewall", "delete", "rule", f"name={PANIC_RULE}"])
    # Verify that the rule has actually been deleted — He was announcing "The panic is over" It remains busy
    if _firewall_rule_count(PANIC_RULE) != 0:
        send_message(rtl("[X] The lockdown rule has not been removed — Panic mode "
                         "<b>It’s still activated</b>! Repeat /panic off Or see permissions"))
        return
    config["panic_active"] = False
    save_config()
    audit_record("Panic mode is over")
    send_message(rtl("<b>Panic mode is over</b> — RDP Back available "
                     "(Fortify it: /harden fix And /lockdown on)"))


def panic_rearm():
    """If the tool is restarted and panic is activated - Make sure the rule exists
    - We delete the old rule first: Repetition was accumulating rules with the same name"""
    port = int(config.get("rdp_port", 3389))
    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    f"name={PANIC_RULE}"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
    ps_ok(f"New-NetFirewallRule -DisplayName '{PANIC_RULE}' -Direction Inbound "
          f"-Protocol TCP -LocalPort {port} -Action Block "
          f"-ErrorAction SilentlyContinue")
    if not _panic_rule_exists():
        # The rule is missing, so RDP is NOT actually closed. Never report panic
        # as active while the port may be open.
        config["panic_active"] = False
        save_config()
        audit_record("Panic rule missing on restart - panic mode reported inactive")
        send_message(rtl("[WARN] Panic mode was active, but its firewall rule could not be "
                         "recreated. RDP is <b>not</b> closed. Panic mode has been reported "
                         "inactive — activate it again with /panic on"))
        return
    send_message(rtl(" Panic mode is still activated from before — RDP Closed. /panic off To return"))


def _parse_hours(spec):
    """Analyze "9-23" To (9, 23) - Supports night shifts 22-6"""
    m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", (spec or "").strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a > 23 or b > 23 or a == b:
        return None
    return a, b


def rdp_schedule_tick():
    """Opens and closes an outlet RDP According to specified working hours"""
    spec = config.get("rdphours", "")
    rng = _parse_hours(spec)
    port = int(config.get("rdp_port", 3389))
    blocked_flag = bool(config.get("rdpsched_blocked"))
    if rng:
        a, b = rng
        in_hours = (a <= datetime.now().hour < b) if a < b \
            else (datetime.now().hour >= a or datetime.now().hour < b)
    else:
        in_hours = True
    if not in_hours and not blocked_flag:
        try:
            r = subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                                f"name={SCHED_RULE}", "dir=in", "action=block",
                                "protocol=TCP", f"localport={port}"],
                               capture_output=True, timeout=30, creationflags=NO_WINDOW)
            if r.returncode == 0:
                config["rdpsched_blocked"] = True
                save_config()
                send_message(rtl(f" Outside hours RDP ({spec}) — I closed the port {port}"))
        except Exception as e:
            print(f"[schedule] error: {e}")
    elif in_hours and blocked_flag:
        _netsh(["advfirewall", "firewall", "delete", "rule", f"name={SCHED_RULE}"])
        # Verify that the rule has actually been deleted — He was recording "Open" The rule remains in use
        # And don’t try again (The sign is flipped to open)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-NetFirewallRule -DisplayName '{SCHED_RULE}' "
             "-ErrorAction SilentlyContinue).Count"],
            capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if _decode_out(r.stdout).strip() in ("", "0"):
            config["rdpsched_blocked"] = False
            save_config()
            send_message(rtl(f"Hours started RDP ({spec}) — I opened the port {port}"))
        else:
            print("[schedule] Failed to delete lockout rule - Try again next session")


def check_services():
    """Monitors registered Windows services - If I stopped, he would repeat it and warn me"""
    for w in (config.get("svcwatch") or []):
        name = (w.get("name") or "").strip()
        if not name:
            continue
        try:
            svc = psutil.win_service_get(name).as_dict()
        except Exception:
            continue
        if svc.get("status") == "running":
            continue
        now_ts = time.time()
        if now_ts - _svcwatch_last.get(name.lower(), 0) < 900:
            continue  # Try to reset all 15 1 minute max
        _svcwatch_last[name.lower()] = now_ts
        if len(_svcwatch_last) > 200:
            for k in [k for k, t in _svcwatch_last.items() if now_ts - t > 86400]:
                _svcwatch_last.pop(k, None)
        if ps_ok(f"Start-Service -Name '{name}' -ErrorAction Stop", timeout=60):
            send_message(rtl(f" Service <b>{esc(name)}</b> She was standing — "
                             "It restarted automatically"))
        else:
            send_message(rtl(f"[X] Service <b>{esc(name)}</b> Standing and failing "
                             "Restart it — Review it manually"))


def _selfheal_job():
    """Self-cleaning when the system disk is full"""
    try:
        freed = clean_temp_files()
        send_message(rtl("<b>Self cleaning worked</b> (Disk bypass 95%)") + "\n"
                     + rtl(f"Space freed up: {format_size(freed)}"))
    except Exception as e:
        send_message(rtl(f"[X] Self cleaning failed: {e}"))


PS_HARDEN = (
    "$nla=(Get-ItemProperty 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal "
    "Server\\WinStations\\RDP-Tcp' -ErrorAction SilentlyContinue).UserAuthentication; "
    "Write-Output ('NLA|'+$nla); "
    "$na=net accounts; "
    "$lo=$na | Select-String -Pattern 'Lockout threshold|Threshold'; "
    "if ($lo) { Write-Output ('LOCKOUT|'+$lo[0]) } else { Write-Output 'LOCKOUT|?' }; "
    "$adm=Get-LocalUser -Name 'Administrator' -ErrorAction SilentlyContinue; "
    "Write-Output ('ADMIN|'+[bool]$adm)"
)


def harden_report(fix=False):
    """Immunization test RDP: NLA + Account lock + Name Administrator - With automatic repair"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_HARDEN],
                           capture_output=True, timeout=90, creationflags=NO_WINDOW)
        info = {}
        for ln in _decode_out(r.stdout).splitlines():
            p0 = ln.split("|", 1)
            if len(p0) == 2:
                info[p0[0].strip()] = p0[1].strip()
    except Exception as e:
        send_message(rtl(f"[X] Scan failed: {e}"))
        return
    lines = [rtl(" <b>Immunization test RDP</b>"), ""]
    fixes = []
    if info.get("NLA") == "1":
        lines.append(rtl("[OK] NLA (Network layer authentication): Activated"))
    else:
        lines.append(rtl("[X] NLA: Disabled — It allows testing passwords before authentication"))
        fixes.append("NLA")
    lockout = info.get("LOCKOUT", "?")
    m0 = re.search(r"(\d+)", lockout) if lockout and lockout != "?" else None
    if lockout == "?":
        lines.append(rtl("[WARN] Account lock: I couldn’t read politics (Windows in an unsupported language)"))
    elif m0 and int(m0.group(1)) > 0:
        lines.append(rtl(f"[OK] Account lock: After {m0.group(1)} Failed attempt"))
    else:
        lines.append(rtl("[X] Account lock: Disabled — Experimentation has no limits"))
        fixes.append("LOCKOUT")
    if info.get("ADMIN") == "True":
        lines.append(rtl("[WARN] Account Administrator With its default name — Rename it "
                         "(If you use it to login!)"))
    else:
        lines.append(rtl("[OK] Account Administrator: Renamed or not found"))
    if fix and fixes:
        ok1 = ok2 = None
        if "NLA" in fixes:
            ok1 = ps_ok("Set-ItemProperty 'HKLM:\\System\\CurrentControlSet\\Control\\"
                        "Terminal Server\\WinStations\\RDP-Tcp' -Name "
                        "UserAuthentication -Value 1")
        if "LOCKOUT" in fixes:
            ok2 = ps_ok("net accounts /lockoutthreshold:10")
        parts = []
        if ok1 is not None:
            parts.append("NLA " + ("[OK]" if ok1 else "[X]"))
        if ok2 is not None:
            parts.append(rtl("Account lock " + ("[OK] (After 10 Attempts)" if ok2 else "[X]")))
        lines.append(rtl(" Repair: " + " | ".join(parts)))
        lines.append(rtl("Recheck: /harden"))
    elif fixes:
        lines.append(rtl("Automatic repair: /harden fix"))
    send_message("\n".join(lines))


PS_BIGFILES = (
    'Get-ChildItem -Path "$env:SystemDrive\\" -Recurse -File -Force '
    '-ErrorAction SilentlyContinue | '
    'Sort-Object Length -Descending | Select-Object -First 20 | '
    'ForEach-Object { Write-Output ([math]::Round($_.Length/1MB,1).ToString() '
    '+ \'MB|\' + $_.FullName) }'
)


def bigfiles_job():
    """Bigger 20 File on the system disk - Diagnosis of disk fullness"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_BIGFILES],
                           capture_output=True, timeout=600, creationflags=NO_WINDOW)
        rows = [ln.strip() for ln in _decode_out(r.stdout).splitlines()
                if "|" in ln][:20]
    except Exception as e:
        send_message(rtl(f"[X] Disk check failed: {e}"))
        return
    if not rows:
        send_message(rtl("I found no large files (Or the examination stops)"))
        return
    send_message(rtl("<b>The largest files on the disk</b>") + "\n<pre>"
                 + esc("\n".join(rows)) + "</pre>")


def nettest_job(host):
    """Comprehensive testing: DNS + ping + outlets — Differentiate your problem from their problem"""
    lines = [rtl(f"<b>Connection test:</b> {esc(host)}"), ""]
    try:
        infos = socket.getaddrinfo(host, None)
        ips = sorted({i[4][0] for i in infos})
        lines.append(rtl(f"[OK] DNS: Resolves to {', '.join(ips[:4])}"))
        ip0 = ips[0]
    except Exception as e:
        lines.append(rtl(f"[X] DNS: Name resolution failed ({esc(e)})"))
        send_message("\n".join(lines))
        return
    if _ping_ok(ip0):
        lines.append(rtl("[OK] Ping: He responds"))
    else:
        lines.append(rtl("[WARN] Ping: What responds (Some servers block it — There is no evidence of a malfunction)"))
    for p in (80, 443):
        try:
            with socket.create_connection((host, p), timeout=5):
                lines.append(rtl(f"[OK] outlet {p}: Open"))
        except Exception:
            lines.append(rtl(f"[X] outlet {p}: Closed or blocked"))
    send_message("\n".join(lines))


def ps_detail(name):
    """Details of each version of the process: Full path and its owner — Detects fakes"""
    rows = []
    for p in psutil.process_iter(['pid', 'name', 'exe', 'username',
                                  'memory_info']):
        try:
            n = p.info.get('name') or ''
            if name.lower() in n.lower():
                mi = p.info.get('memory_info')
                rows.append({
                    "pid": p.info['pid'], "name": n,
                    "exe": p.info.get('exe') or '?',
                    "user": p.info.get('username') or '?',
                    "mem": mi.rss / 1024 ** 2 if mi else 0.0,
                })
        except Exception:
            pass
    if not rows:
        return rtl(f"I didn’t find any process named {esc(name)}")
    lines = [rtl(f" <b>Operations {esc(name)}</b> ({len(rows)} Process)"), "<pre>"]
    for r0 in rows[:12]:
        lines.append(esc(f"PID {r0['pid']:>7} {r0['mem']:7.0f}MB {r0['name'][:24]}"))
    lines.append("</pre>")
    for r0 in rows[:12]:
        lines.append(rtl(f"• [{r0['pid']}] {esc(r0['exe'])} — {esc(r0['user'])}"))
    return "\n".join(lines)


PS_LOGIN_LOG = success_query(3, report=True)


def _logins_job(n):
    """Latest successful logins via RDP"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_LOGIN_LOG],
                           capture_output=True, timeout=120, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Security event query failed; login history is unavailable")
        rows = [ln.strip() for ln in _decode_out(r.stdout).splitlines()
                if "|" in ln][:n]
    except Exception as e:
        send_message(rtl(f"[X] Reading failed: {e}"))
        return
    if not rows:
        send_message(rtl("There are no logins RDP registered during 3 days"))
        return
    send_message(rtl(f"<b>Latest successful logins</b> ({len(rows)})") + "\n<pre>"
                 + esc("\n".join(rows)) + "</pre>"
                 + rtl("Columns: UTC event time | Account | Source IP | Event record ID"))


PS_STARTUP = (
    "Write-Output '---RUN---'; "
    "foreach ($k in @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',"
    "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run')) { "
    "try { $p=Get-ItemProperty -Path $k -ErrorAction Stop; "
    "$p.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | "
    "ForEach-Object { Write-Output ($_.Name+' = '+$_.Value) } } catch {} }; "
    "Write-Output '---TASK---'; "
    "Get-ScheduledTask -ErrorAction SilentlyContinue | "
    "Where-Object { $_.TaskPath -notlike '\\Microsoft*' } | "
    "ForEach-Object { Write-Output ($_.State.ToString()+' | '+$_.TaskName) }"
)


def startup_job():
    """Inventory of automatic start programs: Keys Run and irregular scheduled tasks"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_STARTUP],
                           capture_output=True, timeout=120, creationflags=NO_WINDOW)
        section, run_rows, task_rows = "", [], []
        for ln in _decode_out(r.stdout).splitlines():
            ln = ln.strip()
            if ln == "---RUN---":
                section = "RUN"
            elif ln == "---TASK---":
                section = "TASK"
            elif ln and section == "RUN":
                run_rows.append(ln)
            elif ln and section == "TASK":
                task_rows.append(ln)
    except Exception as e:
        send_message(rtl(f"[X] Inventory failure: {e}"))
        return
    lines = [rtl("<b>Auto start programs</b>"), ""]
    lines.append(rtl(f" Keys Run ({len(run_rows)}):"))
    lines.append("<pre>" + esc("\n".join(run_rows[:15]) or "-") + "</pre>")
    lines.append(rtl(f" Irregular scheduled tasks ({len(task_rows)}):"))
    lines.append("<pre>" + esc("\n".join(task_rows[:15]) or "-") + "</pre>")
    lines.append(rtl("Strange entrance? This is a favorite place to hide malware"))
    send_message("\n".join(lines))


PS_SYSINFO = (
    "$os=Get-CimInstance Win32_OperatingSystem; "
    "Write-Output ('CAPTION|'+$os.Caption); "
    "Write-Output ('VERSION|'+$os.Version); "
    "$rb=(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
    "WindowsUpdate\\Auto Update\\RebootRequired') -or "
    "(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
    "Component Based Servicing\\RebootPending'); "
    "Write-Output ('REBOOT|'+$rb); "
    "$cs=Get-CimInstance Win32_ComputerSystem; "
    "Write-Output ('RAM|'+[math]::Round($cs.TotalPhysicalMemory/1GB,1)); "
    "$p=Get-CimInstance Win32_Processor | Select-Object -First 1; "
    "Write-Output ('CPU|'+$p.Name.Trim())"
)


def _sysinfo_job():
    """System card: Version, hardware, pending boot, memory pressure"""
    info = {}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_SYSINFO],
                           capture_output=True, timeout=90, creationflags=NO_WINDOW)
        for ln in _decode_out(r.stdout).splitlines():
            p0 = ln.split("|", 1)
            if len(p0) == 2:
                info[p0[0]] = p0[1].strip()
    except Exception as e:
        send_message(rtl(f"[X] Failed to collect information: {e}"))
        return
    mem = psutil.virtual_memory()
    sw = psutil.swap_memory()
    lines = [
        rtl("<b>System information</b>"), "",
        rtl(f" System: {esc(info.get('CAPTION', '?'))}"),
        rtl(f" Version: {esc(info.get('VERSION', '?'))}"),
        rtl(f" Processor: {esc(info.get('CPU', '?')[:50])}"),
        rtl(f" rams: {mem.percent:.0f}% User from {info.get('RAM', '?')} GB"),
        rtl(f" Migration file: {sw.percent:.0f}% User"),
        rtl(f" Duration of operation: {format_uptime()}"),
        rtl(" There is a pending restart (Updates)" if info.get("REBOOT") == "True"
            else "[OK] There is no pending restart"),
    ]
    send_message("\n".join(lines))


def when_report(metric="cpu", threshold=80, hours=24):
    """When consumption exceeds its limit during a period - Who registered? history Same"""
    cutoff = time.time() - hours * 3600
    pts = [h for h in _history if h.get("t", 0) >= cutoff]
    key = "c" if metric == "cpu" else "r"
    hits = [h for h in pts if h.get(key, 0) >= threshold]
    if not hits:
        return rtl(f"[OK] There are no moments of transcendence {metric.upper()} {threshold}% "
                   f"During another {hours} hours")
    ranges = []
    start = prev = None
    for h in pts:
        if h.get(key, 0) >= threshold:
            if start is None:
                start = h["t"]
            prev = h["t"]
        elif start is not None:
            ranges.append((start, prev))
            start = None
    if start is not None:
        ranges.append((start, prev))
    lines = [rtl(f" <b>Moments of transcendence {metric.upper()} {threshold}%</b> "
                 f"— Another {hours} hours ({len(hits)} Minute)"), "", "<pre>"]
    for s, e in ranges[:15]:
        lines.append(f"{datetime.fromtimestamp(s):%m-%d %H:%M} -> "
                     f"{datetime.fromtimestamp(e):%H:%M}")
    lines.append("</pre>")
    return "\n".join(lines)


def getlog_job():
    """It sends you the last bit of history of the tool itself"""
    if not os.path.isfile(LOG_FILE):
        send_message(rtl("No record yet"))
        return
    size = os.path.getsize(LOG_FILE)
    p = os.path.join(tempfile.gettempdir(), f"rdpm_log_{int(time.time())}.txt")
    with open(LOG_FILE, "rb") as f:
        if size > 40 * 1024:
            f.seek(-40 * 1024, 2)
        data = f.read()
    with open(p, "wb") as f:
        f.write(data)
    send_document(p, rtl(f" Another {format_size(len(data))} From the tool registry"))


PS_UPDATES = (
    "$rb=(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
    "WindowsUpdate\\Auto Update\\RebootRequired') -or "
    "(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
    "Component Based Servicing\\RebootPending'); "
    "Write-Output ('REBOOT|'+$rb); "
    "try { $s=New-Object -ComObject Microsoft.Update.Session; "
    "$se=$s.CreateUpdateSearcher(); "
    "$res=$se.Search('IsInstalled=0 and IsHidden=0'); "
    "Write-Output ('COUNT|'+$res.Updates.Count); "
    "$res.Updates | Select-Object -First 15 | "
    "ForEach-Object { Write-Output ('U|'+$_.Title) } } "
    "catch { Write-Output ('ERR|'+$_.Exception.Message) }"
)


def updates_job():
    """Pending Windows updates + Restart status"""
    info, titles = {}, []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_UPDATES],
                           capture_output=True, timeout=300, creationflags=NO_WINDOW)
        for ln in _decode_out(r.stdout).splitlines():
            p0 = ln.split("|", 1)
            if len(p0) == 2:
                if p0[0] == "U":
                    titles.append(p0[1])
                else:
                    info[p0[0]] = p0[1].strip()
    except Exception as e:
        send_message(rtl(f"[X] Update check failed: {e}"))
        return
    lines = [rtl("<b>Windows updates</b>"), "",
             rtl(" There is a pending restart" if info.get("REBOOT") == "True"
                 else "[OK] There is no pending restart")]
    if info.get("COUNT") is not None:
        lines.append(rtl(f" Pending updates: {info['COUNT']}"))
        for t in titles:
            lines.append(rtl(f"• {esc(t[:70])}"))
    elif info.get("ERR"):
        lines.append(rtl(f"[WARN] I couldn’t get the list: {esc(info['ERR'][:120])}"))
    send_message("\n".join(lines))


def config_backup_job():
    """Sends a copy of your settings to the chat — Tokens and computer secrets are hidden"""
    data = _redact_config(config)
    p = None
    queued = False
    try:
        fd, p = tempfile.mkstemp(prefix="rdpm_config_backup_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        queued = send_document(p, rtl(" Settings copy (Tokens and secrets are hidden)"))
    except Exception as e:
        send_message(rtl(f"[X] Copy failed: {e}"))
    finally:
        if p and not queued:
            try:
                os.remove(p)
            except OSError:
                pass


# ----------------------------- Monitoring -----------------------------

def usage_level(cpu, ram):
    return resource_usage_level(cpu, ram, config)


_resource_alert_policy = ResourceAlertPolicy()


LEVEL_INFO = {
    "warning": ("", "HIGH RESOURCE USAGE"),
    "danger": ("", "VERY HIGH RESOURCE USAGE"),
    "critical": ("", "CRITICAL RESOURCE USAGE"),
}


def format_duration(secs):
    """Duration in seconds to read Arabic text"""
    secs = int(secs)
    h, m = secs // 3600, (secs % 3600) // 60
    if h and m:
        return f"{h} hour and {m} Minute"
    if h:
        return f"{h} hours"
    return f"{m} Minute"


def parse_duration(text):
    """Analyze the duration of such 3h / 30m / 2d (A number without a unit = Hours) - It goes back seconds or so None"""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hmd]?)", (text or "").strip().lower())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return int(val * 60)
    if unit == "d":
        return int(val * 86400)
    return int(val * 3600)


def alerts_muted():
    """Are regular alerts muted now? (Wish and Critical are never affected)"""
    try:
        return time.time() < float(config.get("muted_until", 0) or 0)
    except Exception:
        return False


def send_usage_alert(cpu, ram_pct, used_gb, total_gb, level, spike=None):
    if alerts_muted() and level != "critical":
        return
    _icon, title = LEVEL_INFO[level]
    body = (f"CPU   {cpu:5.1f}%\n"
            f"RAM   {ram_pct:5.1f}%   ({used_gb:.1f}/{total_gb:.1f} GB)\n"
            f"limits  warn {config['cpu_alert_threshold']}  "
            f"danger {config['danger_threshold']}  "
            f"critical {config['critical_threshold']}")
    if spike:
        body += f"\nSudden spike: CPU {spike['cpu_delta']:+.0f}, RAM {spike['ram_delta']:+.0f} percentage points"
    send_message(f"<b>{title}</b>\n<pre>{esc(body)}</pre>")


def check_watched_processes():
    """Check the programs under supervision (/watch)"""
    targets = config.get("watch") or []
    if not targets:
        return
    sums = {w["name"].lower(): 0 for w in targets}
    for p in psutil.process_iter(['name', 'memory_info']):
        try:
            pname = (p.info.get('name') or '').lower()
            mi = p.info.get('memory_info')
            if not mi:
                continue
            for key in sums:
                if key in pname:
                    sums[key] += mi.rss
        except Exception:
            pass
    for w in targets:
        mb = sums[w["name"].lower()] / (1024 ** 2)
        if mb >= w["ram_mb"] and \
                time.time() - _watch_cooldown.get(w["name"], 0) >= 600:
            _watch_cooldown[w["name"]] = time.time()
            if len(_watch_cooldown) > 200:
                cutoff = time.time() - 3600
                for k in [k for k, t in _watch_cooldown.items() if t < cutoff]:
                    _watch_cooldown.pop(k, None)
            if not alerts_muted():
                send_message(
                    f" <b>Program monitoring</b>\n"
                    f"Program <b>{w['name']}</b> Exceeding the limit:\n"
                    f" It is used now: {mb / 1024:.2f} GB "
                    f"(limit {w['ram_mb'] / 1024:.1f} GB)\n"
                    f"To close it send: /kill {w['name']}"
                )


def check_sessions():
    """Report verified session changes; observation time is not a Windows logon time."""
    global _known_sessions
    if not _check_start("sessions"):
        return
    try:
        sessions = get_rdp_sessions(strict=True)
        current = {(str(item.get("user", "")), str(item.get("id", "")), str(item.get("session", ""))):
                   str(item.get("state", "unknown")) for item in sessions if item.get("user")}
        if _known_sessions is None:
            _known_sessions = current
            return
        previous = _known_sessions if isinstance(_known_sessions, dict) else {}
        observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = []
        for key in current.keys() - previous.keys():
            lines.append(f"Session appeared: {esc(key[0])} | session {esc(key[1] or key[2])} | {esc(current[key])}")
        for key in previous.keys() - current.keys():
            lines.append(f"Session disappeared: {esc(key[0])} | session {esc(key[1] or key[2])}")
        for key in current.keys() & previous.keys():
            if current[key] != previous[key]:
                lines.append(f"Session state changed: {esc(key[0])} | session {esc(key[1] or key[2])} | "
                             f"{esc(previous[key])} -> {esc(current[key])}")
        if lines and not alerts_muted():
            send_buttons("<b>RDP session changes</b>\nObserved at " + observed + "\n" + "\n".join(lines)
                         + "\nUse login history for the Windows event time and source IP.",
                         [[("Login event history", "cmd:/logins"), ("Current sessions", "cmd:/rdp")]])
        _known_sessions = current
    except Exception as exc:
        print(f"[sessions] verified snapshot unavailable: {exc}")
    finally:
        _check_end("sessions")


def speedtest_job(silent=False):
    try:
        ping_ms, down, up = run_speedtest()
        send_message(
            f" <b>Internet speed</b>\n"
            f"DL  Download: {down:.1f} Mbps\n"
            f"UL  Raise: {up:.1f} Mbps\n"
            f" Response: {ping_ms:.0f} ms"
        )
    except Exception as e:
        if not silent:
            send_message(f"[X] Speed measurement failed: {e}")


def monitor_loop():
    """Main episode: Graduated alerts + Anomaly + Tablets + Programs + Sessions + Reports"""
    global _auto_streak, _last_auto_check
    global _last_auto_restart, _last_disk_check, _last_watch_check, _last_session_check
    global _last_history_append, _last_history_save, _last_speedtest, _last_daily, _last_weekly
    global _session_locked, _last_lock_time, _last_temp_check
    global _last_failed_check, _last_clean_day, _last_critical_check
    global _last_heartbeat, _last_keepalive_check, _last_rdp_check
    global _last_net_watch, _last_update_check, _last_learn
    global _last_svcwatch_check, _last_selfheal, _last_rdpsched_check
    global _last_allow_sync, _last_fw_check
    release_thread = None

    while True:
        try:
            now_ts = time.time()
            now = datetime.now()
            cpu, ram_pct, used_gb, total_gb = get_usage()

            # --- Network speed ---
            update_net_speed()

            # --- Consumption record (Every minute) ---
            if now_ts - _last_history_append >= 60:
                _last_history_append = now_ts
                append_history(cpu, ram_pct)
            if now_ts - _last_history_save >= 300:
                _last_history_save = now_ts
                save_history()

            # One decision for each system sample: combine threshold and spike context.
            notice = _resource_alert_policy.observe(cpu, ram_pct, now_ts, config, muted=alerts_muted())
            if notice:
                if notice["kind"] == "threshold":
                    send_usage_alert(cpu, ram_pct, used_gb, total_gb, notice["level"], notice["spike"])
                elif notice["kind"] == "recovery":
                    send_message("<b>Usage back to normal</b>\n<pre>"
                                 + esc(f"CPU {cpu:.1f}%\nRAM {ram_pct:.1f}%\n"
                                       f"Duration: {format_duration(notice['duration'])}\n"
                                       f"Peak CPU: {notice['peak_cpu']:.1f}%\n"
                                       f"Peak RAM: {notice['peak_ram']:.1f}%") + "</pre>")
                else:
                    spike = notice["spike"]
                    send_buttons("<b>SUDDEN SPIKE</b>\n<pre>" + esc(
                        f"CPU {cpu:.1f}% ({spike['cpu_delta']:+.0f} points)\n"
                        f"RAM {ram_pct:.1f}% ({spike['ram_delta']:+.0f} points)") + "</pre>",
                        [[("Review top processes", "cmd:/top")]])

            # --- Automatic restart (Check every minute) ---
            if now_ts - _last_auto_check >= 60:
                _last_auto_check = now_ts
                if config["auto_restart_enabled"] and (
                        cpu >= config["auto_restart_cpu"]
                        or ram_pct >= config["auto_restart_ram"]):
                    _auto_streak += 1
                    if _auto_streak >= config["auto_restart_consecutive"] and \
                            now_ts - _last_auto_restart > config["restart_cooldown"]:
                        _last_auto_restart = now_ts
                        _auto_streak = 0
                        do_restart(
                            f"Very high consumption (CPU {cpu:.0f}% / RAM {ram_pct:.0f}%) "
                            f"Continuous for several minutes", auto=True)
                else:
                    _auto_streak = 0

            # --- Discs (Every minute) ---
            if now_ts - _last_disk_check >= 60:
                _last_disk_check = now_ts
                for dev, pct, free, _total in get_disks():
                    if pct >= config["disk_threshold"] and not _disk_alerted.get(dev):
                        _disk_alerted[dev] = True
                        if not alerts_muted():
                            send_buttons(
                                rtl("<b>DISK SPACE ALERT</b>") + "\n"
                                + rtl(f"Disk {esc(dev)} is {pct:.0f}% full "
                                      f"(only {free:.1f} GB left)"),
                                [[("Clean now", "run:/clean"),
                                  ("Biggest files", "run:/bigfiles")]])
                    elif pct < config["disk_threshold"] - 5 and _disk_alerted.get(dev):
                        _disk_alerted[dev] = False
                        if not alerts_muted():
                            send_message(rtl(f"Disk {dev} is back under {config['disk_threshold']}%"))

            # --- Programs are under supervision (Every minute) ---
            if now_ts - _last_watch_check >= 60:
                _last_watch_check = now_ts
                check_watched_processes()

            # --- Sessions RDP (Eat 30 Again - With a separate thread: Deadline qwinsta 10 Seconds
            #     It was freezing the whole main loop) ---
            if config.get("session_alerts") and now_ts - _last_session_check >= 30:
                _last_session_check = now_ts
                threading.Thread(target=check_sessions, daemon=True).start()

            # --- Failed login attempts (Every minute) ---
            if (config.get("failed_login_alerts")
                    or config.get("failed_login_block")
                    or config.get("trap_users")) \
                    and now_ts - _last_failed_check >= 60:
                _last_failed_check = now_ts
                threading.Thread(target=check_failed_logons,
                                 daemon=True).start()

            # --- Critical events in the log (Every minute) ---
            if config.get("critical_alerts") and \
                    now_ts - _last_critical_check >= 60:
                _last_critical_check = now_ts
                threading.Thread(target=check_critical_events,
                                 daemon=True).start()

            # --- The pulse: Message "It still works" Eat N hours ---
            hb = float(config.get("heartbeat_hours", 0) or 0)
            if hb > 0:
                if _last_heartbeat == 0:
                    _last_heartbeat = now_ts
                elif now_ts - _last_heartbeat >= hb * 3600:
                    _last_heartbeat = now_ts
                    send_message(
                        rtl(f"<b>Still alive</b> - {hb:.0f} hours without issues") + "\n"
                        + rtl(f"CPU: {cpu:.1f}% | RAM: {ram_pct:.1f}%") + "\n"
                        + rtl(f"Machine uptime: {format_uptime()}")
                    )

            # --- Revitalize programs (Every minute) ---
            if config.get("keepalive") and \
                    now_ts - _last_keepalive_check >= 60:
                _last_keepalive_check = now_ts
                threading.Thread(target=check_keepalive, daemon=True).start()

            # --- Outlet monitoring RDP (Every minute) ---
            if config.get("rdp_watch", True) and \
                    now_ts - _last_rdp_check >= 60:
                _last_rdp_check = now_ts
                threading.Thread(target=check_rdp_service, daemon=True).start()

            # --- Internet monitoring (Every minute) ---
            if config.get("net_watch", True) and \
                    now_ts - _last_net_watch >= 60:
                _last_net_watch = now_ts
                threading.Thread(target=check_internet, daemon=True).start()

            # --- Firewall guarding (Eat 5 Minutes) ---
            if config.get("fw_guard", True) and \
                    now_ts - _last_fw_check >= 300:
                _last_fw_check = now_ts
                threading.Thread(target=check_firewall_guard, daemon=True).start()

            # --- Check for a newer version (Eat N hours) ---
            uch = float(config.get("update_check_hours", 0) or 0)
            if config.get("update_url") and uch > 0:
                if _last_update_check == 0:
                    _last_update_check = now_ts
                elif now_ts - _last_update_check >= uch * 3600:
                    _last_update_check = now_ts
                    threading.Thread(target=check_update_available,
                                     daemon=True).start()

            # --- Learn IP Success (Eat 10 Minutes) ---
            if config.get("auto_learn_ips", True) and \
                    now_ts - _last_learn >= 600:
                _last_learn = now_ts
                threading.Thread(target=learn_successful_ips,
                                 daemon=True).start()

            # --- Automatically terminate the lock when its duration expires ---
            # (The condition required the lock to be operational and timed out together = Impossible together,
            #  The lock remains activated forever, and the restriction rules are accumulated from an old session)
            _luntil = float(config.get("lockdown_until", 0) or 0)
            if _luntil and now_ts > _luntil \
                    and (release_thread is None or not release_thread.is_alive()):
                # The release worker clears the deadline only after success.
                # Keep failed releases eligible without overlapping workers.
                release_thread = threading.Thread(
                    target=lockdown_release, kwargs={"auto": True}, daemon=True)
                release_thread.start()

            # --- Account for transferred data (Eat 30 Again) ---
            if now_ts - _last_traffic_check >= 30:
                traffic_job()

            # --- Monitor services (Every minute) ---
            if config.get("svcwatch") and now_ts - _last_svcwatch_check >= 60:
                _last_svcwatch_check = now_ts
                threading.Thread(target=check_services, daemon=True).start()

            # --- Working hours RDP (Every minute - She was creating a new thread every 5 Seconds) ---
            if (config.get("rdphours") or config.get("rdpsched_blocked")) \
                    and now_ts - _last_rdpsched_check >= 60:
                _last_rdpsched_check = now_ts
                threading.Thread(target=rdp_schedule_tick, daemon=True).start()

            # --- Synchronization of inventory rules RDP With the current port (Eat 10 Minutes) ---
            if config.get("rdp_allow_active") \
                    and now_ts - _last_allow_sync >= 600:
                _last_allow_sync = now_ts
                threading.Thread(target=check_rdp_allow_sync,
                                 daemon=True).start()

            # --- Self-cleaning when the system disk is full ---
            if config.get("selfheal_disk") and now_ts - _last_selfheal >= 6 * 3600:
                for dev, pct, _f, _t in get_disks():
                    if dev.upper().startswith(
                            os.environ.get("SystemDrive", "C:").upper()) \
                            and pct >= 95:
                        _last_selfheal = now_ts
                        threading.Thread(target=_selfheal_job, daemon=True).start()
                        break

            # --- Heat (Every two minutes) ---
            if now_ts - _last_temp_check >= 120:
                _last_temp_check = now_ts

                def _temp_watch():
                    global _last_temp_alert
                    try:
                        temps = get_temps()
                        hot = {k: v for k, v in temps.items()
                               if v >= config.get("temp_threshold", 85)}
                        if hot and time.time() - _last_temp_alert >= 600:
                            _last_temp_alert = time.time()
                            parts = ", ".join(f"{k} {v:.0f}°C"
                                              for k, v in hot.items())
                            if not alerts_muted():
                                send_buttons(
                                    rtl("<b>HIGH TEMPERATURE</b>") + "\n"
                                    + rtl(f"{parts} - high temperature can throttle the machine, check cooling"),
                                    [[("Read temps", "run:/temp"),
                                      ("Top processes", "run:/top")]])
                    except Exception as e:
                        print(f"[temp] error: {e}")

                threading.Thread(target=_temp_watch, daemon=True).start()

            # --- Automatic session lock ---
            lock_min = int(config.get("auto_lock_minutes") or 0)
            if lock_min > 0:
                idle = idle_seconds()
                if idle >= lock_min * 60 and not _session_locked \
                        and now_ts - _last_lock_time > lock_min * 60:
                    _last_lock_time = now_ts
                    if lock_session():
                        _session_locked = True
                        send_message(
                            " <b>The session was automatically locked</b>\n"
                            f"The device was idle {lock_min} Minute\n"
                            "To disable: /set lock 0")
                elif idle < 60:
                    _session_locked = False

            # --- Automatic weekly cleaning ---
            if config.get("auto_clean_enabled") and \
                    now.weekday() == config.get("auto_clean_day", 5) and \
                    now.hour == config.get("auto_clean_hour", 3) and \
                    _last_clean_day != now.date():
                _last_clean_day = now.date()

                def _auto_clean():
                    try:
                        freed = clean_temp_files()
                        send_message("<b>Automatic weekly cleaning</b>\n"
                                     f"Edited: {format_size(freed)}")
                    except Exception as e:
                        print(f"[clean] error: {e}")

                threading.Thread(target=_auto_clean, daemon=True).start()

            # --- Periodic speed measurement ---
            hours = config.get("speedtest_interval_hours", 0)
            if hours and hours > 0 and now_ts - _last_speedtest >= hours * 3600:
                _last_speedtest = now_ts
                threading.Thread(target=speedtest_job, kwargs={"silent": True},
                                 daemon=True).start()

            # --- Daily report ---
            if config["daily_report_enabled"] and \
                    now.hour == config["daily_report_hour"] and _last_daily != now.date():
                _last_daily = now.date()
                threading.Thread(target=send_daily_report, daemon=True).start()

            # --- Weekly report ---
            if config["weekly_report_enabled"] and \
                    now.weekday() == config["weekly_report_day"] and \
                    now.hour == config["weekly_report_hour"] and \
                    _last_weekly != now.date():
                _last_weekly = now.date()
                threading.Thread(target=send_weekly_report, daemon=True).start()

        except Exception as e:
            print(f"[monitor] error: {e}")

        time.sleep(5)


# ----------------------------- Chat commands -----------------------------

def set_guide():
    """Detailed guide for all settings with current values and examples"""
    c = config
    return "\n".join([
        "<b>Settings guide</b> - The value in parentheses is the current",
        "━━━━━━━━━━━━━━━",
        "",
        "<b> Limits of tiered alerts</b>",
        "3 Levels, each one more severe than the one before it:",
        f"• <b>/set cpu 50</b> ({c['cpu_alert_threshold']}%) - Warning [WARN] For the processor",
        "   As soon as the processor exceeds the percentage, it starts sending alerts",
        f"• <b>/set ram 50</b> ({c['ram_alert_threshold']}%) - Warning [WARN] For rams",
        f"• <b>/set danger 80</b> ({c['danger_threshold']}%) - Danger ",
        f"• <b>/set critical 95</b> ({c['critical_threshold']}%) - Critical ",
        "   If you get to the point of embarrassment, it means that the device has almost stopped - We advise you to settle /top You see the reason",
        "",
        "<b> Behavior of alerts</b>",
        f"• <b>/set interval 300</b> ({c['alert_interval']} Again)",
        f"   Effective reminder: {ResourceAlertPolicy.timings(c)['reminder_seconds']} seconds (minimum 1800).",
        "   Warning: sustained for 120s; recovery: below warning by 5 points for 180s. Critical bypasses mute.",
        f"• <b>/set spike 30</b> ({c['spike_threshold']}%)",
        "   Immediate alert if the consumption rate jumps within a minute",
        "   Example: It was 20% And suddenly it happened 55% → You will receive an alert immediately without waiting",
        "   Put it down 100 If you do not want this type of alert",
        "",
        "<b> disk</b>",
        f"• <b>/set disk 90</b> ({c['disk_threshold']}%)",
        "   One warning when the disk is full to this percentage (A second warning when it returns to normal)",
        "",
        "<b> Scheduled reports</b>",
        f"• <b>/set daily on</b> ({'Activated' if c['daily_report_enabled'] else 'Disabled'}) "
        f"+ <b>/set dailyhour 20</b> ({c['daily_report_hour']}:00)",
        "   Daily report: Average and highest consumption + Chart 24 hours",
        f"• <b>/set weekly on</b> ({'Activated' if c['weekly_report_enabled'] else 'Disabled'}) "
        f"+ <b>/set weeklyday 4</b> ({AR_DAYS[c['weekly_report_day']]})",
        "   Weekly report on a specific day - Numbers: 0=Monday 1=Tuesday 2=Wednesday "
        "3=Thursday 4=Friday 5=Saturday 6=Sunday",
        "",
        "<b> Automatic speed measurement</b>",
        f"• <b>/set speedtest 6</b> ({c['speedtest_interval_hours'] or 'Disabled'})",
        "   It measures the internet speed every few hours and sends you the result (0 = Disabled)",
        "   Useful for monitoring the quality of the internet on a device RDP Remotely",
        "",
        "<b> Automatic restart</b>",
        f"• <b>/set autorestart on</b> ({'Activated' if c['auto_restart_enabled'] else 'Off'})",
        "   The device is working restart Alone in just one case:",
        "   If consumption exceeds a limit autolimit He stayed on top of it for a while autocount Continuous minutes",
        f"• <b>/set autolimit 90</b> (CPU/RAM {c['auto_restart_cpu']}%)",
        f"• <b>/set autocount 3</b> ({c['auto_restart_consecutive']} Minutes)",
        "   Complete example: autolimit 95 + autocount 5 I mean:",
        "   If the processor or RAM is higher 95% For a period 5 Minutes after each other → restart Auto",
        "   [WARN] Before returning, you will receive a message and you have it 30 Seconds to cancel with /cancel_restart",
        "",
        "<b> Activation keys (Potential security risk)</b>",
        f"• <b>/set exec on|off</b> ({'Activated' if c['exec_enabled'] else 'Disabled'})",
        "   Order /exec Runs any command CMD On the device - The most powerful and dangerous thing",
        f"• <b>/set uploads on|off</b> ({'Activated' if c['uploads_enabled'] else 'Disabled'})",
        "   Send a file to the bot = Saves on the device",
        f"• <b>/set users on|off</b> ({'Activated' if c['user_management'] else 'Off'})",
        "   Commands for creating and deleting users and changing passwords",
        "    If you don’t need these commands daily: Leave it off Activate it the moment you need it",
        f"• <b>/set accountwatch on|off</b> ({'Activated' if c.get('account_watch', True) else 'Off'})",
        "   Immediate alert upon any change in accounts: Create/Delete/Disable/Traffic whistle/"
        "Add to group — Even if it comes from outside the tool (Detects back accounts)",
        f"• <b>/set sessions on|off</b> ({'Activated' if c['session_alerts'] else 'Off'})",
        "   Immediate alert when someone enters or exits the device",
        "",
        "<b>UL  Update the tool</b>",
        f"• <b>/set update Link</b> ({'Specific' if c['update_url'] else 'Not specified'})",
        "   Direct link to file rdp_monitor.py New (Like GitHub Raw)",
        "   Then he ordered /update Safely pulls out the new copy and replaces it",
        "",
        "<b> Security</b>",
        f"• <b>/set name PC2</b> ({c.get('instance_name') or 'Without'})",
        "   The name appears before each message - It is necessary for several devices on the same chat",
        f"• <b>/set logins on|off</b> ({'Activated' if c.get('failed_login_alerts') else 'Disabled'})",
        "   Immediate alert upon failed login attempts (Testing passwords reveals RDP)",
        f"• <b>/set critical on|off</b> ({'Activated' if c.get('critical_alerts') else 'Disabled'})",
        "   Immediate alert of any critical event (Level 1) In the system log - The strongest indication of a malfunction",
        "   And complete analysis at any time: /diagnose",
        "",
        "<b> Pulse and self-monitoring</b>",
        f"• <b>/set heartbeat 6</b> ({c.get('heartbeat_hours', 6)} hours)",
        "   Message 'It still works' Every few hours - If it does not arrive, I will know that the tool has fallen (0 = Disabled)",
        f"• <b>/set rdpwatch on|off</b> ({'Activated' if c.get('rdp_watch', True) else 'Disabled'})",
        "   Outlet monitoring RDP: If the service stops listening, it will restart it and alert you",
        f"• <b>/set netwatch on|off</b> ({'Activated' if c.get('net_watch', True) else 'Disabled'})",
        f"   Internet monitoring (ping {c.get('ping_target', '1.1.1.1')}): Warning when cutting and returning",
        f"• <b>/set updatecheck {c.get('update_check_hours', 24)}</b> (hours)",
        "   Check for a newer version from the update link and alert you without installation (0 = Disabled)",
        f"• <b>/set fwguard on|off</b> ({'Activated' if c.get('fw_guard', True) else 'Disabled'})",
        "   Firewall guarding: All protection (Ban/Confinement/Lock) Depend on it -"
        " If it turns off, it activates it and notifies you immediately",
        "• <b>/mute 3h</b> - Temporarily mute regular alerts (Security and criticality remain)",
        "",
        "<b> Account for transferred data</b>",
        f"• <b>/set traffic 500</b> ({c.get('traffic_quota_gb', 0) or 'Without'} GB) - share of the month,"
        " Alert when 50% And80% And95% (0 = Without a share)",
        f"• <b>/set trafficday 1</b> ({c.get('traffic_reset_day', 1)}) - The start day of the billing cycle",
        "   Full report at any time: /traffic (My day + cycle + Another 7 days)",
        f"• <b>/set block on|off</b> ({'Activated' if c.get('failed_login_block') else 'Disabled'}) "
        f"+ <b>/set blocklimit 10</b> ({c.get('failed_login_block_threshold')})",
        "   Ban IP Automatically locks into the firewall after the specified number of attempts",
        f"• <b>/set tempalert 85</b> ({c.get('temp_threshold')}°C) - Heat alert",
        f"• <b>/set lock 15</b> ({c.get('auto_lock_minutes') or 'Disabled'})",
        "   Automatically lock the session after X minutes without use (0 = Disabled)",
        "",
        "<b> Protection RDP Additional (Ready orders)</b>",
        "• <b>/setrdpport 44389</b> - Change port RDP Completely "
        "(registry + Firewall + Close the old one)",
        "• <b>/rdpallow add IP</b> + apply - Limit contact to IP Only reliable",
        "• <b>/firewall</b> - Check firewall and open ports",
        "• <b>/netstat</b> - All active connections and who is using them",
        "",
        "<b> Automatic cleaning</b>",
        f"• <b>/set autoclean on</b> ({'Activated' if c.get('auto_clean_enabled') else 'Disabled'}) "
        f"+ <b>/set cleanday 5</b> ({AR_DAYS[c.get('auto_clean_day', 5)]})",
        "   Cleaning TEMP and Recycle Bin weekly + Report what was released",
        "   Manual cleaning at any time: /clean",
        "",
        " All settings are saved automatically and remain even after restart",
        "Display values without explanation: /status"
    ])


SET_BOUNDS = {
    "cpu": (1, 100), "ram": (1, 100), "danger": (1, 100),
    "critical": (1, 100), "disk": (10, 99), "spike": (1, 100),
    "interval": (30, 86400), "dailyhour": (0, 23),
    "weeklyday": (0, 6), "speedtest": (0, 8760),
    "autolimit": (50, 100), "autocount": (1, 60),
    "lock": (0, 1440), "tempalert": (40, 120),
    "blocklimit": (1, 100), "cleanday": (0, 6),
    "heartbeat": (0, 168), "updatecheck": (0, 8760),
    "lockdownlimit": (1, 1000), "lockdownmins": (1, 1440),
    "traffic": (0, 1000000), "trafficday": (1, 28),
}

SET_ENABLE_CONFIRM = {
    "exec": "exec_enabled", "users": "user_management",
    "image": "image_enabled", "imagedel": "image_delete_after",
    "autorestart": "auto_restart_enabled", "lockdown": "lockdown",
}


def set_overview():
    """A short index; /set all retains the complete reference."""
    return ("<b>Settings</b>\n"
            "Alerts: cpu, ram, danger, critical, disk, spike, interval\n"
            "Reports: daily, dailyhour, weekly, weeklyday, speedtest\n"
            "Access: exec, users, uploads, sessions, name, lock\n"
            "Protection: logins, block, blocklimit, lockdown, rdphours\n"
            "Automation: autorestart, autolimit, autocount, autoclean, heartbeat\n"
            "Image & cloud: image, imagedel, rclone, rcloneremote\n\n"
            "Use /set &lt;key&gt; for the current value and examples, or /set all for every setting.")


def set_key_help(key):
    entries = [line for line in set_guide().splitlines()
               if re.search(r"/set\s+" + re.escape(key) + r"(?:\s|<)", line, re.I)]
    if entries:
        return "<b>Setting: " + esc(key) + "</b>\n" + "\n".join(entries) + "\n\nChange: /set " + esc(key) + " &lt;value&gt;"
    suggestions = difflib.get_close_matches(key, SET_BOUNDS.keys(), n=3)
    return "[X] Unknown setting." + (" Did you mean: " + ", ".join(suggestions) + "?" if suggestions else "") + "\nSee /set."


# --- Settings: one validated path shared by /set and the WebConsole panel ---

# key -> config field (used to read the current value for the panel)
SET_FIELDS = {
    "cpu": "cpu_alert_threshold", "ram": "ram_alert_threshold",
    "danger": "danger_threshold", "critical": "critical_threshold",
    "disk": "disk_threshold", "spike": "spike_threshold",
    "interval": "alert_interval", "daily": "daily_report_enabled",
    "dailyhour": "daily_report_hour", "weekly": "weekly_report_enabled",
    "weeklyday": "weekly_report_day", "speedtest": "speedtest_interval_hours",
    "exec": "exec_enabled", "users": "user_management",
    "uploads": "uploads_enabled", "sessions": "session_alerts",
    "accountwatch": "account_watch", "name": "instance_name",
    "lock": "auto_lock_minutes", "logins": "failed_login_alerts",
    "block": "failed_login_block", "blocklimit": "failed_login_block_threshold",
    "tempalert": "temp_threshold", "traffic": "traffic_quota_gb",
    "trafficday": "traffic_reset_day", "autorestart": "auto_restart_enabled",
    "autolimit": "auto_restart_cpu", "autocount": "auto_restart_consecutive",
    "autoclean": "auto_clean_enabled", "heartbeat": "heartbeat_hours",
    "rdpwatch": "rdp_watch", "netwatch": "net_watch", "fwguard": "fw_guard",
    "updatecheck": "update_check_hours", "image": "image_enabled",
    "imagedel": "image_delete_after", "rcloneremote": "rclone_remote",
    "subnetblock": "subnetblock", "selfheal": "selfheal_disk",
    "newipalert": "new_ip_alerts", "learn": "auto_learn_ips",
    "learnforlockdown": "learn_for_lockdown", "lockdown": "lockdown",
    "lockdownlimit": "lockdown_limit", "lockdownmins": "lockdown_minutes",
}

# (group, [(key, label, type, min, max, unit), ...]) for the panel settings tab
SETTINGS_SCHEMA = [
    ("Alerts", [
        ("cpu", "CPU warning", "int", 1, 100, "%"),
        ("ram", "RAM warning", "int", 1, 100, "%"),
        ("danger", "Danger threshold", "int", 1, 100, "%"),
        ("critical", "Critical threshold", "int", 1, 100, "%"),
        ("disk", "Disk warning", "int", 10, 99, "%"),
        ("spike", "Sudden spike", "int", 1, 100, "%"),
        ("interval", "Requested reminder interval", "int", 30, 86400, "s"),
    ]),
    ("Reports", [
        ("daily", "Daily report", "bool", None, None, ""),
        ("dailyhour", "Daily report hour", "int", 0, 23, "h"),
        ("weekly", "Weekly report", "bool", None, None, ""),
        ("weeklyday", "Weekly report day (0=Mon)", "int", 0, 6, ""),
        ("speedtest", "Auto speed test", "int", 0, 8760, "h"),
    ]),
    ("Access", [
        ("exec", "Bot command execution (/exec)", "bool", None, None, ""),
        ("users", "User management", "bool", None, None, ""),
        ("uploads", "Receive files", "bool", None, None, ""),
        ("sessions", "Session alerts", "bool", None, None, ""),
        ("accountwatch", "Account watch", "bool", None, None, ""),
        ("name", "Device name", "text", None, None, ""),
        ("lock", "Auto-lock idle", "int", 0, 1440, "min"),
    ]),
    ("Protection", [
        ("logins", "Failed-login alerts", "bool", None, None, ""),
        ("block", "Auto-ban offenders", "bool", None, None, ""),
        ("blocklimit", "Auto-ban after", "int", 1, 100, "tries"),
        ("tempalert", "Temperature alert", "int", 40, 120, "C"),
        ("traffic", "Traffic quota", "int", 0, 1000000, "GB"),
        ("trafficday", "Billing cycle day", "int", 1, 28, ""),
        ("lockdown", "Auto lockdown", "bool", None, None, ""),
        ("lockdownlimit", "Lockdown after", "int", 1, 1000, "tries"),
        ("lockdownmins", "Lockdown duration", "int", 1, 1440, "min"),
    ]),
    ("Automation", [
        ("autorestart", "Auto restart", "bool", None, None, ""),
        ("autolimit", "Auto restart limit", "int", 50, 100, "%"),
        ("autocount", "Auto restart after", "int", 1, 60, "min"),
        ("autoclean", "Weekly cleaning", "bool", None, None, ""),
        ("heartbeat", "Heartbeat", "int", 0, 168, "h"),
        ("rdpwatch", "RDP watch", "bool", None, None, ""),
        ("netwatch", "Internet watch", "bool", None, None, ""),
        ("fwguard", "Firewall guard", "bool", None, None, ""),
        ("updatecheck", "Update check", "int", 0, 8760, "h"),
    ]),
    ("Image & cloud", [
        ("image", "System imaging", "bool", None, None, ""),
        ("imagedel", "Delete image after upload", "bool", None, None, ""),
        ("rcloneremote", "Image upload target", "text", None, None, ""),
    ]),
]


def settings_snapshot():
    """Current settings as panel-ready groups."""
    groups = []
    for gname, items in SETTINGS_SCHEMA:
        rows = []
        for key, label, typ, lo, hi, unit in items:
            field = SET_FIELDS.get(key, key)
            rows.append({"key": key, "label": label, "type": typ,
                         "min": lo, "max": hi, "unit": unit,
                         "value": config.get(field)})
            if key == "interval":
                timing = ResourceAlertPolicy.timings(config)
                rows[-1]["help"] = ("Effective reminder: %ds (minimum 1800s). Warning must persist %ds; "
                                     "recovery must persist %ds and be %d percentage points below warning. "
                                     "Danger and critical bypass the warning delay; critical bypasses mute."
                                     % (timing["reminder_seconds"], timing["warning_hold_seconds"],
                                        timing["recovery_hold_seconds"], timing["recovery_margin_percent"]))
        groups.append({"name": gname, "items": rows})
    return groups


def apply_setting(key, val):
    """Validate and apply one setting. Returns (ok, human message).

    Single source of truth for /set <key> <value> and the WebConsole panel.
    """
    key = str(key or "").strip().lower()
    val = str(val if val is not None else "")
    low = val.lower()
    if key in SET_BOUNDS and low.isdigit():
        minimum, maximum = SET_BOUNDS[key]
        if not minimum <= int(low) <= maximum:
            return False, ("%s must be between %d and %d. Nothing changed."
                           % (key, minimum, maximum))
    if key == "name" and (not val or len(val) > 48):
        return False, "Name must contain 1 to 48 characters. Nothing changed."
    if key == "rcloneremote" and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\s]*", val):
        return False, "Use a destination such as myremote:Images. Nothing changed."
    before = dict(config)
    ok = True
    if key == "cpu" and low.isdigit():
        config["cpu_alert_threshold"] = max(1, min(100, int(val)))
    elif key == "ram" and low.isdigit():
        config["ram_alert_threshold"] = max(1, min(100, int(val)))
    elif key == "danger" and low.isdigit():
        config["danger_threshold"] = max(1, min(100, int(val)))
    elif key == "critical" and low.isdigit():
        config["critical_threshold"] = max(1, min(100, int(val)))
    elif key == "disk" and low.isdigit():
        config["disk_threshold"] = max(10, min(99, int(val)))
    elif key == "spike" and low.isdigit():
        config["spike_threshold"] = max(1, min(100, int(val)))
    elif key == "interval" and low.isdigit():
        config["alert_interval"] = max(30, min(86400, int(val)))
    elif key == "daily" and low in ("on", "off"):
        config["daily_report_enabled"] = (low == "on")
    elif key == "dailyhour" and low.isdigit() and 0 <= int(val) < 24:
        config["daily_report_hour"] = int(val)
    elif key == "weekly" and low in ("on", "off"):
        config["weekly_report_enabled"] = (low == "on")
    elif key == "weeklyday" and low.isdigit():
        config["weekly_report_day"] = int(val) % 7
    elif key == "speedtest" and low.isdigit():
        config["speedtest_interval_hours"] = int(val)
    elif key == "autorestart" and low in ("on", "off"):
        config["auto_restart_enabled"] = (low == "on")
    elif key == "autolimit" and low.isdigit():
        config["auto_restart_cpu"] = max(50, min(100, int(val)))
        config["auto_restart_ram"] = max(50, min(100, int(val)))
    elif key == "autocount" and low.isdigit():
        config["auto_restart_consecutive"] = max(1, min(60, int(val)))
    elif key == "exec" and low in ("on", "off"):
        config["exec_enabled"] = (low == "on")
    elif key == "users" and low in ("on", "off"):
        config["user_management"] = (low == "on")
    elif key == "accountwatch" and low in ("on", "off"):
        config["account_watch"] = (low == "on")
    elif key == "uploads" and low in ("on", "off"):
        config["uploads_enabled"] = (low == "on")
    elif key == "image" and low in ("on", "off"):
        config["image_enabled"] = (low == "on")
    elif key == "sessions" and low in ("on", "off"):
        config["session_alerts"] = (low == "on")
    elif key == "name":
        config["instance_name"] = "" if low in ("none", "off") else val
    elif key == "lock" and low.isdigit():
        config["auto_lock_minutes"] = max(0, min(1440, int(val)))
    elif key == "tempalert" and low.isdigit():
        config["temp_threshold"] = max(40, min(120, int(val)))
    elif key == "logins" and low in ("on", "off"):
        config["failed_login_alerts"] = (low == "on")
    elif key == "critical" and low in ("on", "off"):
        config["critical_alerts"] = (low == "on")
    elif key == "block" and low in ("on", "off"):
        config["failed_login_block"] = (low == "on")
    elif key == "blocklimit" and low.isdigit():
        config["failed_login_block_threshold"] = max(1, min(100, int(val)))
    elif key == "logontypes" and re.fullmatch(r"10|3|3,10|10,3", low):
        config["failed_logon_types"] = ("10" if "10" in low and "3" not in low
                                        else "3,10" if "3" in low and "10" in low
                                        else low)
    elif key == "autoclean" and low in ("on", "off"):
        config["auto_clean_enabled"] = (low == "on")
    elif key == "cleanday" and low.isdigit():
        config["auto_clean_day"] = int(val) % 7
    elif key == "heartbeat" and low.isdigit():
        config["heartbeat_hours"] = max(0, min(168, int(val)))
    elif key == "rdpwatch" and low in ("on", "off"):
        config["rdp_watch"] = (low == "on")
    elif key == "netwatch" and low in ("on", "off"):
        config["net_watch"] = (low == "on")
    elif key == "fwguard" and low in ("on", "off"):
        config["fw_guard"] = (low == "on")
    elif key == "updatecheck" and low.isdigit():
        config["update_check_hours"] = int(val)
    elif key == "lockdown" and low in ("on", "off"):
        config["lockdown"] = (low == "on")
    elif key == "lockdownlimit" and low.isdigit():
        config["lockdown_limit"] = max(1, min(1000, int(val)))
    elif key == "lockdownmins" and low.isdigit():
        config["lockdown_minutes"] = max(1, min(1440, int(val)))
    elif key == "learn" and low in ("on", "off"):
        config["auto_learn_ips"] = (low == "on")
    elif key == "learnforlockdown" and low in ("on", "off"):
        config["learn_for_lockdown"] = (low == "on")
    elif key == "traffic" and low.isdigit():
        config["traffic_quota_gb"] = max(0, min(1000000, int(val)))
    elif key == "trafficday" and low.isdigit():
        config["traffic_reset_day"] = min(max(int(val), 1), 28)
    elif key == "rclone" and val:
        config["rclone_path"] = val
    elif key == "rcloneremote" and val:
        config["rclone_remote"] = val
    elif key == "imagedel" and low in ("on", "off"):
        config["image_delete_after"] = (low == "on")
    elif key == "subnetblock" and low in ("on", "off"):
        config["subnetblock"] = (low == "on")
    elif key == "selfheal" and low in ("on", "off"):
        config["selfheal_disk"] = (low == "on")
    elif key == "newipalert" and low in ("on", "off"):
        config["new_ip_alerts"] = (low == "on")
    elif key == "rdphours":
        if low in ("off", "none", "0"):
            config["rdphours"] = ""
        else:
            rng = _parse_hours(val)
            if rng:
                config["rdphours"] = f"{rng[0]}-{rng[1]}"
            else:
                ok = False
    elif key == "update" and val.startswith("https://"):
        config["update_url"] = val
    elif key == "updatehash" and re.fullmatch(r"[0-9a-fA-F]{64}", val):
        config["update_hash"] = val.lower()
    else:
        ok = False
    if not ok:
        return False, "Invalid value or setting. Use /set <key> for examples."
    save_config()
    changed = [(name, before.get(name), value) for name, value in config.items()
               if before.get(name) != value]
    if changed:
        details = ", ".join("%s: %s -> %s" % (name, old, new)
                            for name, old, new in changed)
        return True, "Setting saved - " + details
    return True, "No change; the setting already has that value."

HELP_TEXT = help_text(COMMAND_INFO)

BOT_MENU = telegram_menu(COMMAND_INFO)


@serialized_user_command
def handle_command(text):
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower().split("@")[0]  # Ignore @Name_Bot in groups
    args = parts[1:]

    # ---------- Monitoring ----------
    if cmd == "/view":
        send_message(format_report())

    elif cmd == "/net":
        send_message(format_net_report())

    elif cmd == "/traffic":
        days = 7
        if args and args[0].isdigit() and 1 <= int(args[0]) <= 30:
            days = int(args[0])
        send_plain(traffic_report(days))

    elif cmd == "/top":
        send_message("Operations are being analyzed...")
        send_message(format_top_report())

    elif cmd == "/chart":
        if not HAS_MATPLOTLIB:
            send_message("[X] Install matplotlib First: pip install matplotlib")
            return
        send_message("The diagram is being drawn...")
        path = make_chart(24)
        if path:
            queued = send_photo(path, " Another consumption 24 hours (Every point = Minute)",
                                cleanup=True)
            if not queued:
                try:
                    os.remove(path)
                except OSError:
                    pass
        else:
            send_message(" There is not enough data yet - Collected every minute, try after a while.")

    elif cmd == "/report":
        send_message("The report is being prepared...")
        threading.Thread(target=send_daily_report, daemon=True).start()

    elif cmd == "/rdp":
        send_message(format_rdp_report())

    elif cmd == "/listusers":
        send_message(format_users_report())

    elif cmd == "/speedtest":
        send_message("Speed is being measured (~20 Again)...")
        threading.Thread(target=speedtest_job, daemon=True).start()

    elif cmd == "/temp":
        send_message("Reading the sensors...")
        threading.Thread(target=temp_job, daemon=True).start()

    elif cmd == "/diagnose":
        hours = 24
        if args and args[0].isdigit() and 1 <= int(args[0]) <= 30:
            hours = int(args[0]) * 24
        period = f"{hours} hours" if hours < 48 else f"{hours // 24} days"
        send_message(f"Records are being analyzed (Another {period})...")

        def _diagnose_job():
            send_plain(diagnose_report(hours))

        threading.Thread(target=_diagnose_job, daemon=True).start()

    elif cmd == "/logstats":
        days = 7
        if args and args[0].isdigit() and 1 <= int(args[0]) <= 30:
            days = int(args[0])
        send_message(f"Other statistics are being compiled {days} days...")

        def _logstats_job():
            send_plain(logstats_report(days))

        threading.Thread(target=_logstats_job, daemon=True).start()

    elif cmd == "/exportlogs":
        scope = args[0].lower() if args else "all"
        if scope not in ("all", "system", "application"):
            send_message("Use: /exportlogs [all|system|application]")
            return
        send_message("Exporting error logs (It may take a minute)...")

        def _export_job():
            export_logs_job(scope)

        threading.Thread(target=_export_job, daemon=True).start()

    elif cmd == "/dumps":
        dumps = _crash_dumps()
        if not dumps:
            send_message(" It does not contain recent crash dump files (This is a good thing)")
            return
        path, size, mtime = dumps[0]
        when = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        if size > 45 * 1024 * 1024:
            send_message(f"[X] Latest file ({os.path.basename(path)}) Its size "
                         f"{format_size(size)} Greater than Telegram limit 45MB\n"
                         "Track: " + path)
            return
        send_message(f"Sending the latest dump file ({when})...")
        send_document(path, f" Malfunction dump file - {when}")

    # ---------- Control ----------
    elif cmd == "/screenshot":
        path = take_screenshot()
        if path:
            queued = send_photo(path, " A screenshot of the device", cleanup=True)
            if not queued:
                try:
                    os.remove(path)
                except OSError:
                    pass
        else:
            send_message("[X] The shot failed (Make sure you install pillow) Or the screen is locked.")

    elif cmd == "/exec":
        if not config.get("exec_enabled"):
            send_message("Order /exec Disabled. Activate it with /set exec on\n"
                         "/exec is disabled. Enable it with /set exec on")
            return
        if not args:
            send_message("Use: /exec dir C:\\ confirm\n"
                         "Usage: /exec dir C:\\ confirm\n\n"
                         "[WARN] The command is actually executed on the device — Add confirm To confirm\n"
                         "[WARN] This runs a real shell command — add confirm")
            return
        has_confirm = args[-1].lower() == "confirm"
        shell_text = text.strip().split(None, 1)[1]
        if has_confirm:
            shell_text = shell_text.rsplit(None, 1)[0] if len(args) > 1 else ""
        if not shell_text:
            send_message("Use: /exec dir C:\\ confirm\n"
                         "Usage: /exec dir C:\\ confirm\n\n"
                         "[WARN] The command is actually executed on the device — Add confirm To confirm")
            return
        if not has_confirm:
            msg = ("[WARN] Dangerous matter: Executing commands on the device.\n"
                   "To confirm click Confirm Below (Or resend with confirm):\n"
                   f"<code>/exec {esc(shell_text)} confirm</code>\n\n"
                   "[WARN] Dangerous command. Tap Confirm below to execute.")
            btns = confirm_buttons("/exec " + shell_text)
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        send_plain(exec_command(shell_text))

    elif cmd == "/kill":
        if not args:
            send_message("Use: /kill chrome")
            return
        name = args[0]
        if "confirm" not in [a.lower() for a in args[1:]]:
            msg = rtl(f"[WARN] Close all copies <b>{esc(name)}</b>? "
                      "Work that is not preserved in it is lost.")
            btns = confirm_buttons(f"/kill {name}")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        send_message(f"Closing in progress {esc(name)}...")
        killed = kill_by_name(name)
        if killed:
            send_message("[OK] has been closed:\n" + "\n".join(esc(k) for k in killed[:15]))
        else:
            send_message(f"I didn’t find any process named {esc(name)} (Exact match in name)")

    elif cmd == "/download":
        if not args:
            send_message("Use: /download C:\\path\\file.txt")
            return
        path = os.path.expanduser(os.path.expandvars(" ".join(args)))
        if not os.path.isfile(path):
            send_message(f"[X] File not found:\n{esc(path)}")
        elif os.path.getsize(path) > 45 * 1024 * 1024:
            send_message("[X] The file is larger than 45MB (Telegram limit).")
        else:
            send_message("Sending...")
            send_document(path)

    elif cmd == "/run":
        if not args:
            send_message("Use: /run notepad")
            return
        # It actually executes programs - Same as git /exec Exactly (He was running orders shell
        # With symbols like & Even with exec off!)
        if not config.get("exec_enabled"):
            send_message("/run Disabled - Activate it with /set exec on (Same key /exec)")
            return
        has_confirm = args[-1].lower() == "confirm"
        target = text.strip().split(None, 1)[1]
        if has_confirm:
            target = target.rsplit(None, 1)[0] if len(args) > 1 else ""
        if not target:
            send_message("Use: /run notepad confirm")
            return
        if not has_confirm:
            msg = rtl(f"[WARN] Run <b>{esc(target)}</b> On the device?")
            btns = confirm_buttons("/run " + target)
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        try:
            os.startfile(target)  # None shell - There is no cross-injection & | > etc
            send_message(f"I turned on: {esc(target)}")
        except Exception as e:
            send_message(f"[X] Playback failed: {esc(e)}")

    elif cmd == "/msg":
        if not args:
            send_message("Use: /msg Mission accomplished")
            return
        show_message_box(" ".join(args))
        send_message("[OK] The message is displayed on the device screen")

    elif cmd == "/logoff":
        if len(args) >= 2 and args[1].lower() == "confirm":
            name = args[0].lower()
            sess = [s for s in get_rdp_sessions()
                    if s["user"].lower() == name]
            if not sess:
                send_message(f"[X] No user session was found {esc(args[0])}. "
                             "View sessions: /rdp")
                return
            target = sess[0]
            arg = target["id"] or target["session"]
            r = subprocess.run(["logoff", arg], capture_output=True, timeout=20, creationflags=NO_WINDOW)
            if r.returncode == 0:
                send_message(f"[OK] Was fired {target['user']} From the session")
            else:
                send_message("[X] Ejection failed: "
                             + _decode_out(r.stdout).strip())
        else:
            msg = ("[WARN] The package closes its programs without saving!\n"
                   "Current sessions: /rdp\n"
                   "To confirm click Confirm Below")
            if args:
                btns = confirm_buttons(f"/logoff {args[0]}")
                if btns:
                    send_buttons(msg, btns)
                    return
            send_message(msg)

    # ---------- User management ----------
    elif cmd == "/adduser":
        if not config.get("user_management"):
            send_message("User management is disabled. Activate it with /set users on")
            return
        has_confirm = bool(args and args[-1].lower() == "confirm")
        parts = args[:-1] if has_confirm else args
        if len(parts) < 2:
            send_message("Use:\n"
                         "/adduser ahmed Pass@123 admin - Admin user\n"
                         "/adduser ahmed Pass@123 - Regular user (With validity RDP)")
            return
        name, password = parts[0], parts[1]
        role = parts[2].lower() if len(parts) >= 3 \
            and parts[2].lower() in ("admin", "user") else "user"
        if not valid_username(name):
            send_message("[X] Username is invalid (Even 20 Letters, without symbols such as / \\ [ ] : ; | < > + = , ? *)")
            return
        weak = _password_weak(password)
        if weak:
            send_message("[X] The password is weak:\n[X] Weak password:\n"
                         f"• {weak}\n\n"
                         "Use 8+ Typefaces with uppercase and lowercase letters, numbers, and symbols\n"
                         "Use 8+ chars with upper/lower case, digits and symbols")
            return
        if not has_confirm:
            msg = rtl(f"[WARN] Create an account <b>{esc(name)}</b> "
                      f"({'Supervisor' if role == 'admin' else 'Normal with RDP'})?\n"
                      "The password remains visible in the chat history!")
            btns = confirm_buttons(f"/adduser {name} "
                                   + " ".join(parts[1:3]))
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        send_message(f"Creating user {esc(name)}...")
        rc, out = run_net(["user", name, password, "/add"])
        if rc != 0:
            send_message("[X] User creation failed:\n" + out.strip())
            return
        lines = [f"[OK] User created <b>{name}</b>"]
        if role == "admin":
            _g, ok = add_to_group(name, ("Administrators",), ("admin",))
            lines.append(" Added to Administrators (Supervisor)" if ok
                         else "[WARN] The user was created, but I could not add it to the moderators - See permissions")
        else:
            _g, ok = add_to_group(name, ("Remote Desktop Users",),
                                  ("remote desktop", "Remote desktop", "rdp"))
            lines.append(" Regular user" + (" With access via RDP" if ok else ""))
        lines.append("Note: The password appears in the chat history - Change it on the machine if the chat is shared with anyone.")
        audit_record(f"Create an account {name} ({role})")
        send_message("\n".join(lines))

    elif cmd == "/deluser":
        if not config.get("user_management"):
            send_message("User management is disabled. Activate it with /set users on")
            return
        if len(args) >= 2 and args[1].lower() == "confirm":
            name = args[0]
            if not valid_username(name):
                send_message("[X] Username is invalid")
                return
            allowed, warn = last_admin_guard(name)
            if not allowed:
                send_message(warn)
                return
            rc, out = run_net(["user", name, "/delete"])
            msg = (f" User has been deleted <b>{name}</b> From the device.") if rc == 0 else \
                  ("[X] Failed to delete user:\n" + out.strip())
            if warn:
                msg = warn + "\n\n" + msg
            audit_record(f"Delete account {name}")
            send_message(msg)
        else:
            msg = ("[WARN] <b>Deletion is permanent and cannot be undone!</b>\n"
                   "[WARN] <b>Deletion is permanent!</b>\n"
                   "To confirm click Confirm Below — Or resend with confirm")
            if args:
                btns = confirm_buttons(f"/deluser {args[0]}")
                if btns:
                    send_buttons(msg, btns)
                    return
            send_message(msg)

    elif cmd == "/disableuser":
        if not config.get("user_management"):
            send_message("User management is disabled. Activate it with /set users on")
            return
        if len(args) >= 2 and args[1].lower() == "confirm":
            name = args[0]
            if not valid_username(name):
                send_message("[X] Username is invalid")
                return
            allowed, warn = last_admin_guard(name)
            if not allowed:
                send_message(warn)
                return
            rc, out = run_net(["user", name, "/active:no"])
            msg = (f" The account has been disabled <b>{name}</b> — He can’t get in, "
                   "But his files and record remain.\n"
                   "To activate: /enableuser " + name) if rc == 0 else \
                  ("[X] Account deactivation failed:\n" + out.strip())
            if warn:
                msg = warn + "\n\n" + msg
            audit_record(f"Disable account {name}")
            send_message(msg)
        else:
            msg = ("[WARN] Disabling prevents access without deleting anything (Safer than deletion).\n"
                   "[WARN] Disabling blocks login without deleting anything.\n"
                   "To confirm click Confirm Below")
            if args:
                btns = confirm_buttons(f"/disableuser {args[0]}")
                if btns:
                    send_buttons(msg, btns)
                    return
            send_message(msg)

    elif cmd == "/enableuser":
        if not config.get("user_management"):
            send_message("User management is disabled. Activate it with /set users on")
            return
        if not args:
            send_message("Use: /enableuser ahmed")
            return
        name = args[0]
        if not valid_username(name):
            send_message("[X] Username is invalid")
            return
        if "confirm" not in [a.lower() for a in args[1:]]:
            msg = rtl(f"[WARN] Activate the account <b>{esc(name)}</b> Again?")
            btns = confirm_buttons(f"/enableuser {name}")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        rc, out = run_net(["user", name, "/active:yes"])
        if rc == 0:
            audit_record(f"Activate the account {name}")
            send_message(f"[OK] The account has been activated <b>{name}</b> — He can enter again")
        else:
            send_message("[X] Account activation failed:\n" + out.strip())

    elif cmd == "/renameuser":
        if not config.get("user_management"):
            send_message("User management is disabled. Activate it with /set users on")
            return
        if len(args) < 2:
            send_message("Use: /renameuser Name_Old name_New")
            return
        old, new = args[0], args[1]
        if not valid_username(old) or not valid_username(new) \
                or "'" in old or "'" in new:
            send_message("[X] Invalid name")
            return
        if "confirm" not in [a.lower() for a in args[2:]]:
            send_buttons("Rename <b>" + esc(old) + "</b> to <b>" + esc(new) + "</b>?",
                         confirm_buttons(f"/renameuser {old} {new}"))
            return
        send_message(f"Renaming {old} → {new}...")
        ok, err = rename_local_user(old, new)
        if ok:
            send_message(f"[OK] Renamed: <b>{old}</b> → <b>{new}</b>\n"
                         "The password and permissions do not change\n"
                         "Note: The profile folder remains with the old name")
        else:
            send_message("[X] Rename failed:\n" + err[:300]
                         + "\n(Often the new name is used or the old one does not exist)")

    elif cmd == "/restart":
        if "confirm" in [a.lower() for a in args]:
            do_restart("Manual request from the user via Telegram")
        else:
            msg = rtl("[WARN] Reboot your device now?\n"
                      "(Then a window 30 seconds to cancel: /cancel_restart)")
            btns = confirm_buttons("/restart")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
    elif cmd == "/cancel_restart":
        cancel_restart()

    elif cmd == "/update":
        if "confirm" not in [a.lower() for a in args]:
            send_buttons("Start the software update?", confirm_buttons("/update"))
        else:
            threading.Thread(target=update_self, daemon=True).start()

    elif cmd == "/audit":
        if not _audit:
            send_message(" The audit log is empty")
            return
        lines = ["<b>Latest recorded transactions</b>\n"]
        for a in _audit[-15:]:
            ts = datetime.fromtimestamp(a["t"]).strftime("%m-%d %H:%M")
            lines.append(f"• {ts} — {a['e']}")
        send_message("\n".join(lines))

    elif cmd == "/blocklist":
        if not _blocked:
            send_message(" What’s in any IP Currently blocked")
        else:
            lines = ["<b>IP Blocked in firewall</b>\n"]
            for ip, ts in sorted(_blocked.items()):
                when = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
                lines.append(f"• {ip} (since {when})")
            lines.append("\nLift the ban: /unblock IP")
            send_message("\n".join(lines))

    elif cmd == "/unblock":
        if not args:
            send_message("Use: /unblock 1.2.3.4")
        elif args[0] in _blocked:
            if "confirm" not in [a.lower() for a in args[1:]]:
                send_buttons("Remove the firewall block for <b>" + esc(args[0]) + "</b>?",
                             confirm_buttons("/unblock " + args[0]))
                return
            gone = unblock_ip(args[0])
            if gone:
                send_message(f"[OK] The ban has been lifted {args[0]} Actually")
            else:
                send_message(f"[X] I was unable to remove the ban rule for {args[0]} "
                             "From the firewall — Try again or check your permissions")
        else:
            send_message(f"{args[0]} Not on the ban list")

    elif cmd in ("/block", "/blocksubnet"):
        # Manual blocking: From chat or from the hack alerts buttons
        if not args or not _valid_ip(args[0]):
            send_message("Use:\n"
                         "/block 1.2.3.4 confirm — Ban IP Final\n"
                         "/blocksubnet 1.2.3.4 confirm — Network blocking /24 Complete")
            return
        ip = args[0]
        subnet = (cmd == "/blocksubnet")
        if subnet and "." not in ip:
            send_message("[X] Network blocking supported IPv4 Only")
            return
        if "confirm" not in [a.lower() for a in args[1:]]:
            what = (f"Block the entire network {'.'.join(ip.split('.')[:3])}.x (256 Title)"
                    if subnet else f"Ban {ip}")
            msg = (rtl(f"[WARN] <b>{what}</b> Permanently in Windows Firewall.") + "\n"
                   + rtl("All communication from this address is immediately rejected - All ports.") + "\n"
                   + rtl("Make sure it is not IP Your current device!"))
            send_buttons(msg, confirm_buttons(f"/{'blocksubnet' if subnet else 'block'} {ip}"))
            return
        ok, bstat = block_subnet(ip) if subnet else block_ip(ip)
        if ok and bstat == "added":
            audit_record(("Network blocking /24: " if subnet else "Manual blocking: ") + ip)
            send_message("[OK] Banned <b>" + esc(ip) + "</b> "
                         + ("(network /24 Complete) " if subnet else "")
                         + "In the firewall\n"
                         + "List: /blocklist — Lift the ban: /unblock "
                         + (('.'.join(ip.split('.')[:3]) + '.0/24') if subnet else ip))
        elif ok:
            send_message("" + esc(ip) + " Banned before — List: /blocklist")
        else:
            send_message(f"[X] Blocking failed: {esc(bstat)}")

    elif cmd == "/allow":
        # Now declare the user ID (User ID) No chat: Members of groups do not inherit validity
        trusted = [str(t) for t in (config.get("trusted_user_ids") or [])]
        legacy = [str(t) for t in (config.get("trusted_chat_ids") or [])]
        if not args or args[0] == "list":
            send_message(
                " <b>Trusted accounts (User ID)</b>\n"
                f"Main: {config['chat_id']}\n"
                "Additional: " + (", ".join(trusted) if trusted else "There is no")
                + ("\n(legacy chat ids): " + ", ".join(legacy) if legacy else "")
                + "\n\nAddition: /allow add 123456789\n"
                "Remove: /allow del 123456789\n"
                "Trusted can send commands and receive all alerts\n"
                "[WARN] Know that a trustworthy person can give himself authority over others - Only add people you trust"
            )
        elif args[0] == "add" and len(args) >= 2 \
                and args[1].lstrip("-").isdigit():
            tid = str(args[1])
            if tid not in trusted:
                if "confirm" not in [a.lower() for a in args[2:]]:
                    send_buttons("Grant full bot control to user ID <b>" + esc(tid) + "</b>?",
                                 confirm_buttons("/allow add " + tid))
                    return
                trusted.append(tid)
                config["trusted_user_ids"] = trusted
                save_config()
                audit_record(f"Trusted addition: {tid}")
                send_message(f"[OK] Added {tid} For trusted accounts")
            else:
                send_message("Pre-existing")
        elif args[0] == "del" and len(args) >= 2 \
                and args[1].lstrip("-").isdigit():
            if args[1] in trusted:
                trusted.remove(args[1])
                config["trusted_user_ids"] = trusted
                save_config()
                audit_record(f"Reliable removal: {args[1]}")
                send_message(f"[OK] Removed {args[1]} From trusted accounts")
            else:
                send_message("It is not available")
        else:
            send_message("Use:\n/allow list\n/allow add 123456789\n/allow del 123456789")

    elif cmd == "/clean":
        if "confirm" not in [a.lower() for a in args]:
            send_buttons("Clean TEMP files and empty the Recycle Bin? Files in the Recycle Bin cannot be restored afterward.",
                         confirm_buttons("/clean"))
            return
        send_message("Cleaning in progress (Files TEMP + Recycle Bin)...")

        def _clean_now():
            try:
                freed = clean_temp_files()
                send_message(f"<b>Cleaning done</b>\n"
                             f"Space freed up: {format_size(freed)}")
            except Exception as e:
                send_message(f"[X] Cleaning error: {e}")

        threading.Thread(target=_clean_now, daemon=True).start()

    # ---------- Protection RDP Advanced ----------
    elif cmd == "/firewall":
        send_message("Reading effective RDP firewall policy; external reachability is not tested...")

        def _fw_job():
            send_message("<pre>" + esc(format_rdp_policy(get_firewall_report())) + "</pre>")

        threading.Thread(target=_fw_job, daemon=True).start()

    elif cmd == "/netstat":
        send_message("Communications are being analyzed...")
        send_message(format_netstat())

    elif cmd == "/trap":
        traps = [str(t) for t in (config.get("trap_users") or [])]
        if not args or args[0] == "list":
            send_message(
                rtl(" <b>User traps</b>") + "\n"
                + rtl("current: " + (", ".join(traps) if traps else "There is no")) + "\n"
                + rtl("Any login attempt is a trap = Instant final ban on the first attempt") + "\n"
                + rtl("Addition: /trap add Name — Delete: /trap del Name") + "\n"
                + rtl(" Write names that you never use, such as: Administrator And admin"))
        elif args[0] == "add" and len(args) >= 2:
            name = args[1]
            if name.lower() in [t.lower() for t in traps]:
                send_message(rtl("Pre-existing"))
            else:
                traps.append(name)
                config["trap_users"] = traps
                save_config()
                send_message(rtl(f"[OK] The trap <b>{esc(name)}</b> Published — "
                                 "The first person to try it gets banned immediately"))
        elif args[0] == "del" and len(args) >= 2:
            before = len(traps)
            traps = [t for t in traps if t.lower() != args[1].lower()]
            config["trap_users"] = traps
            save_config()
            send_message(rtl("[OK] I removed the trap") if len(traps) < before
                         else rtl("It doesn’t exist"))
        else:
            send_message(rtl("Use:\n/trap — The offer\n/trap add Name\n/trap del Name"))

    elif cmd == "/panic":
        if not args or args[0].lower() == "status":
            state = (" Activated — RDP Completely closed" if config.get("panic_active")
                     else "Not activated")
            send_message(rtl(f" <b>Panic mode</b>: {state}") + "\n"
                         + rtl("Run: /panic on — Off: /panic off"))
        elif args[0].lower() == "on":
            if len(args) >= 2 and args[1].lower() == "confirm":
                panic_on()
            else:
                msg = (rtl(" <b>Panic mode shuts down RDP Totally!</b>\n"
                           "All attempts to log in are blocked — Even you.\n"
                           "It remains closed until /panic off Even after reboot.\n\n"
                           "To confirm click Confirm Below"))
                btns = confirm_buttons("/panic on")
                if btns:
                    send_buttons(msg, btns)
                else:
                    send_message(msg)
        elif args[0].lower() == "off":
            if "confirm" not in [a.lower() for a in args[1:]]:
                send_buttons("[WARN] Reopen RDP by disabling panic mode?",
                             confirm_buttons("/panic off"))
            else:
                panic_off()
        else:
            send_message(rtl("Use: /panic | /panic on | /panic off"))

    elif cmd == "/harden":
        fix = bool(args and args[0].lower() == "fix")
        if fix and "confirm" not in [a.lower() for a in args[1:]]:
            msg = rtl("[WARN] <b>/harden fix</b> Modify the system: Activate NLA "
                      "Unlock the account — Confirm?")
            btns = confirm_buttons("/harden fix")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)
            return
        send_message(rtl("Immunization screening is underway..."))
        threading.Thread(target=harden_report, args=(fix,), daemon=True).start()

    elif cmd == "/bigfiles":
        send_message(rtl("The disk is being scanned (It may take a few minutes)..."))
        threading.Thread(target=bigfiles_job, daemon=True).start()

    elif cmd == "/nettest":
        if not args:
            send_message(rtl("Use: /nettest google.com"))
            return
        host = args[0]
        send_message(rtl(f"Testing in progress {esc(host)}..."))
        threading.Thread(target=nettest_job, args=(host,), daemon=True).start()

    elif cmd == "/ps":
        if not args:
            send_message(rtl("Use: /ps chrome"))
            return
        send_plain(ps_detail(" ".join(args)))

    elif cmd == "/logins":
        n = int(args[0]) if args and args[0].isdigit() and 1 <= int(args[0]) <= 30 else 10
        send_message(rtl("Reading the latest entries..."))
        threading.Thread(target=_logins_job, args=(n,), daemon=True).start()

    elif cmd == "/startup":
        send_message(rtl("Inventorying automatic start programs..."))
        threading.Thread(target=startup_job, daemon=True).start()

    elif cmd == "/sysinfo":
        send_message(rtl("Collecting system information..."))
        threading.Thread(target=_sysinfo_job, daemon=True).start()

    elif cmd == "/when":
        metric, threshold = "cpu", 80
        for a0 in args:
            if a0.lower() in ("cpu", "ram"):
                metric = a0.lower()
            elif a0.isdigit():
                threshold = int(a0)
        send_plain(when_report(metric, threshold))

    elif cmd in ("/botlog", "/getlog"):
        getlog_job()

    elif cmd == "/test":
        send_message(rtl(f"[OK] <b>Test message — I arrived!</b> "
                         f"The hour {datetime.now():%H:%M:%S}\n"
                         "Notifications channel is running 100%"))

    elif cmd == "/updates":
        send_message(rtl("Checking for Windows updates (It may take a minute)..."))
        threading.Thread(target=updates_job, daemon=True).start()

    elif cmd == "/svc":
        if len(args) >= 2 and args[0].lower() == "restart":
            name = args[1]
            if not re.fullmatch(r"[A-Za-z0-9_\- ]{1,40}", name):
                send_message(rtl("[X] Invalid service name"))
                return
            if "confirm" not in [a.lower() for a in args[2:]]:
                msg = rtl(f"[WARN] Restart the service <b>{esc(name)}</b>? "
                          "What depends on it stops momentarily")
                btns = confirm_buttons(f"/svc restart {name}")
                if btns:
                    send_buttons(msg, btns)
                else:
                    send_message(msg)
                return
            send_message(rtl(f"The service is restarting {esc(name)}..."))
            ok = ps_ok(f"Restart-Service -Name '{name}' -Force -ErrorAction Stop",
                       timeout=120)
            send_message(rtl(f"[OK] The service has been restarted {esc(name)}" if ok
                             else f"[X] Restart failed {esc(name)} "
                                  "(Correct name? Administrator powers?)"))
        else:
            send_message(rtl("Use: /svc restart Name_Service"))

    elif cmd == "/svcwatch":
        w = [dict(x) for x in (config.get("svcwatch") or [])]
        if not args or args[0] == "list":
            send_message(
                rtl(" <b>Supervised services</b>") + "\n"
                + rtl("current: " + (", ".join(x["name"] for x in w)
                                     if w else "There is no")) + "\n"
                + rtl("If the service stops, it will restart it and alert you") + "\n"
                + rtl("Addition: /svcwatch add W32Time — Delete: /svcwatch del W32Time"))
        elif args[0] == "add" and len(args) >= 2:
            name = args[1]
            if not re.fullmatch(r"[A-Za-z0-9_\- ]{1,40}", name):
                send_message(rtl("[X] Invalid service name"))
                return
            if not any(x["name"].lower() == name.lower() for x in w):
                w.append({"name": name})
            config["svcwatch"] = w
            save_config()
            send_message(rtl(f"[OK] Service <b>{esc(name)}</b> Under surveillance — "
                             "If I stop, restart it"))
        elif args[0] == "del" and len(args) >= 2:
            before = len(w)
            w = [x for x in w if x["name"].lower() != args[1].lower()]
            config["svcwatch"] = w
            save_config()
            send_message(rtl("[OK] I removed the service from monitoring") if len(w) < before
                         else rtl("It doesn’t exist"))
        else:
            send_message(rtl("Use:\n/svcwatch — The offer\n/svcwatch add Name\n"
                             "/svcwatch del Name"))

    elif cmd == "/shutdown":
        if args and args[0].lower() == "confirm":
            audit_record("Turn off the device from Telegram")
            send_message(rtl("[WARN] <b>Turn off the device during 30 Again!</b> "
                             "To cancel: /cancel_restart"))
            subprocess.run(["shutdown", "/s", "/t", "30"],
                           capture_output=True, timeout=15, creationflags=NO_WINDOW)
        else:
            msg = rtl("[WARN] Extinguishing stops everything!\n"
                      "To confirm click Confirm Below\n"
                      "To cancel after confirmation: /cancel_restart")
            btns = confirm_buttons("/shutdown")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)

    elif cmd == "/configbackup":
        threading.Thread(target=config_backup_job, daemon=True).start()

    elif cmd == "/image":
        if not args or args[0] == "status":
            st = _image_state
            if st.get("phase") == "imaging":
                send_message("<b>Imaging in progress</b>\n" + image_progress_line() +
                             "\nStop: /image stop")
            elif st.get("phase") == "uploading":
                send_message("[UP] <b>Upload in progress</b>\n"
                             "File: <code>" +
                             esc(os.path.basename(st.get("vhdx") or "")) + "</code>\n"
                             "To: <b>" + esc(st.get("remote") or "") + "</b>\n"
                             "Progress: " + str(st.get("upload_pct", 0)) + "%\n" +
                             (esc(st.get("upload_detail") or "") + "\n"
                              if st.get("upload_detail") else "") +
                             "Chart: /image chart | Stop: /image stop")
            elif st.get("phase") == "done":
                send_message("<b>Last operation</b>\n"
                             "File: <code>" +
                             esc(os.path.basename(st.get("vhdx") or "")) + "</code>\n"
                             "Upload target: " + esc(st.get("remote") or "(none)") + "\n"
                             "New image: /image start | Upload again: /image upload")
            else:
                send_message(
                    " <b>Full system image (VHDX)</b>\n"
                    "Attempts to capture the system volumes while Windows runs. "
                    "Disk2vhd may create one VHDX per physical disk. Verify every file "
                    "and test a restore in a VM before relying on the image.\n\n"
                    "Use:\n"
                    "/image start - image now + auto upload (if configured)\n"
                    "/image list - images already on this machine\n"
                    "/image upload [n|path] - upload an existing image (no new image)\n"
                    "/image chart - upload progress chart (image)\n"
                    "/image link [n|path] - Google Drive share link for an image\n"
                    "/image status • /image progress • /image stop\n\n"
                    "Needs free space equal to the used space. If no second disk exists, "
                    "the image is written to the system disk (a warning is shown).\n\n"
                    "Cloud upload setup: /rclone (install, add gdrive, set target)\n\n"
                    "After it finishes, keep all files together and perform a VM restore drill."
                )
            return
        sub = args[0].lower()
        if sub == "start":
            if not config.get("image_enabled", False):
                send_message("[X] System imaging is disabled by default for security.\n"
                             "Activate it when needed: /set image on")
                return
            has_confirm = any(a.lower() == "confirm" for a in args[1:])
            clean_args = [a for a in args[1:] if a.lower() != "confirm"]
            remote = clean_args[0] if clean_args else None
            if not has_confirm:
                msg = ("[WARN] Imaging the system is a heavy process and may consume a lot of space.\n"
                       "Make sure you have a backup and access Console Then press Confirm.")
                cmdline = "/image start" + (f" {remote}" if remote else "")
                send_buttons(msg, confirm_buttons(cmdline))
                return
            threading.Thread(target=image_start, args=(remote,),
                             daemon=True).start()
        elif sub == "stop":
            proc = _image_state.get("proc")
            phase = _image_state.get("phase")
            if phase == "imaging" and proc:
                try:
                    proc.kill()
                except Exception:
                    pass
                _image_state["phase"] = None
                _persist_image_state()
                audit_record("Imaging cancelled by user")
                send_message("<b>Imaging stopped.</b>\n"
                             "Delete the partial .vhdx manually if you wish.")
            elif phase == "uploading" and proc:
                try:
                    proc.kill()
                except Exception:
                    pass
                _image_state["phase"] = "done"
                _persist_image_state()
                audit_record("Upload cancelled by user")
                send_message("<b>Upload stopped.</b>\n"
                             "The remote may keep a partial file; re-run /image upload to finish.")
            else:
                send_message("No job is running. See /image status.")
        elif sub == "progress":
            if _image_state.get("phase") == "imaging":
                send_message("<b>Imaging</b> " + image_progress_line())
            elif _image_state.get("phase") == "uploading":
                send_message("[UP] <b>Upload</b> " + str(_image_state.get("upload_pct", 0)) +
                             "% - " + esc(os.path.basename(_image_state.get("vhdx") or "")) +
                             " -> " + esc(_image_state.get("remote") or ""))
            else:
                send_message("No job is running. See /image status.")
        elif sub == "list":
            send_message(image_list_text())
        elif sub == "chart":
            image_upload_chart()
        elif sub == "link":
            image_link(args[1:])
        elif sub == "upload":
            selection = [a for a in args[1:] if a.lower() != "confirm"]
            if "confirm" not in [a.lower() for a in args[1:]]:
                files = image_list_files()
                if selection and selection[0].isdigit() and 1 <= int(selection[0]) <= len(files):
                    path = files[int(selection[0]) - 1]
                elif selection and os.path.isfile(selection[0]):
                    path = selection[0]
                elif not selection and files:
                    path = files[0]
                else:
                    send_message("[X] Image not found. Check /image list.")
                    return
                remote = config.get("rclone_remote")
                if not remote:
                    send_message("[X] Set an image destination with /rclone set first.")
                    return
                size = os.path.getsize(path)
                preview = ("Upload this system image?\nFile: <code>" + esc(path) +
                           "</code>\nSize: " + format_size(size) +
                           "\nDestination: <code>" + esc(remote) + "</code>")
                pid = pend_store({"fn": _confirm_image_upload,
                                  "args": (path, remote, size)})
                send_buttons(preview, [[("Confirm upload", "cf:" + pid),
                                        ("Cancel", "cx:" + pid)]])
            else:
                image_upload(selection)
        else:
            send_message("Use:\n/image - help and status\n/image start [remote]\n"
                         "/image list\n/image upload [n|path]\n/image stop\n/image progress")

    elif cmd == "/setrdpport":
        current = int(config.get("rdp_port", 3389))
        if not args:
            setrdpport_wizard()
            return
        if not args[0].isdigit():
            send_message(f"Use: /setrdpport 44389\n"
                         f"Current port: {current}")
            return
        port = int(args[0])
        if not (1024 <= port <= 65535):
            send_message("[X] The port must be between 1024 And 65535")
            return
        if port == current:
            send_message("This is the already current port")
            return
        if len(args) >= 2 and args[1].lower() == "confirm":
            send_message(
                "Changing port RDP Safely...\n"
                "[WARN] Your current connection will be cut off the moment you apply")
            res = change_rdp_port(port)
            if res.get("busy"):
                send_message(f"[X] port {port} Busy with another program he’s listening to now — "
                             "Choose a different port. Nothing has changed.")
                return
            if not res.get("reg"):
                send_message("[X] Registry modification failed (Check administrator permissions) "
                             "- Nothing has changed")
                return
            if not res.get("listen"):
                send_message("[X] The new port was not listened to after the application — I blinked "
                             "automatically for the old port <b>" + str(current) + "</b> "
                             "And I restarted the service.\n"
                             "Try a second port or check the log: /botlog")
                return
            lines = [f"[OK] New port: <b>{port}</b> (Pretty sure he’s actually listening)"]
            if res.get("old"):
                lines.append(f"Close the old port {current}")
            if res.get("allow"):
                lines.append("I prepared the application of the inventory IP On the new port")
            lines.append(f"\nCall now: <b>IP:{port}</b>\n"
                         "Update the port forwarding on the router in case of interference from outside the network")
            send_message("\n".join(lines))
        else:
            msg = (
                "[WARN] <b>Change plan - Read before you confirm:</b>\n"
                f"1) port: {current} → {port}\n"
                "2) I will edit the registry + Open the port on the firewall "
                "+ Close the old port + The service was restarted RDP\n"
                "3) Your connection will be cut off - Reconnect with IP:port_New\n"
                "4) Update the port forwarding on the router if there is interference from outside the network\n\n"
                "To execute, click Confirm Below"
            )
            btns = confirm_buttons(f"/setrdpport {args[0]}")
            if btns:
                send_buttons(msg, btns)
            else:
                send_message(msg)

    elif cmd == "/rdpallow":
        port = int(config.get("rdp_port", 3389))
        ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
        active = bool(config.get("rdp_allow_active"))
        lockdown = lockdown_active()
        if not args or args[0] == "list":
            send_message(
                f" <b>Palace RDP On IP Specific</b> (port {port})\n"
                f"Status: {'Activated [OK]' if active else 'Inactive'}\n"
                "The IP allowed: " + (", ".join(ips) if ips else "There is no")
                + "\n\nAddition: /rdpallow add 1.2.3.4\n"
                "Remove: /rdpallow del 1.2.3.4\n"
                "Activate the restriction: /rdpallow apply confirm\n"
                "Cancel everything: /rdpallow clear"
            )
        elif args[0] == "add" and len(args) >= 2:
            ip = args[1]
            if not _valid_ip(ip):
                send_message("[X] IP Invalid")
            elif ip in ips:
                send_message("Pre-existing")
            else:
                ips.append(ip)
                config["rdp_allowed_ips"] = ips
                save_config()
                if lockdown:
                    # Keep the lockdown whitelist intact while locked.
                    apply_rdp_allow(lockdown_ips())
                    send_message(f"[OK] Added {ip} The rules were updated immediately")
                elif active and apply_rdp_allow(ips):
                    send_message(f"[OK] Added {ip} The rules were updated immediately")
                else:
                    send_message(f"[OK] Added {ip}\n"
                                 "Activate the restriction with /rdpallow apply confirm")
        elif args[0] == "del" and len(args) >= 2 and args[1] in ips:
            if active and not lockdown and len(ips) == 1:
                send_buttons("[WARN] This is the last allowed IP. Removing it would open RDP to every IP. Review /rdpallow clear instead.",
                             confirm_buttons("/rdpallow clear"))
                return
            ips.remove(args[1])
            config["rdp_allowed_ips"] = ips
            save_config()
            if lockdown:
                # Never disable the restriction or drop the lockdown whitelist
                # while a lockdown is still running.
                apply_rdp_allow(lockdown_ips())
                send_message(f"[OK] Removed {args[1]} And updated the rules")
            elif active:
                if ips:
                    apply_rdp_allow(ips)
                    send_message(f"[OK] Removed {args[1]} And updated the rules")
                else:
                    apply_rdp_allow([])
                    config["rdp_allow_active"] = False
                    save_config()
                    send_message("The list became empty, so I canceled the entire list")
            else:
                send_message(f"[OK] Removed {args[1]} From the list")
        elif args[0] == "apply":
            if len(args) >= 2 and args[1].lower() == "confirm":
                if not ips:
                    send_message("[X] The list is empty - Add IP First: /rdpallow add IP")
                    return
                send_message("The restriction is being activated...")
                if apply_rdp_allow(lockdown_ips() if lockdown else ips):
                    config["rdp_allow_active"] = True
                    save_config()
                    send_message(
                        f"[OK] <b>RDP Now confined</b> On the port {port} For:\n"
                        + "\n".join(f"• {ip}" for ip in ips)
                        + "\n\nYes IP The second is prevented from communicating\n"
                        "To cancel: /rdpallow clear")
                else:
                    send_message("[X] Activation of the restriction failed and all changes were rolled back "
                                 "(Check administrator permissions)"
                                 + (f"\nThe reason: {_allow_fail_info}" if _allow_fail_info else ""))
            else:
                msg = (
                    "[WARN] <b>Risk of self-blocking:</b> If the IP Who you are currently calling from "
                    "Not in the list to check connection RDP!\n"
                    "Current list: " + (", ".join(ips) if ips else "Empty")
                    + "\nTo confirm click Confirm Below"
                )
                pid = pend_store({"fn": _confirm_rdp_allow,
                                  "args": (list(ips), bool(lockdown))})
                btns = [[("Confirm - apply this list", "cf:" + pid),
                         ("Cancel", "cx:" + pid)]]
                if btns:
                    send_buttons(msg, btns)
                else:
                    send_message(msg)
        elif args[0] == "clear":
            # Unblocking opens RDP To the world - It is worth confirming
            if lockdown:
                send_message("[X] A security lockdown is active - RDP is intentionally restricted. "
                             "Release it first with /lockdown release, then clear the allow-list.")
            elif len(args) >= 2 and args[1].lower() == "confirm":
                ok, message = api_rdp_allow_clear()
                send_message(("[OK] " if ok else "[X] ") + esc(message))
            else:
                msg = (rtl("[WARN] <b>Unblocking opens RDP For any IP In the world!</b>") + "\n"
                       + rtl("Limitation protection is removed from the firewall immediately.") + "\n"
                       + rtl("The safest alternative: Edit the list with /rdpallow add|del"))
                send_buttons(msg, confirm_buttons("/rdpallow clear"))
        else:
            send_message("Use:\n/rdpallow list\n/rdpallow add 1.2.3.4\n"
                         "/rdpallow del 1.2.3.4\n/rdpallow apply confirm\n"
                         "/rdpallow clear")

    # ---------- Surveillance by name ----------
    elif cmd == "/watch":
        if not args or args[0] == "list":
            watches = config.get("watch") or []
            if not watches:
                send_message(
                    " <b>Monitor programs by name</b>\n"
                    "It alerts you if a particular program consumes more RAM than the limit you specify.\n"
                    "Example: <b>/watch add chrome 3072</b>\n"
                    "I mean: Watch ChromeIf he consumes more than 3072 Mega (3 Giga) "
                    "Notice me - The warning is repeated every time 10 Minutes as long as it exceeds the limit.\n\n"
                    "Currently: There are no programs under supervision."
                )
            else:
                lines = [" <b>Programs are under supervision</b>\n"]
                for w in watches:
                    lines.append(f"• {w['name']} - Ram limit {w['ram_mb'] / 1024:.1f} GB")
                lines.append("\nAlert when the limit is exceeded (Eat 10 Minutes maximum)")
                send_message("\n".join(lines))
        elif args[0] == "add" and len(args) >= 2:
            name = args[1]
            mb = int(args[2]) if len(args) > 2 and args[2].isdigit() else 3072
            config["watch"] = [w for w in (config.get("watch") or [])
                               if w["name"].lower() != name.lower()]
            config["watch"].append({"name": name, "ram_mb": mb})
            save_config()
            send_message(f"[OK] Added {name} To monitor "
                         f"(Ram limit {mb / 1024:.1f} GB)")
        elif args[0] == "del" and len(args) >= 2:
            before = len(config.get("watch") or [])
            config["watch"] = [w for w in (config.get("watch") or [])
                               if w["name"].lower() != args[1].lower()]
            save_config()
            if len(config["watch"]) < before:
                send_message(f"[OK] has been removed {args[1]} From surveillance.")
            else:
                send_message(f"{args[1]} I’m not under surveillance at all.")
        else:
            send_message("Use:\n/watch add chrome 3072\n/watch list\n/watch del chrome")

    elif cmd == "/mute":
        if not args:
            remaining = float(config.get("muted_until", 0) or 0) - time.time()
            if remaining > 0:
                send_message(f" Regular alerts are muted for a period of time {format_duration(remaining)}\n"
                             "Critical and security alerts are always delivered\n"
                             "To raise the mute: /mute off")
            else:
                send_message(" <b>Temporarily mute alerts</b>\n"
                             "Use:\n"
                             "/mute 3h - Mute 3 Hours\n"
                             "/mute 30m - Mute 30 Minute\n"
                             "/mute 2d - Muted for two days\n"
                             "/mute off - Unmute\n\n"
                             "The one who jokes: Consumption and surge alerts "
                             "Discs, temperature, sessions and monitoring programs\n"
                             "Who doesn’t joke: Breakthroughs, critical events, and software revivals")
            return
        if args[0].lower() in ("off", "0", "cancel"):
            config["muted_until"] = 0
            save_config()
            send_message("[OK] I lifted the mute - All alerts are back")
            return
        secs = parse_duration(args[0])
        if secs is None or secs < 60:
            send_message("[X] Invalid duration. Examples: /mute 3h Or /mute 30m Or /mute 2d")
            return
        secs = min(secs, 7 * 24 * 3600)  # Maximum one week
        config["muted_until"] = time.time() + secs
        save_config()
        send_message(f" Regular notifications are muted for a while {format_duration(secs)}\n"
                     "Critical and security alerts (Breakthroughs, critical events, software revivals) Normal delivery\n"
                     "To unmute early: /mute off")

    elif cmd == "/keepalive":
        ka = [dict(w) for w in (config.get("keepalive") or [])]
        if not args or args[0] == "list":
            if not ka:
                send_message(" <b>Automatically revive programs</b>\n"
                             "If an important program is locked, the tool launches it immediately and alerts you.\n\n"
                             "Addition: /keepalive add chrome\n"
                             "Add with run command: /keepalive add app.exe C:\\path\\app.exe\n"
                             "Currently: There is no program under revival")
            else:
                lines = [" <b>Programs under automatic revival</b>\n"]
                for w in ka:
                    lines.append(f"• {w['name']}"
                                 + (f" ({w['run']})" if w.get("run") else ""))
                lines.append("\nRemove: /keepalive del Name")
                send_message("\n".join(lines))
        elif args[0] == "add" and len(args) >= 2:
            name = args[1]
            run = " ".join(args[2:]) if len(args) > 2 else ""
            if run and not config.get("exec_enabled"):
                send_message("[X] Adding a custom run command to revive requires /set exec on\n"
                             "(Custom commands are executed via shell — Same seriousness /exec)")
                return
            ka = [w for w in ka if w["name"].lower() != name.lower()]
            ka.append({"name": name, "run": run})
            config["keepalive"] = ka
            save_config()
            send_message(f"[OK] <b>{name}</b> Under auto revive now\n"
                         "If it is locked, it will turn on immediately and you will receive an alert\n"
                         "For preview: /keepalive list")
        elif args[0] == "del" and len(args) >= 2:
            before = len(ka)
            ka = [w for w in ka if w["name"].lower() != args[1].lower()]
            config["keepalive"] = ka
            save_config()
            if len(ka) < before:
                send_message(f"[OK] Removed {args[1]} From spontaneous revival")
            else:
                send_message(f"{args[1]} Not under revival at all")
        else:
            send_message("Use:\n/keepalive add chrome\n"
                         "/keepalive add app.exe C:\\path\\app.exe\n"
                         "/keepalive list\n/keepalive del chrome")

    elif cmd == "/whitelist":
        ips = [str(i) for i in (config.get("rdp_allowed_ips") or [])]
        learned = sorted((config.get("learned_ips") or {}).keys())
        if not args or args[0] == "list":
            learned_txt = ", ".join(learned[:15]) if learned else "There is no"
            if len(learned) > 15:
                learned_txt += f" And{len(learned) - 15} Other"
            send_message(
                " <b>Whitelist for RDP</b>\n"
                "Manual: " + (", ".join(ips) if ips else "There is no")
                + "\nAutomatically learned from a successful entry (Another 14 day): " + learned_txt
                + "\n\nAutomatic learning: "
                + ("Activated" if config.get("auto_learn_ips", True) else "Disabled")
                + " (/whitelist learn on|off)\n"
                "Add manual: /whitelist add IP\nDelete: /whitelist del IP\n"
                "Permanent confinement (Without lock): /rdpallow apply confirm\n"
                "Auto lock uses this menu: /lockdown")
        elif args[0] == "learn" and len(args) >= 2 \
                and args[1].lower() in ("on", "off"):
            config["auto_learn_ips"] = (args[1].lower() == "on")
            save_config()
            send_message("[OK] Automatic learning "
                         + ("Activated - Eat IP He succeeded in entering RDP Registers for the list"
                            if config["auto_learn_ips"] else "Disabled"))
        elif args[0] == "add" and len(args) >= 2:
            ip = args[1]
            if not _valid_ip(ip):
                send_message("[X] IP Invalid")
            elif ip in ips:
                send_message("Pre-existing")
            else:
                ips.append(ip)
                config["rdp_allowed_ips"] = ips
                save_config()
                if lockdown_active():
                    apply_rdp_allow(lockdown_ips())
                    send_message(f"[OK] Added {ip} The locking rules were updated immediately")
                elif config.get("rdp_allow_active"):
                    apply_rdp_allow(ips)
                    send_message(f"[OK] Added {ip} The inventory rules were updated immediately")
                else:
                    send_message(f"[OK] Added {ip}\n"
                                 "Permanent confinement: /rdpallow apply confirm")
        elif args[0] == "del" and len(args) >= 2:
            target_ip = args[1]
            if (target_ip in ips and len(ips) == 1
                    and config.get("rdp_allow_active") and not lockdown_active()):
                send_buttons("[WARN] This is the last allowed IP. Removing it would open RDP to every IP. Review /rdpallow clear instead.",
                             confirm_buttons("/rdpallow clear"))
                return
            removed = False
            if target_ip in ips:
                ips.remove(target_ip)
                config["rdp_allowed_ips"] = ips
                removed = True
            # It is also crossed out from the educated woman — There was nothing in it that could be erased IP Educated!
            learned = dict(config.get("learned_ips") or {})
            if target_ip in learned:
                del learned[target_ip]
                config["learned_ips"] = learned
                removed = True
            if removed:
                save_config()
                if config.get("rdp_allow_active"):
                    target = lockdown_ips() if lockdown_active() else ips
                    apply_rdp_allow(target)
                    send_message(f"[OK] Removed {target_ip} (Manual and educated) And updated the rules")
                else:
                    send_message(f"[OK] Removed {target_ip} From the list")
            else:
                send_message(f"{target_ip} Not on the lists")
        else:
            send_message("Use:\n/whitelist - The offer\n/whitelist add IP\n"
                         "/whitelist del IP\n/whitelist learn on|off")

    elif cmd == "/lockdown":
        if not args:
            if lockdown_active():
                remaining = float(config.get("lockdown_until", 0)) - time.time()
                send_message(f" <b>The lock is now working</b>\n"
                             f"remaining: {format_duration(remaining)}\n"
                             f"IP Currently allowed: {len(lockdown_ips())}\n"
                             "Early cancellation: /lockdown release")
            else:
                send_message(
                    " <b>Automatic locking against intrusion waves</b>\n"
                    f"Status: {'Activated [OK]' if config.get('lockdown') else 'Disabled (Job: /lockdown on)'}\n"
                    f"It works if you arrive {config.get('lockdown_limit', 30)} Failed attempt "
                    f"Collected from all IP During {config.get('failed_login_window', 15)} Minute\n"
                    f"Duration: {config.get('lockdown_minutes', 60)} Minute (/set lockdownmins N)\n\n"
                    "When activated it shortens RDP On whitelist only "
                    "(Manual, learner only if you agree to it) Anything is prohibited IP New on the first try\n"
                    "Instant playback: /lockdown now\n"
                    "Note: This is the ideal solution against residential proxies that change IP Constantly")
            return
        sub = args[0].lower()
        if sub == "on":
            if "confirm" not in [a.lower() for a in args[1:]]:
                send_buttons("Enable automatic RDP lockdown after repeated failed logins? Review /whitelist first.",
                             confirm_buttons("/lockdown on"))
                return
            config["lockdown"] = True
            save_config()
            send_message("[OK] Auto lock is activated\n"
                         f"It will work if you arrive {config.get('lockdown_limit', 30)} "
                         "Failed attempt distributed over all IP\n"
                         "We will check your device now and add IP Your successful entry to the list...")
            threading.Thread(target=learn_successful_ips, daemon=True).start()
        elif sub == "off":
            config["lockdown"] = False
            was_active = lockdown_active()
            if was_active:
                lockdown_release()
            else:
                save_config()
                send_message("[OK] Auto lock is disabled")
        elif sub == "now":
            if lockdown_active():
                send_message("The lock is already working (/lockdown For the case)")
            elif "confirm" in [a.lower() for a in args[1:]]:
                # From the confirmation button or handwriting - Optional minutes before confirm
                mins = None
                for a in args[1:]:
                    if a.isdigit():
                        mins = int(a)
                        break
                threading.Thread(target=lockdown_start,
                                 kwargs={"minutes": mins, "manual": True},
                                 daemon=True).start()
            else:
                msg = (" <b>Manual lock shorts out RDP Whitelist immediately</b>\n"
                       "Yes IP A new person tries to enter and is banned on the first attempt.\n"
                       "Make sure that IP Your device is on the list (/whitelist)!\n\n"
                       "To confirm click Confirm Below")
                btns = confirm_buttons("/lockdown now")
                if btns:
                    send_buttons(msg, btns)
                else:
                    send_message(msg)
        elif sub == "release":
            if lockdown_active():
                lockdown_release()
            else:
                send_message("There is no lock currently working")
        else:
            send_message("Use:\n/lockdown - Status\n/lockdown on|off\n"
                         "/lockdown now [minutes]\n/lockdown release")

    # ---------- Settings ----------
    elif cmd == "/status":
        w_list = ", ".join(w["name"] for w in (config.get("watch") or [])) or "Nothing"
        send_message(
            "<b>Current settings</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"Alert limits: Warning {config['cpu_alert_threshold']}% | "
            f"Danger {config['danger_threshold']}% | "
            f"critical {config['critical_threshold']}%\n"
            f"Effective resource reminder: {ResourceAlertPolicy.timings(config)['reminder_seconds']}s "
            f"(requested {config['alert_interval']}s; minimum 1800s)\n"
            f"Sudden spike limit: {config['spike_threshold']}% Within a minute\n"
            f"Disk alert limit: {config['disk_threshold']}%\n"
            f"Daily report: {'Activated ' + str(config['daily_report_hour']) + ':00' if config['daily_report_enabled'] else 'Disabled'}\n"
            f"Weekly report: {'Activated ' + AR_DAYS[config['weekly_report_day']] if config['weekly_report_enabled'] else 'Disabled'}\n"
            f"Periodic speed measurement: {str(config['speedtest_interval_hours']) + ' hours' if config['speedtest_interval_hours'] else 'Disabled'}\n"
            f"Programs under supervision: {w_list}\n"
            f"Automatic restart: {'Activated' if config['auto_restart_enabled'] else 'Off'} "
            f"(Limit {config['auto_restart_cpu']}% For a period {config['auto_restart_consecutive']} Minutes)\n"
            f"Order /exec: {'Activated' if config['exec_enabled'] else 'Disabled'} | "
            f"Receive files: {'Activated' if config['uploads_enabled'] else 'Disabled'} | "
            f"Session alerts: {'Activated' if config['session_alerts'] else 'Off'}\n"
            f"User management: {'Activated' if config['user_management'] else 'Off'}\n"
            f"Version name: {config.get('instance_name') or 'Without'} | "
            f"Trusted accounts: {1 + len(config.get('trusted_chat_ids') or [])} | "
            f"Auto lock: {str(config.get('auto_lock_minutes')) + ' Minute' if config.get('auto_lock_minutes') else 'Disabled'}\n"
            f"Temperature limit: {config.get('temp_threshold')}°C | "
            f"Login attempts alert: {'Activated' if config.get('failed_login_alerts') else 'Disabled'} | "
            f"Auto ban: {'Activated' if config.get('failed_login_block') else 'Disabled'} "
            f"(After {config.get('failed_login_block_threshold')} try) | "
            f"Weekly cleaning: {'Activated' if config.get('auto_clean_enabled') else 'Disabled'}\n"
            f"Critical event alerts: {'Activated' if config.get('critical_alerts') else 'Disabled'}\n"
            f"The pulse: {str(config.get('heartbeat_hours', 6)) + ' hours' if config.get('heartbeat_hours') else 'Off'} | "
            f"Monitoring RDP: {'Activated' if config.get('rdp_watch', True) else 'Disabled'} | "
            f"Internet monitoring: {'Activated' if config.get('net_watch', True) else 'Disabled'}\n"
            f"Automatic revival: {', '.join(w['name'] for w in (config.get('keepalive') or [])) or 'Nothing'}\n"
            + (" Alerts are muted even "
               + f"{datetime.fromtimestamp(config.get('muted_until', 0)):%m-%d %H:%M}"
               if alerts_muted() else "Alerts: Not muffled")
            + "\n Whitelist: "
            + f"{len(config.get('rdp_allowed_ips') or [])} manual, {len(config.get('learned_ips') or {})} Educated"
            + " | Auto lock: " + ("Activated" if config.get("lockdown") else "Disabled")
            + ("\n The lock is active until "
               + f"{datetime.fromtimestamp(config.get('lockdown_until', 0)):%m-%d %H:%M}"
               if lockdown_active() else "")
        )

    elif cmd == "/set" and not args:
        send_message(set_overview())

    elif cmd == "/set" and len(args) == 1:
        send_message(set_guide() if args[0].lower() == "all" else set_key_help(args[0].lower()))

    elif cmd == "/set" and len(args) >= 2:
        key, val = args[0].lower(), args[1]
        if key == "name":
            val = " ".join(args[1:]).strip()
        low = val.lower()
        if (key in SET_ENABLE_CONFIRM and low == "on"
                and not config.get(SET_ENABLE_CONFIRM[key])
                and "confirm" not in [a.lower() for a in args[2:]]):
            send_buttons("Enable <b>" + esc(key) + "</b>? Review the effect with /set " + esc(key) + ".",
                         confirm_buttons("/set " + key + " on"))
            return
        ok, msg = apply_setting(key, val)
        send_message(("[OK] " if ok else "[X] ") + esc(msg))

    elif cmd == "/panel":
        send_panel_info()

    elif cmd == "/panelstatus":
        send_panel_status()

    elif cmd in ("/paneltoken", "/token"):
        send_panel_token()

    elif cmd == "/panelremote":
        if args and args[0].lower() in ("direct", "open", "any", "public") and "confirm" not in [a.lower() for a in args[1:]]:
            send_buttons("<b>Enable direct HTTPS access by IP:port?</b>\n"
                         "The panel will accept connections from any IPv4 address on its configured port. "
                         "Login still requires your token. Settings and the firewall rule are saved. "
                         "A self-signed certificate may show a browser warning.",
                         confirm_buttons("/panelremote direct"))
        else:
            panel_remote(" ".join(a for a in args if a.lower() != "confirm"))

    elif cmd == "/backup":
        ok, info = queue_backup_request()
        if ok:
            send_message("<b>Backup requested</b> — the SYSTEM worker will start it and "
                         "report here when it finishes.")
        else:
            send_message(f"Could not queue backup: {esc(info)}")

    elif cmd == "/backupstatus":
        send_message(backup_status_text())

    elif cmd == "/backupprogress":
        send_message(backup_progress_text())

    elif cmd == "/backupschedule":
        if not args:
            schedule_menu()
        elif args[0].lower() == "custom":
            send_message("Send: /backupschedule daily HH:MM")
        elif args[0].lower() == "off" and "confirm" not in [a.lower() for a in args[1:]]:
            send_buttons("Disable automatic backups? Manual backups remain available.",
                         confirm_buttons("/backupschedule off"))
        else:
            send_message(backup_schedule_set(args))

    elif cmd == "/cloud":
        if args and args[0].lower() == "test":
            cloud_test()
        else:
            cloud_menu()

    elif cmd == "/rclone":
        sub = args[0].lower() if args else ""
        if sub == "install":
            threading.Thread(target=rclone_install, daemon=True).start()
        elif sub == "add":
            rclone_add(args[1:])
        elif sub == "token":
            rclone_token(args[1:])
        elif sub == "gdrive":
            threading.Thread(target=rclone_gdrive, args=(args[1:],),
                             daemon=True).start()
        elif sub == "auth":
            if len(args) < 3:
                send_message("Usage: /rclone auth &lt;name&gt; &lt;type&gt;\n"
                             "Example: /rclone auth myonedrive onedrive")
            else:
                threading.Thread(target=rclone_authorize,
                                 args=(args[1], args[2]), daemon=True).start()
        elif sub == "client":
            rclone_client(args[1:])
        elif sub == "list":
            rclone_remotes_menu()
        elif sub == "test":
            rclone_test(args[1:])
        elif sub == "set":
            rclone_set(args[1:])
        elif sub == "del":
            rclone_del(args[1:])
        else:
            rclone_menu()

    elif cmd == "/backsrc":
        if not args or args[0] == "list":
            send_message(backsources_list_text())
        elif args[0] == "add" and len(args) >= 2:
            send_message(backsources_add(" ".join(args[1:])))
        elif args[0] == "remove" and len(args) >= 2:
            confirmed = args[-1].lower() == "confirm"
            token = " ".join(args[1:-1] if confirmed else args[1:])
            sources = _backsrc_sources()
            last_source = (len(sources) == 1 and
                           (token == "1" or os.path.abspath(os.path.expandvars(
                               token.strip('"'))) == os.path.abspath(sources[0])))
            if last_source and not confirmed:
                send_buttons("Remove the last backup source <code>" + esc(sources[0]) +
                             "</code>? Scheduled backups will have nothing to back up.",
                             confirm_buttons("/backsrc remove " + token))
            else:
                send_message(backsources_remove(token))
        elif args[0] == "browse":
            backsources_browse(" ".join(args[1:]) if len(args) >= 2 else None)
        elif args[0] == "drives":
            backsources_drives()
        else:
            send_message("Usage:\n/backsrc list\n/backsrc add &lt;path&gt;\n"
                         "/backsrc remove &lt;index|path&gt;\n/backsrc browse [path]\n"
                         "/backsrc drives")

    elif cmd == "/backuplist":
        send_message(backup_list_text())

    elif cmd == "/restorelist":
        send_message(restore_list_text())

    elif cmd == "/restore":
        if not args:
            send_message("Usage: /restore <archive-name> — see /restorelist")
        elif args[-1].lower() == "confirm":
            name = args[0]
            send_message(f"Restoring {esc(name)} into an isolated folder...")
            res, err = suite_restore(name)
            if err:
                send_message(f"[X] Restore failed: {esc(err)}")
            elif res and res.get("status") == "ok":
                send_message(f"<b>Restore complete</b>\n{esc(res['message'])}\n"
                             f"Folder: <code>{esc(res['dest'])}</code>")
            else:
                send_message(f"Restore issue: {esc((res or {}).get('message', ''))}")
        else:
            btns = confirm_buttons(f"/restore {args[0]}")
            if btns:
                send_buttons(f"Restore <b>{esc(args[0])}</b> into an isolated folder "
                             "under the suite? It will not overwrite the original paths.", btns)

    elif cmd == "/drill":
        if args and args[0].lower() == "confirm":
            send_message("Running a restore drill...")
            res, err = suite_drill()
            if err:
                send_message(f"[X] Drill failed: {esc(err)}")
            elif res and res.get("status") == "ok":
                send_message(f"<b>Restore drill passed</b>\n{esc(res['message'])}")
            else:
                send_message(f"Drill issue: {esc((res or {}).get('message', ''))}")
        else:
            btns = confirm_buttons("/drill")
            if btns:
                send_buttons("Run a restore drill now? It restores the newest archive into "
                             "an isolated folder and verifies it.", btns)

    elif cmd == "/start":
        show_menu_page("root")

    elif cmd == "/help":
        send_message(HELP_TEXT)

    elif cmd == "/docs":
        if args:
            send_message(docs_card_text(args[0]))
        else:
            send_message(docs_index_text())

    elif cmd == "/menu":
        show_menu_page("root")

    elif cmd == "/noop":
        send_message("Cancelled - nothing was sent to the machine.")

    else:
        send_message("Unknown command. Send /help for the menu.")


_cmd_rate = {}                     # {user_id: [ts]} To specify the command rate
_cmd_queue = None                  # Order execution queue (Prevents disabling reception)
RATE_LIMIT_CMDS = 30               # Maximum number of commands per minute per user
RATE_LIMIT_WINDOW = 60
MAX_COMMAND_QUEUE = 100            # Bound waiting work; never block Telegram polling.


def _scrub_secrets(text):
    """Hides passwords from the command text before writing them to the audit log
    - Everything after the username becomes *** (Only the first word was replaced with a password
      There are spaces that remain exposed in audit.json)"""
    return re.sub(r"(/(?:adduser|pass(?:word)?|exec|run|rclone)\b).*", r"\1 ***",
                  str(text), flags=re.I | re.S)


def _rate_limited(uid):
    """True If the user exceeds the limit of orders per minute"""
    now = time.time()
    dq = _cmd_rate.setdefault(uid, deque())
    while dq and now - dq[0] > RATE_LIMIT_WINDOW:
        dq.popleft()
    # Drop idle users so the map cannot grow without bound.
    if len(_cmd_rate) > 200:
        for k in [k for k, v in _cmd_rate.items()
                  if not v or now - v[-1] > RATE_LIMIT_WINDOW]:
            _cmd_rate.pop(k, None)
    if len(dq) >= RATE_LIMIT_CMDS:
        return True
    dq.append(now)
    return False


def record_usage(uid, action, status, request_id, duration_ms=None):
    try:
        return append_event(USAGE_FILE, source="telegram", actor="telegram:" + str(uid),
                            action=action, status=status, request_id=request_id, duration_ms=duration_ms)
    except Exception as exc:
        print(f"[audit] Usage recording failed: {type(exc).__name__}")
        return None


def _queued_action(fn, args):
    if fn in (handle_command, handle_run_callback) and args:
        command = (str(args[0]).strip().split() or ["unknown"])[0].lower().split("@")[0]
        return command if command in COMMAND_INFO else "unknown"
    if fn is handle_incoming_file:
        return "upload"
    if fn is handle_pending:
        return "confirmation"
    return "menu"


def _command_worker():
    """Executes commands from the queue in order — /exec Long does not stop receiving messages"""
    while True:
        fn, cb_args, uid, request_id = _cmd_queue.get()
        started = time.monotonic()
        status = "completed"
        try:
            fn(*cb_args)
        except Exception as e:
            status = "failed"
            try:
                send_plain(f"[X] Error executing the command: {e}")
            except Exception:
                pass
        finally:
            record_usage(uid, _queued_action(fn, cb_args), status, request_id,
                         (time.monotonic() - started) * 1000)
            _cmd_queue.task_done()


def _enqueue_command(fn, args, uid):
    """Reject excess work immediately, without storing command arguments in logs."""
    try:
        request_id = secrets.token_hex(16)
        _cmd_queue.put_nowait((fn, args, uid, request_id))
        record_usage(uid, _queued_action(fn, args), "queued", request_id)
        return True
    except queue.Full:
        audit_record(f" queue-full user {uid}")
        record_usage(uid, _queued_action(fn, args), "denied", request_id)
        return False


def telegram_loop():
    """Receive commands and files from Telegram (Long Polling)"""
    global _cmd_queue
    _cmd_queue = queue.Queue(maxsize=MAX_COMMAND_QUEUE)
    threading.Thread(target=_command_worker, daemon=True).start()
    offset = 0
    print("[telegram] listening for commands...")
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{config['telegram_token']}/getUpdates",
                params={"offset": offset, "timeout": 30,
                        "allowed_updates": '["message","callback_query"]'},
                timeout=40)
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                # ---------- Button presses (inline keyboard) ----------
                cb = update.get("callback_query")
                if cb:
                    uid = str(cb.get("from", {}).get("id", ""))
                    cbid = cb.get("id")
                    if uid not in _allowed_user_ids():
                        record_usage(uid, "authentication", "denied", secrets.token_hex(16))
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="Unauthorized")
                        continue
                    if _rate_limited(uid):
                        record_usage(uid, "rate_limit", "denied", secrets.token_hex(16))
                        audit_record(f" rate-limit user {uid}")
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="Rate limit exceeded - slow down")
                        continue
                    d = cb.get("data", "")
                    audit_record(f"{uid}: [button] {_scrub_secrets(d)[:60]}")
                    if d.startswith("run:"):
                        queued = _enqueue_command(handle_run_callback, (d[4:],), uid)
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="Queued for review" if queued else "Server busy - try again shortly")
                    elif d.startswith("cf:"):
                        queued = _enqueue_command(handle_pending, (d[3:],), uid)
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="Confirmed - queued for execution" if queued else "Server busy - try again shortly")
                    elif d.startswith("cx:"):
                        pend_take(d[3:])
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="Canceled - Nothing was implemented")
                    else:
                        queued = _enqueue_command(handle_menu_callback, (d,), uid)
                        tg_api("answerCallbackQuery", callback_query_id=cbid,
                               text="" if queued else "Server busy - try again shortly")
                    continue
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                cid = str(chat.get("id"))
                uid = str(msg.get("from", {}).get("id", ""))
                # Always declare the user ID from.id — Group chat is not granted
                # Never powers: If the main chat was a group, every member of it was
                # He can order the device. Groups are intended for alerts only — To control add
                # Your personal ID /allow add (Or use private chat mainly)
                allowed = uid in _allowed_user_ids() or (
                    chat.get("type") == "private"
                    and cid in _allowed_user_ids())
                if not allowed:
                    record_usage(uid, "authentication", "denied", secrets.token_hex(16))
                    audit_record(f" denied chat {cid} user {uid}")
                    continue
                if _rate_limited(uid):
                    record_usage(uid, "rate_limit", "denied", secrets.token_hex(16))
                    audit_record(f" rate-limit user {uid}")
                    send_message(" Large number of orders within a minute — Slow down\n"
                                 " Rate limit exceeded — slow down")
                    continue
                if msg.get("document") or msg.get("photo"):
                    audit_record(f"{uid}: [File/Image]")
                    if not _enqueue_command(handle_incoming_file, (msg,), uid):
                        send_message("Server busy - file was not queued; try again shortly")
                    continue
                text = msg.get("text", "")
                if text.startswith("/"):
                    audit_record(f"{uid}: {_scrub_secrets(text)[:80]}")
                    # Remove messages containing credentials when Telegram grants
                    # the bot deletion rights; report failure so users can delete them.
                    if re.match(r"^/(?:pass(?:word)?|adduser|rclone\s+(?:add|token|client))\s", text, re.I):
                        deleted = tg_api("deleteMessage", chat_id=cid,
                                         message_id=msg.get("message_id"))
                        if not deleted.get("ok"):
                            send_message("[WARN] Telegram did not delete the credential message. Remove it from chat history and rotate the secret if this chat is shared.")
                    if not _enqueue_command(handle_command, (text,), uid):
                        send_message("Server busy - command was not queued; try again shortly")
        except Exception as e:
            print(f"[telegram] listen error: {e}")
            time.sleep(3)


# ----------------------------- Unpack system changes ( uninstall) -----------------------------

def _cleanup_system_changes():
    """Unpacks the security changes that the tool has applied to the system — Before uninstalling:
    - Deletes rules: Panic, scheduling, blocking, and legacy port blocking — And restores the base
      The public port does not even remain RDP Clogged after the tool is gone
    - Returns the default inbound policy as it was before the enumeration and restores broken rules
    - It will not be removed (On purpose): outlet RDP Allocated, created accounts, files Disk2vhd —
      and blocking rules IP Protection remains useful only with --purge-blocks"""
    port = _rdp_registry_port() or int(config.get("rdp_port", 3389))
    print(f"[cleanup] restoring firewall state for RDP port {port} ...")
    ok_all = True
    # Never discard an active allow-list by default. Opening RDP to every
    # source requires the explicit --remove-allowlist option.
    keep_allow = (bool(config.get("rdp_allow_active")) or
                  "--keep-allowlist" in sys.argv[1:]) and \
                 "--remove-allowlist" not in sys.argv[1:]
    if keep_allow and not config.get("rdp_allow_active"):
        print("[cleanup] FAILED - no active IP allow-list is recorded; cannot preserve one")
        return False
    names = [PANIC_RULE, SCHED_RULE, RDP_BLOCK_RULE, "RDPMonitor Old RDP Port Block"]
    if not keep_allow:
        names += [RDP_ALLOW_RULE, RDP_ALLOW_TCP_RULE, RDP_ALLOW_UDP_RULE,
                  RDP_STAGE_TCP_RULE, RDP_STAGE_UDP_RULE]
    for name in names:
        ok, err = _netsh(["advfirewall", "firewall", "delete", "rule",
                          f"name={name}"])
        if not ok:
            ok_all = False
            print(f"[cleanup] failed deleting {name}: {err}")
    # Clean up old global port rules first so that duplicates do not accumulate
    ok, err = _netsh(["advfirewall", "firewall", "delete", "rule",
                      f"name=RDPMonitor RDP {port}"])
    if not ok:
        ok_all = False
        print(f"[cleanup] failed deleting generic RDP rule: {err}")
    if not keep_allow:
        # These rules and policies were disabled precisely because they
        # bypass the IP allow-list. Do not reactivate them while retaining it.
        for rname in (config.get("rdpallow_disabled_rules") or []):
            if not _enable_saved_rule(rname):
                ok_all = False
                print(f"[cleanup] failed re-enabling firewall rule: {rname}")
        for prof, act in (config.get("pre_default_inbound") or {}).items():
            if not ps_ok(f"Set-NetFirewallProfile -Profile '{_ps_quote(prof)}' "
                         f"-DefaultInboundAction {act} -ErrorAction Stop", timeout=60):
                ok_all = False
                print(f"[cleanup] failed restoring profile {prof} to {act}")
    if keep_allow:
        print("[cleanup] IP allow-list rules and disabled broad rules retained; "
              "verify the effective firewall policy manually")
    else:
        generic_ok, err = _create_general_rdp_rule(port)
        if generic_ok:
            print(f"[cleanup] RDP allow rule restored on port {port}")
        else:
            ok_all = False
            print(f"[cleanup] failed restoring RDP allow rule: {err}")
        print("[cleanup] WARNING: the IP allow-list restriction was REMOVED and a general RDP")
        print("         allow rule was created, so RDP is now open to ANY source.")
        print("         To preserve an active restriction, do not pass --remove-allowlist.")
    if "--purge-blocks" in sys.argv[1:]:
        load_blocked()
        for ip in list(_blocked.keys()):
            if not unblock_ip(ip):
                ok_all = False
                print(f"[cleanup] failed purging IP block: {ip}")
        print("[cleanup] IP block purge completed")
    print("[cleanup] NOT reverted (intentionally): custom RDP port, created")
    print("         users, downloaded tools. Current RDP port is from registry.")
    if not keep_allow:
        print("[cleanup] NOTE: unrestricted RDP is possible; review the effective rules.")
    if ok_all:
        print("[cleanup] done")
    else:
        print("[cleanup] FAILED - one or more changes were not restored")
    return ok_all


# ----------------------------- Operating -----------------------------

def main():
    # Cleaning mode: python rdp_monitor.py --cleanup [--purge-blocks]
    # Unpacks the tool’s changes to the system without running monitoring (to use uninstall)
    if "--cleanup" in sys.argv[1:]:
        load_config()
        if not CONFIG_LOAD_OK:
            print("[cleanup] FAILED - no valid saved configuration; refusing to change "
                  "firewall rules without knowing the active RDP allow-list")
            return 1
        if not acquire_instance_lock():
            print("[cleanup] FAILED - the monitor is still running; stop it before cleanup")
            return 1
        return 0 if _cleanup_system_changes() else 1

    # Permanent record: All outputs print Reach the console (If any) And to file rdp_monitor.log
    # - Addresses disappearance of errors when running with pythonw Without window
    for retained in (LOG_FILE, LOG_FILE + ".old"):
        scrub_file(retained)
    sys.stdout = _TeeWriter(sys.stdout)
    sys.stderr = _TeeWriter(sys.stderr)

    # Prevent running two copies (Important because the tool runs automatically when you log in)
    if not acquire_instance_lock():
        print("RDP Monitor is already running in the background - not starting a second copy.")
        # Without this message, the window closes immediately and the user does not know why
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "The tool is already running in the background [OK]\n\n"
                   "You don’t need to operate it manually - Control it from Telegram.\n"
                   "To check its condition: Send /status For bot\n"
                   "Or from CMD: python autostart.py status",
                "RDP Monitor", 0x40000)
        except Exception:
            pass
        return

    load_config()
    if not config.get("telegram_token") or not config.get("chat_id"):
        first_time_setup()
    _harden_config_acl()
    _harden_dir_acl()

    global _last_speedtest
    _last_speedtest = time.time()
    load_history()
    load_audit()
    load_blocked()
    load_traffic()
    load_alert_queue()
    recover_image_state()

    # If panic mode is already activated - We reapply the lockout rule
    if config.get("panic_active"):
        threading.Thread(target=panic_rearm, daemon=True).start()

    print("=" * 60)
    print("  RDP Monitor v4.3-fixed is running - press Ctrl+C to stop")
    print("=" * 60)
    print(f"  matplotlib: {'available' if HAS_MATPLOTLIB else 'not installed (required for /chart)'}")
    print("  token: DPAPI-encrypted at rest")

    cpu, ram_pct, used_gb, total_gb = get_usage()
    print(f"  CPU: {cpu:.1f}%  |  RAM: {ram_pct:.1f}% "
          f"({used_gb:.1f}/{total_gb:.1f} GB)")

    label = "RDP Monitor"
    if config.get("instance_name"):
        label += f" ({config['instance_name']})"
    send_message(
        f"<b>{label} is UP</b>\n"
        f"CPU: {cpu:.1f}%\n"
        f"RAM: {ram_pct:.1f}% ({used_gb:.2f}/{total_gb:.2f} GB)\n"
        f"Machine uptime: {format_uptime()}\n\n"
        f"Alert thresholds: warn {config['cpu_alert_threshold']}% / "
        f"danger {config['danger_threshold']}% / "
        f"critical {config['critical_threshold']}%\n"
        "Send /help for the full command reference."
    )

    # Startup report: Last extinguished status + Blue screens + Dump files
    threading.Thread(target=boot_report, daemon=True).start()

    # List of bot commands in the Telegram interface (Menu button )
    threading.Thread(
        target=tg_api, args=("setMyCommands",),
        kwargs={"commands": BOT_MENU}, daemon=True).start()

    # Queue pending alerts: Resend what failed during an internet outage
    threading.Thread(target=_drain_alert_queue, daemon=True).start()

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    t = threading.Thread(target=account_events_loop, daemon=True)
    t.start()
    # Relay backup results through this unified bot (the backup bot is retired).
    threading.Thread(target=backup_relay_loop, daemon=True).start()
    # Live progress message for running backups.
    threading.Thread(target=backup_live_loop, daemon=True).start()
    # Execute WebConsole panel requests (RDP security actions).
    threading.Thread(target=monitor_control_loop, daemon=True).start()
    # Generate the documentation database (docs/COMMANDS.md).
    try:
        generate_docs_file()
    except Exception:
        pass

    try:
        telegram_loop()
    except KeyboardInterrupt:
        print("\nStopped.")
        save_history()
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
