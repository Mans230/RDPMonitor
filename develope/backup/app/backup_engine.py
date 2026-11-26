# -*- coding: utf-8 -*-
"""Pickup engine — Pressure ZIP While preserving the original tracks within Folder in the name of history.

Archive structure:
    Backup_2026-08-08_03-00-00.zip
    └── 2026-08-08_03-00-00/
        ├── manifest.txt                  (Index: Archive name, size, original path)
        ├── C/inetpub/wwwroot/site/...   (The original path is saved)
        └── D/data/...

If there is a password in the settings, it is used AES (pyzipper) — The file opens with 7-Zip/WinRAR.

    General contract (do not break it; the interface depends on it):
    create_backup(cfg, log, progress_cb=None, cancel_event=None) -> (files, status)
        - progress_cb(percent: int, message: str) Called during examination and compression.
        - cancel_event: threading.Event — When set, the process stops gracefully and is deleted
          Partial files, returns ([], "cancelled").
        - status: "ok" | "partial" | "cancelled" | "error"
    split_file(path, max_part_bytes, progress_cb=None, cancel_event=None) -> list[str]
        Divide into batches 8MB (It does not read the entire file into memory).
"""

import os
import time
import json
import fnmatch
import hashlib
import shutil
import datetime
import zipfile

try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    HAS_PYZIPPER = False

from logger_utils import log as _default_log
from i18n import tr

# Folder the tool itself — Always excluded from copying (In it config.json The session and previous versions)
TOOL_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BACKUP_DIR = os.path.join(TOOL_ROOT, "local_backups")

# Read batch size during partitioning — 8MB So that the entire file is not read in memory
CHUNK_SIZE = 8 * 1024 * 1024

# Files currently being uploaded on Telegram — Do not delete them during cleaning
_files_in_use = set()

# Statistics of the last successful backup — He reads it scheduler To report
LAST_STATS = {"count": 0, "size": 0, "errors": 0, "verified": None, "sha256": "", "signature": None}

# Status of the latest local copy (Content fingerprint) — To reveal "No change" Keep one copy
LOCAL_STATE_FILE = os.path.join(TOOL_ROOT, "logs", "local_state.json")


class _Cancelled(Exception):
    """Internal exception to stop the process when set cancel_event."""


def mark_in_use(path):
    _files_in_use.add(os.path.abspath(path))


def unmark_in_use(path):
    _files_in_use.discard(os.path.abspath(path))


def _is_cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _should_exclude(path, exclude_exts, max_size_bytes):
    ext = os.path.splitext(path)[1].lower()
    if ext in exclude_exts:
        return True, tr("core.exclude.ext", ext=ext)
    if max_size_bytes > 0:
        try:
            if os.path.getsize(path) > max_size_bytes:
                return True, tr("core.exclude.too_large")
        except OSError:
            return True, tr("core.exclude.size_unknown")
    return False, ""


def _arcname_for(file_path):
    """Convert the full path to a path within the archive while preserving the structure.
    C:\\inetpub\\wwwroot\\a.txt  ->  C/inetpub/wwwroot/a.txt
    """
    p = os.path.abspath(file_path)
    drive, rest = os.path.splitdrive(p)
    drive = drive.replace(":", "").replace("\\", "").replace("/", "")
    rest = rest.lstrip("\\/")
    return os.path.join(drive, rest).replace("\\", "/") if drive else rest.replace("\\", "/")


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_inside_tool(path):
    """Is the path inside the folder the same tool?"""
    p, root = _norm(os.path.realpath(path)), _norm(os.path.realpath(TOOL_ROOT))
    return p == root or p.startswith(root + os.sep)


def _matches_pattern(path, patterns):
    """Pattern without path separator that matches the name (node_modules, *.bak); Otherwise matches the full path."""
    if not patterns:
        return False
    full = _norm(path)
    name = os.path.normcase(os.path.basename(path))
    for pat in patterns:
        if ("\\" in pat or "/" in pat):
            if fnmatch.fnmatch(full, _norm(pat)) or full.startswith(_norm(pat) + os.sep):
                return True
        elif fnmatch.fnmatch(name, os.path.normcase(pat)):
            return True
    return False


def normalize_patterns(patterns):
    out = []
    for p in patterns or []:
        p = p.strip().strip('"').rstrip("\\/")
        if p:
            out.append(p)
    return out


def collect_files(sources, exclude_exts, max_size_mb, progress_cb=None, exclude_patterns=None,
                  cancel_event=None):
    """Collect all files from sources with exceptions applied (The tool folder is always excluded).

    Returns (files, skipped, missing) where `missing` lists configured sources
    that do not exist, so the caller can fail instead of reporting a false success.
    """
    exclude_exts = [e.lower() if e.startswith(".") else "." + e.lower() for e in exclude_exts]
    patterns = normalize_patterns(exclude_patterns)
    max_size_bytes = int(max_size_mb or 0) * 1024 * 1024
    files, skipped, missing = [], [], []
    tool_skipped = False
    def walk_error(error):
        missing.append(error.filename or "unreadable directory")
        skipped.append((error.filename or "", str(error)))
    for src in sources:
        if _is_cancelled(cancel_event):
            raise _Cancelled()
        src = src.strip().strip('"')
        if not src:
            continue
        src = os.path.abspath(src)
        if not os.path.exists(src):
            skipped.append((src, tr("core.collect.missing_source_reason")))
            missing.append(src)
            _default_log(tr("core.collect.missing_source", src=src), "WARN")
            continue
        if is_inside_tool(src):
            tool_skipped = True
            skipped.append((src, tr("core.exclude.tool_folder")))
            continue
        if os.path.isfile(src):
            ex, reason = _should_exclude(src, exclude_exts, max_size_bytes)
            if not ex and _matches_pattern(src, patterns):
                ex, reason = True, tr("core.exclude.pattern")
            (skipped if ex else files).append((src, reason) if ex else src)
            continue
        for root, dirs, names in os.walk(src, onerror=walk_error):
            if _is_cancelled(cancel_event):
                raise _Cancelled()
            kept = []
            for d in dirs:
                full_d = os.path.join(root, d)
                if is_inside_tool(full_d):
                    tool_skipped = True
                    skipped.append((full_d, tr("core.exclude.tool_folder")))
                elif _matches_pattern(full_d, patterns):
                    skipped.append((full_d, tr("core.exclude.pattern")))
                else:
                    kept.append(d)
            dirs[:] = kept
            for name in names:
                if _is_cancelled(cancel_event):
                    raise _Cancelled()
                full = os.path.join(root, name)
                if is_inside_tool(full):
                    tool_skipped = True
                    skipped.append((full, tr("core.exclude.tool_folder")))
                    continue
                ex, reason = _should_exclude(full, exclude_exts, max_size_bytes)
                if not ex and _matches_pattern(full, patterns):
                    ex, reason = True, tr("core.exclude.pattern")
                if ex:
                    skipped.append((full, reason))
                else:
                    files.append(full)
                if progress_cb and (len(files) % 200 == 0):
                    progress_cb(0, tr("core.collect.scanned", count=len(files)))
    if tool_skipped:
        _default_log(tr("core.collect.tool_skipped", path=TOOL_ROOT), "WARN")
    # Overlapping configured sources must not create duplicate ZIP members.
    unique = {}
    for path in files:
        unique.setdefault(_norm(path), path)
    return list(unique.values()), skipped, missing


def file_sha256(path, cancel_event=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if _is_cancelled(cancel_event):
                raise _Cancelled()
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path, password="", expected_count=None, manifest_name=None):
    """Open the archive, verify every entry CRC, and compare the entry count.

    Only the generated manifest entry is excluded from the count. Passing the
    exact manifest path avoids miscounting a user file that happens to be
    named manifest.txt somewhere in the backed-up sources.
    """
    try:
        if password and HAS_PYZIPPER:
            zf = pyzipper.AESZipFile(path, "r")
            zf.setpassword(password.encode("utf-8"))
        else:
            zf = zipfile.ZipFile(path, "r")
        with zf:
            bad = zf.testzip()
            if bad:
                return False, tr("core.verify.bad_entry", name=bad)
            names = zf.namelist()
            if manifest_name and manifest_name not in names:
                return False, "generated manifest is missing"
            entries = len([n for n in names if n != manifest_name]) if manifest_name else len(names)
        if expected_count is not None and entries != expected_count:
            return False, tr("core.verify.count_mismatch", found=entries, expected=expected_count)
        return True, tr("core.verify.ok", count=entries)
    except Exception as e:
        return False, str(e)


_SAMPLE = 64 * 1024


def _file_sample_digest(fp):
    """Cheap content fingerprint: size plus the first and last 64 KB."""
    st = os.stat(fp)
    h = hashlib.sha256()
    h.update(str(st.st_size).encode())
    with open(fp, "rb") as f:
        h.update(f.read(_SAMPLE))
        if st.st_size > 2 * _SAMPLE:
            f.seek(-_SAMPLE, os.SEEK_END)
            h.update(f.read(_SAMPLE))
    return h.hexdigest()


def files_signature(files):
    """Content fingerprint: Relative path + Size + Edit time + content sample.

    Including a content sample avoids deleting a distinct backup when two source
    states happen to share the same size and (coarse) modification time.
    """
    h = hashlib.sha256()
    for fp in sorted(files):
        try:
            st = os.stat(fp)
            try:
                digest = _file_sample_digest(fp)
            except OSError:
                digest = "unreadable"
            h.update(f"{_arcname_for(fp)}|{st.st_size}|{int(st.st_mtime)}|{digest}\n".encode("utf-8", "replace"))
        except OSError:
            h.update(f"{_arcname_for(fp)}|unreadable\n".encode("utf-8", "replace"))
    return h.hexdigest()


def _load_local_state():
    try:
        with open(LOCAL_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_local_state(state):
    try:
        os.makedirs(os.path.dirname(LOCAL_STATE_FILE), exist_ok=True)
        with open(LOCAL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def create_backup(cfg, log=None, progress_cb=None, cancel_event=None):
    """Create a backup archive.

    He comes back (files, status):
        files  — List of resulting file paths (archive; It may become more numerous in the future with division)
        status — "ok" | "partial" | "cancelled" | "error"
                 "partial" means the archive exists but some files were unreadable.
    """
    _log = log or _default_log
    bcfg = cfg["backup"]
    sources = bcfg.get("sources", [])
    if not sources:
        raise ValueError(tr("core.backup.no_sources"))

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"Backup_{stamp}.zip"
    archive_path = os.path.join(BACKUP_DIR, archive_name)
    # Pak Aban in the same second: Do not overwrite the existing one — Add suffix _2, _3, ...
    suffix = 1
    while os.path.exists(archive_path):
        suffix += 1
        archive_name = f"Backup_{stamp}_{suffix}.zip"
        archive_path = os.path.join(BACKUP_DIR, archive_name)
    inner_root = stamp  # An internal folder with the name of date and time

    _log(tr("core.backup.start", name=archive_name))
    try:
        files, skipped, missing = collect_files(
            sources,
            bcfg.get("exclude_extensions", []),
            bcfg.get("exclude_max_size_mb", 0),
            progress_cb,
            exclude_patterns=bcfg.get("exclude_patterns", []),
            cancel_event=cancel_event,
        )
    except _Cancelled:
        _log(tr("core.backup.cancelled"), "WARN")
        return [], "cancelled"
    if _is_cancelled(cancel_event):
        _log(tr("core.backup.cancelled"), "WARN")
        return [], "cancelled"
    # A configured source that vanished means the backup cannot be complete.
    # Abort (fail closed) instead of reporting a successful backup.
    if missing and bcfg.get("require_all_sources", True):
        _log(tr("core.backup.missing_sources", list=", ".join(missing[:5])), "ERROR")
        raise ValueError(tr("core.backup.missing_sources", list=", ".join(missing[:5])))
    signature = files_signature(files)
    if not files:
        raise ValueError(tr("core.backup.no_files"))

    # Free-space precheck: the archive never exceeds the uncompressed total, so
    # require at least that much free space before writing anything.
    try:
        total_bytes = sum(os.path.getsize(f) for f in files)
        free_bytes = shutil.disk_usage(BACKUP_DIR).free
        if total_bytes > 0 and free_bytes < total_bytes:
            raise ValueError(tr("core.backup.no_space",
                                need=f"{total_bytes / 1024 / 1024:.0f}",
                                free=f"{free_bytes / 1024 / 1024:.0f}"))
    except OSError:
        pass

    password = (bcfg.get("archive_password") or "").strip()
    use_aes = bool(password) and HAS_PYZIPPER
    if password and not HAS_PYZIPPER:
        # Fail closed: never silently write an unencrypted archive when the
        # user configured a password.
        _log(tr("core.backup.no_pyzipper"), "ERROR")
        raise ValueError(tr("core.backup.encryption_unavailable"))

    total = len(files)
    _log(tr("core.backup.counts", total=total, skipped=len(skipped),
            enc=tr("core.backup.enc_aes") if use_aes else tr("core.backup.enc_none")))

    errors = 0
    vss_state = "off"
    manifest = []  # A real index inside the archive: Name, size, original path
    shadows = None
    archive_handle = None
    archive_created = False
    if bcfg.get("use_vss") and os.name == "nt":
        import vss
        shadows = vss.ShadowSet({os.path.splitdrive(f)[0] for f in files}, _log)
    try:
        if shadows is not None:
            shadows.__enter__()
            # A snapshot that could not be created means the affected drives were
            # read live; surface that so it is never assumed to be safe.
            vss_state = "partial" if shadows.failed_drives else "active"
        # Exclusive creation prevents same-second concurrent jobs overwriting data.
        archive_handle = open(archive_path, "xb")
        archive_created = True
        if use_aes:
            zf = pyzipper.AESZipFile(
                archive_handle, "w",
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES,
            )
            zf.setpassword(password.encode("utf-8"))
        else:
            zf = zipfile.ZipFile(archive_handle, "w", compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=True, compresslevel=6)

        with zf:
            for i, fp in enumerate(files, 1):
                if _is_cancelled(cancel_event):
                    raise _Cancelled()
                arc = f"{inner_root}/{_arcname_for(fp)}"
                src_path = shadows.map(fp) if shadows is not None else fp
                try:
                    zf.write(src_path, arc)
                    entry = zf.getinfo(arc)
                    # Manifest metadata describes the bytes archived, not a later live state.
                    fsize = entry.file_size
                    crc = entry.CRC
                    if use_aes and crc == 0 and fsize != 0:
                        # AES AE-2 may omit CRC; its authentication tag is
                        # verified when the entry is read on restore.
                        crc = None
                    manifest.append((arc, fsize, os.path.abspath(fp), crc))
                except Exception as e:
                    errors += 1
                    _log(tr("core.backup.compress_failed", path=fp, err=e), "WARN")
                # Updated at every actual change in the percentage (Each small backup file,
                # And a maximum ~90 Big update) So the tape moves smoothly
                if progress_cb and (i == total or int(i * 90 / total) != int((i - 1) * 90 / total)):
                    progress_cb(int(i * 90 / total), tr("core.backup.compressing", i=i, total=total))

            # An actual text index file inside the archive that makes it easy to see the content without decompressing
            header = tr("core.backup.manifest_header", stamp=stamp, count=len(manifest))
            lines = [header, tr("core.backup.manifest_columns")]
            lines += [(f"{arc}\t{fsize}\t{orig}" + (f"\t{crc:08x}" if crc is not None else ""))
                      for arc, fsize, orig, crc in manifest]
            # A backup without its manifest cannot be restored or drilled.
            zf.writestr(f"{inner_root}/manifest.txt", "\n".join(lines) + "\n")
            if progress_cb:
                progress_cb(95, tr("core.backup.writing_index"))
    except _Cancelled:
        # Close the raw handle before deleting: on Windows a file that is still
        # open cannot be removed, which would leave a half-written archive.
        if archive_handle is not None:
            try:
                archive_handle.close()
            except Exception:
                pass
            archive_handle = None
        if archive_created:
            _safe_remove(archive_path)
        _log(tr("core.backup.cancelled"), "WARN")
        return [], "cancelled"
    except Exception as e:
        if archive_handle is not None:
            try:
                archive_handle.close()
            except Exception:
                pass
            archive_handle = None
        if archive_created:
            _safe_remove(archive_path)
        _log(tr("core.backup.failed", err=e), "ERROR")
        return [], "error"
    finally:
        if archive_handle is not None:
            try:
                archive_handle.close()
            except Exception:
                pass
        if shadows is not None:
            shadows.__exit__(None, None, None)

    size = os.path.getsize(archive_path)
    LAST_STATS.update({"archive": archive_path, "count": len(manifest), "size": size, "errors": errors,
                       "missing": len(missing), "encrypted": bool(use_aes),
                       "vss": vss_state,
                       "verified": None, "sha256": "", "signature": signature})
    _log(tr("core.backup.done", name=archive_name,
            size_mb=f"{size / 1024 / 1024:.1f}", errors=errors))

    if bcfg.get("verify", True):
        if progress_cb:
            progress_cb(96, tr("core.verify.running"))
        ok, msg = verify_archive(archive_path, password if use_aes else "",
                                 expected_count=len(manifest),
                                 manifest_name=f"{inner_root}/manifest.txt")
        LAST_STATS["verified"] = ok
        if not ok:
            _log(tr("core.verify.failed", name=archive_name, err=msg), "ERROR")
            _safe_remove(archive_path)
            return [], "error"
        _log(tr("core.verify.passed", name=archive_name, msg=msg))
    try:
        LAST_STATS["sha256"] = file_sha256(archive_path, cancel_event)
        _log(f"SHA-256: {LAST_STATS['sha256']}")
    except _Cancelled:
        _safe_remove(archive_path)
        _log(tr("core.backup.cancelled"), "WARN")
        return [], "cancelled"
    except OSError as e:
        _log(tr("core.verify.hash_failed", err=e), "WARN")

    # Prune only after the scheduler confirms the full job and delivery.
    if progress_cb:
        progress_cb(100, tr("core.backup.finished", name=archive_name))
    # Any file that could not be read means the archive is incomplete: report
    # "partial" so it is never treated as a full success.
    return [archive_path], ("partial" if errors or missing else "ok")


def _safe_remove(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


# Files older than this age are not automatically deleted (It may be being uploaded by another process)
RECENCY_GUARD = 3600


def _try_remove(full, name, _log, force=False):
    """Delete a file respecting files in use and recent files.
    force=True Goes beyond the clock keeper (Used only to delete duplicate copies of matching content)."""
    if os.path.abspath(full) in _files_in_use:
        _log(tr("core.cleanup.skip_in_use", name=name))
        return False
    if not force and RECENCY_GUARD > 0:
        try:
            if time.time() - os.path.getmtime(full) < RECENCY_GUARD:
                _log(tr("core.cleanup.skip_recent", name=name))
                return False
        except OSError:
            pass
    os.remove(full)
    _log(tr("core.cleanup.deleted", name=name))
    return True


def cleanup_old_local(cfg, log=None, current_name=None, current_signature=None):
    """Prune local ZIPs only after a fully successful job, keeping N copies."""
    _log = log or _default_log
    keep = max(1, int(cfg["backup"].get("keep_local_copies", 1)))
    try:
        all_files = os.listdir(BACKUP_DIR)
        zips = sorted(
            (f for f in all_files if f.startswith("Backup_") and f.endswith(".zip")),
            reverse=True,
        )
        keep_set = set(zips[:keep])
        if current_name:
            keep_set.add(current_name)
        for old in zips:
            if old != current_name and old not in keep_set:
                _try_remove(os.path.join(BACKUP_DIR, old), old, _log)
        if current_name and current_signature:
            _save_local_state({"signature": current_signature, "archive": current_name})
        # Remnants of partition parts: Yes .part* A retained copy does not follow the same rules
        _remove_stray_parts(all_files, current_name, _log)
    except Exception as e:
        _log(tr("core.cleanup.error", err=e), "WARN")


def _remove_stray_parts(all_files, current_name, _log):
    """Parts of the partition that do not belong to the retained copy are deleted."""
    for f in all_files:
        if not f.startswith("Backup_") or ".part" not in f:
            continue
        base = f.split(".part")[0]
        if current_name and base == current_name:
            continue
        _try_remove(os.path.join(BACKUP_DIR, f), f, _log)


def list_local_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("Backup_") and f.endswith(".zip")),
        reverse=True,
    )


def split_file(path, max_part_bytes=1900 * 1024 * 1024, progress_cb=None, cancel_event=None):
    """Split a large file into parts (If it is larger than the Telegram limit 2GB).

    Read in batches 8MB Only — The entire file is not loaded into memory.
    Returns a list of parts paths; Upon cancellation, the partial parts are deleted and returned [].
    Integration on Windows: copy /b file.zip.part* file.zip
    """
    if max_part_bytes <= 0:
        raise ValueError("max_part_bytes must be positive")
    if _is_cancelled(cancel_event):
        return []
    size = os.path.getsize(path)
    if size <= max_part_bytes:
        return [path]
    parts = []
    done = 0
    out = None
    try:
        with open(path, "rb") as src:
            idx = 0
            written = 0
            while True:
                if _is_cancelled(cancel_event):
                    raise _Cancelled()
                to_read = min(CHUNK_SIZE, max_part_bytes - written)
                chunk = src.read(to_read) if to_read > 0 else b""
                if not chunk:
                    if out is not None:
                        out.close()
                        out = None
                    break
                if out is None:
                    idx += 1
                    part_path = f"{path}.part{idx:03d}"
                    out = open(part_path, "xb")
                    parts.append(part_path)
                    written = 0
                out.write(chunk)
                written += len(chunk)
                done += len(chunk)
                if progress_cb:
                    pct = int(done * 100 / size)
                    progress_cb(pct, tr("core.split.progress", percent=pct))
                if written >= max_part_bytes:
                    out.close()
                    out = None
                    written = 0
    except _Cancelled:
        if out is not None:
            out.close()
        for p in parts:
            _safe_remove(p)
        _default_log(tr("core.split.cancelled"), "WARN")
        return []
    except Exception as e:
        if out is not None:
            out.close()
        for p in parts:
            _safe_remove(p)
        _default_log(tr("core.split.failed", err=e), "ERROR")
        raise
    _default_log(tr("core.split.done", count=len(parts)))
    return parts


def cleanup_parts(archive_path):
    """Delete temporary partition parts after sending."""
    d = os.path.dirname(archive_path)
    base = os.path.basename(archive_path)
    try:
        for f in os.listdir(d):
            if f.startswith(base + ".part"):
                os.remove(os.path.join(d, f))
    except Exception as e:
        _default_log(tr("core.split.cleanup_failed", err=e), "WARN")
