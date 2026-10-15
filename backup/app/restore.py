# -*- coding: utf-8 -*-
"""Restore and restore-drill engine for RDP Suite backups.

A verified archive CRC is not proof that a backup can be restored, so this
module extracts an archive into a new, isolated destination, then
verifies every restored file against the archive manifest by size AND content
(CRC). It refuses to restore when the manifest is missing or malformed, when the
manifest does not match the archive contents, or when the destination already
exists / contains a link or reparse point. It never restores over the original
paths: the caller chooses an isolated destination and the archive's relative
structure is recreated underneath it.

Public contract (do not break):
    list_backups() -> list[dict]
    new_restore_dir(base, label="") -> str
    restore_archive(archive_path, dest_root, password="", progress_cb=None,
                    cancel_event=None) -> dict
    run_drill(cfg, dest_root, log=None, cancel_event=None) -> dict
"""

import datetime
import os
import shutil
import time
import zipfile
import zlib
import uuid

from logger_utils import log as _default_log

try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    HAS_PYZIPPER = False

import backup_engine

MANIFEST_NAME = "manifest.txt"
CHUNK = 1024 * 1024


def _is_manifest(name):
    # Only the generated root index, never a backed-up user's manifest.txt.
    return name == MANIFEST_NAME or (name.count("/") == 1 and name.endswith("/" + MANIFEST_NAME))


def _safe_target(dest_root, member_name):
    """Reject zip-slip and Windows aliases (ADS, devices, trailing dots/spaces)."""
    parts = member_name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update("COM" + c for c in "123456789¹²³")
    reserved.update("LPT" + c for c in "123456789¹²³")
    if (not member_name or "\\" in member_name or
            any(not p or p in (".", "..") or p.endswith((".", " ")) or
                any(ord(c) < 32 or c in ':<>\"|?*' for c in p) or
                p.split(".")[0].upper() in reserved for p in parts)):
        raise ValueError("unsafe path in archive: " + member_name)
    root = os.path.normpath(os.path.abspath(dest_root))
    target = os.path.normpath(os.path.join(root, *parts))
    if not os.path.normcase(target).startswith(os.path.normcase(root + os.sep)):
        raise ValueError("unsafe path in archive: " + member_name)
    return target


class _RestoreCancelled(Exception):
    pass


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise _RestoreCancelled()


def _crc32(path, cancel_event=None):
    crc = 0
    with open(path, "rb") as f:
        while True:
            _check_cancel(cancel_event)
            chunk = f.read(CHUNK)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _is_reparse_point(path):
    """True when the path itself is a symlink/junction (Windows reparse point)."""
    try:
        if os.path.islink(path):
            return True
    except OSError:
        return True
    if os.name != "nt":
        return False
    try:
        import ctypes
        FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attrs != -1 and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def _assert_no_links(path):
    dest = os.path.abspath(path)
    drive, rest = os.path.splitdrive(dest)
    current = drive + os.sep if drive else os.sep
    if _is_reparse_point(current):
        raise ValueError("destination path contains a link/reparse point: " + current)
    for part in rest.strip("\\/").split("\\" if os.name == "nt" else "/"):
        if not part:
            continue
        current = os.path.join(current, part)
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError("destination path contains a link/reparse point: " + current)


def _assert_safe_dest(dest_root):
    """Require a new destination with no link/reparse point in its path."""
    dest = os.path.abspath(dest_root)
    _assert_no_links(dest)
    if os.path.lexists(dest):
        raise ValueError("destination already exists: " + dest)


def new_restore_dir(base, label=""):
    """Return a unique, timestamped destination directory (never overwrites)."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in (label or "restore") if c.isalnum() or c in "-_")[:40]
    return os.path.join(base, "%s-%s-%s" % (safe or "restore", stamp, uuid.uuid4().hex))


def list_backups():
    """Return local archives, newest first, with basic metadata."""
    out = []
    d = backup_engine.BACKUP_DIR
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return out
    for name in names:
        path = os.path.join(d, name)
        if not (name.startswith("Backup_") and name.endswith(".zip") and os.path.isfile(path)):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "path": path, "size": st.st_size, "mtime": st.st_mtime})
    return out


def _open_archive(path, password=""):
    if password and HAS_PYZIPPER:
        zf = pyzipper.AESZipFile(path, "r")
        zf.setpassword(password.encode("utf-8"))
        return zf
    return zipfile.ZipFile(path, "r")


def read_manifest(zf):
    """Parse exactly one generated index; reject malformed or duplicate rows."""
    names = [name for name in zf.namelist() if _is_manifest(name)]
    if len(names) != 1:
        raise ValueError("archive must contain exactly one generated manifest")
    raw = zf.read(names[0]).decode("utf-8")
    lines = raw.splitlines()
    if len(lines) < 2:
        raise ValueError("malformed manifest header")
    entries = []
    seen = set()
    for line in lines[2:]:
        parts = line.split("\t")
        if len(parts) not in (3, 4) or not parts[0] or parts[0] in seen:
            raise ValueError("malformed or duplicate manifest entry")
        size = int(parts[1])
        crc = int(parts[3], 16) if len(parts) == 4 else None
        if size < 0 or (crc is not None and not 0 <= crc <= 0xFFFFFFFF):
            raise ValueError("invalid manifest size or CRC")
        seen.add(parts[0])
        entries.append((parts[0], size, crc))
    return entries


def restore_archive(archive_path, dest_root, password="", progress_cb=None, cancel_event=None):
    """Extract an archive into a new isolated destination and verify it.

    Returns a dict:
        status  — "ok" | "error" | "cancelled"
        dest    — destination directory
        restored— number of files written
        checked — manifest entries verified
        missing — files that were absent, size-mismatched, or content-mismatched
        message — human-readable detail
    """
    result = {"status": "error", "dest": dest_root, "restored": 0,
              "checked": 0, "missing": [], "message": "", "created": False}
    if not os.path.isfile(archive_path):
        result["message"] = "archive not found"
        return result
    if password and not HAS_PYZIPPER:
        result["message"] = "archive is encrypted but pyzipper is not installed"
        return result

    # Never write into an existing/linked destination.
    try:
        _assert_safe_dest(dest_root)
    except ValueError as e:
        result["message"] = str(e)
        return result
    dest_root = os.path.abspath(dest_root)

    try:
        zf = _open_archive(archive_path, password)
    except Exception as e:
        result["message"] = "cannot open archive: %r" % e
        return result

    try:
        with zf:
            manifest = read_manifest(zf)
            members = [n for n in zf.namelist() if not n.endswith("/") and not _is_manifest(n)]
            if not manifest:
                result["message"] = ("archive has no valid manifest; refusing to report a "
                                     "successful restore")
                return result
            if (len(set(members)) != len(members) or
                    {arc for arc, _, _ in manifest} != set(members)):
                result["message"] = "manifest and archive members do not match exactly"
                return result
            targets = [_safe_target(dest_root, name) for name in members]
            normalized = {os.path.normcase(target) for target in targets}
            if len(normalized) != len(targets):
                raise ValueError("archive members alias the same destination")
            for target in targets:
                parent = os.path.dirname(target)
                while parent != dest_root:
                    if os.path.normcase(parent) in normalized:
                        raise ValueError("archive file conflicts with a directory")
                    parent = os.path.dirname(parent)

            info = {i.filename: i for i in zf.infolist()}
            _check_cancel(cancel_event)
            _assert_safe_dest(dest_root)
            os.makedirs(os.path.dirname(dest_root), exist_ok=True)
            os.mkdir(dest_root)
            result["created"] = True
            restored = 0
            total = max(1, len(members))
            for i, name in enumerate(members, 1):
                _check_cancel(cancel_event)
                target = _safe_target(dest_root, name)
                _assert_no_links(target)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _assert_no_links(target)
                with zf.open(name) as src, open(target, "xb") as dst:
                    while True:
                        _check_cancel(cancel_event)
                        chunk = src.read(CHUNK)
                        if not chunk:
                            break
                        dst.write(chunk)
                restored += 1
                result["restored"] = restored
                if progress_cb and (i == total or i % 200 == 0):
                    progress_cb(int(i * 100 / total), "restoring %d/%d" % (i, total))

            # Verify every manifest entry: exists, correct size, correct content.
            missing = []
            for arc, size, crc in manifest:
                _check_cancel(cancel_event)
                target = _safe_target(dest_root, arc)
                if not os.path.isfile(target):
                    missing.append(arc)
                    continue
                if size >= 0 and os.path.getsize(target) != size:
                    missing.append(arc)
                    continue
                actual = _crc32(target, cancel_event)
                if crc is not None:
                    # Verify against the ORIGINAL content hash recorded at backup time.
                    if actual != crc:
                        missing.append(arc)
                else:
                    # Older manifest without a hash: fall back to the archive CRC.
                    member = info.get(arc)
                    # AE-2 omits CRC; zf.open already verified its authentication tag.
                    if (member is not None and getattr(member, "wz_aes_version", None) != 2
                            and actual != (member.CRC & 0xFFFFFFFF)):
                        missing.append(arc)
    except _RestoreCancelled:
        result["status"] = "cancelled"
        result["message"] = "cancelled by user"
        return result
    except Exception as e:
        result["message"] = "restore failed: %r" % e
        return result

    result.update({"status": "ok" if not missing else "error",
                   "restored": restored, "checked": len(manifest), "missing": missing[:20],
                   "message": "restored %d files, verified %d manifest entries (size + CRC)"
                              % (restored, len(manifest))})
    if missing:
        result["message"] += "; %d mismatched" % len(missing)
    return result


def run_drill(cfg, dest_root, log=None, cancel_event=None):
    """Restore the newest archive into a new isolated dir and verify it.

    The extracted copy is removed afterwards unless keep=True in the config.
    """
    _log = log or _default_log
    backups = list_backups()
    if not backups:
        return {"status": "error", "message": "no local archive to drill"}
    newest = backups[0]
    password = (cfg.get("backup", {}).get("archive_password") or "").strip()
    drill_cfg = cfg.get("restore_drill", {}) or {}
    base = dest_root or drill_cfg.get("dest") or os.path.join(
        backup_engine.TOOL_ROOT, "restore-drills")
    target = new_restore_dir(base, "drill")
    _log("Restore drill started: %s -> %s" % (newest["name"], target))
    res = restore_archive(newest["path"], target, password=password,
                          cancel_event=cancel_event)
    res["archive"] = newest["name"]
    if res["status"] == "ok":
        _log("Restore drill passed: %s" % res["message"])
    else:
        _log("Restore drill FAILED: %s" % res.get("message", ""), "ERROR")
    if not drill_cfg.get("keep", False) and res.get("created", False):
        try:
            shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass
    res["drilled_at"] = time.time()
    return res
