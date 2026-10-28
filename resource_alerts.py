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
    def __init__(self):
        self.samples = deque(maxlen=24)
        self.last_level = "ok"
        self.last_alert = 0
        self.last_spike = 0
        self.was_over = False

    def observe(self, cpu, ram, now, config, muted=False):
        self.samples.append((now, cpu, ram))
        old = next((sample for sample in self.samples if now-sample[0] <= 60), None)
        spike = None
        if old and now-old[0] >= 45 and now-self.last_spike >= config["spike_cooldown"]:
            deltas = (cpu-old[1], ram-old[2])
            if max(deltas) >= config["spike_threshold"]:
                spike = {"cpu_delta": deltas[0], "ram_delta": deltas[1]}
        level = usage_level(cpu, ram, config)
        if level != "ok":
            self.was_over = True
            ranks = {"ok": 0, "warning": 1, "danger": 2, "critical": 3}
            due = now-self.last_alert >= max(config["alert_interval"], 900)
            if not muted and (ranks[level] > ranks[self.last_level] or due):
                self.last_level, self.last_alert = level, now
                if spike:
                    self.last_spike = now
                return {"kind": "threshold", "level": level, "spike": spike}
            return None
        recovered = self.was_over
        self.was_over = False
        self.last_level, self.last_alert = "ok", 0
        if muted:
            return None
        if recovered:
            if spike:
                self.last_spike = now
            return {"kind": "recovery", "spike": spike}
        if spike:
            self.last_spike = now
            return {"kind": "spike", "spike": spike}
        return None
