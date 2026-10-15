# RDP Monitor Suite

**v4.3-full-fixed** — a self-hosted monitoring, security, and administration suite for
Windows servers that you reach over RDP.

It runs quietly on the machine, watches health and security, and lets you check on it,
control it, and back it up from a Telegram chat or a local web panel — without opening
a public admin port.

---

## Table of contents

- [What this is](#what-this-is)
- [Who it is for](#who-it-is-for)
- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation (step by step)](#installation-step-by-step)
- [First-run checklist](#first-run-checklist)
- [Everyday commands](#everyday-commands)
- [The local WebConsole](#the-local-webconsole)
- [Backups and restore](#backups-and-restore)
- [How secrets are stored](#how-secrets-are-stored)
- [Important security notes](#important-security-notes)
- [Uninstall](#uninstall)
- [Running the tests](#running-the-tests)
- [Project layout](#project-layout)
- [Project status](#project-status)
- [License](#license)

---

## What this is

RDP Monitor Suite is a single Windows folder that you drop onto a VPS or remote server.
Once installed it:

- monitors CPU, RAM, disk, network, temperature, sessions, and Windows event logs;
- protects the RDP service from brute-force and distributed logon attacks;
- takes scheduled backups (ZIP or restic) and ships them to cloud storage;
- optionally captures a full bootable system image;
- gives you two control surfaces: a **Telegram bot** and a **localhost-only web panel**.

Everything is driven from this folder. There is no cloud service, no account, and no
telemetry — the only network calls are the ones you configure (Telegram, cloud storage,
optional speed tests).

It is a consolidated, separately maintained build based on v4.3. It includes the
corrected core, transactional TCP/UDP firewall handling, per-installation Windows
mutexes, safer defaults, persistent retry queues, and a hardened WebConsole. See
[`CHANGELOG-FIXED.md`](CHANGELOG-FIXED.md) and [`PATCH-NOTES.md`](PATCH-NOTES.md).

## Who it is for

**Good fit:**

- System administrators running **Windows VPS / dedicated servers** they connect to over RDP.
- Solo operators and small teams who want **phone-based monitoring and control** of a machine
  they cannot watch 24/7.
- Anyone who wants **active RDP brute-force protection** (auto-blocking, allow-lists,
  lockdown, panic) without a paid security product.
- People who need **scheduled off-host backups** of a Windows box.

**Not a good fit:**

- Non-Windows hosts — this is Windows-only (it uses Windows Firewall, DPAPI, VSS,
  scheduled tasks, and PowerShell).
- Users who cannot get **Administrator rights** on the machine (most features need them).
- Multi-tenant or untrusted-user machines — the bot grants powerful control of the host
  to whoever holds the Telegram token.
- Anyone who wants a managed SaaS product. This is self-hosted and you own the risk.

**The security model in one line:** the person who controls the Telegram bot controls the
machine. Treat the bot token and chat like the server's root password.

## What it does

### Monitoring
- `/view` live CPU, RAM, disk, network, sessions, uptime
- `/top` highest CPU/RAM processes, `/chart` 24-hour CPU/RAM graph
- `/report` daily report, `/temp` CPU/GPU temperature when sensors exist
- `/net` and `/speedtest` network usage and real speed tests
- `/rdp` active RDP sessions and remote IPs, `/listusers` local accounts

### Control
- `/screenshot` desktop capture, `/exec` and `/run` command/program execution (off by default)
- `/kill` terminate processes, `/msg` on-screen message
- `/download` send a file to chat, `/restart` / `/shutdown confirm` / `/cancel_restart`
- `/audit` recent accepted and rejected actions

### RDP security
- Watches Windows Event ID **4625** for failed logons
- Can create persistent Windows Firewall **block rules** for repeat offenders
- `/blocklist` and `/unblock <IP>` manage tracked addresses
- `/rdpallow add <IP>` + `/rdpallow apply confirm` enable **default-deny** RDP access
- `/lockdown on` detects **distributed** attacks across many source addresses
- `/panic on` closes RDP at the firewall until `/panic off`
- `/harden` checks NLA, account lockout, and administrator-account posture
- `/firewall`, `/netstat`, `/diagnose` for diagnostics

### Backups
- ZIP or restic engines, optional AES password, CRC/manifest verification
- Local retention, cloud delivery through **rclone**, share links
- Restore, and automated **restore drills** that prove the archive actually restores
- Separate SYSTEM worker so scheduled backups run with no user signed in

### Optional system imaging
- `/image start` captures every volume into a VHDX (Disk2vhd), optional rclone upload
- Disabled by default; requires confirmation and a VM restore drill before you trust it

### Local WebConsole
- Authenticated browser panel on `127.0.0.1:8399` (see [below](#the-local-webconsole))

## Requirements

| Item | Requirement |
| --- | --- |
| OS | Windows 10/11 or Windows Server 2016+ (x64) |
| Python | Python 3.9 or newer, **64-bit**, with `pip` on PATH |
| Privileges | An **Administrator** terminal for install/uninstall and most features |
| Network | Internet access for Telegram and (optional) cloud storage |
| Telegram | A Telegram account and a bot token from [@BotFather](https://t.me/BotFather) |

The suite installs its own Python dependencies. Windows Scheduled Tasks, the Windows
Firewall, DPAPI, and PowerShell ship with Windows.

## Installation (step by step)

> Work in an **Administrator** PowerShell or Command Prompt, and `cd` into the folder
> that contains `rdp_suite.py`.

**1. Install Python 3.9+ (64-bit).**
Download from [python.org](https://www.python.org/downloads/windows/) and tick
**“Add python.exe to PATH”** during setup. Verify:

```console
python --version
```

**2. Install the dependencies.**

```console
python -m pip install -r requirements.txt
```

This installs the monitor requirements and, through `-r backup/requirements.txt`, the
backup engine and Telegram library.

**3. Create a Telegram bot.**
Talk to [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the **bot token**.
Send your new bot any message, then find your numeric **chat ID** (for example with
[@userinfobot](https://t.me/userinfobot)).

**4. Run the guided first-run setup.**

```console
python rdp_monitor.py
```

On first launch it asks for the **bot token** and **chat ID**, writes `config.json`,
and starts the monitor. Send `/start` to your bot to confirm it answers. Stop it with
`Ctrl+C` once configured (the installer will start it properly).

**5. Register the Windows tasks.**

Either double-click **`install.bat`**, or run:

```console
python rdp_suite.py install
```

This creates **two** scheduled tasks by design:

- **`RDPSuite`** — the interactive monitor + WebConsole, started at Administrator logon.
- **`RDPSuiteBackup`** — the backup worker, running as **SYSTEM** at startup.

The split preserves user-scoped DPAPI and interactive desktop features for the monitor
while letting VSS backups run without a signed-in user.

**6. Verify.**

```console
python rdp_suite.py status
```

Send `/test` in Telegram. To open the web panel:

```console
python rdp_suite.py open
```

## First-run checklist

- [ ] `python rdp_suite.py status` shows the tasks registered and running.
- [ ] `/test` in Telegram replies.
- [ ] `/view` returns a live report.
- [ ] Add yourself to the trusted list if needed: `/allow add <your-telegram-user-id>`.
- [ ] Set your alert thresholds and heartbeat: `/set` (opens the settings guide).
- [ ] Configure backups: `/backsrc add <path>`, `/backupschedule daily 03:00`.
- [ ] Run one backup and a drill: `/backup`, then `/drill`.
- [ ] **Before changing RDP port, allow-list, or lockdown:** confirm your current
      management IP and keep provider-console access open.
- [ ] Do the risky tests (firewall, imaging, cloud) on a **disposable VM** first.

## Everyday commands

`rdp_suite.py` is the launcher/management CLI:

```console
python rdp_suite.py status          # tasks, ports, component state
python rdp_suite.py open            # open the WebConsole in a browser
python rdp_suite.py backup-now      # queue a manual backup
python rdp_suite.py backup-status   # backup worker state
python rdp_suite.py backup-gui      # desktop backup settings window
python rdp_suite.py restore-list    # list local archives
python rdp_suite.py restore <archive> --to <dir>
python rdp_suite.py drill           # restore+verify the newest archive
python rdp_suite.py install         # register scheduled tasks
python rdp_suite.py uninstall       # remove scheduled tasks
```

Autostart helpers:

```console
python autostart.py status
python autostart.py install
python autostart.py uninstall
```

A per-installation Windows named mutex prevents duplicate monitor instances.

The **complete, generated command reference** for every bot command lives in
[`docs/COMMANDS.md`](docs/COMMANDS.md), and the bot itself can show it with `/help` and
`/docs <command>`.

## The local WebConsole

Recommended local use (Administrator terminal):

```console
python webconsole\RDPWebConsole.py
```

Open `http://127.0.0.1:8399/` and enter the login token. To display or rotate it:

```console
python webconsole\RDPWebConsole.py token
python webconsole\RDPWebConsole.py rotate-token
```

Install local at-logon startup **without** opening an inbound firewall port:

```console
python webconsole\RDPWebConsole.py install
```

Remote access should normally go through a VPN such as **Tailscale** or **WireGuard**.
Direct remote mode is refused unless TLS files and an explicit source-IP allow-list are
configured:

```console
set RDPWC_TLS_CERT=C:\secure\cert.pem
set RDPWC_TLS_KEY=C:\secure\key.pem
set RDPWC_ALLOWED_IPS=203.0.113.5/32
python webconsole\RDPWebConsole.py install-remote
```

WebConsole security defaults:

- Command and program execution are disabled (`exec_enabled=false`).
- File downloads are disabled (`downloads_enabled=false`).
- The login token is protected with Windows DPAPI and never appears in the URL.
- Sessions expire after 30 minutes and modifying requests require CSRF protection.
- Downloads, when explicitly enabled, are restricted to configured roots and 50 MB.
- Request, connection, authentication, and worker limits are enforced.

See [`webconsole/README.md`](webconsole/README.md) and [`SECURITY.md`](SECURITY.md).

## Backups and restore

Local ZIP retention runs only after a fully successful backup **and** delivery. Partial
or failed jobs retain the prior local copies, and `keep_local_copies` applies even when
sources appear unchanged. A failed manifest write aborts and removes the incomplete ZIP.
Keep an independent off-host copy as well.

- `python rdp_suite.py restore-list` lists local archives.
- `python rdp_suite.py restore <archive-name> --to <dir>` restores into a new, empty
  folder and verifies every file by size **and** CRC against the archive manifest.
- `python rdp_suite.py drill` restores the newest archive into a new folder, verifies it,
  then removes the copy.
- A restore refuses to run when the manifest is missing/malformed, when it does not match
  the archive contents, or when the destination already exists (to avoid overwriting a
  previous restore).
- Set `restore_drill.enabled` in `backup\config.json` to run periodic drills automatically.

The backup worker runs as SYSTEM, so its configuration and secrets live in
`backup\config.json` and are protected with **machine-scoped** Windows DPAPI. See
[`backup/README_EN.md`](backup/README_EN.md).

## How secrets are stored

Secrets are never committed to source control (see [`.gitignore`](.gitignore)) and are
never stored in plaintext at rest:

- `config.json` — bot token (DPAPI-encrypted), chat id, learned IPs.
- `backup/config.json` — cloud remotes, rclone path, restic password.
- `webconsole/webconsole_state.json` — panel login token (DPAPI-encrypted).
- `webconsole/tls/` — the panel TLS private key.

The Telegram bot token and WebConsole login token are encrypted with the Windows **DPAPI**
(user scope), so only the same Windows account on the same machine can decrypt them.
Secret-bearing files and the TLS private key have their ACLs hardened to the owner.

Use the shipped [`config.example.json`](config.example.json) and
[`backup/config.example.json`](backup/config.example.json) as templates.

## Important security notes

- `/exec`, `/run`, uploads, user management, and system imaging are **disabled by default**
  in the fixed build. Enable only when you need them, and turn them back off.
- Self-update requires HTTPS and a configured SHA-256 fingerprint.
- Telegram passwords or secrets typed into chat **remain in chat history**.
- A successful RDP login does **not** automatically make an address trusted for lockdown.
- Windows display-language parsing is primarily designed for English systems.
- Uninstall removes managed tasks and firewall policy but does **not** reverse every
  administrative action — such as created accounts, an RDP port change, downloaded files,
  or NLA/account-policy changes.
- **Uninstall and the RDP IP allow-list:** when an allow-list is active, uninstall keeps
  its rules, the broad rules it disabled, and its restrictive inbound policy. Review the
  effective firewall rules from the provider console after uninstall. To explicitly remove
  the restriction and open RDP to any source, run cleanup with `--remove-allowlist`
  (only when you intend to do so). You can also explicitly request preservation with:
  ```console
  python rdp_monitor.py --cleanup --keep-allowlist
  ```
- **Test firewall and RDP policy changes on a disposable VM with provider-console access
  first.**

## Uninstall

```console
python rdp_suite.py uninstall
```

Removes the scheduled tasks and runs policy cleanup. Configuration and data are preserved
by default. Review the [security notes](#important-security-notes) above for what is *not*
reversed.

## Running the tests

Non-destructive, offline tests ship with the tool:

```console
python -m unittest discover -s tests -v
```

The bundled safety, backup, and WebConsole tests mock Telegram, Windows machine actions,
cloud operations, and Disk2vhd; they never contact the live bot or change firewall state.

## Project layout

```
rdp_suite.py            Unified launcher / management CLI
rdp_monitor.py          RDP protection + monitor Telegram bot
autostart.py            Per-user autostart helpers
install.bat             One-click dependency install + task registration
uninstall.bat           Removes the scheduled tasks
config.example.json     Template for config.json
docs/COMMANDS.md        Generated reference for every bot command
webconsole/             Hardened local browser panel
backup/                 ZIP/restic backup engine + SYSTEM worker
tests/                  Offline safety and contract tests
scripts/                Installer and helper scripts
```

## Project status

This is the **v4.3-full-fixed** build. It is a hardened repair of v4.3 and passes the
bundled offline test suite (safety, backup, WebConsole, and interaction/release-contract
checks). Those tests mock Telegram, Windows machine actions, cloud operations, and
Disk2vhd.

**Not yet verified by the offline tests** — and therefore requiring a disposable Windows
VM with a separate bot token before production use:

- live Telegram Confirm/Cancel flows across chats and after restart;
- real firewall behavior (verify from an out-of-band provider console);
- real cloud write/read/delete and off-host recovery;
- scheduled backup/restore to another machine;
- single- and multi-disk imaging, VSS/encrypted volumes, and a VM boot from the output.

Treat this as a strong starting point that you validate for your own environment, not as a
turnkey production guarantee.

## License

[MIT](LICENSE) © 2026 RDPMonitor contributors.
