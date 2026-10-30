# Panel and bot coverage

The panel provides live CPU/RAM/disk readings and history, processes/services,
sessions/local-account operations, RDP allow-list/lockdown/panic controls, common
monitor settings, automation, diagnostics/log export, backup status/manual runs,
isolated restores and restore drills. These use authenticated API requests and
the existing server-side confirmation flow for changes.

The bot still has fuller setup workflows for:

- rclone/cloud account authorization, remote creation/testing/removal and target selection;
- system-image capture/upload/cancellation and image management;
- backup source paths and schedule configuration;
- public panel activation/allow-list management and retrieving its login token.

Some corresponding switches, status displays or desktop launch buttons exist in
the panel; they do not replace those complete setup workflows. This change adds
bandwidth monitoring, not the missing cloud/image/backup setup forms.

## Bandwidth

Open **Bandwidth** from the desktop sidebar, mobile **More**, or the Overview
network block. The page shows adapter/host rates in Mbps or MiB/s, rate history,
adapter IPs/link speed/OS byte and packet counters/errors/drops, recorded day and
quota-cycle totals, retained daily history/CSV, and socket/process activity.
Adapter selection filters live rates/history; recorded daily totals remain
host-wide. Quota/reset-day settings are the same monitor settings used by the bot.

Live rates come from Windows counters approximately every two seconds. Recorded
usage shares the bot's ledger, samples about every 30 seconds and atomically saves
days and raw per-adapter baselines every five minutes. A saved baseline on the
same Windows boot permits restart catch-up without adding the same bytes twice.
New boots/adapters and counter resets establish a new baseline rather than
assigning pre-observation totals to today. Long sample gaps crossing midnight are
flagged because daily allocation follows the sample date. Corrupt history is
reported and preserved instead of overwritten with empty successful results.

Previous aggregate totals are retained and explicitly marked as legacy estimates;
they cannot be corrected retroactively. Up to 95 recorded days are retained.
Selecting an adapter does not reconstruct its historical totals from the old
aggregate ledger. Missing rate/daily samples stay gaps, not invented zeros.

These are host adapter counters, including internal/tunnel/loopback traffic.
Multiple adapters can count the same transfer; this is not a provider billing
meter. GiB uses 1024^3 bytes, and link speed is not an Internet speed test. Socket
and per-process counts are connection counts, not per-process/user byte usage.
No packet contents, ETW session, driver or per-process byte capture is installed.
