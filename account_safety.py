"""Serialize account checks and mutations across this monitor's control threads."""
import functools
import threading

_ACCOUNT_LOCK = threading.RLock()
USER_COMMANDS = frozenset({"/adduser", "/deluser", "/disableuser", "/enableuser", "/renameuser"})


def serialized_account_action(fn):
    @functools.wraps(fn)
    def locked(*args, **kwargs):
        with _ACCOUNT_LOCK:
            return fn(*args, **kwargs)
    return locked


def serialized_user_command(fn):
    @functools.wraps(fn)
    def locked(text, *args, **kwargs):
        command = (str(text).strip().split() or [""])[0].lower().split("@")[0]
        if command in USER_COMMANDS:
            with _ACCOUNT_LOCK:
                return fn(text, *args, **kwargs)
        return fn(text, *args, **kwargs)
    return locked
