# -*- coding: utf-8 -*-
"""Encrypt secrets inside config.json using Windows DPAPI.

Encrypted values are stored in  "dpapi:<base64>"  — It can only be decrypted on the same device.
The device range is used (LOCAL_MACHINE) So you can serve SYSTEM Unpack it too,
So copy config.json To another device that does not reveal any secret.

SECURITY NOTE: machine scope means any local account on this device can also
decrypt these values. Protect config.json with an ACL limited to the service
account and Administrators, and prefer user-scoped DPAPI when SYSTEM access is
not required.

On non-Windows, the values are saved as they are (Without encryption).
"""

import os
import base64

PREFIX = "dpapi:"
_ENTROPY = b"VPSBackupTool/secrets/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def is_available():
    return os.name == "nt"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _to_blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _from_blob(blob):
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def _protect(data):
        src, _b1 = _to_blob(data)
        ent, _b2 = _to_blob(_ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptProtectData(ctypes.byref(src), None, ctypes.byref(ent), None, None,
                                         _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE,
                                         ctypes.byref(out)):
            raise OSError(ctypes.FormatError())
        return _from_blob(out)

    def _unprotect(data):
        src, _b1 = _to_blob(data)
        ent, _b2 = _to_blob(_ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent), None, None,
                                           _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(ctypes.FormatError())
        return _from_blob(out)


def is_protected(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(value):
    """Plain text -> "dpapi:..." (Null or pre-coded values are returned as is)."""
    if not value or not isinstance(value, str) or is_protected(value) or not is_available():
        return value
    return PREFIX + base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")


def unprotect(value):
    """"dpapi:..." -> Plain text. raises OSError If the value is from another device."""
    if not is_protected(value):
        return value
    if not is_available():
        raise OSError("DPAPI-encrypted value cannot be decrypted on this platform")
    raw = base64.b64decode(value[len(PREFIX):])
    return _unprotect(raw).decode("utf-8")
