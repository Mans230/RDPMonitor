# -*- coding: utf-8 -*-
"""External monitoring (dead-man switch) Cross healthchecks.io Or any compatible service.

The tool sends ping When starting each copy (/start) And upon success (The link itself) And when you fail (/fail).
If the tool itself stops or the server is turned off, the external service will not receive ping On time
So I sent you a warning (Email/Telegram/...) — This is what the tool cannot do for itself.
"""

import urllib.request

from logger_utils import log
from i18n import tr


def ping(cfg, kind="", body=""):
    url = (cfg.get("monitoring", {}).get("healthcheck_url") or "").strip().rstrip("/")
    if not url:
        return False
    if kind:
        url = f"{url}/{kind}"
    return _post(url, body)


def _post(url, body=""):
    try:
        data = body.encode("utf-8")[:10000] if body else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"User-Agent": "VPS-Backup-Tool"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        log(tr("core.monitor.ping_failed", err=e), "WARN")
        return False


def heartbeat(cfg, body=""):
    """pulse 'The tool is live' — The external service will alert you if the pulses stop (The server is off/The tool collapsed)."""
    url = (cfg.get("monitoring", {}).get("heartbeat_url") or "").strip().rstrip("/")
    return bool(url) and _post(url, body)
