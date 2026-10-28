# Hardened RDPWebConsole

Personal operator tokens, the request-confirmation protocol and audit semantics
are documented in [USAGE-AUDIT](../docs/USAGE-AUDIT.md) and
[SECURITY-CHANGES](../docs/SECURITY-CHANGES.md). Upgrade the HTML, Python server and
helper modules together; older clients cannot issue protected actions without
fresh server nonces. See [validation and rollback](../docs/VALIDATION.md).

Run from an **Administrator** terminal.

## Local use (recommended)

```console
python RDPWebConsole.py
```

Open `http://127.0.0.1:8399/` and enter the login token. To display or rotate it:

```console
python RDPWebConsole.py token
python RDPWebConsole.py rotate-token
```

Install local at-logon startup without opening a firewall port:

```console
python RDPWebConsole.py install
```

## Security defaults

- The login token is protected with Windows DPAPI and is never put in the URL.
- Administrator command/program execution is disabled (`exec_enabled=false`).
- File downloads are disabled (`downloads_enabled=false`).
- Sessions expire after 30 minutes and modifying requests require CSRF protection.
- Local mode accepts loopback clients and Host headers only.

Prefer a VPN for remote access. Direct remote mode requires a TLS certificate, private
key, and explicit source-IP allow-list; see the main `README.md` before using
`install-remote`.
