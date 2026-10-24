"""Bounded local usage journals. Command arguments, tokens and output are excluded."""
import collections
import json
import os
from pathlib import Path
import threading
import time
import uuid
import warnings

_LOCK = threading.RLock()
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 10


def append_event(path, *, source, actor, action, status, request_id=None, session="",
                 duration_ms=None, max_bytes=MAX_BYTES, backups=BACKUPS):
    record = {"version": 1, "t": time.time(), "source": str(source)[:32],
              "actor": str(actor)[:80], "action": str(action)[:80], "status": str(status)[:24],
              "request_id": str(request_id or uuid.uuid4().hex)[:64]}
    if session:
        record["session"] = str(session)[:32]
    if duration_ms is not None:
        record["duration_ms"] = max(0, round(float(duration_ms), 3))
    path = Path(path)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size >= max_bytes:
                Path(str(path) + f".{backups}").unlink(missing_ok=True)
                for index in range(backups - 1, 0, -1):
                    previous = Path(str(path) + f".{index}")
                    if previous.exists():
                        os.replace(previous, Path(str(path) + f".{index + 1}"))
                os.replace(path, Path(str(path) + ".1"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
    except (OSError, ValueError) as exc:
        warnings.warn(f"Usage audit write failed: {type(exc).__name__}", RuntimeWarning, stacklevel=2)
        return None


def read_events(path, backups=BACKUPS):
    """Read oldest-to-newest; tolerate an interrupted final JSON line."""
    result = []
    with _LOCK:
        for item in [Path(str(path) + f".{i}") for i in range(backups, 0, -1)] + [Path(path)]:
            try:
                with item.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            record = json.loads(line)
                            if isinstance(record, dict) and record.get("version") == 1:
                                result.append(record)
                        except (ValueError, TypeError):
                            continue
            except FileNotFoundError:
                continue
    return result


def summarize(events):
    events = list(events)
    return {"events": len(events),
            "by_actor": dict(collections.Counter(e.get("actor", "unknown") for e in events)),
            "by_action": dict(collections.Counter(e.get("action", "unknown") for e in events)),
            "by_status": dict(collections.Counter(e.get("status", "unknown") for e in events))}
