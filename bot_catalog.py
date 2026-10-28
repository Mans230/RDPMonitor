"""One canonical category per command; aliases remain accepted but are not duplicated."""
import html

CATEGORIES = {
    "resources": ("CPU & RAM", ["view", "top", "chart", "report", "temp", "when", "ps"]),
    "network": ("Network & traffic", ["net", "traffic", "speedtest", "nettest", "netstat"]),
    "accounts": ("Sessions & accounts", ["rdp", "logins", "listusers", "adduser", "disableuser", "enableuser", "renameuser", "deluser", "logoff"]),
    "security": ("RDP security & firewall", ["audit", "blocklist", "block", "blocksubnet", "unblock", "whitelist", "rdpallow", "lockdown", "panic", "harden", "setrdpport", "firewall", "allow", "trap"]),
    "automation": ("Programs & services", ["watch", "keepalive", "svcwatch"]),
    "backup": ("Backup & restore", ["backup", "backupprogress", "backupstatus", "backuplist", "backsrc", "backupschedule", "restorelist", "restore", "drill"]),
    "cloud": ("Cloud & system images", ["cloud", "rclone", "image"]),
    "control": ("Device actions", ["screenshot", "exec", "kill", "run", "msg", "download", "restart", "shutdown", "cancel_restart", "svc"]),
    "diagnostics": ("Diagnostics & logs", ["diagnose", "logstats", "botlog", "exportlogs", "dumps", "bigfiles", "sysinfo", "startup", "updates"]),
    "settings": ("Settings & alerts", ["set", "status", "mute", "clean", "test", "configbackup", "update"]),
    "panel": ("Web panel", ["panel", "panelstatus", "paneltoken", "panelremote"]),
    "docs": ("Help & navigation", ["docs", "help", "menu"]),
}
ALIASES = {"/getlog": "/botlog", "/token": "/paneltoken", "/start": "/menu"}
HIDDEN = {"/noop": "docs"}
PAGE_ALIASES = {"mon": "resources", "users": "accounts", "sec": "security", "ctrl": "control", "maint": "settings"}
LABELS = {"watch": "Per-process RAM limit", "view": "Live CPU / RAM snapshot",
          "set": "One settings guide", "logins": "Who logged in, source & UTC time",
          "rdp": "Current session states", "blocksubnet": "Block IPv4 /24 (high impact)"}
OWNERS = {"/" + command: key for key, (_, commands) in CATEGORIES.items() for command in commands}
OWNERS.update(HIDDEN)
OWNERS.update({alias: OWNERS[canonical] for alias, canonical in ALIASES.items()})


def canonical_command(command):
    return ALIASES.get(command, command)


def category_title(command):
    owner = OWNERS.get(canonical_command(command))
    return CATEGORIES[owner][0] if owner else "Other"


def build_menus():
    menus = {"root": ("<b>RDP Monitor</b>\nChoose one category. Every command opens a review card.",
                      [(title, "menu:" + key) for key, (title, _) in CATEGORIES.items()])}
    for key, (title, commands) in CATEGORIES.items():
        menus[key] = ("<b>" + title + "</b>\nReview the purpose and effect before running a command.",
                      [(LABELS.get(command, "/" + command), "cmd:/" + command) for command in commands])
    return menus


def help_text(info):
    lines = ["<b>RDP Monitor command reference</b>"]
    for title, commands in CATEGORIES.values():
        lines.extend(["", "<b>" + title + "</b>"])
        for command in commands:
            description = info.get("/" + command, ("Open its review card for details.",))[0]
            lines.append("/" + command + " — " + html.escape(description))
    lines.append("\nAliases: /start → /menu; /getlog → /botlog; /token → /paneltoken.")
    return "\n".join(lines)


def telegram_menu(info):
    return [{"command": command, "description": (title + " — " + info.get("/"+command, (command,))[0])[:256]}
            for title, commands in CATEGORIES.values() for command in commands]
