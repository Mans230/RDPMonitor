# RDP Suite - Command reference

## Control

### /cancel_restart
- Purpose: Cancels a scheduled restart/shutdown inside the cancel window.
- Usage: `/cancel_restart`
- Panel: ctl

**What it does:** Cancels a pending restart/shutdown.

**Steps (backend commands):**
1. Abort
   ```
   shutdown /a
   ```

**Effect:** The pending shutdown is cancelled.
**Output:** A confirmation.
**Troubleshoot:** Only works inside the cancel window.
**Related:** /restart /shutdown

### /download
- Purpose: Sends a file from the machine to this chat (up to 45MB, Telegram's limit).
- Usage: `/download C:\path\file`
- Panel: file

**What it does:** Sends a file from the machine (up to 45 MB).

**Steps (backend commands):**
1. Read
   ```
   open the path
   ```
2. Send
   ```
   sendDocument
   ```

**Effect:** The file is sent to the chat.
**Output:** The file.
**Troubleshoot:** Paths outside approved roots may be refused.
**Related:** /configbackup

### /exec
- Purpose: Runs an arbitrary CMD command on the machine with admin rights and returns full output. THE most dangerous command - anyone with your Telegram controls the whole machine. Keep it off (/set exec off) when not needed.
- Usage: `/exec <command> confirm`
- Panel: tools
- Risk: dangerous (confirmation required)

**What it does:** Runs a shell command on the machine (only when exec is enabled).

**Steps (backend commands):**
1. Gate
   ```
   config.exec_enabled must be true (/set exec on)
   ```
2. Confirm
   ```
   the command must include 'confirm'
   ```
3. Run
   ```
   subprocess.run(cmd, shell=True, capture_output=True)
   ```

**Effect:** A real command runs as the tool's account.
**Output:** The command output (tail).
**Troubleshoot:** Disabled by default; enable with /set exec on. Avoid interactive commands.
**Related:** /run /kill /set

### /kill
- Purpose: Force-kills every process matching the name (all instances). Unsaved work in those programs is lost.
- Usage: `/kill chrome confirm`
- Panel: live
- Risk: dangerous (confirmation required)

**What it does:** Terminates processes by PID.

**Steps (backend commands):**
1. Guard
   ```
   refuse PIDs 0, 4, and the tool itself
   ```
2. Kill
   ```
   psutil.Process(pid).kill()
   ```

**Effect:** The processes end.
**Output:** The count killed and any errors.
**Troubleshoot:** Confirm the PID from /top or /view first.
**Related:** /top /ps

### /msg
- Purpose: Shows a message on the logged-in desktop.
- Usage: `/msg <text>`
- Panel: ctl

**What it does:** Shows a popup message on the desktop.

**Steps (backend commands):**
1. Send
   ```
   msg * <text>
   ```

**Effect:** A message box appears for signed-in users.
**Output:** Delivered (no text output).
**Troubleshoot:** Needs an active interactive session.
**Related:** /screenshot

### /restart
- Purpose: Restarts the machine after a 30-second warning window (cancelable with /cancel_restart).
- Usage: `/restart confirm`
- Panel: ctl
- Risk: dangerous (confirmation required)

**What it does:** Reboots the machine with a cancel window.

**Steps (backend commands):**
1. Schedule
   ```
   shutdown /r /t 5
   ```

**Effect:** The machine reboots.
**Output:** A confirmation.
**Troubleshoot:** Cancel with /cancel_restart inside the window.
**Related:** /shutdown /cancel_restart

### /run
- Purpose: Launches a program on the machine (like typing it in Run box).
- Usage: `/run notepad confirm`
- Panel: tools
- Risk: dangerous (confirmation required)

**What it does:** Starts an executable in the interactive session.

**Steps (backend commands):**
1. Gate
   ```
   config.exec_enabled must be true
   ```
2. Start
   ```
   subprocess.Popen([path] + args, shell=False)
   ```

**Effect:** The program starts detached.
**Output:** "started" or an error.
**Troubleshoot:** Provide a full path; check it is not blocked.
**Related:** /exec /kill

### /screenshot
- Purpose: Captures the interactive desktop and sends it.
- Usage: `/screenshot`
- Panel: tools

**What it does:** Captures the interactive desktop.

**Steps (backend commands):**
1. Capture
   ```
   PIL ImageGrab.grab(all_screens=True)
   ```
2. Send
   ```
   sendPhoto
   ```

**Effect:** A PNG of the current screen is sent.
**Output:** The image, or a failure notice.
**Troubleshoot:** Fails if the session is locked or Pillow is missing.
**Related:** /view

### /shutdown
- Purpose: Powers the machine OFF after 30 seconds (cancel with /cancel_restart).
- Usage: `/shutdown confirm`
- Panel: ctl
- Risk: dangerous (confirmation required)

**What it does:** Powers off the machine with a cancel window.

**Steps (backend commands):**
1. Schedule
   ```
   shutdown /s /t 5
   ```

**Effect:** The machine powers off.
**Output:** A confirmation.
**Troubleshoot:** Cancel with /cancel_restart inside the window.
**Related:** /restart /cancel_restart

### /svc
- Purpose: Restarts a Windows service (with confirmation).
- Usage: `/svc restart <name>`
- Panel: tools
- Risk: dangerous (confirmation required)

**What it does:** Restarts a Windows service.

**Steps (backend commands):**
1. Restart
   ```
   Restart-Service -Name <name> -Force -ErrorAction Stop
   ```

**Effect:** The service restarts (dependents briefly stop).
**Output:** "The service has been restarted" or an error.
**Troubleshoot:** Use the exact service name; needs admin rights.
**Related:** /startup

## Maintenance

### /botlog
- Purpose: Sends the tail of the tool's own log file (rdp_monitor.log) - use it when the tool itself misbehaves.
- Usage: `/botlog`
- Panel: diagnostics

**What it does:** The tool's own recent log.

**Steps (backend commands):**
1. Read
   ```
   rdp_monitor.log tail
   ```

**Effect:** Read-only.
**Output:** Recent log lines.
**Troubleshoot:** Rotate if it grows large.
**Related:** /diagnose

### /clean
- Purpose: Deletes files older than 24h from TEMP folders and empties the Recycle Bin, then reports how much space was freed. Locked files are skipped safely.
- Usage: `/clean`
- Panel: ctl

**What it does:** Cleans old TEMP files and the recycle bin.

**Steps (backend commands):**
1. Delete old TEMP files
   ```
   os.unlink() for files older than 24h in %TEMP% and C:\Windows\Temp
   ```
2. Empty the recycle bin
   ```
   Clear-RecycleBin -Force
   ```

**Effect:** Frees disk space.
**Output:** Files removed and space freed.
**Troubleshoot:** Locked files are skipped.
**Related:** /bigfiles /view

### /configbackup
- Purpose: Sends a copy of the configuration with secrets hidden.
- Usage: `/configbackup`
- Panel: diagnostics

**What it does:** Sends a copy of the configuration with secrets hidden.

**Steps (backend commands):**
1. Redact
   ```
   remove token/secret fields
   ```
2. Send
   ```
   sendDocument
   ```

**Effect:** A redacted config copy is sent.
**Output:** The JSON file.
**Troubleshoot:** Secrets are never included.
**Related:** /status

### /diagnose
- Purpose: Analyzes recent System/Application error events and explains likely causes.
- Usage: `/diagnose [days]`
- Panel: diagnostics

**What it does:** Analyzes recent System/Application error events and explains causes.

**Steps (backend commands):**
1. Query
   ```
   Get-WinEvent -FilterHashtable @{LogName='System'|'Application'; Level=@(1,2); StartTime=$st}
   ```

**Effect:** Read-only analysis.
**Output:** A grouped diagnosis.
**Troubleshoot:** Run from an administrator account.
**Related:** /logstats /dumps

### /dumps
- Purpose: Sends the newest Windows crash dump (minidump) file.
- Usage: `/dumps`
- Panel: diagnostics

**What it does:** Sends the newest Windows crash dump.

**Steps (backend commands):**
1. Find
   ```
   C:\Windows\Minidump newest .dmp
   ```
2. Send
   ```
   sendDocument
   ```

**Effect:** The dump file is sent.
**Output:** The file, or "no recent dumps".
**Troubleshoot:** Files over 45 MB are not sent; the path is reported instead.
**Related:** /diagnose

### /exportlogs
- Purpose: Exports the last 7 days of System/Application error events to a ZIP and sends it.
- Usage: `/exportlogs [all|system|application]`
- Panel: diagnostics

**What it does:** Exports the last 7 days of error events to a ZIP and sends it.

**Steps (backend commands):**
1. Export each log
   ```
   wevtutil epl <log> <out>.evtx /q:"*[System[(Level=1 or Level=2) and TimeCreated[timediff(@SystemTime) <= <ms>]]]" /ow:true
   ```
2. Compress
   ```
   Compress-Archive -Path <files> -DestinationPath <zip>
   ```

**Effect:** A ZIP of .evtx files is produced and sent.
**Output:** The archive (<= 45 MB).
**Troubleshoot:** Try /exportlogs system if the combined size is too large.
**Related:** /dumps /botlog

### /logstats
- Purpose: Groups system log events by source for the last N days.
- Usage: `/logstats [days]`
- Panel: diagnostics

**What it does:** Groups system log events by source for N days.

**Steps (backend commands):**
1. Query
   ```
   Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$st} | Group-Object ProviderName
   ```

**Effect:** Read-only.
**Output:** Counts per source.
**Troubleshoot:** Use a longer window for rare errors.
**Related:** /diagnose

### /mute
- Purpose: Silences non-critical alerts (usage, disk, temp, sessions) for a period. Security and critical alerts always arrive.
- Usage: `/mute 3h | /mute off`
- Panel: ctl

**What it does:** Silences non-critical alerts for a period.

**Steps (backend commands):**
1. Set
   ```
   config.mute_until = now + duration
   ```

**Effect:** Routine alerts pause; security alerts continue.
**Output:** A confirmation.
**Troubleshoot:** /mute off restores alerts.
**Related:** /status

### /set
- Purpose: Detailed settings guide with current values and examples.
- Usage: `/set`
- Panel: settings

**What it does:** Detailed settings guide and value changes.

**Steps (backend commands):**
1. Update
   ```
   config[key] = value; save_config()
   ```

**Effect:** The setting changes immediately.
**Output:** A confirmation.
**Troubleshoot:** Use /set with no args for the guide.
**Related:** /status

### /status
- Purpose: Current value of every setting in one message.
- Usage: `/status`
- Panel: settings

**What it does:** Current value of every setting.

**Steps (backend commands):**
1. Read
   ```
   config.json
   ```

**Effect:** Read-only.
**Output:** A settings summary.
**Troubleshoot:** Change values with /set.
**Related:** /set

### /test
- Purpose: Sends a test message to confirm the bot can reach you.
- Usage: `/test`
- Panel: ctl

**What it does:** Sends a test message to verify the alert channel.

**Steps (backend commands):**
1. Send
   ```
   sendMessage to the configured chat
   ```

**Effect:** A test message arrives.
**Output:** The test message.
**Troubleshoot:** If it fails, check the token and chat id.
**Related:** /status

### /update
- Purpose: Self-updates from the configured HTTPS URL and SHA-256 fingerprint.
- Usage: `/update`
- Panel: ctl
- Risk: dangerous (confirmation required)

**What it does:** Self-update from the configured HTTPS URL and SHA-256.

**Steps (backend commands):**
1. Download
   ```
   HTTPS GET update_url
   ```
2. Verify
   ```
   SHA-256 matches update_hash
   ```
3. Apply
   ```
   replace the script
   ```

**Effect:** The tool updates to the new version.
**Output:** A success or failure notice.
**Troubleshoot:** Requires HTTPS and a matching hash; disabled by default.
**Related:** /status

### /watch
- Purpose: Alerts when a program exceeds a RAM limit.
- Usage: `/watch list | add <name> <MB> | del <name>`
- Panel: automation

**What it does:** Alerts when a program exceeds a RAM limit.

**Steps (backend commands):**
1. Sample
   ```
   psutil process memory per matching name each cycle
   ```

**Effect:** A warning when the limit is exceeded (cooldown 10 min).
**Output:** The program and its current RAM.
**Troubleshoot:** Use /watch add <name> <MB>.
**Related:** /top

## Monitoring

### /bigfiles
- Purpose: Scans the system drive and lists the 20 largest files with their full paths. Use it when the disk is full. The scan can take a few minutes.
- Usage: `/bigfiles`
- Panel: diagnostics

**What it does:** 20 largest files on the system drive.

**Steps (backend commands):**
1. Scan
   ```
   walk the system drive and sort by size
   ```

**Effect:** Read-only.
**Output:** A largest-files list.
**Troubleshoot:** Excludes protected system paths.
**Related:** /clean

### /chart
- Purpose: Generates a graph image of CPU and RAM over the last 24 hours (one sample per minute) and sends it as a photo.
- Usage: `/chart`
- Panel: charts

**What it does:** Graph image of CPU/RAM over the last 24 hours.

**Steps (backend commands):**
1. Render
   ```
   matplotlib from history.json
   ```

**Effect:** Read-only.
**Output:** A PNG chart.
**Troubleshoot:** Needs matplotlib installed.
**Related:** /report /view

### /firewall
- Purpose: Shows whether the Domain/Private/Public firewall profiles are enabled and lists every inbound allow port.
- Usage: `/firewall`
- Panel: diagnostics

**What it does:** Shows firewall profile state and RDP-related rules (read-only).

**Steps (backend commands):**
1. Profile state
   ```
   netsh advfirewall show allprofiles
   ```
2. RDP rules
   ```
   Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow ...
   ```

**Effect:** No changes; a report only.
**Output:** Profile table and rule list.
**Troubleshoot:** If profiles show off, enable the firewall from Windows Security.
**Related:** /rdpallow /harden

### /listusers
- Purpose: Lists all local Windows accounts and marks which ones are administrators.
- Usage: `/listusers`
- Panel: users

**What it does:** Lists local Windows accounts.

**Steps (backend commands):**
1. Enumerate
   ```
   Get-LocalUser
   ```

**Effect:** Read-only.
**Output:** A user table.
**Troubleshoot:** Run from an administrator account.
**Related:** /adduser /logins

### /logins
- Purpose: Last successful RDP logins from the Security event log: time, username, source IP. Use it after any suspicion - it shows who actually got in.
- Usage: `/logins`
- Panel: diagnostics

**What it does:** Last successful RDP logins with source IPs.

**Steps (backend commands):**
1. Query
   ```
   Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624}
   ```

**Effect:** Read-only.
**Output:** A login list.
**Troubleshoot:** Needs audit logon events enabled.
**Related:** /rdp /blocklist

### /net
- Purpose: Current download/upload speed, plus total data transferred since the machine booted.
- Usage: `/net`
- Panel: live

**What it does:** Current download/upload speed and totals since boot.

**Steps (backend commands):**
1. Sample
   ```
   psutil.net_io_counters() delta
   ```

**Effect:** Read-only.
**Output:** Speed and totals.
**Troubleshoot:** Speed is an average over the last interval.
**Related:** /speedtest /traffic

### /netstat
- Purpose: All active TCP connections (local -> remote with owning process) and all listening ports, marked local-only vs open-to-network. Reveals backdoors and unexpected listeners.
- Usage: `/netstat`
- Panel: tools

**What it does:** Active connections and listening ports with the owning process.

**Steps (backend commands):**
1. Enumerate
   ```
   psutil.net_connections(kind='tcp')
   ```

**Effect:** Read-only.
**Output:** A connection table.
**Troubleshoot:** May need admin rights for all PIDs.
**Related:** /rdp /firewall

### /nettest
- Purpose: Tests connectivity and latency to a host.
- Usage: `/nettest <host>`
- Panel: diagnostics

**What it does:** Connectivity and latency to a host.

**Steps (backend commands):**
1. Test
   ```
   TCP connect / ping to the host
   ```

**Effect:** Read-only.
**Output:** Reachability and latency.
**Troubleshoot:** Use a hostname or IP.
**Related:** /net /speedtest

### /ps
- Purpose: Shows details for processes matching a name.
- Usage: `/ps <name>`
- Panel: diagnostics

**What it does:** Details for processes matching a name.

**Steps (backend commands):**
1. Match
   ```
   psutil process_iter by name
   ```
2. Detail
   ```
   exe, cmdline, user, cpu, memory
   ```

**Effect:** Read-only.
**Output:** Process details.
**Troubleshoot:** Use a distinctive name.
**Related:** /top /kill

### /rdp
- Purpose: Lists active RDP sessions (user, session, state, ID) and every remote IP currently connected to the RDP port via netstat.
- Usage: `/rdp`
- Panel: sec

**What it does:** Shows active RDP sessions and remote IPs.

**Steps (backend commands):**
1. Sessions
   ```
   qwinsta
   ```
2. Recent logins
   ```
   Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624;StartTime=$st}
   ```

**Effect:** Read-only.
**Output:** Sessions and caller IPs.
**Troubleshoot:** Combine with /blocklist for banned callers.
**Related:** /logins /blocklist

### /report
- Purpose: Today's report: average and peak CPU/RAM since midnight with the chart, plus today's transferred data. The same report is sent automatically every day at the configured hour.
- Usage: `/report`
- Panel: diagnostics

**What it does:** Today's averages and peaks.

**Steps (backend commands):**
1. Aggregate
   ```
   history.json for today
   ```

**Effect:** Read-only.
**Output:** Averages and peaks.
**Troubleshoot:** History builds up over time.
**Related:** /chart

### /speedtest
- Purpose: Measures real internet speed via Cloudflare (~20 seconds): ping, download and upload Mbps.
- Usage: `/speedtest`
- Panel: diagnostics

**What it does:** Real internet speed test.

**Steps (backend commands):**
1. Download/upload
   ```
   HTTP transfer to Cloudflare endpoints
   ```

**Effect:** Read-only.
**Output:** Mbps down/up and latency.
**Troubleshoot:** Consumes bandwidth; run sparingly.
**Related:** /net /nettest

### /startup
- Purpose: Inventory of autostart entries: registry Run keys and non-Microsoft scheduled tasks. Anything unfamiliar here is a classic malware persistence spot.
- Usage: `/startup`
- Panel: diagnostics

**What it does:** Autostart inventory: Run keys and non-Microsoft scheduled tasks.

**Steps (backend commands):**
1. Read
   ```
   registry Run keys + Get-ScheduledTask
   ```

**Effect:** Read-only.
**Output:** A startup list.
**Troubleshoot:** Compare against expected entries.
**Related:** /sysinfo

### /sysinfo
- Purpose: System card: Windows version, CPU model, RAM size and pressure, pagefile usage, uptime, and whether a reboot is pending (from Windows Update).
- Usage: `/sysinfo`
- Panel: tools

**What it does:** OS, hardware, pagefile, pending reboot.

**Steps (backend commands):**
1. Collect
   ```
   platform + psutil + Get-CimInstance
   ```

**Effect:** Read-only.
**Output:** System details.
**Troubleshoot:** Pending-reboot reads the registry.
**Related:** /startup

### /temp
- Purpose: Reads CPU temperature via WMI and GPU via nvidia-smi. Many VPS machines expose no sensors - in that case it says so.
- Usage: `/temp`
- Panel: diagnostics

**What it does:** CPU/GPU temperature when sensors are available.

**Steps (backend commands):**
1. Read
   ```
   WMI/OpenHardwareMonitor sensors via PowerShell
   ```

**Effect:** Read-only.
**Output:** Temperature readings.
**Troubleshoot:** Many VMs expose no sensors.
**Related:** /view

### /top
- Purpose: Lists the 10 processes consuming the most CPU and the 10 using the most RAM right now, with PID, memory and CPU per process. Use it to find what is loading the machine.
- Usage: `/top`
- Panel: apps

**What it does:** Top processes by CPU and by RAM.

**Steps (backend commands):**
1. Enumerate
   ```
   psutil.process_iter() with cpu_percent and memory_info
   ```

**Effect:** Read-only.
**Output:** A ranked process list with PIDs.
**Troubleshoot:** First sample of a new process may read 0%.
**Related:** /kill /ps

### /traffic
- Purpose: Bandwidth accounting: today, the current billing cycle, quota bar, all-time total, and a daily table. Counted machine-wide (all users), persisted in traffic.json.
- Usage: `/traffic`
- Panel: sec

**What it does:** Bandwidth accounting: today, billing cycle, quota, daily table.

**Steps (backend commands):**
1. Aggregate
   ```
   traffic.json counters
   ```

**Effect:** Read-only.
**Output:** Totals and a daily table.
**Troubleshoot:** Quota alerts are configured with /set traffic.
**Related:** /net

### /updates
- Purpose: Queries Windows Update: number of pending updates with titles, and whether a reboot is pending.
- Usage: `/updates`
- Panel: diagnostics

**What it does:** Pending Windows updates and reboot flag.

**Steps (backend commands):**
1. Query
   ```
   Windows Update COM API / USOClient
   ```

**Effect:** Read-only.
**Output:** A pending-update list.
**Troubleshoot:** Can be slow on first run.
**Related:** /sysinfo

### /view
- Purpose: Full live report: CPU %, RAM % and GB used, network speed up/down right now, disk usage with free space, active login sessions count, and machine uptime. Reads information only - changes nothing.
- Usage: `/view`
- Panel: live

**What it does:** Live snapshot of CPU, RAM, network, disks, sessions, and uptime.

**Steps (backend commands):**
1. Sample
   ```
   psutil.cpu_percent(), virtual_memory(), net_io_counters(), disk_usage(), boot_time()
   ```

**Effect:** Read-only.
**Output:** A formatted report.
**Troubleshoot:** Values are point-in-time samples.
**Related:** /top /chart

### /when
- Purpose: Reports when CPU or RAM last exceeded a threshold, from saved history.
- Usage: `/when [cpu|ram] [percent]`
- Panel: diagnostics

**What it does:** When CPU/RAM last exceeded a threshold.

**Steps (backend commands):**
1. Analyze
   ```
   history.json thresholds
   ```

**Effect:** Read-only.
**Output:** Timestamps above the threshold.
**Troubleshoot:** Needs accumulated history.
**Related:** /chart /report

## Other

### /backupschedule
- Purpose: View or change the automatic backup schedule: daily at a time, every N hours, or several specific times.
- Usage: `/backupschedule [daily HH:MM | interval HOURS | times HH:MM,HH:MM | on | off]`
- Panel: backup

**What it does:** View or change the automatic backup schedule.

**Steps (backend commands):**
1. Update
   ```
   backup/config.json schedule (mode/time/interval/times)
   ```

**Effect:** The worker applies the new schedule within seconds.
**Output:** The current schedule with buttons.
**Troubleshoot:** Modes: daily HH:MM, interval HOURS, times HH:MM,HH:MM.
**Related:** /backupstatus

### /cloud
- Purpose: Choose the cloud destinations from your existing rclone remotes (enable/disable with buttons) and test the connection.
- Usage: `/cloud | /cloud test`
- Panel: backup

**What it does:** Choose cloud destinations from existing rclone remotes and test them.

**Steps (backend commands):**
1. List
   ```
   rclone listremotes
   ```
2. Update
   ```
   backup/config.json cloud.remotes
   ```
3. Test
   ```
   rclone lsd <remote>
   ```

**Effect:** Selected remotes receive each backup.
**Output:** The destination list with toggle buttons.
**Troubleshoot:** Create remotes with rclone config; the worker uses the stored rclone.conf.
**Related:** /backup /backupstatus

### /docs
- Purpose: Documentation database: what runs behind each command, its effect, and troubleshooting. /docs shows the index; /docs <command> shows one card.
- Usage: `/docs [command]`
- Panel: docs

**What it does:** The documentation database (index and per-command documents).

**Steps (backend commands):**
1. Render
   ```
   COMMAND_INFO + COMMAND_DOCS + PANEL_COVERAGE
   ```

**Effect:** Read-only.
**Output:** An index or a full document.
**Troubleshoot:** Generated to docs/COMMANDS.md too.
**Related:** /help

### /getlog
- Purpose: Shows the bot's recent log; alias of /botlog.
- Usage: `/getlog`
- Panel: bot-only

### /keepalive
- Purpose: Lists or manages programs restarted automatically when they stop.
- Usage: `/keepalive list|add|del`
- Panel: automation

### /menu
- Purpose: Shows the interactive button menu.
- Usage: `/menu`
- Panel: bot-only

**What it does:** The interactive button menu.

**Steps (backend commands):**
1. Render
   ```
   MENU_PAGES
   ```

**Effect:** Read-only.
**Output:** The menu.
**Troubleshoot:** Tap a section to expand it.
**Related:** /help

### /noop
- Purpose: Cancels a pending action (used by the Cancel buttons).
- Usage: `/noop`
- Panel: bot-only

**What it does:** Cancels a pending action.

**Steps (backend commands):**
1. No-op
   ```
   nothing is executed
   ```

**Effect:** The pending action is dropped.
**Output:** A cancellation notice.
**Troubleshoot:** Used by Cancel buttons.

### /start
- Purpose: Opens the main button menu.
- Usage: `/start`
- Panel: bot-only

**What it does:** Opens the main menu.

**Steps (backend commands):**
1. Render
   ```
   MENU_PAGES['root']
   ```

**Effect:** Read-only.
**Output:** The main menu.
**Troubleshoot:** Same as /menu.
**Related:** /menu

### /svcwatch
- Purpose: Lists or manages Windows services restarted automatically when they stop.
- Usage: `/svcwatch list|add|del`
- Panel: automation

## Panel & Backup

### /backsrc
- Purpose: Manage what gets backed up: list sources, add or remove a file/folder, or browse with a desktop-style file browser (drives, breadcrumbs, folders and files, paging).
- Usage: `/backsrc list | add <path> | remove <index|path> | browse [path] | drives`
- Panel: backup

**What it does:** Manage what gets backed up (add/remove/browse).

**Steps (backend commands):**
1. Update
   ```
   backup/config.json backup.sources
   ```
2. Reload
   ```
   worker reloads config before the next run
   ```

**Effect:** The backup set changes.
**Output:** The updated source list.
**Troubleshoot:** Missing sources abort the backup (fail closed).
**Related:** /backup /backupstatus

### /backup
- Purpose: Queues a manual backup on the isolated SYSTEM worker. It reports here when it finishes.
- Usage: `/backup`
- Panel: backup

**What it does:** Runs a backup now: archive, verify, upload to cloud, and report a link.

**Steps (backend commands):**
1. Queue the request
   ```
   write backup/control/request.json
   ```
2. SYSTEM worker picks it up
   ```
   create_backup(): collect files, zip (AES if password), verify CRC, write manifest
   ```
3. Upload to the cloud
   ```
   rclone copy <archive> <remote>:VPS-Backups --stats-one-line
   ```
4. Create a share link
   ```
   rclone link <remote>:VPS-Backups/<archive>
   ```
5. Deliver
   ```
   Telegram message + link; local retention keeps 3 copies
   ```

**Effect:** A verified archive exists locally, is uploaded, and a link is sent.
**Output:** A structured result (archive, size, encryption, cloud, link).
**Troubleshoot:** Check /backupstatus and the worker log; add sources with /backsrc.
**Related:** /backupstatus /backsrc /restore

### /backuplist
- Purpose: Lists the local backup archives with size and time.
- Usage: `/backuplist`
- Panel: backup

**What it does:** Local backup archives with size and time.

**Steps (backend commands):**
1. List
   ```
   backup/local_backups
   ```

**Effect:** Read-only.
**Output:** An archive list.
**Troubleshoot:** Restore with /restore.
**Related:** /restorelist /restore

### /backupprogress
- Purpose: Shows the live progress of a running backup (percentage, phase, name).
- Usage: `/backupprogress`
- Panel: backup

**What it does:** Live progress of a running backup.

**Steps (backend commands):**
1. Read
   ```
   control/progress.json
   ```

**Effect:** Read-only.
**Output:** Percent, phase, and message.
**Troubleshoot:** Updated during compression and cloud upload.
**Related:** /backup

### /backupstatus
- Purpose: Backup worker state, last successful run, schedule, and recent archives.
- Usage: `/backupstatus`
- Panel: backup

**What it does:** Worker state, last run, schedule, recent archives.

**Steps (backend commands):**
1. Read
   ```
   control/status.json + logs/last_run.json + local_backups
   ```

**Effect:** Read-only.
**Output:** A status summary.
**Troubleshoot:** Use /backupschedule to change timing.
**Related:** /backup /backupschedule

### /drill
- Purpose: Restores the newest archive into an isolated folder and verifies it, then removes the copy. A restore test, not just a CRC check.
- Usage: `/drill`
- Panel: backup
- Risk: dangerous (confirmation required)

**What it does:** Restore drill: restores the newest archive, verifies it, then removes the copy.

**Steps (backend commands):**
1. Pick the newest archive
   ```
   backup/local_backups newest Backup_*.zip
   ```
2. Restore + verify
   ```
   same steps as /restore
   ```
3. Clean up
   ```
   remove the temporary restore folder unless keep=true
   ```

**Effect:** Proves the latest backup can actually be restored.
**Output:** "Restore drill passed" or a failure with the reason.
**Troubleshoot:** If it fails, inspect the archive and manifest.
**Related:** /restore /restorelist /backupstatus

### /image
- Purpose: System image attempt: captures selected volumes into one or more VHDX files while Windows runs. Verify the complete file set and test a restore in a VM before relying on it. Needs free space equal to the used space; if no second disk is present the image is written to the system disk. Optionally uploads via rclone.
- Usage: `/image start|list|upload|status|progress|stop`
- Panel: bot-only

**What it does:** Full system image into a VHDX with disk2vhd (all volumes, including boot).

**Steps (backend commands):**
1. Run
   ```
   disk2vhd.exe -c * <file.vhdx>
   ```
2. Upload
   ```
   rclone copy of the VHDX
   ```

**Effect:** One bootable VHDX is produced (needs free space equal to used space).
**Output:** Progress and the file.
**Troubleshoot:** Mount on Hyper-V/Azure directly; for KVM/Proxmox run qemu-img convert -f vhdx -O qcow2. Needs admin rights.
**Related:** /backup

### /panel
- Purpose: WebConsole panel: shows the local URL and a button to reveal the login token on demand.
- Usage: `/panel`
- Panel: panel

**What it does:** Shows the WebConsole URL and a token button.

**Steps (backend commands):**
1. Read
   ```
   webconsole_state.json port
   ```

**Effect:** Read-only.
**Output:** The URL and a Get-token button.
**Troubleshoot:** Local-only unless remote mode is configured.
**Related:** /paneltoken /panelstatus

### /panelremote
- Purpose: Turns remote access to the WebConsole panel on or off. On enables HTTPS on 0.0.0.0 with a self-signed certificate and a firewall/IP allow-list (loopback + Tailscale + this host). open allows any IP; allow/deny edit the list.
- Usage: `/panelremote on|off|status|open|allow <ip>|deny <ip>`
- Panel: panel

**What it does:** Turns remote access to the panel on or off.

**Steps (backend commands):**
1. Generate
   ```
   self-signed TLS cert -> webconsole/tls/panel.crt.pem
   ```
2. Set
   ```
   webconsole_state.json bind=0.0.0.0 + allowed_ips
   ```
3. Firewall
   ```
   netsh advfirewall add rule remoteip=<allow-list>
   ```
4. Restart
   ```
   supervisor rebinds the WebConsole on 0.0.0.0:8399
   ```

**Effect:** The panel answers on https://<host-ip>:8399/ for allowed IPs only.
**Output:** Enabled/disabled and the reachable URLs.
**Troubleshoot:** on allows loopback + Tailscale 100.64.0.0/10 + this host; use allow <ip> for more, open for any IP, off to revert.
**Related:** /panel /panelstatus

### /panelstatus
- Purpose: Checks whether the WebConsole is reachable and whether a login token is stored.
- Usage: `/panelstatus`
- Panel: panel

**What it does:** Checks whether the WebConsole is reachable.

**Steps (backend commands):**
1. Probe
   ```
   HTTP GET /health on 127.0.0.1:<port>
   ```

**Effect:** Read-only.
**Output:** Reachable yes/no and token stored.
**Troubleshoot:** If down, check the RDPSuite task.
**Related:** /panel

### /paneltoken
- Purpose: Reveals the current WebConsole login token in chat.
- Usage: `/paneltoken`
- Panel: panel

**What it does:** Reveals the WebConsole login token.

**Steps (backend commands):**
1. Read
   ```
   token_enc -> DPAPI unprotect
   ```

**Effect:** The token is sent.
**Output:** The token.
**Troubleshoot:** Rotate if leaked.
**Related:** /panel

### /rclone
- Purpose: Set up cloud upload entirely from chat: install rclone, create remotes (S3/B2/Wasabi/SFTP/WebDAV directly; Google Drive, OneDrive, Dropbox with a pasted token), list/test them, and choose where /image uploads. Stored in one config the SYSTEM worker also uses.
- Usage: `/rclone [install|gdrive|auth|client|add|token|list|test|set|del]`
- Panel: panel

**What it does:** Cloud (rclone) setup from chat: install, create remotes, test, set target.

**Steps (backend commands):**
1. Install
   ```
   download rclone-current-windows-amd64.zip -> backup/rclone/rclone.exe
   ```
2. Google Drive
   ```
   /rclone gdrive runs rclone authorize drive and saves the token
   ```
3. OAuth other
   ```
   /rclone auth <name> <type> for onedrive/dropbox
   ```
4. Non-OAuth
   ```
   rclone --config backup/rclone/rclone.conf config create <name> <type> key value ...
   ```
5. Target
   ```
   config.rclone_remote = <remote:path>
   ```

**Effect:** Remotes live in backup/rclone/rclone.conf, shared with the SYSTEM worker.
**Output:** The remote list, a test result, or the active upload target.
**Troubleshoot:** OAuth types (drive/onedrive/dropbox) need a token from rclone authorize on any device.
**Related:** /image /cloud

### /restore
- Purpose: Restores one archive into an isolated folder under the suite and verifies the restored files. It never overwrites the original paths.
- Usage: `/restore <archive-name>`
- Panel: backup
- Risk: dangerous (confirmation required)

**What it does:** Restores one archive into a new isolated folder and verifies it.

**Steps (backend commands):**
1. Refuse an unsafe destination
   ```
   destination must be new/empty with no reparse points
   ```
2. Extract
   ```
   zip extract into the isolated folder (zip-slip protected)
   ```
3. Verify
   ```
   each manifest entry: exists, size matches, CRC matches the manifest
   ```

**Effect:** Files are restored to an isolated folder; originals are untouched.
**Output:** "restored N files, verified M manifest entries".
**Troubleshoot:** A missing/invalid manifest aborts; a non-empty destination is refused.
**Related:** /restorelist /drill /backuplist

### /restorelist
- Purpose: Lists the local archives available to restore.
- Usage: `/restorelist`
- Panel: backup

**What it does:** Archives available to restore.

**Steps (backend commands):**
1. List
   ```
   backup/local_backups
   ```

**Effect:** Read-only.
**Output:** An archive list.
**Troubleshoot:** Restore with /restore <name>.
**Related:** /restore /drill

### /token
- Purpose: Reveals the WebConsole login token.
- Usage: `/token`
- Panel: panel

**What it does:** Reveals the WebConsole login token.

**Steps (backend commands):**
1. Read
   ```
   webconsole_state.json token_enc -> DPAPI unprotect
   ```

**Effect:** The panel login token is sent.
**Output:** The token (keep it private).
**Troubleshoot:** Rotate with the panel rotate-token command if leaked.
**Related:** /panel /paneltoken

## Security

### /allow
- Purpose: Manage trusted Telegram user IDs allowed to control the device.
- Usage: `/allow list | add <id> | del <id>`
- Panel: bot-only

**What it does:** Manage extra trusted Telegram user IDs.

**Steps (backend commands):**
1. Update
   ```
   config.trusted_user_ids add/del
   ```

**Effect:** Those IDs may control the device.
**Output:** The updated list.
**Troubleshoot:** Groups are not inherited; use private chat IDs.
**Related:** /status

### /audit
- Purpose: Last commands executed via the bot, files sent, and rejected unauthorized access attempts.
- Usage: `/audit`
- Panel: sec

**What it does:** Recent accepted and rejected actions.

**Steps (backend commands):**
1. Read
   ```
   audit.json tail
   ```

**Effect:** Read-only.
**Output:** An action history.
**Troubleshoot:** Records commands and blocks.
**Related:** /blocklist

### /block
- Purpose: Blocks an IP immediately in Windows Firewall (all protocols, permanent until /unblock). Double-check it is not your own IP.
- Usage: `/block <ip> confirm`
- Panel: sec
- Risk: dangerous (confirmation required)

**What it does:** Permanently blocks one IP in Windows Firewall.

**Steps (backend commands):**
1. Add the block rule
   ```
   netsh advfirewall firewall add rule name="RDPMonitor Block <ip>" dir=in action=block remoteip=<ip>
   ```
2. Record it
   ```
   blocked.json[<ip>] = now
   ```

**Effect:** All inbound traffic from that IP is rejected.
**Output:** "Banned <ip> in the firewall".
**Troubleshoot:** Confirm it is not your own IP. Remove with /unblock.
**Related:** /blocksubnet /unblock /blocklist

### /blocklist
- Purpose: Every IP the tool blocked in Windows Firewall and when.
- Usage: `/blocklist`
- Panel: sec

**What it does:** IPs currently blocked in the firewall.

**Steps (backend commands):**
1. Read
   ```
   blocked.json
   ```

**Effect:** Read-only.
**Output:** Blocked IPs with timestamps.
**Troubleshoot:** Remove with /unblock.
**Related:** /block /unblock

### /blocksubnet
- Purpose: Blocks the whole /24 network of an IP (256 addresses) - for rotating proxies attacking from the same range.
- Usage: `/blocksubnet <ip> confirm`
- Panel: rdpsec
- Risk: dangerous (confirmation required)

**What it does:** Blocks the whole /24 network of an IP.

**Steps (backend commands):**
1. Add the subnet block rule
   ```
   netsh advfirewall firewall add rule name="RDPMonitor Block <net>.0/24" dir=in action=block remoteip=<net>.0/24
   ```

**Effect:** Every address in that /24 is rejected.
**Output:** "Banned <net>.0/24 (network)".
**Troubleshoot:** Confirm the network is not yours; remove with /unblock on the /24 entry.
**Related:** /block /unblock

### /harden
- Purpose: Audits RDP hardening: NLA enabled, account lockout policy, Administrator account renamed. '/harden fix' auto-fixes the first two (needs confirm).
- Usage: `/harden [fix] confirm`
- Panel: diagnostics

**What it does:** Checks and optionally fixes RDP authentication and account policy.

**Steps (backend commands):**
1. Check Network Level Authentication
   ```
   Get-ItemProperty 'HKLM:\System\...\WinStations\RDP-Tcp' -Name UserAuthentication
   ```
2. Check account lockout policy
   ```
   net accounts
   ```
3. Check administrator accounts
   ```
   Get-LocalGroupMember -Group Administrators
   ```
4. Apply fixes (only with 'fix')
   ```
   Set-ItemProperty UserAuthentication=1; net accounts /lockoutthreshold:<n>
   ```

**Effect:** Hardens RDP authentication and account lockout.
**Output:** A findings list; 'fix' applies the changes.
**Troubleshoot:** Review each finding before applying; re-run to verify.
**Related:** /rdp /rdpallow /firewall

### /lockdown
- Purpose: Emergency lock: instantly restricts RDP to the whitelist and blocks any new IP on first attempt. Auto-expires.
- Usage: `/lockdown on|off|now|release`
- Panel: rdpsec
- Risk: dangerous (confirmation required)

**What it does:** Temporary strict lockdown: RDP limited to trusted IPs for a set time.

**Steps (backend commands):**
1. Learn recent successful IPs
   ```
   Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624;StartTime=$st}
   ```
2. Apply the trusted allow-list
   ```
   apply_rdp_allow(lockdown_ips()) -> same netsh/Set-NetFirewallProfile steps as /rdpallow
   ```
3. Set the expiry
   ```
   config.lockdown_until = now + minutes (auto-released by the monitor loop)
   ```

**Effect:** RDP is limited to trusted IPs; new attempts are banned on the first try.
**Output:** "The lock worked" with the trusted IP count.
**Troubleshoot:** Ensure your current IP is trusted first. End early with /lockdown release.
**Related:** /rdpallow /panic /whitelist

### /panic
- Purpose: Closes the RDP port ENTIRELY at firewall level and blocks all previous attackers. Stays closed across reboots until you send /panic off. You will not be able to connect either!
- Usage: `/panic on|off`
- Panel: rdpsec
- Risk: dangerous (confirmation required)

**What it does:** Emergency: closes RDP completely for everyone.

**Steps (backend commands):**
1. Block every IP that failed to log in
   ```
   block_ip(ip) for each -> netsh advfirewall firewall add rule name="RDPMonitor Block <ip>" dir=in action=block remoteip=<ip>
   ```
2. Create a block rule on the RDP port
   ```
   New-NetFirewallRule -DisplayName 'RDPMonitor PANIC' -Direction Inbound -Protocol TCP -LocalPort <port> -Action Block -ErrorAction Stop
   ```
3. Verify the rule exists
   ```
   (Get-NetFirewallRule -DisplayName 'RDPMonitor PANIC').Count
   ```

**Effect:** RDP is closed for all sources.
**Output:** "Panic mode is activated!" or an explicit failure notice.
**Troubleshoot:** You must reach the machine another way. /panic off deletes the rule and re-verifies.
**Related:** /rdpallow /lockdown /firewall

### /rdpallow
- Purpose: Restricts RDP to specific IPs only: allow rule for the list + block rule for everyone else. Danger of locking yourself out - make sure your IP is in the list first.
- Usage: `/rdpallow add|del|apply|clear`
- Panel: rdpsec
- Risk: dangerous (confirmation required)

**What it does:** Restricts RDP to a list of allowed IPs (default-deny for everyone else).

**Steps (backend commands):**
1. Create staging allow rules (TCP + UDP)
   ```
   netsh advfirewall firewall add rule name="RDPMonitor RDP Allow Staging TCP|UDP" dir=in action=allow protocol=TCP|UDP localport=<port> remoteip=<ip1,ip2,...>
   ```
2. Rename staging rules to the final names
   ```
   Set-NetFirewallRule -DisplayName 'RDPMonitor RDP Allow Staging TCP' -NewDisplayName 'RDPMonitor RDP Allow List TCP' (and UDP)
   ```
3. Scan for broad allow rules that bypass the list
   ```
   Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow ... (reads address/service filters)
   ```
4. Disable those broad rules
   ```
   Disable-NetFirewallRule -Name <rule-id> (saved so they can be re-enabled)
   ```
5. Set the profile default inbound action to Block
   ```
   Set-NetFirewallProfile -Profile '<profile>' -DefaultInboundAction Block
   ```
6. Remove the old general RDP rule
   ```
   netsh advfirewall firewall delete rule name="RDPMonitor RDP <port>"
   ```
7. Rollback on failure
   ```
   Enable-NetFirewallRule for saved rules; Set-NetFirewallProfile -DefaultInboundAction Allow; delete the allow rules
   ```

**Effect:** RDP is reachable only from the listed IPs.
**Output:** "RDP is now restricted to the allow-list".
**Troubleshoot:** If it fails it restores the previous rules. Verify with /firewall and from a provider console; never apply without your current IP in the list.
**Related:** /whitelist /lockdown /firewall

### /setrdpport
- Purpose: Wizard to change the RDP port: edits the registry, opens the new port in the firewall, blocks the old one, restarts the RDP service. Your current RDP connection DROPS the moment it applies - reconnect to IP:newport.
- Usage: `/setrdpport <port> confirm`
- Panel: rdpsec
- Risk: dangerous (confirmation required)

**What it does:** Changes the RDP listening port, opens it, verifies it, and closes the old port.

**Steps (backend commands):**
1. Check the new port is free
   ```
   psutil.net_connections() scan for a LISTEN socket on the new port
   ```
2. Set the registry port
   ```
   Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name PortNumber -Value <port> -Type DWord -ErrorAction Stop
   ```
3. Open the new port in the firewall
   ```
   New-NetFirewallRule -DisplayName 'RDPMonitor RDP <port>' -Direction Inbound -LocalPort <port> -Protocol TCP -Action Allow -ErrorAction Stop
   ```
4. Restart the RDP service
   ```
   Restart-Service TermService -Force -ErrorAction Stop
   ```
5. Verify the listener belongs to TermService
   ```
   Get-CimInstance Win32_Service -Filter "Name='TermService'" (ProcessId) + psutil listener check on the new port
   ```
6. Close the old port (only after verification)
   ```
   Disable-NetFirewallRule -DisplayGroup 'Remote Desktop'; netsh advfirewall firewall delete rule name="RDPMonitor Old RDP Port Block"; netsh advfirewall firewall add rule name="RDPMonitor Old RDP Port Block" dir=in action=block protocol=TCP localport=<old>
   ```
7. Rollback on failure
   ```
   Set-ItemProperty PortNumber=<old>; Restart-Service TermService; netsh advfirewall firewall delete rule name="RDPMonitor RDP <new>"
   ```

**Effect:** RDP listens on the new port; the old port is blocked only after the new one verifies.
**Output:** "New port: <port> (verified listening)" or a rollback notice.
**Troubleshoot:** No listener -> it rolls back; check admin rights, port conflicts, and update provider firewall/port-forwarding. Keep a console session open.
**Related:** /rdp /rdpallow /firewall

### /trap
- Purpose: Trap usernames: ban an IP immediately on any login attempt using those names.
- Usage: `/trap list | add <name> | del <name>`
- Panel: sec

**What it does:** Honeypot usernames: any login attempt bans the IP.

**Steps (backend commands):**
1. Update
   ```
   config.trap_users add/del
   ```

**Effect:** The first attempt with that name blocks the IP.
**Output:** The trap list.
**Troubleshoot:** Use names no real user has.
**Related:** /blocklist

### /unblock
- Purpose: Removes a firewall block for an IP.
- Usage: `/unblock <ip>`
- Panel: sec
- Risk: dangerous (confirmation required)

**What it does:** Removes a firewall block for an IP and verifies it is gone.

**Steps (backend commands):**
1. Delete the rule
   ```
   netsh advfirewall firewall delete rule name="RDPMonitor Block <ip>"
   ```
2. Verify
   ```
   (Get-NetFirewallRule -DisplayName 'RDPMonitor Block <ip>').Count
   ```
3. Update state
   ```
   blocked.json.pop(<ip>) only if the rule is gone
   ```

**Effect:** The IP can reach the machine again.
**Output:** "The ban has been lifted" or a failure notice.
**Troubleshoot:** If the rule remains, the IP stays tracked; retry or check permissions.
**Related:** /block /blocklist

### /whitelist
- Purpose: The RDP allow list: manual IPs plus IPs learned automatically from successful logins (last 14 days). Used by lockdown.
- Usage: `/whitelist`
- Panel: bot-only

**What it does:** The RDP allow-list (manual + learned IPs).

**Steps (backend commands):**
1. Read
   ```
   config.rdp_allowed_ips + learned_ips
   ```

**Effect:** Read-only view; apply with /rdpallow.
**Output:** The allow-list.
**Troubleshoot:** Learned IPs are used only during lockdown if enabled.
**Related:** /rdpallow /lockdown

## Users

### /adduser
- Purpose: Creates a local Windows account: /adduser name password for a normal user with RDP access, or add 'admin' to make it an administrator. The password stays visible in chat history - change it later if the chat is shared.
- Usage: `/adduser <name> <password> [admin] confirm`
- Panel: users
- Risk: dangerous (confirmation required)

**What it does:** Creates a local account and adds it to a group.

**Steps (backend commands):**
1. Create
   ```
   New-LocalUser -Name <n> -Password (Read-Host -AsSecureString)
   ```
2. Add to group
   ```
   Add-LocalGroupMember -Group <g> -Member <n>
   ```

**Effect:** A new local account exists.
**Output:** "created" or an error.
**Troubleshoot:** Requires user management enabled (/set users on).
**Related:** /deluser /listusers

### /deluser
- Purpose: Deletes a local account permanently. Refuses to remove the last administrator.
- Usage: `/deluser <name> confirm`
- Panel: users
- Risk: dangerous (confirmation required)

**What it does:** Deletes a local account.

**Steps (backend commands):**
1. Delete
   ```
   Remove-LocalUser -Name <n>
   ```

**Effect:** The account is removed.
**Output:** "deleted" or an error.
**Troubleshoot:** The profile folder remains on disk.
**Related:** /adduser /listusers

### /disableuser
- Purpose: Disables an account (cannot log in) without deleting anything - reversible with /enableuser.
- Usage: `/disableuser <name> confirm`
- Panel: users
- Risk: dangerous (confirmation required)

**What it does:** Disables a local account.

**Steps (backend commands):**
1. Disable
   ```
   Disable-LocalUser -Name <n>
   ```

**Effect:** The account cannot sign in.
**Output:** "disabled" or an error.
**Troubleshoot:** Re-enable with /enableuser.
**Related:** /enableuser /listusers

### /enableuser
- Purpose: Re-enables a disabled account.
- Usage: `/enableuser <name> confirm`
- Panel: users
- Risk: dangerous (confirmation required)

**What it does:** Enables a local account.

**Steps (backend commands):**
1. Enable
   ```
   Enable-LocalUser -Name <n>
   ```

**Effect:** The account can sign in again.
**Output:** "enabled" or an error.
**Troubleshoot:** Pair with /disableuser.
**Related:** /disableuser /listusers

### /logoff
- Purpose: Forces a user's RDP session to end immediately. Programs running in that session close without saving.
- Usage: `/logoff <name> confirm`
- Panel: live
- Risk: dangerous (confirmation required)

**What it does:** Logs off a Windows/RDP session.

**Steps (backend commands):**
1. Log off
   ```
   logoff <session-id>
   ```

**Effect:** That session ends.
**Output:** "done" or an error.
**Troubleshoot:** Confirm the session id from /rdp first.
**Related:** /rdp /listusers

### /renameuser
- Purpose: Renames a local Windows account.
- Usage: `/renameuser <old> <new>`
- Panel: users
- Risk: dangerous (confirmation required)

**What it does:** Renames a local account.

**Steps (backend commands):**
1. Rename
   ```
   Rename-LocalUser -Name <old> -NewName <new> -ErrorAction Stop
   ```

**Effect:** The account name changes; profile folder keeps the old name.
**Output:** "Renamed: <old> -> <new>".
**Troubleshoot:** Fails if the new name is taken.
**Related:** /listusers

## root

### /help
- Purpose: This reference.
- Usage: `/help`
- Panel: bot-only

**What it does:** The full command reference.

**Steps (backend commands):**
1. Render
   ```
   HELP_TEXT
   ```

**Effect:** Read-only.
**Output:** The reference.
**Troubleshoot:** Use /docs <command> for details.
**Related:** /docs
