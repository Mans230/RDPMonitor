# -*- coding: utf-8 -*-
"""Volume Shadow Copy (VSS) — Read open files/Locked from a fixed disk snapshot.

Use:
    with ShadowSet(drives, log) as shadows:
        read_path = shadows.map(original_path)   # Path within the shot (Or the original if it fails)

Requires permissions Administrator/SYSTEM. If the snapshot creation fails, copying from the disk continues
Neighborhood with warning. Snapshot IDs are recorded in logs/vss_pending.json Until it is deleted
On the next run, the tool suddenly stopped before being deleted.
"""

import os
import json
import subprocess

from i18n import tr

PENDING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "vss_pending.json")
_NO_WINDOW = 0x08000000


def _ps(script, timeout=300):
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW if os.name == "nt" else 0)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _load_pending():
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return list(json.load(f))
    except Exception:
        return []


def _save_pending(ids):
    try:
        os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(set(ids)), f)
    except Exception:
        pass


def create_snapshot(volume):
    """volume Like 'C:\\' — He comes back (shadow_id, device_path)."""
    script = (
        "$ErrorActionPreference='Stop';"
        f"$r=(Get-WmiObject -List Win32_ShadowCopy).Create('{volume}','ClientAccessible');"
        "if($r.ReturnValue -ne 0){Write-Output ('ERR '+$r.ReturnValue);exit 2};"
        "$s=Get-WmiObject Win32_ShadowCopy|Where-Object{$_.ID -eq $r.ShadowID};"
        "Write-Output ($s.ID+'|'+$s.DeviceObject)"
    )
    code, out, err = _ps(script)
    line = out.splitlines()[-1] if out else ""
    if code != 0 or "|" not in line:
        raise OSError(line or err or f"exit code {code}")
    shadow_id, device = line.split("|", 1)
    return shadow_id.strip(), device.strip()


def delete_snapshot(shadow_id):
    script = ("Get-WmiObject Win32_ShadowCopy|Where-Object{$_.ID -eq '" + shadow_id + "'}"
              "|ForEach-Object{$_.Delete()}")
    code, _out, err = _ps(script, timeout=120)
    if code != 0:
        raise OSError(err or f"exit code {code}")


def cleanup_stale(log):
    """Delete clips left by a previous playback that ended suddenly."""
    pending = _load_pending()
    if not pending:
        return
    left = []
    for sid in pending:
        try:
            delete_snapshot(sid)
            log(tr("core.vss.stale_deleted", id=sid))
        except Exception as e:
            left.append(sid)
            log(tr("core.vss.delete_failed", id=sid, err=e), "WARN")
    _save_pending(left)


class ShadowSet:
    def __init__(self, drives, log):
        self.drives = sorted({d.upper() for d in drives if d})
        self.log = log
        self.devices = {}   # "C:" -> "\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN"
        self.ids = []
        self.failed_drives = []   # drives that fell back to live-file reads

    def __enter__(self):
        if os.name != "nt":
            return self
        cleanup_stale(self.log)
        for drive in self.drives:
            try:
                sid, device = create_snapshot(drive + "\\")
                self.ids.append(sid)
                _save_pending(_load_pending() + [sid])
                self.devices[drive] = device
                self.log(tr("core.vss.created", drive=drive))
            except Exception as e:
                self.failed_drives.append(drive)
                self.log(tr("core.vss.create_failed", drive=drive, err=e), "WARN")
        return self

    def map(self, path):
        drive, rest = os.path.splitdrive(os.path.abspath(path))
        device = self.devices.get(drive.upper())
        return device + rest if device else path

    def __exit__(self, *exc):
        pending = _load_pending()
        for sid in self.ids:
            try:
                delete_snapshot(sid)
                pending = [p for p in pending if p != sid]
            except Exception as e:
                self.log(tr("core.vss.delete_failed", id=sid, err=e), "WARN")
        _save_pending(pending)
        return False
