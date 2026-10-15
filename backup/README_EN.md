# RDP Suite Backup Component

This folder contains the English-only backup engine used by RDP Suite. Do not install a separate scheduled task from this folder; `python ..\rdp_suite.py install` manages the complete product.

Use the **Backup** page in the local WebConsole to view status, start a manual run, inspect recent logs, or open the settings window.

Equivalent commands from `C:\RDPMonitor`:

```console
python rdp_suite.py backup-status
python rdp_suite.py backup-now
python rdp_suite.py backup-gui
```

The backup worker runs as SYSTEM so VSS and daily schedules continue without a signed-in user. Its configuration and secrets are stored in `backup\config.json`; sensitive fields are protected with machine-scoped Windows DPAPI. Runtime logs, backup archives, Telegram session files, and configuration are intentionally excluded from release ZIP files.

Optional helper scripts remain under `backup\scripts` for installing rclone or restic. Autostart is owned only by the suite installer.
