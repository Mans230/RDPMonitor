"""Host network summaries. Connection counts are not process byte accounting."""
import math
import copy
import os
from datetime import datetime, timedelta


def boot_identity():
    """Read a kernel boot identifier independent of wall-clock estimates.

    Windows SystemBootEnvironmentInformation (90) begins with BootIdentifier,
    as defined by System Informer's phnt headers. Unsupported systems retain
    the conservative boot-timestamp fallback.
    """
    try:
        if os.name == "nt":
            import ctypes
            query = ctypes.windll.ntdll.NtQuerySystemInformation
            query.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
            query.restype = ctypes.c_long
            data = ctypes.create_string_buffer(32);length = ctypes.c_ulong()
            if query(90, data, 32, ctypes.byref(length)) == 0 and length.value >= 16 and any(data.raw[:16]):
                return "windows:" + data.raw[:16].hex()
        elif os.path.isfile("/proc/sys/kernel/random/boot_id"):
            with open("/proc/sys/kernel/random/boot_id") as stream:
                return "linux:" + stream.read().strip()
    except (OSError, AttributeError):
        pass
    return None


class TrafficLedger:
    """Atomic snapshots pair per-adapter raw baselines with recorded day totals.

    Fresh boots/adapters establish a baseline; pre-observation bytes are never
    assigned to today. Existing aggregate history is retained and flagged.
    """
    def __init__(self, saved, boot, now, boot_id=None):
        if not isinstance(saved, dict):
            raise ValueError("invalid traffic history")
        days = saved.get("days", saved)
        if not isinstance(days, dict):
            raise ValueError("invalid traffic days")
        for day, values in days.items():
            if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day or not isinstance(values, dict):
                raise ValueError("invalid traffic day")
            if not all(math.isfinite(float(values[k])) and float(values[k]) >= 0 for k in ("down", "up")):
                raise ValueError("invalid traffic totals")
        self.days = {day: {"down": float(values["down"]), "up": float(values["up"])} for day, values in days.items()}
        self.boot = boot
        self.boot_id = boot_id
        self.meta = copy.deepcopy(saved.get("measurement", {}))
        if not self.meta:
            self.meta = {"tracking_since": now, "legacy_history": bool(days), "reset_events": 0,
                         "cross_day_gaps": 0, "legacy_through_date": datetime.fromtimestamp(now).date().isoformat() if days else None}
        # psutil's Windows boot-time estimate varies by fractions of a second
        # across processes. Exact float equality discards a valid saved baseline.
        saved_boot = saved.get("boot")
        same_boot = isinstance(saved_boot, (int, float)) and abs(saved_boot - boot) <= 5
        if saved.get("boot_id") and boot_id:
            same_boot = saved["boot_id"] == boot_id
        self.previous = copy.deepcopy(saved.get("last_nics")) if same_boot else None
        self.last_sample = saved.get("last_sample") if self.previous is not None else None

    def observe(self, counters, now):
        down = up = 0
        for name, value in counters.items():
            previous = (self.previous or {}).get(name)
            if previous is None:
                continue
            sent, recv = value["bytes_sent"] - previous["bytes_sent"], value["bytes_recv"] - previous["bytes_recv"]
            if sent < 0 or recv < 0:
                self.meta["reset_events"] = self.meta.get("reset_events", 0) + 1
                continue
            up += sent; down += recv
        today = datetime.fromtimestamp(now).date().isoformat()
        if self.last_sample and now - self.last_sample > 90 and datetime.fromtimestamp(self.last_sample).date().isoformat() != today:
            self.meta["cross_day_gaps"] = self.meta.get("cross_day_gaps", 0) + 1
        record = self.days.setdefault(today, {"down": 0.0, "up": 0.0})
        record["down"] += down / 1024**2; record["up"] += up / 1024**2
        for day in sorted(self.days)[:-95]:
            del self.days[day]
        if self.meta.get("legacy_through_date") and all(day > self.meta["legacy_through_date"] for day in self.days):
            self.meta["legacy_history"] = False
        self.previous, self.last_sample = copy.deepcopy(counters), now
        return down, up

    def snapshot(self):
        return copy.deepcopy({"days": self.days, "boot": self.boot, "boot_id": self.boot_id, "last_nics": self.previous,
                              "last_sample": self.last_sample, "measurement": self.meta})


def usage_summary(days, quota_gib=0, reset_day=1, today=None):
    today = today or datetime.now().date()
    reset_day = min(28, max(1, int(reset_day or 1)))
    first = today.replace(day=reset_day)
    if first > today:
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=reset_day)
    end = (first.replace(day=28) + timedelta(days=4)).replace(day=reset_day)
    records = []
    for day, rec in (days or {}).items():
        try:
            date = datetime.strptime(day, "%Y-%m-%d").date()
            if date.isoformat() != day or date > today:
                continue
            down, up = float(rec["down"]), float(rec["up"])
            if not all(math.isfinite(v) and v >= 0 for v in (down, up)):
                continue
            records.append({"date": day, "down": round(down * 1024**2), "up": round(up * 1024**2)})
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
    records = sorted(records, key=lambda r: r["date"])[-95:]
    def totals(start):
        rows = [r for r in records if r["date"] >= start.isoformat()]
        down, up = sum(r["down"] for r in rows), sum(r["up"] for r in rows)
        return {"down": down, "up": up, "total": down + up}
    quota = max(0, float(quota_gib or 0)) * 1024**3
    cycle = totals(first)
    return {"today": totals(today), "seven_days": totals(today - timedelta(days=6)),
            "thirty_days": totals(today - timedelta(days=29)), "cycle": cycle,
            "cycle_start": first.isoformat(), "cycle_end": end.isoformat(),
            "reset_day": reset_day, "quota_bytes": round(quota),
            "quota_percent": cycle["total"] / quota * 100 if quota else None,
            "quota_remaining": max(0, round(quota) - cycle["total"]) if quota else None,
            "days": records, "server_date": today.isoformat(),
            "recorded_start": records[0]["date"] if records else None,
            "scope": "All adapters, all Windows users. Includes internal/tunnel traffic; may count the same transfer on multiple adapters."}


def adapter_rates(previous, current, seconds):
    result = {}
    for name, cur in current.items():
        old = previous.get(name)
        if old is None or seconds <= 0:
            result[name] = {"up": None, "down": None, "reset": False}
            continue
        reset = any(cur[key] < old.get(key, 0) for key in ("bytes_sent", "bytes_recv"))
        result[name] = {"up": None if reset else (cur["bytes_sent"] - old["bytes_sent"]) / seconds,
                        "down": None if reset else (cur["bytes_recv"] - old["bytes_recv"]) / seconds,
                        "reset": reset}
    return result
