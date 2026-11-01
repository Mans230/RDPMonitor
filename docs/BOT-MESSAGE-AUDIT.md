# Telegram command presentation audit

All 88 catalog commands were exercised individually, plus 27 argument/confirmation cases (115 total). Each also opened its review card and generated its documentation card.

The audit uses disposable runtime paths, fake Telegram delivery, mocked Windows queries and speed measurements, plus a process audit barrier against host writes, process launches and outbound network connections. Background read-only jobs execute synchronously against these fixtures. Administrative operations are reviewed or simulated; they were not applied to the live server. This is presentation and failure-path coverage, not a live end-to-end test of every administrative operation.

Long text replies use balanced HTML pages estimated at 16 rows × 32 columns, with navigation editing the same message. Exact font metrics depend on the Telegram client. Code/text content is preserved across pages. Pages are chat-bound, expire after ten minutes, and are held only in bounded process memory. Confirmation prompts keep their complete action context and are not paginated.

`/top` defaults to five CPU processes; buttons switch to RAM or ranks 6–10. PID 0 (idle time) is excluded, and CPU uses total machine capacity. `/view` fits one normal mobile page. `/help` opens categories; `/docs` retains full references. Required-argument commands show a compact usage guide when called without a target.

No command execution, OS mutations or outbound delivery occurred during this fixture audit. Success below means the expected presentation path returned without an uncaught exception, including clear unavailable/error states when a query was deliberately denied.

| Command | Reply | Review card | Documentation |
| --- | --- | --- | --- |
| `/adduser` | Pass | Pass | 2 page(s) |
| `/allow` | Pass | Pass | 2 page(s) |
| `/audit` | Pass | Pass | 2 page(s) |
| `/backsrc` | Pass | Pass | 2 page(s) |
| `/backup` | Pass | Pass | 3 page(s) |
| `/backuplist` | Pass | Pass | 1 page(s) |
| `/backupprogress` | Pass | Pass | 2 page(s) |
| `/backupschedule` | Pass | Pass | 2 page(s) |
| `/backupstatus` | Pass | Pass | 2 page(s) |
| `/bigfiles` | Pass | Pass | 2 page(s) |
| `/block` | Pass | Pass | 2 page(s) |
| `/blocklist` | Pass | Pass | 2 page(s) |
| `/blocksubnet` | Pass | Pass | 2 page(s) |
| `/botlog` | Pass | Pass | 1 page(s) |
| `/cancel_restart` | Pass | Pass | 2 page(s) |
| `/chart` | Pass | Pass | 2 page(s) |
| `/clean` | Pass | Pass | 2 page(s) |
| `/cloud` | Pass | Pass | 2 page(s) |
| `/configbackup` | Pass | Pass | 2 page(s) |
| `/deluser` | Pass | Pass | 2 page(s) |
| `/diagnose` | Pass | Pass | 2 page(s) |
| `/disableuser` | Pass | Pass | 2 page(s) |
| `/docs` | Pass | Pass | 2 page(s) |
| `/download` | Pass | Pass | 2 page(s) |
| `/drill` | Pass | Pass | 2 page(s) |
| `/dumps` | Pass | Pass | 2 page(s) |
| `/enableuser` | Pass | Pass | 2 page(s) |
| `/exec` | Pass | Pass | 2 page(s) |
| `/exportlogs` | Pass | Pass | 2 page(s) |
| `/firewall` | Pass | Pass | 3 page(s) |
| `/getlog` | Pass | Pass | 1 page(s) |
| `/harden` | Pass | Pass | 3 page(s) |
| `/help` | Pass | Pass | 1 page(s) |
| `/image` | Pass | Pass | 2 page(s) |
| `/keepalive` | Pass | Pass | 1 page(s) |
| `/kill` | Pass | Pass | 2 page(s) |
| `/listusers` | Pass | Pass | 2 page(s) |
| `/lockdown` | Pass | Pass | 3 page(s) |
| `/logins` | Pass | Pass | 2 page(s) |
| `/logoff` | Pass | Pass | 2 page(s) |
| `/logstats` | Pass | Pass | 2 page(s) |
| `/menu` | Pass | Pass | 1 page(s) |
| `/msg` | Pass | Pass | 2 page(s) |
| `/mute` | Pass | Pass | 2 page(s) |
| `/net` | Pass | Pass | 2 page(s) |
| `/netstat` | Pass | Pass | 2 page(s) |
| `/nettest` | Pass | Pass | 2 page(s) |
| `/noop` | Pass | Pass | 1 page(s) |
| `/panel` | Pass | Pass | 2 page(s) |
| `/panelremote` | Pass | Pass | 2 page(s) |
| `/panelstatus` | Pass | Pass | 2 page(s) |
| `/paneltoken` | Pass | Pass | 1 page(s) |
| `/panic` | Pass | Pass | 3 page(s) |
| `/ps` | Pass | Pass | 2 page(s) |
| `/rclone` | Pass | Pass | 3 page(s) |
| `/rdp` | Pass | Pass | 2 page(s) |
| `/rdpallow` | Pass | Pass | 5 page(s) |
| `/renameuser` | Pass | Pass | 2 page(s) |
| `/report` | Pass | Pass | 1 page(s) |
| `/restart` | Pass | Pass | 2 page(s) |
| `/restore` | Pass | Pass | 3 page(s) |
| `/restorelist` | Pass | Pass | 2 page(s) |
| `/run` | Pass | Pass | 2 page(s) |
| `/screenshot` | Pass | Pass | 2 page(s) |
| `/set` | Pass | Pass | 2 page(s) |
| `/setrdpport` | Pass | Pass | 5 page(s) |
| `/shutdown` | Pass | Pass | 2 page(s) |
| `/speedtest` | Pass | Pass | 2 page(s) |
| `/start` | Pass | Pass | 1 page(s) |
| `/startup` | Pass | Pass | 2 page(s) |
| `/status` | Pass | Pass | 1 page(s) |
| `/suiteupdate` | Pass | Pass | 1 page(s) |
| `/svc` | Pass | Pass | 2 page(s) |
| `/svcwatch` | Pass | Pass | 1 page(s) |
| `/sysinfo` | Pass | Pass | 2 page(s) |
| `/temp` | Pass | Pass | 2 page(s) |
| `/test` | Pass | Pass | 2 page(s) |
| `/token` | Pass | Pass | 2 page(s) |
| `/top` | Pass | Pass | 2 page(s) |
| `/traffic` | Pass | Pass | 2 page(s) |
| `/trap` | Pass | Pass | 2 page(s) |
| `/unblock` | Pass | Pass | 2 page(s) |
| `/update` | Pass | Pass | 2 page(s) |
| `/updates` | Pass | Pass | 2 page(s) |
| `/view` | Pass | Pass | 2 page(s) |
| `/watch` | Pass | Pass | 2 page(s) |
| `/when` | Pass | Pass | 2 page(s) |
| `/whitelist` | Pass | Pass | 2 page(s) |

Argument cases:

`/top cpu 1`, `/top cpu 2`, `/top ram 1`, `/top ram 2`, `/top invalid`, `/exec whoami`, `/kill worker.exe`, `/run notepad`, `/logoff 1`, `/adduser fixture-user`, `/deluser fixture-user`, `/disableuser fixture-user`, `/enableuser fixture-user`, `/renameuser fixture-user renamed-user`, `/panic on`, `/rdpallow apply`, `/lockdown now`, `/harden fix`, `/svc restart Spooler`, `/restore fixture.zip`, `/backsrc remove 1`, `/backupschedule off`, `/image start`, `/suiteupdate now`, `/panelremote direct`, `/set cpu invalid`, `/traffic 30`

Reproduce with `python -B scripts/audit_bot_messages.py`. Regression tests run this inventory automatically and verify no missing catalog command, missing reply, unhandled exception or oversized base review card.
