# -*- coding: utf-8 -*-
"""Cloud upload via rclone — supports Google Drive, Dropbox, OneDrive, S3, B2 And more than 40 Service.

The client activates his cloud accounts once with a command:  rclone config
Then he chooses the destinations (remotes) From the tool interface — It can be raised to more than one point at a time.
"""

import os
import re
import json
import time
import subprocess
import shutil

from logger_utils import log
from i18n import tr

RCLONE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rclone")

# Path rclone.conf Actual user — Necessary for the tool to run as a service SYSTEM
# (Account SYSTEM He has a folder AppData Different and will not find cloud accounts without it)
RCLONE_CONFIG = ""

# No practical time limit for uploading (Large copies were failing after two hours)
UPLOAD_TIMEOUT = 24 * 3600


def find_rclone():
    """find rclone.exe — From the tool folder or from PATH."""
    exe = "rclone.exe" if os.name == "nt" else "rclone"
    local = os.path.join(RCLONE_DIR, exe)
    if os.path.exists(local):
        return local
    system = shutil.which("rclone")
    return system


def is_available():
    return find_rclone() is not None


def _detect_config_path():
    """The path it uses rclone For the current user (If the file already exists)."""
    local = os.path.join(RCLONE_DIR, "rclone.conf")
    if os.path.exists(local):
        return os.path.abspath(local)
    exe = find_rclone()
    if not exe:
        return ""
    try:
        proc = subprocess.run([exe, "config", "file"], capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace",
                              creationflags=0x08000000 if os.name == "nt" else 0)
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.lower().endswith(".conf") and os.path.exists(line):
                return line
    except Exception:
        pass
    return ""


def configure(cfg):
    """Install path rclone.conf. He comes back True If a new path is discovered and added to cfg (Worth saving)."""
    global RCLONE_CONFIG
    path = (cfg.get("cloud", {}).get("rclone_config") or "").strip()
    if path and os.path.exists(path):
        RCLONE_CONFIG = path
        return False
    detected = _detect_config_path()
    if path and not detected:
        log(tr("core.cloud.config_missing", path=path), "WARN")
    RCLONE_CONFIG = detected or path
    if detected and detected != path:
        cfg.setdefault("cloud", {})["rclone_config"] = detected
        return True
    return False


def base_args():
    return ["--config", RCLONE_CONFIG] if RCLONE_CONFIG else []


def _run(args, timeout=7200):
    """Run a command rclone And return (Success?, Outputs)."""
    exe = find_rclone()
    if not exe:
        return False, "rclone not found — run scripts\\install_rclone.bat first"
    cmd = [exe] + base_args() + args
    # Hide window rclone Black on Windows — Uploading is completely silent
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", **kwargs)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "rclone timed out (the operation took too long)"
    except Exception as e:
        return False, str(e)


def _run_progress(args, progress_cb=None, timeout=UPLOAD_TIMEOUT):
    """Run rclone and stream its percentage (via --stats-one-line) to progress_cb."""
    exe = find_rclone()
    if not exe:
        return False, "rclone not found"
    cmd = [exe] + base_args() + args + ["--stats-one-line", "--stats", "2s"]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", **kwargs)
    except Exception as e:
        return False, str(e)
    out_lines = []
    deadline = time.time() + timeout
    try:
        for line in proc.stdout:
            out_lines.append(line)
            if progress_cb:
                m = re.search(r"(\d{1,3})\s*%", line)
                if m:
                    try:
                        progress_cb(min(100, int(m.group(1))), "")
                    except Exception:
                        pass
            if time.time() > deadline:
                proc.kill()
                return False, "rclone timed out"
        proc.wait()
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return False, str(e)
    return proc.returncode == 0, "".join(out_lines).strip()


def list_remotes():
    """List of destinations set up in rclone (Example: ['gdrive:', 'dropbox:'])."""
    ok, out = _run(["listremotes"], timeout=60)
    if not ok:
        log(tr("core.cloud.listremotes_fail", err=out[:300]), "WARN")
        return []
    return [r.strip() for r in out.splitlines() if r.strip()]


def verify_upload(archive_path, dest):
    """Match the uploaded file with the local one (Size + The hashtag if the service supports it). He comes back (ok, Description)."""
    name = os.path.basename(archive_path)
    ok, out = _run(["check", os.path.dirname(os.path.abspath(archive_path)), dest,
                    "--one-way", "--include", f"/{name}"], timeout=3600)
    if not ok:
        return False, out[-300:]
    size_only = "hash" in out.lower() and ("could not" in out.lower() or "no common" in out.lower())
    return True, "size only" if size_only else "hash match"


def _remote_file_id(archive_path, dest):
    """The file ID on the service — To discover two destinations that point to the same account/Vol."""
    ok, out = _run(["lsjson", dest, "--files-only", "--no-mimetype",
                    "--include", f"/{os.path.basename(archive_path)}"], timeout=300)
    if not ok:
        return None
    try:
        start = out.find("[")
        items = json.JSONDecoder().raw_decode(out[start:])[0] if start >= 0 else []
        return items[0].get("ID") if items else None
    except Exception:
        return None


def _clean(out):
    """lines rclone Only useful — No notifications NOTICE The long one."""
    lines = [l for l in out.splitlines() if " NOTICE: " not in l and l.strip()]
    return "\n".join(lines).strip()[-400:] if lines else out[-300:]


def upload_to_cloud(archive_path, cfg, progress_cb=None, verify=True):
    """Upload the archive to all activated destinations. Returns a list (remote, Success, Message)."""
    ccfg = cfg["cloud"]
    remotes = ccfg.get("remotes", [])
    folder = ccfg.get("remote_folder", "VPS-Backups").strip("/")
    results = []
    seen_ids = {}

    if not remotes:
        log(tr("core.cloud.no_remotes"), "WARN")
        return results

    for idx, remote in enumerate(remotes):
        remote = remote.strip()
        if not remote.endswith(":"):
            remote += ":"
        dest = f"{remote}{folder}"
        log(tr("core.cloud.uploading", name=os.path.basename(archive_path), dest=dest))
        if progress_cb:
            progress_cb(int(idx * 100 / len(remotes)), tr("core.cloud.uploading_progress", remote=remote))
        try:
            import backup_engine
            backup_engine.mark_in_use(archive_path)  # Do not be deleted by another process during upload
        except Exception:
            pass
        def _local_cb(local_pct, _msg):
            if progress_cb:
                overall = int((idx + local_pct / 100.0) * 100 / len(remotes))
                progress_cb(overall, tr("core.cloud.uploading_progress", remote=remote))

        ok, out = _run_progress(["copy", archive_path, dest, "--retries", "3",
                                 "--low-level-retries", "10"],
                                progress_cb=_local_cb, timeout=UPLOAD_TIMEOUT)
        try:
            import backup_engine
            backup_engine.unmark_in_use(archive_path)
        except Exception:
            pass
        if not ok:
            if not os.path.exists(archive_path):
                log(tr("core.cloud.source_vanished", name=os.path.basename(archive_path)), "ERROR")
            log(tr("core.cloud.upload_fail", dest=dest, err=_clean(out)), "ERROR")
            results.append((remote, False, _clean(out)[:200]))
            continue
        log(tr("core.cloud.upload_ok", dest=dest))
        msg = "uploaded"
        if verify:
            vok, how = verify_upload(archive_path, dest)
            if not vok:
                log(tr("core.cloud.verify_fail", dest=dest, err=_clean(how)), "ERROR")
                results.append((remote, False, "verification failed"))
                continue
            log(tr("core.cloud.verify_ok", dest=dest, how=how))
            msg = f"verified ({how})"
            fid = _remote_file_id(archive_path, dest)
            if fid and fid in seen_ids:
                log(tr("core.cloud.same_storage", a=seen_ids[fid], b=remote), "WARN")
                msg += " — same storage as " + seen_ids[fid]
            elif fid:
                seen_ids[fid] = remote
        results.append((remote, True, msg))
        apply_retention(remote, cfg, keep_name=os.path.basename(archive_path))
    return results


def apply_retention(remote, cfg, keep_name=None):
    """Delete copies of the tool only (Backup_*.zip) Older than the retention period — It does not touch any other file.

    The archive we just uploaded is explicitly excluded: rclone preserves the
    local modification time, so a restored/old archive would otherwise be
    deleted immediately after a "successful" upload.
    """
    days = int(cfg["cloud"].get("retention_days", 30))
    folder = cfg["cloud"].get("remote_folder", "VPS-Backups").strip("/")
    dest = f"{remote}{folder}"
    filters = ["delete", dest, "--min-age", f"{days}d"]
    if keep_name:
        filters += ["--exclude", "/" + keep_name]
    filters += ["--include", "/Backup_*.zip", "--include", "/Backup_*.zip.part*"]
    ok, out = _run(filters)
    if ok:
        log(tr("core.cloud.retention_ok", days=days, dest=dest))
    else:
        log(tr("core.cloud.retention_fail", dest=dest, err=out[:300]), "WARN")


def _normalized_remotes(cfg):
    """List of enabled destinations in rclone Standard (ending with ':')."""
    remotes = []
    for r in cfg["cloud"].get("remotes", []):
        r = r.strip()
        if not r:
            continue
        if not r.endswith(":"):
            r += ":"
        remotes.append(r)
    return remotes


def get_share_link(archive_path, cfg):
    """Create a public sharing link for the file on all enabled destinations.

    He comes back dict In the form of {remote: link Or None} — Link for each remote He succeeded, andNone When he failed.
    """
    links = {}
    folder = cfg["cloud"].get("remote_folder", "VPS-Backups").strip("/")
    name = os.path.basename(archive_path)
    for remote in _normalized_remotes(cfg):
        ok, out = _run(["link", f"{remote}{folder}/{name}"], timeout=120)
        link = None
        if ok:
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line.startswith("http"):
                    link = line
                    break
        if link:
            links[remote] = link
        else:
            log(tr("core.cloud.link_fail", remote=remote, err=out[:200]), "WARN")
            links[remote] = None
    return links


def list_remote_backups(cfg):
    """List of instances on all enabled destinations (To order /list In the bot).

    He comes back dict In the form of {remote: [lines lsl]} — Another 30 Copy for each remote.
    """
    result = {}
    folder = cfg["cloud"].get("remote_folder", "VPS-Backups").strip("/")
    for remote in _normalized_remotes(cfg):
        ok, out = _run(["lsl", f"{remote}{folder}"], timeout=120)
        if not ok:
            log(tr("core.cloud.list_fail", remote=remote, err=out[:200]), "WARN")
            result[remote] = []
            continue
        lines = [l.strip() for l in out.splitlines() if l.strip().endswith(".zip")]
        result[remote] = lines[-30:]  # Another 30 Copy
    return result
