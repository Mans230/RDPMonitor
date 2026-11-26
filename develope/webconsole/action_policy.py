"""Server confirmation policy. Read-only variants do not need confirmation."""
CONFIRMED_ACTIONS = frozenset({
    "user", "reboot", "shutdown", "kill", "kill_app", "clean_temp", "msg", "logoff",
    "service", "run_command", "start_program", "screenshot", "backup_now", "backup_gui",
    "restore", "drill", "rdp", "settings_set", "block_subnet", "set_rdp_port", "mute",
    "trap", "cancel_restart", "automation", "update_now", "exportlogs", "send_file",
    "block_ip", "unblock_ip", "test_alert",
})


def requires_confirmation(action, body):
    if action not in CONFIRMED_ACTIONS:
        return False
    if action == "service" and body.get("mode", "status") == "status":
        return False
    if action == "rdp" and body.get("op") == "rdp_status":
        return False
    if action in ("automation", "trap") and body.get("op", "list") == "list":
        return False
    return True


def confirmation_arguments(body):
    return {k: v for k, v in body.items() if k not in ("action", "target", "nonce")}


def audit_action(action, body):
    """Use enumerated labels only: never copy free-text arguments into usage logs."""
    if action == "prepare":
        target = body.get("target")
        return "prepare:" + (target if isinstance(target, str) and target in CONFIRMED_ACTIONS else "unknown")
    variants = {
        "user": ("op", {"add", "enable", "disable", "delete", "password", "rename"}),
        "rdp": ("op", {"rdp_status", "rdp_allow_add", "rdp_allow_remove", "rdp_allow_apply", "rdp_allow_clear", "lockdown", "panic"}),
        "service": ("mode", {"status", "start", "stop", "restart"}),
        "automation": ("op", {"list", "add", "del"}),
        "trap": ("op", {"list", "add", "del"}),
    }
    if action in variants:
        key, allowed = variants[action]
        value = body.get(key)
        return action + ":" + (value if isinstance(value, str) and value in allowed else "unknown")
    return action if action in CONFIRMED_ACTIONS else "unknown"
