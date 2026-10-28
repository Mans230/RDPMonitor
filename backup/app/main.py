# -*- coding: utf-8 -*-
"""VPS Backup Tool — main entry point.

Modes:
    python main.py            → modern English GUI (CustomTkinter, dark/light)
    python main.py --now      → immediate backup without GUI
    python main.py --daemon   → background mode (schedule + bot, no GUI) — for autostart
"""

import os
import sys
import time
import queue
import threading
import inspect
import subprocess
import json
import secrets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import load_config, save_config
from logger_utils import log, read_recent_logs
import cloud_uploader
from telegram_bot import TelegramManager
from scheduler import DailyScheduler, run_with_retries, last_successful_run, last_summary
import scheduler as scheduler_module
from i18n import tr, set_language, get_language

APP_NAME = "VPS Backup Tool"
ACCENT = "#14b8a6"          # calm teal accent
ACCENT_HOVER = "#0d9488"

# ---- crash diagnostics: No collapse (Even with pythonw No console) It is recorded in the log ----
def _install_crash_hooks():
    import traceback
    import faulthandler
    try:
        crash_file = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "logs", "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(crash_file)
    except Exception:
        crash_file = None
    def _thread_hook(args):
        log(f"Thread '{args.thread.name}' crashed: "
            f"{traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)}", "ERROR")
    def _sys_hook(t, v, tb):
        log(f"FATAL unhandled exception: {traceback.format_exception(t, v, tb)}", "ERROR")
    try:
        threading.excepthook = _thread_hook
        sys.excepthook = _sys_hook
    except Exception:
        pass
    return crash_file

_install_crash_hooks()

_tg_ref = [None]
_lock_ref = [None]  # keeps the single-instance lock alive for the whole run
TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROL_DIR = os.path.join(TOOL_ROOT, "control")
CONTROL_REQUEST = os.path.join(CONTROL_DIR, "request.json")
CONTROL_STATUS = os.path.join(CONTROL_DIR, "status.json")
CONTROL_PROGRESS = os.path.join(CONTROL_DIR, "progress.json")
_control_status_lock = threading.Lock()


def _write_control_progress(data):
    """Publish live backup progress for the unified bot and the panel."""
    os.makedirs(CONTROL_DIR, exist_ok=True)
    payload = dict(data)
    payload["updated"] = time.time()
    tmp = CONTROL_PROGRESS + "." + secrets.token_hex(4) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True)
        os.replace(tmp, CONTROL_PROGRESS)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _progress_cb(kind):
    """Return a progress callback that writes control/progress.json."""
    def cb(percent, message):
        try:
            _write_control_progress({"state": "running", "kind": kind,
                                     "percent": int(percent or 0),
                                     "message": str(message)[:200]})
        except Exception:
            pass
    return cb

def trd(key, **kwargs):
    """Return an English UI message."""
    return tr(key, **kwargs)


def disp(text):
    """Return display text unchanged."""
    return text


def acquire_instance_lock():
    """Single-instance lock: returns a handle if we are the only running copy, else None."""
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.lock")
    try:
        fh = open(lock_path, "a+b")
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_ref[0] = fh
        return fh
    except OSError:
        return None


def notify(title, message):
    """Windows toast notification via plyer — never crashes (e.g. on Linux)."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name=APP_NAME, timeout=8)
    except Exception:
        pass


def call_with_supported_kwargs(func, *args, **kwargs):
    """Call func passing only the kwargs its signature actually accepts.

    Keeps the GUI compatible with both the old core (no cancel_event) and the
    new core contracts (progress_cb(percent, message), cancel_event).
    """
    try:
        params = inspect.signature(func).parameters
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in params}
    except (TypeError, ValueError):
        pass
    return func(*args, **kwargs)


def make_progress_adapter(sink):
    """Adapt both progress_cb styles into sink(percent_or_None, message).

    New core: progress_cb(percent:int, message:str) — old core: progress_cb(message:str).
    """
    def _adapter(*args):
        percent, message = None, ""
        if len(args) >= 2:
            percent, message = args[0], args[1]
            try:
                percent = max(0, min(100, int(percent)))
            except (TypeError, ValueError):
                percent, message = None, " ".join(str(a) for a in args)
        elif args:
            message = args[0]
        sink(percent, str(message))
    return _adapter


def wait_for_pending_uploads(tg, timeout=4 * 3600):
    """Wait until Telegram uploads finish before exiting (--now mode)."""
    try:
        bot_alive = tg.is_configured() and getattr(tg, "_running", False)
    except Exception:
        bot_alive = True
    if not bot_alive:
        return  # nothing will be uploaded — no reason to wait
    grace = time.time() + 10
    while time.time() < grace and getattr(tg, "active_uploads", 0) == 0:
        time.sleep(1)  # give queued sends a chance to start
    wait_fn = getattr(tg, "wait_pending_uploads", None)
    if callable(wait_fn):
        try:
            wait_fn(timeout=timeout)
            return
        except TypeError:
            try:
                wait_fn(timeout)
                return
            except Exception:
                pass
        except Exception:
            pass
    # Fallback for cores without wait_pending_uploads
    deadline = time.time() + timeout
    while getattr(tg, "active_uploads", 0) > 0 and time.time() < deadline:
        time.sleep(5)


def load_and_prepare_config():
    """load_config + Install path rclone.conf (Save it until you find it SYSTEM Later)."""
    import config_manager
    cfg = load_config()
    if not config_manager.LOAD_OK:
        log(tr("core.config.load_error", err="config.json is not valid JSON"), "ERROR")
    try:
        if cloud_uploader.configure(cfg) and config_manager.LOAD_OK:
            save_config(cfg)
    except Exception as e:
        log(f"rclone config detection failed: {e}", "WARN")
    try:
        if not config_manager.harden_backup_assets(cfg):
            log("ACL hardening failed for one or more backup assets; review filesystem permissions.", "WARN")
    except Exception as e:
        log(f"ACL hardening failed: {e}", "WARN")
    return cfg


def _telegram_creds(cfg):
    t = cfg.get("telegram", {}) or {}
    return (t.get("bot_token"), t.get("api_id"), t.get("api_hash"),
            t.get("chat_id"), t.get("bot_enabled"))


def _config_watch(cfg, tg=None):
    """Reload config.json when the GUI/panel changes it, and re-detect rclone.

    The daemon previously loaded the config once at startup, so GUI edits to
    sources, schedule, credentials, or destinations never reached the worker.
    If Telegram credentials changed, the client is reconnected with the new ones.
    """
    import config_manager
    try:
        last = os.path.getmtime(config_manager.CONFIG_FILE)
    except OSError:
        last = 0
    creds = _telegram_creds(cfg)
    while True:
        time.sleep(5)
        try:
            mtime = os.path.getmtime(config_manager.CONFIG_FILE)
        except OSError:
            continue
        if mtime == last:
            continue
        last = mtime
        try:
            new = config_manager.load_config()
            if not config_manager.LOAD_OK:
                log("Invalid configuration on disk; keeping the last working settings", "ERROR")
                continue
            cloud_uploader.configure(new)
            cfg.clear()
            cfg.update(new)
            log("Configuration reloaded from disk (revision %d)"
                % config_manager.config_revision(cfg))
            if tg is not None and _telegram_creds(cfg) != creds:
                creds = _telegram_creds(cfg)
                try:
                    tg.stop()
                    tg.start()
                    log("Telegram client reconnected after credential change")
                except Exception as e:
                    log(f"Telegram reconnect failed: {e}", "WARN")
        except Exception as e:
            log(f"Config reload failed: {e}", "WARN")


def write_pid_file():
    try:
        pid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.pid")
        with open(pid_path, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def backup_status_of(result, cancel_event=None):
    """Normalize a run_with_retries result into a display status.

    Returns 'ok' | 'partial' | 'cancelled' | 'busy' | 'error'. "partial" means an
    archive exists but files were unreadable or a destination failed.
    """
    if result is True or result == "ok":
        return "ok"
    if result in ("partial", "warn"):
        return "partial"
    if result == "busy":
        return "busy"
    if result == "cancelled" or (cancel_event is not None and cancel_event.is_set()):
        return "cancelled"
    return "error"


def _write_control_status(data):
    """Atomically publish non-secret worker status for the suite UI."""
    os.makedirs(CONTROL_DIR, exist_ok=True)
    payload = dict(data)
    payload["updated"] = time.time()
    tmp = CONTROL_STATUS + "." + secrets.token_hex(4) + ".tmp"
    with _control_status_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True)
        os.replace(tmp, CONTROL_STATUS)


def _status_heartbeat(cfg):
    """Reflect scheduled as well as WebConsole-triggered backup activity."""
    import config_manager
    while True:
        try:
            current = {}
            if os.path.isfile(CONTROL_STATUS):
                with open(CONTROL_STATUS, "r", encoding="utf-8") as f:
                    current = json.load(f)
            version = config_manager.config_version(cfg)
            revision = config_manager.config_revision(cfg)
            busy = scheduler_module.is_busy()
            # Finalize the live progress file when a job is no longer running.
            if not busy and os.path.isfile(CONTROL_PROGRESS):
                try:
                    with open(CONTROL_PROGRESS, "r", encoding="utf-8") as f:
                        prog = json.load(f)
                    if prog.get("state") == "running":
                        prog["state"] = "done"
                        prog["percent"] = 100
                        prog["message"] = "Finished"
                        _write_control_progress(prog)
                except Exception:
                    pass
            if busy and current.get("state") != "running":
                _write_control_status({"state": "running", "pid": os.getpid(),
                                       "config_version": version,
                                       "config_revision": revision,
                                       "message": "Backup job in progress"})
            elif not busy and current.get("state") == "running" \
                    and not os.path.exists(CONTROL_REQUEST):
                _write_control_status({"state": "idle", "pid": os.getpid(),
                                       "config_version": version,
                                       "config_revision": revision,
                                       "message": "Worker ready"})
            elif (current.get("config_version") != version
                  or current.get("config_revision") != revision):
                _write_control_status({**current, "config_version": version,
                                       "config_revision": revision})
        except Exception:
            pass
        time.sleep(2)


def _drill_loop(cfg):
    """Run a periodic restore drill and report the result through the log."""
    import restore as restore_mod
    state_path = os.path.join(os.path.dirname(CONTROL_DIR), "logs", "last_drill.json")
    while True:
        time.sleep(3600)
        try:
            d = cfg.get("restore_drill", {}) or {}
            if not d.get("enabled"):
                continue
            interval = max(1, int(d.get("interval_days", 7)))
            last = 0.0
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    last = float(json.load(f).get("ts", 0))
            except Exception:
                last = 0.0
            if time.time() - last < interval * 86400:
                continue
            res = restore_mod.run_drill(cfg, d.get("dest") or "", log=log)
            try:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump({"ts": time.time(), "status": res.get("status"),
                               "archive": res.get("archive"),
                               "message": res.get("message")}, f)
            except OSError:
                pass
        except Exception as e:
            log("Restore drill error: %s" % e, "ERROR")


def daemon_running():
    """True when the SYSTEM/background worker is alive (so jobs must be queued)."""
    try:
        pid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.pid")
        with open(pid_path, "r", encoding="ascii") as f:
            pid = int(f.read().strip())
    except Exception:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def queue_control_backup(requested_by="gui"):
    """Queue a manual backup for the running worker instead of running one here.

    Prevents the GUI and the daemon from starting two backups at the same time.
    """
    os.makedirs(CONTROL_DIR, exist_ok=True)
    lock_path = CONTROL_REQUEST + ".lock"
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
        if os.path.exists(CONTROL_REQUEST):
            return False, "a backup request is already pending"
        rid = secrets.token_hex(9)
        tmp = CONTROL_REQUEST + "." + secrets.token_hex(4) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "id": rid, "action": "backup",
                       "created": time.time(), "requested_by": requested_by}, f)
        os.replace(tmp, CONTROL_REQUEST)
        return True, rid
    finally:
        os.close(fd)
        try:
            os.remove(lock_path)
        except OSError:
            pass


def _reconcile_control():
    """Recover a request left mid-flight by a crash so it is not silently lost."""
    try:
        names = [n for n in os.listdir(CONTROL_DIR)
                 if n.startswith("processing-") and n.endswith(".json")]
    except OSError:
        names = []
    for name in names:
        path = os.path.join(CONTROL_DIR, name)
        try:
            if not os.path.exists(CONTROL_REQUEST):
                os.replace(path, CONTROL_REQUEST)
                log("Recovered an interrupted backup request; it will run again.")
                return
        except OSError:
            pass
        try:
            os.remove(path)
        except OSError:
            pass


def _control_loop(cfg, tg):
    """Process validated local requests written by the hardened WebConsole."""
    os.makedirs(CONTROL_DIR, exist_ok=True)
    _reconcile_control()
    _write_control_status({"state": "idle", "pid": os.getpid(), "message": "Worker ready"})
    while True:
        if not os.path.isfile(CONTROL_REQUEST):
            time.sleep(2)
            continue
        claimed = os.path.join(CONTROL_DIR, "processing-%d-%s.json" %
                               (os.getpid(), secrets.token_hex(4)))
        try:
            os.replace(CONTROL_REQUEST, claimed)
            with open(claimed, "r", encoding="utf-8") as f:
                request = json.load(f)
            request_id = str(request.get("id", ""))[:80]
            if request.get("action") != "backup" or not request_id:
                raise ValueError("unsupported control request")
            _write_control_status({"state": "running", "pid": os.getpid(),
                                   "request_id": request_id,
                                   "message": "Manual backup started"})
            # Apply the latest config (sources added from the bot/panel) before
            # running, so a just-added source is not missed.
            try:
                import config_manager as _cm
                _fresh = _cm.load_config()
                cloud_uploader.configure(_fresh)
                cfg.clear()
                cfg.update(_fresh)
            except Exception as e:
                log("Config refresh before job failed: %s" % e, "WARN")
            _write_control_progress({"state": "running", "kind": "manual",
                                     "percent": 0, "message": "Starting backup"})
            result = call_with_supported_kwargs(
                run_with_retries, cfg, tg=tg, manual=True,
                progress_cb=_progress_cb("manual"))
            state = backup_status_of(result)
            _write_control_progress({"state": "done" if state == "ok" else "error",
                                     "kind": "manual",
                                     "percent": 100 if state == "ok" else 0,
                                     "message": "Finished (%s)" % state})
            _write_control_status({"state": state, "pid": os.getpid(),
                                   "request_id": request_id,
                                   "message": {"ok": "Manual backup finished",
                                               "partial": "Manual backup finished with warnings",
                                               "cancelled": "Manual backup cancelled",
                                               "busy": "Another backup was already running"}
                                              .get(state, "Manual backup did not complete")})
        except Exception as e:
            _write_control_status({"state": "error", "pid": os.getpid(),
                                   "message": str(e)[:300]})
            log("Suite control request failed: %s" % e, "ERROR")
        finally:
            try:
                os.remove(claimed)
            except OSError:
                pass


# ====================== Headless / immediate modes ======================

def run_headless(now=False):
    if acquire_instance_lock() is None:
        msg = "Another instance of the tool is already running."
        print(msg)
        log(msg, "WARN")
        return
    cfg = load_and_prepare_config()
    set_language("en")
    tg = TelegramManager(cfg, job_runner=lambda manual=True: run_with_retries(cfg, tg=_tg_ref[0], manual=True))
    _tg_ref[0] = tg
    tg.start()
    if now:
        result = call_with_supported_kwargs(run_with_retries, cfg, tg=tg, manual=True)
        status = backup_status_of(result)
        if status == "ok":
            notify(tr("ui.notify.ok_title"), tr("ui.notify.ok_body"))
        elif status == "cancelled":
            notify(tr("ui.notify.cancel_title"), tr("ui.notify.cancel_body"))
        elif status == "partial":
            notify(tr("ui.notify.warn_title"), tr("ui.notify.warn_body"))
        else:
            notify(tr("ui.notify.fail_title"), tr("ui.notify.fail_body"))
        # let Telegram uploads finish before exiting
        wait_for_pending_uploads(tg)
        return
    write_pid_file()
    scheduler = DailyScheduler(cfg, tg=tg, announce=True,
                               progress_cb=_progress_cb("scheduled"))
    scheduler.start()
    threading.Thread(target=_control_loop, args=(cfg, tg),
                     name="suite-control", daemon=True).start()
    threading.Thread(target=_status_heartbeat, args=(cfg,), name="suite-status",
                     daemon=True).start()
    threading.Thread(target=_config_watch, args=(cfg, tg),
                     name="config-watch", daemon=True).start()
    threading.Thread(target=_drill_loop, args=(cfg,),
                     name="restore-drill", daemon=True).start()
    log("Running in background mode — press Ctrl+C to stop")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        scheduler.stop()


# ====================== GUI (CustomTkinter) ======================

def run_gui():
    import customtkinter as ctk

    cfg = load_and_prepare_config()
    set_language("en")

    ctk.set_appearance_mode("dark")   # dark by default
    ctk.set_default_color_theme("green")

    app = BackupApp(cfg)
    app.mainloop()


class BackupApp:
    """Modern English sidebar-based UI with theme switching."""

    NAV_KEYS = ("home", "files", "schedule", "cloud", "telegram", "advanced", "log", "settings")

    def __init__(self, cfg):
        import customtkinter as ctk
        self.ctk = ctk
        self.cfg = cfg
        self.rtl = False
        self.current_page = "home"
        self._service_here = False
        self._force_exit = False
        self._tray = None
        self._tray_hint_shown = False

        self.tg = TelegramManager(cfg, job_runner=lambda manual=True: self._bot_trigger_backup())
        self.backup_running = False
        self.cancel_event = threading.Event()
        self._suppress_notify_until = 0.0

        self.root = ctk.CTk()
        self.root.title(f"{tr('ui.app_title')} — {APP_NAME}")
        self.root.geometry("980x680")
        self.root.minsize(880, 620)

        self._queue = queue.Queue()
        self.remote_checks = {}   # remote name -> BooleanVar

        self._build_ui()
        self._init_tray()
        self._start_services()
        self._start_log_watcher()
        self.root.after(100, self._poll_queue)
        self.root.after(60000, self._auto_home)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- widget helpers ----------------

    @property
    def side(self):
        """Leading side for the current direction (right for Arabic RTL)."""
        return "right" if self.rtl else "left"

    @property
    def anchor(self):
        return "e" if self.rtl else "w"

    def _label(self, parent, text, size=13, bold=False, anchor=None):
        ctk = self.ctk
        return ctk.CTkLabel(parent, text=text, anchor=anchor or self.anchor,
                            justify="right" if self.rtl else "left",
                            font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"))

    def _heading(self, parent, text):
        h = self._label(parent, text, size=20, bold=True)
        h.pack(fill="x", padx=18, pady=(16, 10))
        return h

    def _form_row(self, parent, label_key, var, width=220, show=None):
        """label + entry row, direction-aware. Returns the entry widget."""
        ctk = self.ctk
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=4)
        lbl = self._label(row, trd(label_key))
        entry = ctk.CTkEntry(row, textvariable=var, width=width, show=show,
                             justify="right" if self.rtl else "left")
        lbl.pack(side=self.side, padx=(0, 8) if self.rtl else (8, 0))
        entry.pack(side=self.side, padx=6)
        return entry

    def _switch(self, parent, label_key, var):
        ctk = self.ctk
        sw = ctk.CTkSwitch(parent, text=trd(label_key), variable=var,
                           progress_color=ACCENT, button_hover_color=ACCENT_HOVER)
        sw.pack(anchor=self.anchor, padx=18, pady=5)
        return sw

    def _card(self, parent):
        ctk = self.ctk
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.pack(fill="both", expand=True, padx=12, pady=8)
        return card

    # ---------------- layout ----------------

    def _build_ui(self):
        ctk = self.ctk
        for child in self.root.winfo_children():
            child.destroy()
        self.rtl = False

        self.sidebar = ctk.CTkFrame(self.root, width=210, corner_radius=0,
                                    fg_color=("#e9edf0", "#141a1e"))
        self.sidebar.pack(side=self.side, fill="y")
        self.sidebar.pack_propagate(False)

        self.main_area = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_area.pack(side=self.side, fill="both", expand=True)

        self._build_sidebar()

        self.content = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self.pages = {}
        self._build_home_page()
        self._build_files_page()
        self._build_schedule_page()
        self._build_cloud_page()
        self._build_telegram_page()
        self._build_advanced_page()
        self._build_log_page()
        self._build_settings_page()

        self._build_bottom_bar()
        self.show_page(self.current_page)
        # restore running-backup UI state after a language rebuild
        if self.backup_running:
            self.backup_btn.configure(state="disabled")
            self.cancel_btn.pack(side=self.side, padx=4, pady=12)
            self.set_status(trd("ui.status.cancelling") if self.cancel_event.is_set()
                            else trd("ui.status.running"))
            self._set_progress_busy()

    def _build_sidebar(self):
        ctk = self.ctk
        title = ctk.CTkLabel(self.sidebar, text="" + trd("ui.app_title"),
                             font=ctk.CTkFont(size=15, weight="bold"),
                             anchor=self.anchor, justify="right" if self.rtl else "left",
                             wraplength=178)
        title.pack(fill="x", padx=16, pady=(18, 2))
        sub = ctk.CTkLabel(self.sidebar, text=trd("ui.app_subtitle"),
                           font=ctk.CTkFont(size=11), text_color="gray",
                           anchor=self.anchor, justify="right" if self.rtl else "left",
                           wraplength=180)
        sub.pack(fill="x", padx=16, pady=(0, 14))

        icons = {"home": "", "files": "", "schedule": "", "cloud": "",
                 "telegram": "", "advanced": "", "log": "", "settings": ""}
        self.nav_buttons = {}
        for key in self.NAV_KEYS:
            text = f"{icons[key]}  {trd('ui.nav.' + key)}" if not self.rtl \
                   else f"{trd('ui.nav.' + key)}  {icons[key]}"
            btn = ctk.CTkButton(
                self.sidebar, text=text, height=40, corner_radius=9,
                anchor=self.anchor, font=self.ctk.CTkFont(size=13),
                fg_color="transparent", text_color=("gray10", "gray90"),
                hover_color=("#d5dbdf", "#1f2a30"),
                command=lambda k=key: self.show_page(k))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = btn

        # theme toggle at the bottom of the sidebar
        self.theme_btn = ctk.CTkButton(
            self.sidebar, text=self._theme_toggle_text(), height=36, corner_radius=9,
            anchor="center", fg_color="transparent", border_width=1,
            border_color=ACCENT, text_color=("gray10", "gray90"),
            hover_color=("#d5dbdf", "#1f2a30"), command=self.toggle_theme)
        self.theme_btn.pack(side="bottom", fill="x", padx=10, pady=12)

    def _theme_toggle_text(self):
        import customtkinter as ctk
        dark = ctk.get_appearance_mode().lower() == "dark"
        if get_language() == "ar":
            return (" " + trd("ui.settings.theme_light")) if dark else (" " + trd("ui.settings.theme_dark"))
        return (" " + trd("ui.settings.theme_light")) if dark else (" " + trd("ui.settings.theme_dark"))

    def show_page(self, key):
        self.current_page = key
        for name, page in self.pages.items():
            page.pack_forget()
        page = self.pages[key]
        page.pack(fill="both", expand=True)
        for name, btn in self.nav_buttons.items():
            if name == key:
                btn.configure(fg_color=ACCENT, text_color="white",
                              hover_color=ACCENT_HOVER)
            else:
                btn.configure(fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("#d5dbdf", "#1f2a30"))
        if key == "home":
            self._refresh_home()
        if key == "log":
            self.refresh_log()
        if key == "cloud":
            self.refresh_remotes()

    # ---------------- pages ----------------

    def _build_home_page(self):
        ctk = self.ctk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["home"] = page
        self._heading(page, trd("ui.home.title"))

        card = self._card(page)
        self.home_status = self._label(card, "…", size=18, bold=True)
        self.home_status.pack(fill="x", padx=18, pady=(18, 4))
        self.home_details = self._label(card, "", size=12)
        self.home_details.configure(text_color="gray", wraplength=620, justify="left")
        self.home_details.pack(fill="x", padx=18)
        self.home_next = self._label(card, "…", size=12)
        self.home_next.pack(fill="x", padx=18, pady=(6, 2))
        self.home_summary = self._label(card, "…", size=12)
        self.home_summary.configure(text_color="gray", wraplength=620)
        self.home_summary.pack(fill="x", padx=18, pady=(2, 8))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=18, pady=(4, 16))
        ctk.CTkButton(btns, text="" + trd("ui.actions.backup_now"), width=170, height=38,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.on_backup_now).pack(side=self.side, padx=4)
        ctk.CTkButton(btns, text="" + trd("ui.home.refresh"), width=110,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=("gray10", "gray90"),
                      command=self._refresh_home).pack(side=self.side, padx=4)

        card2 = self._card(page)
        self.home_service = self._label(card2, "…", size=13, bold=True)
        self.home_service.pack(fill="x", padx=18, pady=(16, 2))
        self.home_service_hint = self._label(card2, "", size=11)
        self.home_service_hint.configure(text_color="gray", wraplength=620)
        self.home_service_hint.pack(fill="x", padx=18, pady=(0, 16))

    def _refresh_home(self):
        import datetime
        try:
            last = last_successful_run()
            if last:
                hours = (datetime.datetime.now() - last).total_seconds() / 3600
                ago = (f"{int(hours * 60)} min" if hours < 1 else
                       f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} days")
                warn = hours > float(self.cfg.get("monitoring", {}).get("alert_after_hours", 26) or 0)
                self.home_status.configure(
                    text=("" if warn else "") + trd("ui.home.last_ok", ago=ago))
                self.home_details.configure(text=last_summary() or "")
            else:
                self.home_status.configure(text="" + trd("ui.home.never"))
                self.home_details.configure(text="")
            nxt = DailyScheduler(self.cfg).next_run()
            mins = max(0, int((nxt - datetime.datetime.now()).total_seconds()) // 60)
            self.home_next.configure(text=trd("ui.home.next", time=nxt.strftime("%Y-%m-%d %H:%M"),
                                               in_=f"{mins // 60} h {mins % 60} min"))
            eng = "restic" if self.cfg["backup"].get("engine") == "restic" else "ZIP"
            remotes = ", ".join(self.cfg["cloud"].get("remotes", [])) or "—"
            tg_on = trd("ui.home.on") if self.cfg["telegram"].get("send_report", True) else trd("ui.home.off")
            self.home_summary.configure(text=trd("ui.home.summary", engine=eng, cloud=remotes, tg=tg_on))
        except Exception as e:
            self.home_status.configure(text=f"… {e}")
        self._refresh_home_service()

    def _auto_home(self):
        try:
            if self.current_page == "home":
                self._refresh_home()
        except Exception:
            pass
        self.root.after(60000, self._auto_home)

    def _refresh_home_service(self):
        def job():
            if getattr(self, "_service_here", False):
                self._queue.put(("home_service", "" + trd("ui.home.svc_here"), ""))
                return
            try:
                pid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.pid")
                pid = int(open(pid_path).read().strip())
                pl = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                    capture_output=True, text=True).stdout
                if str(pid) in pl:
                    self._queue.put(("home_service", "" + trd("ui.home.svc_bg"), ""))
                    return
            except Exception:
                pass
            try:
                q = subprocess.run(["schtasks", "/Query", "/TN", "VPSBackupTool"],
                                   capture_output=True)
                if q.returncode == 0:
                    self._queue.put(("home_service", "" + trd("ui.home.svc_task_ready"),
                                     trd("ui.home.svc_task_hint")))
                    return
            except Exception:
                pass
            self._queue.put(("home_service", "" + trd("ui.home.svc_off"),
                             trd("ui.home.svc_off_hint")))
        threading.Thread(target=job, daemon=True).start()

    def _build_files_page(self):
        ctk = self.ctk
        import tkinter as tk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["files"] = page
        self._heading(page, trd("ui.files.title"))

        card = self._card(page)
        self._label(card, trd("ui.files.sources_label")).pack(fill="x", padx=14, pady=(12, 4))

        self.sources_box = ctk.CTkTextbox(card, height=170, font=("Consolas", 12))
        self.sources_box.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.sources_box.insert("1.0", "\n".join(self.cfg["backup"].get("sources", [])))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(btns, text="" + trd("ui.files.add_folder"), width=130,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._add_folder).pack(side=self.side, padx=4)
        ctk.CTkButton(btns, text="" + trd("ui.files.add_file"), width=130,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._add_file).pack(side=self.side, padx=4)

        opts = self._card(page)
        self.excl_var = tk.StringVar(value=" ".join(self.cfg["backup"].get("exclude_extensions", [])))
        self.excl_pat_var = tk.StringVar(value="; ".join(self.cfg["backup"].get("exclude_patterns", [])))
        self.maxsize_var = tk.StringVar(value=str(self.cfg["backup"].get("exclude_max_size_mb", 0)))
        self.pass_var = tk.StringVar(value=self.cfg["backup"].get("archive_password", ""))
        self.keep_var = tk.StringVar(value=str(self.cfg["backup"].get("keep_local_copies", 1)))
        self._form_row(opts, "ui.files.exclude_ext", self.excl_var, width=200)
        self._form_row(opts, "ui.files.exclude_patterns", self.excl_pat_var, width=260)
        self._form_row(opts, "ui.files.exclude_size", self.maxsize_var, width=90)
        self._form_row(opts, "ui.files.password", self.pass_var, width=200, show="•")
        row = self._form_row(opts, "ui.files.keep_copies", self.keep_var, width=70)
        row.master.pack_configure(pady=(4, 12))

    def _add_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            cur = self.sources_box.get("1.0", "end").strip()
            self.sources_box.insert("end", ("\n" if cur else "") + d)

    def _add_file(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename()
        if f:
            cur = self.sources_box.get("1.0", "end").strip()
            self.sources_box.insert("end", ("\n" if cur else "") + f)

    def _build_schedule_page(self):
        ctk = self.ctk
        import tkinter as tk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["schedule"] = page
        self._heading(page, trd("ui.schedule.title"))

        card = self._card(page)
        self.sched_enabled_var = tk.BooleanVar(value=self.cfg["schedule"].get("enabled", True))
        self._switch(card, "ui.schedule.enable", self.sched_enabled_var)

        self.time_var = tk.StringVar(value=self.cfg["schedule"].get("time", "03:00"))
        self.retry_var = tk.StringVar(value=str(self.cfg["schedule"].get("retry_count", 3)))
        self.delay_var = tk.StringVar(value=str(self.cfg["schedule"].get("retry_delay_minutes", 10)))
        self._form_row(card, "ui.schedule.time", self.time_var, width=90)
        self._form_row(card, "ui.schedule.retry_count", self.retry_var, width=70)
        self._form_row(card, "ui.schedule.retry_delay", self.delay_var, width=70)

        card2 = self._card(page)
        self.autostart_var = tk.BooleanVar(value=self.cfg["general"].get("autostart", False))
        sw = self._switch(card2, "ui.schedule.autostart", self.autostart_var)
        sw.pack_configure(pady=(14, 14))

    def _build_cloud_page(self):
        ctk = self.ctk
        import tkinter as tk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["cloud"] = page
        self._heading(page, trd("ui.cloud.title"))

        info = self._label(page, trd("ui.cloud.info"), size=12)
        info.configure(wraplength=640, text_color="gray")
        info.pack(fill="x", padx=18, pady=(0, 6))

        card = self._card(page)
        self.remotes_frame = ctk.CTkScrollableFrame(card, height=180)
        self.remotes_frame.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        # View saved destinations instantly — So that you do not erase them by saving them without opening the page
        self._render_remotes(self.cfg["cloud"].get("remotes", []))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(btns, text="" + trd("ui.cloud.setup"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._open_rclone_config).pack(side=self.side, padx=4)
        ctk.CTkButton(btns, text="" + trd("ui.cloud.refresh"),
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=("gray10", "gray90"),
                      command=self.refresh_remotes).pack(side=self.side, padx=4)
        ctk.CTkButton(btns, text="" + trd("ui.cloud.test_btn"),
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=("gray10", "gray90"),
                      command=self._test_cloud).pack(side=self.side, padx=4)

        opts = self._card(page)
        self.folder_var = tk.StringVar(value=self.cfg["cloud"].get("remote_folder", "VPS-Backups"))
        self.retention_var = tk.StringVar(value=str(self.cfg["cloud"].get("retention_days", 30)))
        self._form_row(opts, "ui.cloud.folder", self.folder_var, width=180)
        row = self._form_row(opts, "ui.cloud.retention", self.retention_var, width=70)
        row.master.pack_configure(pady=(4, 12))

    def refresh_remotes(self):
        """Reload rclone remotes in a worker thread (never blocks the UI)."""
        def job():
            remotes = cloud_uploader.list_remotes()
            self._queue.put(("remotes", remotes))
        threading.Thread(target=job, daemon=True).start()

    def _render_remotes(self, remotes):
        ctk = self.ctk
        import tkinter as tk
        for child in self.remotes_frame.winfo_children():
            child.destroy()
        self.remote_checks = {}
        if not remotes:
            self._label(self.remotes_frame, trd("ui.cloud.no_remotes"), size=12).pack(
                anchor=self.anchor, padx=8, pady=8)
            return
        active = set(self.cfg["cloud"].get("remotes", []))
        for r in remotes:
            var = tk.BooleanVar(value=(r in active or r + ":" in active))
            cb = ctk.CTkCheckBox(self.remotes_frame, text=r, variable=var,
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                 font=("Consolas", 12))
            cb.pack(anchor=self.anchor, padx=8, pady=4)
            self.remote_checks[r] = var

    def _open_rclone_config(self):
        from tkinter import messagebox
        exe = cloud_uploader.find_rclone()
        if not exe:
            messagebox.showerror(trd("ui.cloud.rclone_missing_title"),
                                 trd("ui.cloud.rclone_missing_msg"))
            return
        if os.name == "nt":
            os.system(f'start "" cmd /k "{exe}" config')
        else:
            os.system(f'x-terminal-emulator -e "{exe}" config 2>/dev/null &')

    def _build_telegram_page(self):
        ctk = self.ctk
        import tkinter as tk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["telegram"] = page
        self._heading(page, trd("ui.telegram.title"))

        info = self._label(page, trd("ui.telegram.info"), size=12)
        info.configure(wraplength=640, text_color="gray")
        info.pack(fill="x", padx=18, pady=(0, 6))

        card = self._card(page)
        tcfg = self.cfg["telegram"]
        self.token_var = tk.StringVar(value=tcfg.get("bot_token", ""))
        self.apiid_var = tk.StringVar(value=tcfg.get("api_id", ""))
        self.apihash_var = tk.StringVar(value=tcfg.get("api_hash", ""))
        self.chatid_var = tk.StringVar(value=tcfg.get("chat_id", ""))
        # The direct-send limit field (fixes the old `direct_var` NameError on save)
        self.direct_var = tk.StringVar(value=str(tcfg.get("direct_max_mb", 45)))
        self._form_row(card, "ui.telegram.token", self.token_var, width=300, show="•")
        self._form_row(card, "ui.telegram.api_id", self.apiid_var, width=160)
        self._form_row(card, "ui.telegram.api_hash", self.apihash_var, width=300, show="•")
        self._form_row(card, "ui.telegram.chat_id", self.chatid_var, width=160)
        self._form_row(card, "ui.telegram.direct_max", self.direct_var, width=90)
        hint = self._label(card, trd("ui.telegram.direct_max_hint"), size=11)
        hint.configure(text_color="gray")
        hint.pack(fill="x", padx=44, pady=(0, 8))

        card2 = self._card(page)
        self.send_file_var = tk.BooleanVar(value=tcfg.get("send_file", True))
        self.send_report_var = tk.BooleanVar(value=tcfg.get("send_report", True))
        sw1 = self._switch(card2, "ui.telegram.send_file", self.send_file_var)
        sw1.pack_configure(pady=(14, 4))
        sw2 = self._switch(card2, "ui.telegram.send_report", self.send_report_var)
        sw2.pack_configure(pady=(4, 6))
        ctk.CTkButton(card2, text="" + trd("ui.telegram.test"), width=180,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._test_telegram).pack(anchor=self.anchor, padx=18, pady=(6, 14))

    def _build_advanced_page(self):
        ctk = self.ctk
        import tkinter as tk
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["advanced"] = page
        self._heading(page, trd("ui.advanced.title"))
        bcfg, rcfg = self.cfg["backup"], self.cfg["restic"]
        mcfg = self.cfg.get("monitoring", {})

        # engine
        card = self._card(page)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(14, 4))
        self._label(row, trd("ui.advanced.engine")).pack(side=self.side, padx=(0, 8) if self.rtl else (8, 0))
        self._engine_labels = {"zip": trd("ui.advanced.engine_zip"),
                               "restic": trd("ui.advanced.engine_restic")}
        self.engine_menu = ctk.CTkOptionMenu(
            row, values=list(self._engine_labels.values()),
            fg_color=ACCENT, button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER)
        self.engine_menu.set(self._engine_labels.get(bcfg.get("engine", "zip"), self._engine_labels["zip"]))
        self.engine_menu.pack(side=self.side, padx=6)
        hint = self._label(card, trd("ui.advanced.engine_hint"), size=11)
        hint.configure(text_color="gray", wraplength=620)
        hint.pack(fill="x", padx=18, pady=(0, 6))
        self.restic_repo_var = tk.StringVar(value=rcfg.get("repository", ""))
        self.restic_pass_var = tk.StringVar(value=rcfg.get("password", ""))
        self.keep_daily_var = tk.StringVar(value=str(rcfg.get("keep_daily", 7)))
        self.keep_weekly_var = tk.StringVar(value=str(rcfg.get("keep_weekly", 4)))
        self.keep_monthly_var = tk.StringVar(value=str(rcfg.get("keep_monthly", 12)))
        self._form_row(card, "ui.advanced.restic_repo", self.restic_repo_var, width=260)
        self._form_row(card, "ui.advanced.restic_password", self.restic_pass_var, width=200, show="•")
        self._form_row(card, "ui.advanced.keep_daily", self.keep_daily_var, width=60)
        self._form_row(card, "ui.advanced.keep_weekly", self.keep_weekly_var, width=60)
        r = self._form_row(card, "ui.advanced.keep_monthly", self.keep_monthly_var, width=60)
        r.master.pack_configure(pady=(4, 12))

        # safety
        card2 = self._card(page)
        self.vss_var = tk.BooleanVar(value=bcfg.get("use_vss", False))
        self.verify_var = tk.BooleanVar(value=bcfg.get("verify", True))
        self._switch(card2, "ui.advanced.use_vss", self.vss_var).pack_configure(pady=(14, 4))
        self._switch(card2, "ui.advanced.verify", self.verify_var)
        self.pre_cmd_var = tk.StringVar(value=bcfg.get("pre_command", ""))
        self.post_cmd_var = tk.StringVar(value=bcfg.get("post_command", ""))
        self._form_row(card2, "ui.advanced.pre_command", self.pre_cmd_var, width=320)
        self._form_row(card2, "ui.advanced.post_command", self.post_cmd_var, width=320)
        hint2 = self._label(card2, trd("ui.advanced.hooks_hint"), size=11)
        hint2.configure(text_color="gray", wraplength=620)
        hint2.pack(fill="x", padx=18, pady=(0, 12))

        # monitoring
        card3 = self._card(page)
        self.hc_url_var = tk.StringVar(value=mcfg.get("healthcheck_url", ""))
        self.hb_url_var = tk.StringVar(value=mcfg.get("heartbeat_url", ""))
        self.alert_hours_var = tk.StringVar(value=str(mcfg.get("alert_after_hours", 26)))
        self._form_row(card3, "ui.advanced.healthcheck_url", self.hc_url_var, width=320).master.pack_configure(pady=(14, 4))
        self._form_row(card3, "ui.advanced.heartbeat_url", self.hb_url_var, width=320)
        self._form_row(card3, "ui.advanced.alert_hours", self.alert_hours_var, width=60)
        ctk.CTkButton(card3, text="" + trd("ui.advanced.test_ping"), width=170,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._test_ping).pack(anchor=self.anchor, padx=18, pady=(8, 4))
        hint3 = self._label(card3, trd("ui.advanced.monitor_hint"), size=11)
        hint3.configure(text_color="gray", wraplength=620)
        hint3.pack(fill="x", padx=18, pady=(0, 12))

    def _test_telegram(self):
        if not (self.tg.is_configured() and getattr(self.tg, "_running", False)):
            self.set_status(trd("ui.telegram.test_not_running"))
            return
        self.set_status(trd("ui.telegram.test_sending"))
        ok = self.tg.send_message("Test message from VPS Backup Tool — everything works!")
        self.set_status(trd("ui.telegram.test_sent") if ok else trd("ui.telegram.test_fail"))

    def _test_cloud(self):
        from tkinter import messagebox
        selected = [r for r, var in self.remote_checks.items() if var.get()]
        if not selected:
            messagebox.showinfo(trd("ui.cloud.test"), trd("ui.cloud.test_none"))
            return
        self.set_status(trd("ui.cloud.testing"))

        def job():
            lines = []
            for r in selected:
                remote = r if r.endswith(":") else r + ":"
                ok, out = cloud_uploader._run(["about", remote], timeout=120)
                if ok:
                    free = ""
                    for line in out.splitlines():
                        if line.lower().startswith("free:"):
                            free = line.split(":", 1)[1].strip()
                    lines.append(f"{remote} " + (f"({free} free)" if free else "OK"))
                else:
                    lines.append(f"{remote}: {out[-150:]}")
            self._queue.put(("cloud_test_done", "\n".join(lines)))
        threading.Thread(target=job, daemon=True).start()

    def _test_ping(self):
        from tkinter import messagebox
        import monitor as monitor_mod
        url = self.hc_url_var.get().strip()
        if not url:
            messagebox.showinfo(trd("ui.advanced.test_ping"), trd("ui.advanced.ping_none"))
            return
        ok = monitor_mod.ping({"monitoring": {"healthcheck_url": url}})
        if ok:
            messagebox.showinfo(trd("ui.advanced.test_ping"), trd("ui.advanced.ping_ok"))
        else:
            messagebox.showwarning(trd("ui.advanced.test_ping"), trd("ui.advanced.ping_fail"))

    def _build_log_page(self):
        ctk = self.ctk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["log"] = page
        self._heading(page, trd("ui.log.title"))

        card = self._card(page)
        self.log_box = ctk.CTkTextbox(card, font=("Consolas", 11), state="disabled",
                                      wrap="none")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        ctk.CTkButton(card, text="" + trd("ui.log.refresh"), width=150,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.refresh_log).pack(pady=(0, 12))

    def refresh_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        text = read_recent_logs(300)
        self.log_box.insert("1.0", text)
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _build_settings_page(self):
        ctk = self.ctk
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["settings"] = page
        self._heading(page, trd("ui.settings.title"))

        card = self._card(page)
        # This consolidated build is intentionally English-only.
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(16, 6))
        self._label(row, trd("ui.settings.language")).pack(side=self.side, padx=(0, 8) if self.rtl else (8, 0))
        self.lang_menu = ctk.CTkOptionMenu(
            row, values=["English"], command=self._on_language_change,
            fg_color=ACCENT, button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER)
        self.lang_menu.set("English")
        self.lang_menu.pack(side=self.side, padx=6)

        # theme
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=18, pady=6)
        self._label(row2, trd("ui.settings.theme")).pack(side=self.side, padx=(0, 8) if self.rtl else (8, 0))
        import customtkinter as _ctk
        current_theme = trd("ui.settings.theme_dark") \
            if _ctk.get_appearance_mode().lower() == "dark" else trd("ui.settings.theme_light")
        self.theme_seg = ctk.CTkSegmentedButton(
            row2, values=[trd("ui.settings.theme_dark"), trd("ui.settings.theme_light")],
            command=self._on_theme_seg)
        self.theme_seg.set(current_theme)
        self.theme_seg.pack(side=self.side, padx=6)

        note = self._label(card, trd("ui.settings.restart_note"), size=11)
        note.configure(text_color="gray", wraplength=600)
        note.pack(fill="x", padx=18, pady=(14, 16))

        about = self._label(page, trd("ui.settings.about"), size=11)
        about.configure(text_color="gray", wraplength=620)
        about.pack(side="bottom", fill="x", padx=18, pady=12)

    def _on_language_change(self, choice):
        set_language("en")
        self.cfg.setdefault("general", {})["language"] = "en"

    def _on_theme_seg(self, choice):
        import customtkinter as ctk
        dark = choice == trd("ui.settings.theme_dark")
        ctk.set_appearance_mode("dark" if dark else "light")
        self.theme_btn.configure(text=self._theme_toggle_text())

    def toggle_theme(self):
        import customtkinter as ctk
        dark = ctk.get_appearance_mode().lower() == "dark"
        ctk.set_appearance_mode("light" if dark else "dark")
        self.theme_btn.configure(text=self._theme_toggle_text())
        try:
            self.theme_seg.set(trd("ui.settings.theme_light") if dark else trd("ui.settings.theme_dark"))
        except Exception:
            pass

    # ---------------- bottom bar (status / progress / actions) ----------------

    def _build_bottom_bar(self):
        ctk = self.ctk
        bar = ctk.CTkFrame(self.main_area, height=64, corner_radius=10,
                           fg_color=("#e9edf0", "#141a1e"))
        bar.pack(fill="x", padx=10, pady=10, side="bottom")
        bar.pack_propagate(False)
        self.bottom_bar = bar

        # action buttons (leading side)
        self.save_btn = ctk.CTkButton(bar, text="" + trd("ui.actions.save"), width=140,
                                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                      command=self.on_save)
        self.save_btn.pack(side=self.side, padx=(10, 4), pady=12)
        self.backup_btn = ctk.CTkButton(bar, text="" + trd("ui.actions.backup_now"), width=140,
                                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                        command=self.on_backup_now)
        self.backup_btn.pack(side=self.side, padx=4, pady=12)
        self.cancel_btn = ctk.CTkButton(bar, text="" + trd("ui.actions.cancel"), width=100,
                                        fg_color="#b91c1c", hover_color="#991b1b",
                                        command=self.on_cancel_backup)
        # cancel button is shown only while a backup runs

        # status + progress (trailing side)
        trailing = "left" if self.rtl else "right"
        self.progress = ctk.CTkProgressBar(bar, width=220, progress_color=ACCENT)
        self.progress.set(0)
        self.progress.pack(side=trailing, padx=(4, 10), pady=24)
        self.status_label = ctk.CTkLabel(bar, text=trd("ui.status.ready"),
                                         anchor=self.anchor,
                                         justify="right" if self.rtl else "left")
        self.status_label.pack(side=trailing, fill="x", expand=True, padx=10)

    def set_status(self, text, percent=None):
        self.status_label.configure(text=text)
        if percent is None:
            if self.progress.cget("mode") == "indeterminate":
                self.progress.stop()
            self.progress.configure(mode="determinate")
        else:
            self.progress.configure(mode="determinate")
            self.progress.set(max(0, min(100, percent)) / 100.0)

    def _set_progress_busy(self):
        self.progress.configure(mode="indeterminate")
        self.progress.start()

    # ---------------- collect & save ----------------

    def _collect_into_cfg(self, strict=True):
        """Read every widget into self.cfg. strict=True raises on bad values."""
        cfg = self.cfg

        def val(name, fn):
            try:
                return fn()
            except Exception as e:
                if strict:
                    raise ValueError(f"{name}: {e}")
                return None

        cfg["backup"]["sources"] = [l.strip() for l in
                                    self.sources_box.get("1.0", "end").splitlines() if l.strip()]
        cfg["backup"]["exclude_extensions"] = self.excl_var.get().split()
        cfg["backup"]["exclude_patterns"] = [p.strip() for p in self.excl_pat_var.get().split(";") if p.strip()]
        v = val("exclude_max_size_mb", lambda: int(self.maxsize_var.get() or 0))
        if v is not None:
            cfg["backup"]["exclude_max_size_mb"] = v
        cfg["backup"]["archive_password"] = self.pass_var.get()
        v = val("keep_local_copies", lambda: max(1, int(self.keep_var.get() or 1)))
        if v is not None:
            cfg["backup"]["keep_local_copies"] = v

        cfg["schedule"]["enabled"] = bool(self.sched_enabled_var.get())

        def _parse_time():
            hh, mm = map(int, self.time_var.get().strip().split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError("time out of range")
            return f"{hh:02d}:{mm:02d}"
        v = val("time", _parse_time)
        if v is not None:
            cfg["schedule"]["time"] = v
        v = val("retry_count", lambda: max(1, int(self.retry_var.get() or 3)))
        if v is not None:
            cfg["schedule"]["retry_count"] = v
        v = val("retry_delay_minutes", lambda: max(1, int(self.delay_var.get() or 10)))
        if v is not None:
            cfg["schedule"]["retry_delay_minutes"] = v

        if self.remote_checks:
            selected = [r for r, var in self.remote_checks.items() if var.get()]
            cfg["cloud"]["remotes"] = [r if r.endswith(":") else r + ":" for r in selected]
        # If the destination list is never displayed — Keep what is saved as it is (Do not erase it by saving)
        cfg["cloud"]["remote_folder"] = self.folder_var.get().strip() or "VPS-Backups"
        v = val("retention_days", lambda: max(1, int(self.retention_var.get() or 30)))
        if v is not None:
            cfg["cloud"]["retention_days"] = v

        cfg["telegram"]["bot_token"] = self.token_var.get().strip()
        cfg["telegram"]["api_id"] = self.apiid_var.get().strip()
        cfg["telegram"]["api_hash"] = self.apihash_var.get().strip()
        cfg["telegram"]["chat_id"] = self.chatid_var.get().strip()
        v = val("direct_max_mb", lambda: max(1, float(self.direct_var.get() or 45)))
        if v is not None:
            cfg["telegram"]["direct_max_mb"] = v
        cfg["telegram"]["send_file"] = bool(self.send_file_var.get())
        cfg["telegram"]["send_report"] = bool(self.send_report_var.get())

        engine_by_label = {v: k for k, v in self._engine_labels.items()}
        cfg["backup"]["engine"] = engine_by_label.get(self.engine_menu.get(), "zip")
        cfg["backup"]["use_vss"] = bool(self.vss_var.get())
        cfg["backup"]["verify"] = bool(self.verify_var.get())
        cfg["backup"]["pre_command"] = self.pre_cmd_var.get().strip()
        cfg["backup"]["post_command"] = self.post_cmd_var.get().strip()
        rcfg = cfg.setdefault("restic", {})
        rcfg["repository"] = self.restic_repo_var.get().strip()
        rcfg["password"] = self.restic_pass_var.get()
        for key, var in (("keep_daily", self.keep_daily_var), ("keep_weekly", self.keep_weekly_var),
                         ("keep_monthly", self.keep_monthly_var)):
            v = val(key, lambda var=var: max(0, int(var.get() or 0)))
            if v is not None:
                rcfg[key] = v
        if strict and cfg["backup"]["engine"] == "restic" and not (rcfg["repository"] and rcfg["password"]):
            raise ValueError(trd("ui.advanced.restic_required"))
        mcfg = cfg.setdefault("monitoring", {})
        mcfg["healthcheck_url"] = self.hc_url_var.get().strip()
        mcfg["heartbeat_url"] = self.hb_url_var.get().strip()
        v = val("alert_after_hours", lambda: max(0, float(self.alert_hours_var.get() or 0)))
        if v is not None:
            mcfg["alert_after_hours"] = v

        cfg.setdefault("general", {})["autostart"] = bool(self.autostart_var.get())
        cfg["general"]["language"] = "en"

    def _apply_autostart(self):
        """Register/remove autostart through the suite installer (Windows only).

        The suite owns the scheduled tasks; this GUI toggle just invokes it so it
        never points at a script that is not shipped.
        """
        if os.name != "nt":
            return
        import subprocess
        from tkinter import messagebox
        root = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        script = os.path.join(root, "scripts", "install_suite.ps1")
        if not os.path.exists(script):
            log(tr("core.autostart.failed", err="suite installer not found"), "WARN")
            return
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
        if not self.autostart_var.get():
            args.append("-Remove")
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=120,
                                  creationflags=0x08000000)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[-400:]
                log(tr("core.autostart.failed", err=err), "WARN")
                messagebox.showwarning(trd("ui.schedule.autostart"), trd("ui.msg.autostart_failed", error=err))
        except Exception as e:
            log(tr("core.autostart.failed", err=e), "WARN")

    def on_save(self):
        from tkinter import messagebox
        try:
            self._collect_into_cfg(strict=True)
            save_config(self.cfg)
        except Exception as e:
            messagebox.showerror(trd("ui.msg.invalid_title"),
                                 trd("ui.msg.invalid_body", error=e))
            return False
        self._apply_autostart()
        messagebox.showinfo(trd("ui.msg.saved_title"), trd("ui.msg.saved_body"))
        return True

    # ---------------- manual backup (thread + queue, never freezes the UI) ----------------

    def on_backup_now(self):
        if self.backup_running:
            return
        from tkinter import messagebox
        try:
            self._collect_into_cfg(strict=True)
            save_config(self.cfg)
        except Exception as e:
            messagebox.showerror(trd("ui.msg.invalid_title"),
                                 trd("ui.msg.invalid_body", error=e))
            return
        # If the background worker is running, queue the job there so only one
        # backup can ever run (the GUI and daemon must not run jobs concurrently).
        if daemon_running():
            ok, info = queue_control_backup("gui")
            if ok:
                messagebox.showinfo(trd("ui.msg.saved_title"),
                                    "Backup queued on the background worker.")
                return
            log(f"Could not queue backup, running in this window instead: {info}", "WARN")
        self._start_backup_worker()

    def _bot_trigger_backup(self):
        """Backup triggered from the Telegram bot — runs with the loaded cfg."""
        self._queue.put(("bot_backup",))

    def _start_backup_worker(self):
        self.backup_running = True
        self.cancel_event.clear()
        self.backup_btn.configure(state="disabled")
        self.cancel_btn.pack(side=self.side, padx=4, pady=12)
        self.set_status(trd("ui.status.running"))
        self._set_progress_busy()
        threading.Thread(target=self._backup_job, daemon=True).start()

    def _backup_job(self):
        adapter = make_progress_adapter(
            lambda pct, msg: self._queue.put(("progress", pct, msg)))
        tg = self.tg
        tmp_tg = None
        result = None
        try:
            # The window does not have a bot (The backend version runs it)? Create a temporary connection
            # So that the copy report and the file are delivered to Telegram with the same efficiency.
            if not self._service_here and self.tg.is_configured() \
                    and not getattr(self.tg, "_running", False):
                tmp_tg = TelegramManager(self.cfg, session_name="bot_session_gui", temp_session=True)
                if tmp_tg.start():
                    tmp_tg.wait_ready(90)
                    tg = tmp_tg
                    log(tr("core.tg.temp_started"))
            result = call_with_supported_kwargs(
                run_with_retries, self.cfg, tg=tg, manual=True,
                progress_cb=adapter, cancel_event=self.cancel_event)
            if tmp_tg is not None:
                self._queue.put(("progress", None, trd("ui.status.delivering")))
                tmp_tg.wait_pending_uploads(4 * 3600)
        except Exception as e:
            log(f"Unexpected error in the backup task: {e}", "ERROR")
            result = e
        finally:
            if tmp_tg is not None:
                tmp_tg.stop()
                log(tr("core.tg.temp_stopped"))
        self._queue.put(("backup_done", result))

    def on_cancel_backup(self):
        if not self.backup_running:
            return
        self.cancel_event.set()
        self.set_status(trd("ui.status.cancelling"))
        self.cancel_btn.configure(state="disabled")

    def _finish_backup(self, result):
        status = backup_status_of(result, self.cancel_event)
        self.backup_running = False
        self._suppress_notify_until = time.time() + 30  # log watcher stays quiet
        self.backup_btn.configure(state="normal")
        self.cancel_btn.pack_forget()
        self.cancel_btn.configure(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        if status == "ok":
            self.progress.set(1)
            self.set_status(trd("ui.status.done_ok"), percent=100)
            notify(tr("ui.notify.ok_title"), tr("ui.notify.ok_body"))
        elif status == "cancelled":
            self.progress.set(0)
            self.set_status(trd("ui.status.cancelled"), percent=0)
            notify(tr("ui.notify.cancel_title"), tr("ui.notify.cancel_body"))
        else:
            self.progress.set(0)
            self.set_status(trd("ui.status.done_warn"), percent=0)
            notify(tr("ui.notify.warn_title"), tr("ui.notify.warn_body"))
        try:
            self.refresh_log()
        except Exception:
            pass

    # ---------------- cross-thread queue ----------------

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _kind, pct, msg = item
                    if pct is not None:
                        self.progress.stop()
                        self.set_status(msg, percent=pct)
                    else:
                        self.status_label.configure(text=msg)
                elif kind == "backup_done":
                    self._finish_backup(item[1])
                elif kind == "bot_backup":
                    if not self.backup_running:
                        self._start_backup_worker()
                elif kind == "tray_backup":
                    if self.root.state() == "withdrawn":
                        self.root.deiconify()
                    self.on_backup_now()
                elif kind == "tray_show":
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                elif kind == "tray_exit":
                    self._really_exit()
                elif kind == "home_service":
                    _kind, text, hint = item
                    self.home_service.configure(text=text)
                    self.home_service_hint.configure(text=hint)
                elif kind == "cloud_test_done":
                    from tkinter import messagebox
                    messagebox.showinfo(trd("ui.cloud.test"), item[1])
                elif kind == "notify":
                    _kind, title, body = item
                    notify(title, body)
                elif kind == "remotes":
                    try:
                        self._render_remotes(item[1])
                    except Exception:
                        pass
                elif kind == "logline":
                    pass
        except Exception:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------- completion watcher (scheduled / bot backups) ----------------

    def _start_log_watcher(self):
        threading.Thread(target=self._watch_log_loop, daemon=True).start()

    def _watch_log_loop(self):
        """Tail today's log file; notify when a non-manual backup finishes."""
        import datetime
        offset = None
        path = None
        ok_markers_en = ("job finished", "backup finished", "backup completed")
        fail_markers_en = ("backup failed", "failed to create the archive")
        while True:
            try:
                day = datetime.datetime.now().strftime("%Y-%m-%d")
                new_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "logs", f"backup_{day}.log")
                if new_path != path:
                    path, offset = new_path, None
                if os.path.exists(path):
                    size = os.path.getsize(path)
                    if offset is None:
                        offset = size  # start at the end — ignore history
                    elif size < offset:
                        offset = 0     # truncated
                    if size > offset:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(offset)
                            chunk = f.read()
                        offset = size
                        if time.time() > self._suppress_notify_until:
                            low = chunk.lower()
                            failed = any(m in low for m in fail_markers_en)
                            finished = any(m in low for m in ok_markers_en)
                            if finished or failed:
                                if failed:
                                    self._queue.put(("notify", tr("ui.notify.fail_title"),
                                                     tr("ui.notify.fail_body")))
                                elif "warning" in low:
                                    self._queue.put(("notify", tr("ui.notify.warn_title"),
                                                     tr("ui.notify.warn_body")))
                                else:
                                    self._queue.put(("notify", tr("ui.notify.ok_title"),
                                                     tr("ui.notify.ok_body")))
            except Exception:
                pass
            time.sleep(5)

    # ---------------- system tray ----------------

    def _init_tray(self):
        """System tray icon — Closing hides the window and the application remains running in the background."""
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (64, 64), (20, 26, 30))
            d = ImageDraw.Draw(img)
            d.polygon([(32, 6), (56, 16), (56, 34), (32, 58), (8, 34), (8, 16)], fill=(20, 184, 166))
            d.polygon([(32, 14), (48, 21), (48, 33), (32, 49), (16, 33), (16, 21)], fill=(20, 26, 30))
            d.polygon([(24, 31), (30, 38), (41, 25), (44, 29), (30, 45), (21, 35)], fill=(255, 255, 255))
            menu = pystray.Menu(
                pystray.MenuItem(trd("ui.tray.open"),
                                 lambda ic, it: self._queue.put(("tray_show",)), default=True),
                pystray.MenuItem(trd("ui.tray.backup"),
                                 lambda ic, it: self._queue.put(("tray_backup",))),
                pystray.MenuItem(trd("ui.tray.exit"),
                                 lambda ic, it: self._queue.put(("tray_exit",))),
            )
            self._tray = pystray.Icon("VPSBackupTool", img, APP_NAME, menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            self._tray = None
            log(f"tray icon unavailable: {e}", "WARN")

    def _stop_tray(self):
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        self._tray = None

    def _really_exit(self):
        self._force_exit = True
        self.root.after(0, self._on_close)

    # ---------------- services & close ----------------

    def _start_services(self):
        def start():
            svc_lock = acquire_instance_lock()
            if svc_lock is None:
                self._service_here = False
                self.set_status(trd("ui.status.bg_instance"))
                self.refresh_log()
                return
            self._service_here = True
            self.tg.start()
            adapter = make_progress_adapter(
                lambda pct, msg: self._queue.put(("progress", pct, msg)))
            call_with_supported_kwargs(
                DailyScheduler, self.cfg, tg=self.tg, progress_cb=adapter).start()
            self.refresh_log()
        self.root.after(800, start)

    def _on_close(self):
        from tkinter import messagebox
        if self.backup_running:
            if not messagebox.askyesno(trd("ui.msg.close_backup_title"),
                                       trd("ui.msg.close_backup_body")):
                return
        if getattr(self.tg, "active_uploads", 0) > 0:
            if not messagebox.askyesno(trd("ui.msg.close_upload_title"),
                                       trd("ui.msg.close_upload_body")):
                return
        if self._tray is not None and not self._force_exit:
            # The closure only hides the tai — The scheduler and bot remain running from the window
            self.root.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                notify(APP_NAME, trd("ui.tray.hint"))
            return
        self._stop_tray()
        self.root.destroy()

    def mainloop(self):
        self.root.mainloop()


# ====================== entry point ======================

if __name__ == "__main__":
    if "--now" in sys.argv:
        run_headless(now=True)
    elif "--daemon" in sys.argv:
        run_headless(now=False)
    else:
        run_gui()
