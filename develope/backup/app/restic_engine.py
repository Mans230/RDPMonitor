# -*- coding: utf-8 -*-
"""Incremental copy engine via restic — Uploads only variable parts, no duplicates, and always encrypted.

warehouse (repository) It could be:
    rclone:drive:VPS-Restic   ← Any destination rclone Pre-set (Google Drive, OneDrive, ...)
    D:\\restic-repo            ← A local folder or on another disk
    s3:..., b2:..., sftp:...  ← Other types restic

Restoration:  restic -r <repo> restore latest --target D:\\restore
"""

import os
import json
import shutil
import subprocess

from logger_utils import log as _default_log
from i18n import tr
import backup_engine
import cloud_uploader

RESTIC_DIR = os.path.join(backup_engine.TOOL_ROOT, "restic")
_NO_WINDOW = 0x08000000


def find_restic():
    exe = "restic.exe" if os.name == "nt" else "restic"
    local = os.path.join(RESTIC_DIR, exe)
    if os.path.exists(local):
        return local
    return shutil.which("restic")


def is_available():
    return find_restic() is not None


def _env(cfg):
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = cfg["restic"].get("repository", "").strip()
    env["RESTIC_PASSWORD"] = cfg["restic"].get("password", "")
    if cloud_uploader.RCLONE_CONFIG:
        env["RCLONE_CONFIG"] = cloud_uploader.RCLONE_CONFIG
    # restic On "rclone" Who PATH (Cucumber rclone.program Corrupts Windows paths)
    rclone = cloud_uploader.find_rclone()
    if rclone:
        env["PATH"] = os.path.dirname(os.path.abspath(rclone)) + os.pathsep + env.get("PATH", "")
    env.setdefault("RESTIC_CACHE_DIR", os.path.join(backup_engine.TOOL_ROOT, "restic", "cache"))
    return env


def _base(cfg):
    return [find_restic()]


def _run(cfg, args, timeout=3600):
    try:
        proc = subprocess.run(_base(cfg) + args, env=_env(cfg), capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace",
                              creationflags=_NO_WINDOW if os.name == "nt" else 0)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return -1, "restic timed out"
    except Exception as e:
        return -1, str(e)


def validate(cfg):
    """Returns an error message None."""
    if not is_available():
        return tr("core.restic.missing")
    if not cfg["restic"].get("repository", "").strip():
        return tr("core.restic.no_repo")
    if not cfg["restic"].get("password"):
        return tr("core.restic.no_password")
    return None


def ensure_repo(cfg, log):
    code, _out = _run(cfg, ["cat", "config"], timeout=300)
    if code == 0:
        return True
    log(tr("core.restic.init"))
    code, out = _run(cfg, ["init"], timeout=600)
    if code != 0:
        log(tr("core.restic.init_failed", err=out[-500:]), "ERROR")
        return False
    return True


def _backup_args(cfg):
    bcfg = cfg["backup"]
    args = ["backup", "--json", "--exclude", backup_engine.TOOL_ROOT]
    if bcfg.get("use_vss") and os.name == "nt":
        args.append("--use-fs-snapshot")
    for ext in bcfg.get("exclude_extensions", []):
        ext = ext.strip()
        if ext:
            args += ["--iexclude", "*" + (ext if ext.startswith(".") else "." + ext)]
    for pat in backup_engine.normalize_patterns(bcfg.get("exclude_patterns", [])):
        args += ["--iexclude", pat]
    max_mb = int(bcfg.get("exclude_max_size_mb", 0) or 0)
    if max_mb > 0:
        args += ["--exclude-larger-than", f"{max_mb}M"]
    sources = [os.path.abspath(s.strip().strip('"')) for s in bcfg.get("sources", []) if s.strip()]
    sources = [s for s in sources if os.path.exists(s) and not backup_engine.is_inside_tool(s)]
    return args, sources


def _terminate_tree(proc):
    """Kill restic and its children (for example the rclone helper process).

    Terminating only restic can leave rclone running and the repository locked.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=_NO_WINDOW)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_backup(cfg, log=None, progress_cb=None, cancel_event=None):
    """He comes back dict: status ("ok"|"warn"|"cancelled"|"error"), summary, message."""
    _log = log or _default_log
    err = validate(cfg)
    if err:
        _log(err, "ERROR")
        return {"status": "error", "message": err}
    if not ensure_repo(cfg, _log):
        return {"status": "error", "message": "repository init failed"}
    args, sources = _backup_args(cfg)
    if not sources:
        return {"status": "error", "message": tr("core.backup.no_files")}
    _log(tr("core.restic.start", repo=cfg["restic"]["repository"], count=len(sources)))

    launch = {}
    if os.name == "nt":
        launch["creationflags"] = _NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        launch["start_new_session"] = True
    proc = subprocess.Popen(_base(cfg) + args + sources, env=_env(cfg), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            **launch)
    summary, errors, last_pct = None, [], -1
    import threading
    import collections
    # Bounded: only the tail is ever reported, so do not grow without limit.
    stderr_lines = collections.deque(maxlen=200)
    t = threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True)
    t.start()
    for line in proc.stdout:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_tree(proc)
            break
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        kind = msg.get("message_type")
        if kind == "status" and progress_cb:
            pct = int(float(msg.get("percent_done", 0)) * 90)
            if pct != last_pct:
                last_pct = pct
                progress_cb(pct, tr("core.restic.progress", percent=int(pct / 0.9)))
        elif kind == "error":
            item = msg.get("item") or ""
            e = (msg.get("error") or {}).get("message", "")
            errors.append(f"{item}: {e}")
            _log(tr("core.backup.compress_failed", path=item, err=e), "WARN")
        elif kind == "summary":
            summary = msg
    proc.wait()
    t.join(timeout=5)
    if cancel_event is not None and cancel_event.is_set():
        _log(tr("core.backup.cancelled"), "WARN")
        return {"status": "cancelled"}
    # 0 = success, 3 = Snapshot completed but some files could not be read
    if proc.returncode not in (0, 3) or not summary:
        tail = "".join(stderr_lines)[-500:]
        _log(tr("core.restic.failed", code=proc.returncode, err=tail), "ERROR")
        return {"status": "error", "message": tail}
    status = "ok" if proc.returncode == 0 else "warn"
    _log(tr("core.restic.done", snapshot=summary.get("snapshot_id", "")[:8],
            new=summary.get("files_new", 0), changed=summary.get("files_changed", 0),
            added_mb=f"{summary.get('data_added', 0) / 1024 / 1024:.1f}",
            total_mb=f"{summary.get('total_bytes_processed', 0) / 1024 / 1024:.1f}"))

    if progress_cb:
        progress_cb(92, tr("core.restic.forget"))
    r = cfg["restic"]
    code, out = _run(cfg, ["forget", "--prune",
                           "--keep-daily", str(int(r.get("keep_daily", 7))),
                           "--keep-weekly", str(int(r.get("keep_weekly", 4))),
                           "--keep-monthly", str(int(r.get("keep_monthly", 12)))], timeout=6 * 3600)
    if code != 0:
        _log(tr("core.restic.forget_failed", err=out[-300:]), "WARN")
        status = "warn"

    verified = None
    if r.get("check_after_backup", True) and cfg["backup"].get("verify", True):
        if progress_cb:
            progress_cb(96, tr("core.verify.running"))
        code, out = _run(cfg, ["check"], timeout=6 * 3600)
        verified = code == 0
        if verified:
            _log(tr("core.restic.check_ok"))
        else:
            _log(tr("core.restic.check_failed", err=out[-500:]), "ERROR")
            status = "error"
    if progress_cb:
        progress_cb(100, tr("core.restic.finished"))
    return {"status": status, "summary": summary, "errors": errors, "verified": verified}


def list_snapshots(cfg, limit=20):
    code, out = _run(cfg, ["snapshots", "--json"], timeout=300)
    if code != 0:
        return []
    try:
        snaps = json.JSONDecoder().raw_decode(out[out.find("["):])[0]
    except Exception:
        return []
    lines = [f"{s.get('short_id', '')}  {s.get('time', '')[:19].replace('T', ' ')}" for s in snaps]
    return lines[-limit:]
