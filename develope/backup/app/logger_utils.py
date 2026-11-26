# -*- coding: utf-8 -*-
"""Simple local login — Daily log file on the VPS."""

import os
import datetime
import threading

from i18n import tr

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
_lock = threading.Lock()


def _log_path():
    os.makedirs(LOG_DIR, exist_ok=True)
    day = datetime.datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"backup_{day}.log")


def log(message, level="INFO"):
    """Record a message in the log file + Printing on the console."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {message}"
    with _lock:
        try:
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    try:
        print(line)
    except Exception:
        pass  # Console does not support some characters (Or there is no console with it pythonw)


def read_recent_logs(lines=50):
    """Read the last lines of the log (To display in the interface or command /status)."""
    path = _log_path()
    if not os.path.exists(path):
        return tr("core.log.none_yet")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.readlines()
        return "".join(content[-lines:])
    except Exception as e:
        return tr("core.log.read_failed", err=e)
