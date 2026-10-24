# -*- coding: utf-8 -*-
"""Manage settings file config.json — Load, save and default values.

Secrets (bot token, API hash, passwords, monitoring link) They are saved encrypted with DPAPI
It is automatically unpacked upon loading — The rest of the code deals with normal values only.
"""

import json
import os
import copy
import datetime
import secrets
import subprocess
import threading
import warnings

from i18n import tr
import secrets_store

# Bump when the config layout changes so the active version can be displayed.
SCHEMA_VERSION = 2

_save_lock = threading.Lock()
_NO_WINDOW = 0x08000000


def config_version(cfg):
    """Schema version of the active configuration."""
    try:
        return int((cfg.get("_meta") or {}).get("version", 0))
    except (TypeError, ValueError):
        return 0


def config_revision(cfg):
    """Unique per-save revision, so the worker can prove which save it applied."""
    try:
        return int((cfg.get("_meta") or {}).get("revision", 0))
    except (TypeError, ValueError):
        return 0


def harden_path(path, directory=False):
    """Report protection failures; optional nonexistent assets are skipped."""
    if os.name != "nt" or not os.path.exists(path):
        return True
    perms = "(OI)(CI)F" if directory else "F"
    try:
        result = subprocess.run(["icacls", path, "/inheritance:r",
                        "/grant:r", f"*S-1-5-32-544:{perms}", f"*S-1-5-18:{perms}"],
                       capture_output=True, timeout=15, creationflags=_NO_WINDOW)
    except Exception as exc:
        warnings.warn(f"ACL hardening failed for {path}: {type(exc).__name__}", RuntimeWarning,
                      stacklevel=2)
        return False
    if result.returncode != 0:
        warnings.warn(f"ACL hardening failed for {path}: icacls exit {result.returncode}",
                      RuntimeWarning, stacklevel=2)
        return False
    return True


def harden_backup_assets(cfg=None):
    """Protect the config, rclone credentials, session files, control dir, and archives.

    The backup secrets use machine-scoped DPAPI, which other local accounts could
    decrypt, so filesystem ACLs are the primary protection.
    """
    root = os.path.dirname(os.path.abspath(CONFIG_FILE))
    results = [harden_path(CONFIG_FILE)]
    if cfg:
        rclone_conf = (cfg.get("cloud", {}) or {}).get("rclone_config") or ""
        if rclone_conf:
            results.append(harden_path(rclone_conf))
    for name in ("bot_session_gui.session", "bot_session_pyro.session"):
        results.append(harden_path(os.path.join(root, name)))
    for name in ("control", "local_backups", "logs"):
        results.append(harden_path(os.path.join(root, name), directory=True))
    return all(results)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")

DEFAULT_CONFIG = {
    "_meta": {"version": SCHEMA_VERSION, "revision": 0, "updated": ""},
    "restore_drill": {                     # Periodic restore test (a CRC is not a restore)
        "enabled": False,
        "interval_days": 7,
        "dest": "",
        "keep": False
    },
    "backup": {
        "engine": "zip",                   # zip = Complete daily archive | restic = Incremental copying without duplication
        "sources": [],                     # List of folders/Files to be copied
        "exclude_extensions": [".tmp", ".lock"],   # Extensions excluded
        "exclude_patterns": [],            # Folders/Excluded patterns (Example: node_modules, C:\\Temp\\*)
        "exclude_max_size_mb": 0,          # 0 = without limit; Otherwise excludes larger files
        "archive_password": "",            # Password AES For archive (Empty = Without)
        "keep_local_copies": 3,            # Number of local copies maintained
        "use_vss": False,                  # Copy open files/locked across Volume Shadow Copy
        "verify": True,                    # Examine the archive after creating it + Cloud matching after upload
        "require_all_sources": True,       # Abort (fail closed) if a configured source is missing
        "pre_command": "",                 # A command that is run before copying (Example: Export a database)
        "post_command": "",                # A command to run after copying (Always, even when you fail)
        "hook_timeout_minutes": 60
    },
    "schedule": {
        "enabled": False,
        "mode": "daily",                   # daily | interval | times
        "time": "03:00",                   # daily mode time (24h)
        "times": [],                       # times mode: ["03:00", "15:00"]
        "interval_hours": 6,               # interval mode
        "retry_count": 3,                  # The number of retries on failure
        "retry_delay_minutes": 10          # Interval between attempts
    },
    "cloud": {
        "remotes": [],                     # Destinations rclone (Example: ["gdrive:"])
        "remote_folder": "VPS-Backups",    # The name of the folder on the cloud
        "retention_days": 30,              # Keep copies on the cloud
        "allow_share_links": True,         # Create a public share link per backup (requires encryption)
        "rclone_config": ""                # Path rclone.conf (Automatically detected — Important to serve SYSTEM)
    },
    "restic": {
        "repository": "",                  # Example: rclone:drive:VPS-Restic Or D:\\restic-repo
        "password": "",                    # Repository password — Keep a copy of it outside the server!
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 12,
        "check_after_backup": True         # restic check After each copy
    },
    "telegram": {
        "bot_token": "",                   # Bot token from BotFather
        "api_id": "",                      # Who my.telegram.org
        "api_hash": "",                    # Who my.telegram.org
        "chat_id": "",                     # Authorized user, group, or channel Chat ID
        "bot_enabled": True,               # False retires this bot (the unified monitor bot reports instead)
        "send_file": True,                 # Send the archive itself
        "send_report": True,               # Send a daily report
        "verify_delivery": True,           # Wait for uploads so "delivered" is truthful
        "delivery_timeout": 3600,          # Max seconds to wait for delivery verification
        "direct_max_mb": 45                # At least follow it directly on Telegram — Akbar followed Linkcloud
    },
    "monitoring": {
        "healthcheck_url": "",             # Link ping external (healthchecks.io) — Alarms if the tool stops
        "heartbeat_url": "",               # A separate pulse link is sent every minute — It alerts if the tool itself collapses
        "alert_after_hours": 26            # Telegram alert if this time passes without a successful backup
    },
    "general": {
        "autostart": False,                # Operating with Windows boot
        "language": "en"                   # Interface language: en Or ar (Default is English)
    }
}

# Fields that are saved encrypted on disk
SECRET_FIELDS = (
    ("telegram", "bot_token"),
    ("telegram", "api_hash"),
    ("backup", "archive_password"),
    ("restic", "password"),
    ("monitoring", "healthcheck_url"),
    ("monitoring", "heartbeat_url"),
)


# False If you fail, read config.json — Then nothing is automatically saved over it
LOAD_OK = True


def load_config():
    """Load settings, decrypt secrets, and encrypt any secret that is still plaintext."""
    global LOAD_OK
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    needs_migration = False
    LOAD_OK = True
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                user_cfg = json.load(f)
            _validate_structure(user_cfg)
            _merge(cfg, user_cfg)
        except Exception as e:
            LOAD_OK = False
            print(tr("core.config.load_error", err=e))
            return cfg
    if config_version(cfg) < SCHEMA_VERSION:
        cfg.setdefault("_meta", {})["version"] = SCHEMA_VERSION
        needs_migration = True
    for section, key in SECRET_FIELDS:
        value = cfg.get(section, {}).get(key, "")
        if not value:
            continue
        if secrets_store.is_protected(value):
            try:
                cfg[section][key] = secrets_store.unprotect(value)
            except Exception as e:
                LOAD_OK = False
                # Keep the ciphertext instead of blanking it: a later save would
                # otherwise overwrite the secret with an empty value and it would
                # be unrecoverable. protect() is idempotent, so it is preserved.
                print(tr("core.config.secret_failed", field=f"{section}.{key}", err=e))
                print(f"[config] {section}.{key} left encrypted; it cannot be read on this machine.")
        elif secrets_store.is_available():
            needs_migration = True
    if needs_migration and LOAD_OK:
        try:
            save_config(cfg)
        except Exception as e:
            print(tr("core.config.load_error", err=e))
    return cfg


def save_config(cfg):
    """Save encrypted settings atomically; publish the revision only after success."""
    with _save_lock:
        data = copy.deepcopy(cfg)
        _validate_structure(data)
        meta = {"version": SCHEMA_VERSION,
                "revision": config_revision(cfg) + 1,
                "updated": datetime.datetime.now().isoformat(timespec="seconds")}
        data["_meta"] = meta
        for section, key in SECRET_FIELDS:
            if data.get(section, {}).get(key):
                data[section][key] = secrets_store.protect(data[section][key])
        tmp = CONFIG_FILE + "." + secrets.token_hex(4) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        cfg["_meta"] = dict(meta)
    harden_path(CONFIG_FILE)


def _validate_structure(cfg):
    """Reject malformed sections before consumers can use partial defaults."""
    if not isinstance(cfg, dict):
        raise ValueError("configuration must be an object")
    for section, default in DEFAULT_CONFIG.items():
        if isinstance(default, dict) and section in cfg and not isinstance(cfg[section], dict):
            raise ValueError(f"{section} must be an object")
    for section, key in SECRET_FIELDS:
        if key in cfg.get(section, {}) and not isinstance(cfg[section][key], str):
            raise ValueError(f"{section}.{key} must be a string")
    for section, key in (("backup", "sources"), ("backup", "exclude_extensions"),
                         ("backup", "exclude_patterns"), ("schedule", "times"),
                         ("cloud", "remotes")):
        if key in cfg.get(section, {}):
            value = cfg[section][key]
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(f"{section}.{key} must be a list of strings")


def _merge(base, override):
    """Merge user settings above default without losing keys."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v)
        else:
            base[k] = v
