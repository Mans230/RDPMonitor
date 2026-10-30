"""One notification decision per sample for system CPU/RAM thresholds and spikes."""
from collections import deque


def usage_level(cpu, ram, config):
    if max(cpu, ram) >= config["critical_threshold"]:
        return "critical"
    if max(cpu, ram) >= config["danger_threshold"]:
        return "danger"
    if cpu >= config["cpu_alert_threshold"] or ram >= config["ram_alert_threshold"]:
        return "warning"
    return "ok"


class ResourceAlertPolicy:
    WARNING_HOLD = 120
    RECOVERY_HOLD = 180
    RECOVERY_MARGIN = 5
    REMINDER_INTERVAL = 1800

    def __init__(self):
        self.samples = deque(maxlen=24)
        self.last_level = "ok"
        self.last_alert = 0
        self.last_spike = 0
        self.started = None
        self.warning_since = None
        self.recovery_since = None
        self.peak_cpu = 0
        self.peak_ram = 0

    def observe(self, cpu, ram, now, config, muted=False):
        self.samples.append((now, cpu, ram))
        old = next((sample for sample in self.samples if now-sample[0] <= 60), None)
        spike = None
        if old and now-old[0] >= 45 and now-self.last_spike >= config["spike_cooldown"]:
            deltas = (cpu-old[1], ram-old[2])
            if max(deltas) >= config["spike_threshold"]:
                spike = {"cpu_delta": deltas[0], "ram_delta": deltas[1]}
        level = usage_level(cpu, ram, config)
        if self.started is not None:
            self.peak_cpu = max(self.peak_cpu, cpu)
            self.peak_ram = max(self.peak_ram, ram)
        if level != "ok":
            self.recovery_since = None
            if self.started is None:
                self.started = now
                self.peak_cpu, self.peak_ram = cpu, ram
            if self.warning_since is None:
                self.warning_since = now
            # Ordinary threshold crossings must persist. Danger and critical
            # bypass this delay, including while a warning is pending.
            if level == "warning" and self.last_level == "ok" and now-self.warning_since < self.WARNING_HOLD:
                return None
            ranks = {"ok": 0, "warning": 1, "danger": 2, "critical": 3}
            due = now-self.last_alert >= max(config["alert_interval"], self.REMINDER_INTERVAL)
            escalation = ranks[level] > ranks[self.last_level]
            # A downgrade is never a fresh warning, even after a reminder is due.
            if not muted and (escalation or (level == self.last_level and due)):
                self.last_level, self.last_alert = level, now
                if spike:
                    self.last_spike = now
                return {"kind": "threshold", "level": level, "spike": spike}
            return None
        self.warning_since = None
        if self.started is not None:
            # Separate entry/exit thresholds keep fluctuations around the
            # warning limit in one incident instead of reopening every sample.
            healthy = (cpu <= max(0, config["cpu_alert_threshold"]-self.RECOVERY_MARGIN)
                       and ram <= max(0, config["ram_alert_threshold"]-self.RECOVERY_MARGIN))
            if not healthy:
                self.recovery_since = None
                return None
            if self.recovery_since is None:
                self.recovery_since = now
            if now-self.recovery_since < self.RECOVERY_HOLD:
                return None
            announced = self.last_level != "ok"
            summary = {"duration": now-self.started, "peak_cpu": self.peak_cpu,
                       "peak_ram": self.peak_ram}
            self.started = self.recovery_since = None
            self.last_level, self.last_alert = "ok", 0
            if announced and not muted:
                return {"kind": "recovery", "spike": None, **summary}
            return None
        if muted:
            return None
        if spike:
            self.last_spike = now
            return {"kind": "spike", "spike": spike}
        return None
