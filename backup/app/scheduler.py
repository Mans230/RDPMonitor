# -*- coding: utf-8 -*-
"""Backup mission coordinator + Daily scheduling + Automatic retry + Catch up on missed appointments.

    General contract (do not break it; the interface depends on it):
    run_full_backup(cfg, tg=None, manual=False, progress_cb=None, cancel_event=None) -> bool
        Pass progress_cb(percent, message) And cancel_event (threading.Event) For the engine.
    run_with_retries(cfg, tg=None, manual=False, progress_cb=None, cancel_event=None) -> bool

Case file logs/last_run.json Stores the last successful run + Summary — It is used to catch up
With the last back-up, be warned "There has been no successful backup since X An hour".
"""

import os
import json
import time
import socket
import threading
import datetime
import subprocess

from logger_utils import log, read_recent_logs
from i18n import tr
import backup_engine
import cloud_uploader
import monitor

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "last_run.json")
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control", "last_result.json")


def _write_result(data):
    """Publish a structured result of the last job for the unified bot."""
    try:
        os.makedirs(os.path.dirname(RESULT_FILE), exist_ok=True)
        tmp = RESULT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True)
        os.replace(tmp, RESULT_FILE)
    except Exception:
        pass

# A global lock prevents two concurrent backups from running within a process (Scheduling + The bot + button)
_backup_lock = threading.Lock()
# Complete task lock (Pressure + Raise + Telegram) — A second request during playback is rejected instead of interference
_job_lock = threading.Lock()
_NO_WINDOW = 0x08000000


def is_busy():
    return _job_lock.locked()


_state_lock = threading.Lock()


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state):
    """Write the state file atomically so a crash cannot leave it truncated."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def record_successful_run(when=None, summary=""):
    """Store the time and summary of the last successful backup logs/last_run.json."""
    when = when or datetime.datetime.now()
    try:
        with _state_lock:
            state = _load_state()
            state.update({"last_success": when.isoformat(timespec="seconds"),
                          "last_attempt": when.isoformat(timespec="seconds"),
                          "summary": summary})
            _write_state(state)
    except Exception as e:
        log(tr("core.scheduler.state_save_failed", err=e), "WARN")


def last_successful_run():
    """He comes back datetime For the last successful run or None."""
    raw = _load_state().get("last_success")
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def last_summary():
    return _load_state().get("summary", "")


def record_attempt(when=None):
    """Persist a scheduled attempt so a service restart does not repeat catch-up."""
    when = when or datetime.datetime.now()
    try:
        with _state_lock:
            state = _load_state()
            state["last_attempt"] = when.isoformat(timespec="seconds")
            _write_state(state)
    except Exception as e:
        log(tr("core.scheduler.state_save_failed", err=e), "WARN")


def last_attempted_run():
    raw = _load_state().get("last_attempt")
    try:
        return datetime.datetime.fromisoformat(raw) if raw else None
    except (ValueError, TypeError):
        return None


def _ago(when):
    if not when:
        return "never"
    hours = (datetime.datetime.now() - when).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)} min ago"
    if hours < 48:
        return f"{hours:.1f} h ago"
    return f"{hours / 24:.1f} days ago"


def run_hook(cfg, which, status=""):
    """Run a pre command/After copying. He comes back True Upon success or failure of an order."""
    cmd = (cfg["backup"].get(f"{which}_command") or "").strip()
    if not cmd:
        return True
    timeout = max(1, int(cfg["backup"].get("hook_timeout_minutes", 60))) * 60
    env = os.environ.copy()
    env["BACKUP_STATUS"] = status
    env["BACKUP_TOOL_ROOT"] = backup_engine.TOOL_ROOT
    log(tr("core.hook.start", which=which, cmd=cmd))
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout,
                              env=env, encoding="utf-8", errors="replace",
                              creationflags=_NO_WINDOW if os.name == "nt" else 0)
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if out:
            log(tr("core.hook.output", which=which, out=out[-1500:]))
        if proc.returncode != 0:
            log(tr("core.hook.failed", which=which, code=proc.returncode), "ERROR")
            return False
        log(tr("core.hook.ok", which=which))
        return True
    except subprocess.TimeoutExpired:
        log(tr("core.hook.timeout", which=which, minutes=timeout // 60), "ERROR")
        return False
    except Exception as e:
        log(tr("core.hook.failed", which=which, code=e), "ERROR")
        return False


def _zip_job(cfg, tg, kind_bot, started, progress_cb, cancel_event):
    """Return (status, report_text) — status: ok | partial | error | cancelled.

    "ok" requires every intended file to be captured, the archive to verify, and
    delivery to succeed on every configured destination. Anything less is
    "partial" and is never recorded as a successful backup.
    """
    def _cancelled():
        return cancel_event is not None and cancel_event.is_set()

    # 1) pressure — Under the lock so that two pressures do not overlap (Timestamp collision/Resources)
    try:
        with _backup_lock:
            files, archive_status = backup_engine.create_backup(
                cfg, log, progress_cb=progress_cb, cancel_event=cancel_event)
    except Exception as e:
        log(tr("core.scheduler.archive_failed", err=e), "ERROR")
        return "error", f"Backup ({kind_bot}) failed during compression:\n{e}"

    if archive_status == "cancelled" or (not files and archive_status != "error"):
        return "cancelled", "Backup cancelled by user."
    if not files:
        log(tr("core.scheduler.archive_failed", err="create_backup returned status=error"), "ERROR")
        return "error", f"Backup ({kind_bot}) failed (archive creation or verification) — see the log on the VPS."

    archive_path = files[0]
    if not os.path.exists(archive_path):
        log(tr("core.scheduler.archive_vanished", name=os.path.basename(archive_path)), "ERROR")
        return "error", (f"Backup ({kind_bot}) failed — the archive disappeared from "
                         "local_backups before delivery (deleted while uploading?). See the log.")
    name = os.path.basename(archive_path)
    stats = backup_engine.LAST_STATS
    size = stats.get("size") or os.path.getsize(archive_path)
    count = stats.get("count", 0)
    size_mb = size / 1024 / 1024
    verify = cfg["backup"].get("verify", True)
    # Start "partial" if the engine already reported unreadable files.
    partial = archive_status == "partial"
    if stats.get("vss") == "partial":
        # A requested snapshot failed, so some files were read live.
        partial = True

    # 2) Delivery to Telegram and to the cloud.
    tcfg = cfg["telegram"]
    tg_file_queued = False
    tg_submit_ok = False
    tg_queued = 0
    share_links = {}
    direct_max = float(tcfg.get("direct_max_mb", 45))
    tg_active = bool(tg and tg.is_configured() and tcfg.get("send_file", True))
    if tg_active:
        try:
            if hasattr(tg, "reset_delivery"):
                tg.reset_delivery()
        except Exception:
            pass
    if tg_active and size_mb <= direct_max and not _cancelled():
        tg_submit_ok = bool(tg.send_file(archive_path))
        tg_file_queued = True
        if tg_submit_ok:
            tg_queued += 1

    cloud_results, cloud_errors, notes = [], [], []
    share_links = {}
    cloud_configured = bool(cfg["cloud"].get("remotes"))
    if cloud_configured:
        def _cloud_cb(p, m):
            if progress_cb:
                progress_cb(95 + int(p * 4 / 100), m or "cloud upload")
        if cloud_uploader.is_available():
            cloud_results = cloud_uploader.upload_to_cloud(archive_path, cfg, _cloud_cb, verify=verify)
        else:
            cloud_errors.append(tr("core.scheduler.no_rclone"))
            log(cloud_errors[-1], "ERROR")

    cloud_ok = [r for r in cloud_results if r[1]]
    cloud_fail = [r for r in cloud_results if not r[1]]
    if cloud_fail or cloud_errors:
        partial = True

    # Create a share link for EVERY backup when opted in and the archive is
    # encrypted. The link is reported and stored in the result.
    if cloud_configured and cloud_ok and cloud_uploader.is_available():
        allow_links = bool(cfg["cloud"].get("allow_share_links", False))
        if allow_links and stats.get("encrypted"):
            share_links = {r: l for r, l in
                           (cloud_uploader.get_share_link(archive_path, cfg) or {}).items() if l}
        elif allow_links and not stats.get("encrypted"):
            # A skipped link is a note, not a failed backup.
            notes.append(tr("core.scheduler.share_link_needs_encryption"))
            log(notes[-1], "WARN")

    # Large files without a link are sent as a file; small files were queued above.
    if tg_active and not _cancelled() and not tg_file_queued:
        if share_links:
            lines = [f"Large file ({size_mb:.1f} MB) - download link:",
                     *[f"- {remote} {link}" for remote, link in share_links.items()]]
            if not tg.send_message("\n".join(lines)):
                partial = True
                share_links = {}
        else:
            tg.send_message(
                f"Uploading the file ({size_mb:.1f} MB) - it will arrive in a following message.")
            tg_submit_ok = bool(tg.send_file(archive_path))
            if tg_submit_ok:
                tg_queued += 1

    if tg_active and not tg_submit_ok and not share_links:
        partial = True

    # 3) Verify that Telegram delivery actually completed (sending is async).
    tg_delivered = tg_failed = 0
    can_verify = hasattr(tg, "wait_delivery") and tcfg.get("verify_delivery", True)
    if tg_active and tg_queued and not can_verify:
        # Queued but not verified: never claim a full success.
        partial = True
    if tg_active and can_verify:
        try:
            tg_delivered, tg_failed = tg.wait_delivery(int(tcfg.get("delivery_timeout", 3600)))
        except Exception:
            tg_failed = 1
        # Require every queued upload to be confirmed delivered.
        if tg_queued and (tg_failed or tg_delivered < tg_queued):
            partial = True

    # 4) Honest report: each stage reported independently.
    icon = "" if not partial else ""
    report_lines = [
        f"{icon} New backup ({kind_bot})",
        f"File: {name}",
        f"Size: {size_mb:.1f} MB | Files: {count}",
        f"Encryption: {'AES' if stats.get('encrypted') else 'none'}",
        f"VSS snapshot: {stats.get('vss', 'off')}",
    ]
    if stats.get("missing"):
        report_lines.append(f"Missing sources: {stats.get('missing')}")
    if stats.get("errors"):
        report_lines.append(f"Unreadable files: {stats.get('errors')}")
    report_lines.append("Archive test: "
                        + ("passed " if stats.get("verified") is True else "not verified"))
    if not tg_active:
        tg_line = "not enabled"
    elif share_links:
        tg_line = "download link sent"
    elif tg_failed:
        tg_line = "failed "
    elif tg_queued and tg_delivered >= tg_queued:
        tg_line = "delivered "
    elif tg_queued:
        tg_line = "queued (unverified)"
    else:
        tg_line = "not sent"
    report_lines.append("Telegram: " + tg_line)
    report_lines.append(f"Cloud: {len(cloud_ok)} ok / {len(cloud_fail)} failed"
                        if cloud_configured else "Cloud: not enabled")
    if stats.get("sha256"):
        report_lines.append(f"#⃣ SHA-256: `{stats['sha256'][:16]}…`")
    report_lines += [f"{e}" for e in cloud_errors]
    report_lines += [f"Note: {n}" for n in notes]
    report_lines += [f"Link: {remote} {link}" for remote, link in share_links.items()]
    report = "\n".join(report_lines)

    if tg and tg.is_configured() and tcfg.get("send_report", True):
        tg.send_message(report)

    if cloud_configured and cloud_results:
        cloud_msg = (f"Cloud delivery finished: {len(cloud_ok)} succeeded / {len(cloud_fail)} failed\n"
                     + "\n".join(f"   • {remote} {'' + msg if ok else '' + msg[:120]}"
                                 for remote, ok, msg in cloud_results))
        if tg and tg.is_configured() and tcfg.get("send_report", True):
            if getattr(tg, "temp_session", False):
                log(cloud_msg)
            else:
                tg.send_message(cloud_msg)
    full_report = report

    summary = (f"Last backup: {name} | {size_mb:.1f} MB | {count} files | "
               f"{'partial' if partial else 'complete'} | {started.strftime('%Y-%m-%d %H:%M')}")
    if tg:
        tg.last_backup_info = summary
    _write_result({
        "time": started.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind_bot,
        "status": "partial" if partial else "ok",
        "archive": name,
        "size_mb": round(size_mb, 1),
        "files": count,
        "errors": stats.get("errors", 0),
        "missing": stats.get("missing", 0),
        "encrypted": bool(stats.get("encrypted")),
        "vss": stats.get("vss", "off"),
        "verified": stats.get("verified") is True,
        "sha256": (stats.get("sha256") or "")[:16],
        "telegram_delivered": tg_delivered,
        "telegram_failed": tg_failed,
        "telegram_enabled": bool(tg_active),
        "cloud_ok": len(cloud_ok),
        "cloud_fail": len(cloud_fail),
        "cloud_enabled": bool(cloud_configured),
        "links": share_links,
        "log_tail": [ln for ln in (read_recent_logs(8) or "").splitlines() if ln.strip()][-5:],
    })
    return ("partial" if partial else "ok"), full_report


def _restic_job(cfg, tg, kind_bot, started, progress_cb, cancel_event):
    import restic_engine
    res = restic_engine.run_backup(cfg, log, progress_cb=progress_cb, cancel_event=cancel_event)
    status = res.get("status")
    if status == "cancelled":
        return "cancelled", "Backup cancelled by user."
    if status == "error" and not res.get("summary"):
        return "error", f"Incremental backup ({kind_bot}) failed:\n{str(res.get('message', ''))[:500]}"
    s = res.get("summary") or {}
    added = s.get("data_added", 0) / 1024 / 1024
    total = s.get("total_bytes_processed", 0) / 1024 / 1024
    icon = {"ok": "", "warn": ""}.get(status, "")
    lines = [
        f"{icon} New incremental snapshot ({kind_bot})",
        f"Snapshot: {s.get('snapshot_id', '')[:8]}",
        f"New: {s.get('files_new', 0)} | Changed: {s.get('files_changed', 0)} | "
        f"Unchanged: {s.get('files_unmodified', 0)}",
        f"Uploaded: {added:.1f} MB (of {total:.1f} MB scanned)",
        f"Time: {started.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if res.get("errors"):
        lines.append(f"Unreadable files: {len(res['errors'])}")
    if res.get("verified") is True:
        lines.append("Repository check: passed ")
    elif res.get("verified") is False:
        lines.append("Repository check: FAILED — see the log")
    report = "\n".join(lines)
    if tg and tg.is_configured() and cfg["telegram"].get("send_report", True):
        tg.send_message(report)
    summary = (f"Last snapshot: {s.get('snapshot_id', '')[:8]} | +{added:.1f} MB | "
               f"{started.strftime('%Y-%m-%d %H:%M')}")
    if tg:
        tg.last_backup_info = summary
    if status == "ok":
        final = "ok"
    elif status == "warn":
        final = "partial"  # snapshot created but some files unreadable / check failed
    else:
        final = "error"
    return final, report


def run_full_backup(cfg, tg=None, manual=False, progress_cb=None, cancel_event=None):
    """Complete mission: pre-hook -> copy -> deliver -> verify -> Telegram -> post-hook -> ping.

    Returns a status string: "ok" | "partial" | "warn" | "error" | "cancelled".
    Only "ok" is recorded as a successful backup.
    """
    kind_log = tr("core.scheduler.kind_manual") if manual else tr("core.scheduler.kind_scheduled")
    kind_bot = "manual" if manual else "scheduled"
    log(tr("core.scheduler.job_start", kind=kind_log))
    started = datetime.datetime.now()
    monitor.ping(cfg, "start")

    if not run_hook(cfg, "pre"):
        msg = f"Backup ({kind_bot}) aborted — the pre-backup command failed. See the log on the VPS."
        if tg:
            tg.send_message(msg)
        run_hook(cfg, "post", "error")
        monitor.ping(cfg, "fail", msg)
        return "error"

    status, report = "error", ""
    try:
        if cfg["backup"].get("engine", "zip") == "restic":
            status, report = _restic_job(cfg, tg, kind_bot, started, progress_cb, cancel_event)
        else:
            status, report = _zip_job(cfg, tg, kind_bot, started, progress_cb, cancel_event)
    finally:
        run_hook(cfg, "post", status)

    if status == "cancelled":
        log(tr("core.scheduler.cancelled"), "WARN")
        if tg:
            tg.send_message(report)
        return "cancelled"
    if status == "error":
        if tg:
            tg.send_message(report)
        monitor.ping(cfg, "fail", report)
        return "error"

    if status == "ok":
        if cfg["backup"].get("engine", "zip") == "zip":
            archive = backup_engine.LAST_STATS.get("archive", "")
            if archive:
                backup_engine.cleanup_old_local(
                    cfg, log=log, current_name=os.path.basename(archive),
                    current_signature=backup_engine.LAST_STATS.get("signature"))
        record_successful_run(started, getattr(tg, "last_backup_info", "") if tg else "")
        monitor.ping(cfg, "", report)
    else:
        # partial / warn: not a full success. Do not record it as successful and
        # signal failure to the dead-man switch, but do not retry either.
        monitor.ping(cfg, "fail", report)
    log(tr("core.scheduler.job_end",
           result=tr("core.scheduler.result_ok") if status == "ok" else tr("core.scheduler.result_warn")))
    return status


def run_with_retries(cfg, tg=None, manual=False, progress_cb=None, cancel_event=None):
    """Run the task with automatic retry on failure + Notice."""
    if not _job_lock.acquire(blocking=False):
        log(tr("core.scheduler.busy"), "WARN")
        if tg:
            tg.send_message("A backup is already running — this request was ignored.")
        return "busy"
    try:
        scfg = cfg["schedule"]
        attempts = 1 if manual else max(1, int(scfg.get("retry_count", 3)))
        delay = max(1, int(scfg.get("retry_delay_minutes", 10))) * 60

        last = "error"
        for attempt in range(1, attempts + 1):
            if cancel_event is not None and cancel_event.is_set():
                log(tr("core.scheduler.cancelled"), "WARN")
                return "cancelled"
            try:
                status = run_full_backup(cfg, tg=tg, manual=manual,
                                         progress_cb=progress_cb, cancel_event=cancel_event)
            except Exception as e:
                log(tr("core.scheduler.attempt_error", n=attempt, err=e), "ERROR")
                status = "error"
            last = status
            # Only a hard "error" is retry-worthy; partial/ok/cancelled are final.
            if status != "error":
                return status
            if attempt < attempts:
                log(tr("core.scheduler.retry_wait", n=attempt + 1, minutes=delay // 60))
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        return "cancelled"
                else:
                    time.sleep(delay)

        log(tr("core.scheduler.all_failed"), "ERROR")
        if tg and attempts > 1:
            tg.send_message("Backup failed after all retry attempts — check the log on the VPS.")
        return last
    finally:
        _job_lock.release()


class DailyScheduler:
    """Daily scheduling with fixed time + Catch up on a missed appointment + Alert when there are no successful copies."""

    def __init__(self, cfg, tg=None, progress_cb=None, announce=False):
        self.cfg = cfg
        self.tg = tg
        self.progress_cb = progress_cb
        self.announce = announce
        self._stop = threading.Event()
        self.cancel_event = threading.Event()  # Cancel the ongoing backup when stopped
        self.thread = None
        self._last_run_date = None
        self._started_at = datetime.datetime.now()
        self._last_alert = 0.0

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        threading.Thread(target=self._monitor_loop, name="backup-heartbeat", daemon=True).start()
        if self.cfg["schedule"].get("enabled", True):
            log(tr("core.scheduler.enabled", time=self.cfg["schedule"].get("time", "03:00")))
        else:
            log(tr("core.scheduler.disabled"))

    def stop(self):
        self._stop.set()
        self.cancel_event.set()

    def _parse_times(self):
        """Return sorted [(hh, mm)] from the active schedule mode."""
        scfg = self.cfg["schedule"]
        times = []
        if scfg.get("mode", "daily") == "times":
            for t in (scfg.get("times") or []):
                try:
                    hh, mm = map(int, str(t).split(":"))
                    if 0 <= hh < 24 and 0 <= mm < 60:
                        times.append((hh, mm))
                except (ValueError, TypeError):
                    continue
        if not times:
            try:
                hh, mm = map(int, scfg.get("time", "03:00").split(":"))
            except (ValueError, TypeError):
                hh, mm = 3, 0
            times = [(hh, mm)]
        return sorted(set(times))

    def _scheduled_time_today(self, now):
        hh, mm = self._parse_times()[0]
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    def _interval_hours(self):
        return max(1, int(self.cfg["schedule"].get("interval_hours", 6) or 6))

    def next_run(self, now=None):
        now = now or datetime.datetime.now()
        scfg = self.cfg["schedule"]
        if scfg.get("mode", "daily") == "interval":
            last = last_successful_run() or last_attempted_run() or now
            return last + datetime.timedelta(hours=self._interval_hours())
        times = self._parse_times()
        for hh, mm in times:
            t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t > now:
                return t
        hh, mm = times[0]
        return (now + datetime.timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)

    def _due(self, now):
        """Return whether a scheduled run is due (daily/times/interval)."""
        scfg = self.cfg["schedule"]
        if not scfg.get("enabled", True):
            return False
        last = last_successful_run()
        attempt = last_attempted_run()
        if scfg.get("mode", "daily") == "interval":
            # Use the MOST RECENT of success/attempt. Using only last_success made
            # a failed (partial) run re-trigger every loop.
            candidates = [d for d in (last, attempt) if d]
            ref = max(candidates) if candidates else self._started_at
            return (now - ref).total_seconds() >= self._interval_hours() * 3600
        # daily / times: due if any configured time today has passed and was not run.
        for hh, mm in self._parse_times():
            scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if now < scheduled:
                continue
            if (last and last >= scheduled) or (attempt and attempt >= scheduled):
                continue
            return True
        return False

    def _wait_for_bot(self, timeout=90):
        wait = getattr(self.tg, "wait_ready", None)
        if callable(wait):
            wait(timeout)

    def _announce_start(self):
        if not (self.tg and self.tg.is_configured()):
            return
        last = last_successful_run()
        hours = float(self.cfg.get("monitoring", {}).get("alert_after_hours", 26) or 0)
        lines = [f"Backup service started on {socket.gethostname()}.",
                 f"Last successful backup: {last.strftime('%Y-%m-%d %H:%M') if last else 'never'}"
                 f" ({_ago(last)})"]
        if self.cfg["schedule"].get("enabled", True):
            lines.append(f"Next scheduled backup: {self.next_run().strftime('%Y-%m-%d %H:%M')}")
        else:
            lines.append("The daily schedule is disabled.")
        if hours and last and (datetime.datetime.now() - last).total_seconds() > hours * 3600:
            lines.append(f"No successful backup for more than {hours:g} hours — "
                         "the service was probably down.")
        self.tg.send_message("\n".join(lines))

    def _check_stale(self, now):
        """Warning if more than alert_after_hours Without a successful backup (Once every 12 An hour)."""
        hours = float(self.cfg.get("monitoring", {}).get("alert_after_hours", 26) or 0)
        if not hours or is_busy() or time.time() - self._last_alert < 12 * 3600:
            return
        ref = last_successful_run() or self._started_at
        if (now - ref).total_seconds() <= hours * 3600:
            return
        self._last_alert = time.time()
        last = last_successful_run()
        log(tr("core.scheduler.stale", hours=f"{hours:g}"), "ERROR")
        if self.tg:
            self.tg.send_message(
                f"No successful backup for more than {hours:g} hours!\n"
                f"Last success: {last.strftime('%Y-%m-%d %H:%M') if last else 'never'} ({_ago(last)}).\n"
                "Check the log on the VPS or send /backup.")

    def _loop(self):
        if self.announce:
            try:
                self._wait_for_bot()
                self._announce_start()
            except Exception as e:
                log(tr("core.scheduler.loop_error", err=e), "ERROR")
        self._last_beat = 0.0
        while not self._stop.is_set():
            try:
                now = datetime.datetime.now()
                if self._due(now):
                    if is_busy():
                        # A manual or bot job is already running. Do not mark the
                        # day as attempted; the scheduler will retry next cycle.
                        log(tr("core.scheduler.busy"), "WARN")
                    else:
                        self._last_run_date = now.date()
                        record_attempt(now)
                        late = (now - self._scheduled_time_today(now)).total_seconds() > 600
                        log(tr("core.scheduler.catchup") if late else tr("core.scheduler.scheduled_due"))
                        self._wait_for_bot(30)
                        run_with_retries(self.cfg, tg=self.tg, progress_cb=self.progress_cb,
                                         cancel_event=self.cancel_event)
            except Exception as e:
                log(tr("core.scheduler.loop_error", err=e), "ERROR")
            self._stop.wait(20)  # Check all 20 Again

    def _monitor_loop(self):
        """Emit the external heartbeat and stale check independently of backups.

        The backup loop can block for hours inside run_with_retries, so these
        signals must not depend on it or the dead-man switch raises false alarms.
        """
        while not self._stop.is_set():
            try:
                self._check_stale(datetime.datetime.now())
                monitor.heartbeat(self.cfg)
            except Exception as e:
                log(tr("core.scheduler.loop_error", err=e), "ERROR")
            if self._stop.wait(60):
                break
