# Panel and bot coverage

The panel provides live CPU/RAM/disk readings and history, processes/services,
sessions/local-account operations, RDP allow-list/lockdown/panic controls, common
monitor settings, automation, diagnostics/log export, backup status/manual runs,
isolated restores and restore drills. These use authenticated API requests and
the existing server-side confirmation flow for changes.

## Setup

The owner-only **Setup** page now shares these workflows and saved settings with
the bot. It is available from the sidebar, mobile **More**, and Backup controls.

- Cloud: verified rclone install/repair, Google Drive/OneDrive/Dropbox sign-in or
  OAuth JSON import, S3/B2/SFTP/FTP/WebDAV credential forms, provider follow-up
  questions, OAuth client updates, remote tests/removal and upload destinations.
  Existing names cannot be overwritten; remotes used by destinations cannot be
  removed. Provider options use an explicit allow-list. Install/repair names the
  pinned v1.74.4 build and warns before replacing a newer executable.
- Backup: browse server drives/files/folders, edit source paths, configure
  daily/interval/multiple-time schedules, and choose backup remotes and folder.
  Files are retained when removing sources; retry settings are preserved. Times
  use the server timezone. Changes are read by the existing SYSTEM worker.
- System images: inventory, capture, upload, progress, stop, and public share-link
  creation. Imaging permission remains in Settings. Stop retains partial files.
- Panel access: local-only HTTP, restricted-IP HTTPS, public IPv4 HTTPS, and
  temporary owner-token reveal. Applying access settings restarts the panel and
  requires another login; the page explains certificate/provider-firewall limits.

All changes use authenticated CSRF-protected POST requests and confirmations
bound to exact arguments. Operator logins cannot access Setup or reveal the
owner token. Long operations have bounded job history and visible outcomes;
credentials are excluded from job history, usage events and provider output.
Provider questions/sign-in expire after ten minutes and can be cancelled.
In-progress setup jobs are not resumed after a monitor restart; partial cloud
configuration may need removal and retry. Configuration remains saved.

Browser OAuth runs on the Windows server and requires the user to complete
provider consent through RDP; a phone cannot receive its localhost callback.
Token import from another computer is available. OneDrive/provider choices are
continued through rclone's noninteractive protocol rather than assumed complete:
https://rclone.org/commands/rclone_config_create/ . No cloud consent is bypassed.

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

Windows boot identity uses the Kernel-General OS-start event rather than relying solely on
`psutil.boot_time()`: the wall-clock estimate can drift by more than five seconds
while the machine remains running. A stable boot ID preserves restart catch-up;
a different ID establishes a new baseline. Unsupported systems and older saved
ledgers retain the conservative timestamp fallback during migration.

Previous aggregate totals are retained and explicitly marked as legacy estimates;
they cannot be corrected retroactively. Up to 95 recorded days are retained.
Selecting an adapter does not reconstruct its historical totals from the old
aggregate ledger. Missing rate/daily samples stay gaps, not invented zeros.

These are host adapter counters, including internal/tunnel/loopback traffic.
Multiple adapters can count the same transfer; this is not a provider billing
meter. GiB uses 1024^3 bytes, and link speed is not an Internet speed test. Socket
and per-process counts are connection counts, not per-process/user byte usage.
No packet contents, ETW session, driver or per-process byte capture is installed.
