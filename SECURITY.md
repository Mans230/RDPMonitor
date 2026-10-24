# Security

See [security changes](docs/SECURITY-CHANGES.md) for confirmations, account safety,
resource bounds and remaining limits, and [usage/operator docs](docs/USAGE-AUDIT.md)
for personal credentials and attribution.

Backup secrets use **machine-scoped DPAPI** for the SYSTEM worker, unlike the
user-scoped monitor/owner token storage. File ACLs are their primary local access
boundary. Personal operator tokens are stored as hashes of random credentials in
the protected panel state, not plaintext.

## Secrets are never committed

This project keeps all secrets and runtime state out of source control (see `.gitignore`):

- `config.json` - bot token (DPAPI-encrypted), chat id, learned IPs.
- `backup/config.json` - cloud remotes, rclone path, restic password.
- `webconsole/webconsole_state.json` - panel login token (DPAPI-encrypted).
- `webconsole/tls/` - the panel TLS private key.

Use the shipped `config.example.json` and `backup/config.example.json` as templates.

## How secrets are stored at runtime

- The Telegram bot token and the WebConsole login token are encrypted with the Windows
  **DPAPI** (user scope), so they can only be decrypted by the same Windows account on the
  same machine. They are not stored in plaintext.
- Secret-bearing files and the TLS private key have their ACLs hardened to the owner.

## Remote (outside) access to the WebConsole

The panel is **local-only by default** (`127.0.0.1`). Enabling outside access requires
**HTTPS + an IP allow-list**:

```
python webconsole/RDPWebConsole.py remote-enable            # HTTPS on 0.0.0.0, allow-list = loopback + Tailscale + live RDP client IPs
python webconsole/RDPWebConsole.py remote-enable --allow 0.0.0.0/0   # allow any IP (TLS + token still required)
python webconsole/RDPWebConsole.py remote-disable
```

Or from the bot: `/panelremote on | off | status | open | allow <ip> | deny <ip>`.

When exposing the panel, prefer an allow-list (a VPN such as Tailscale, or your own IP)
over `0.0.0.0/0`. The panel is protected by TLS, a strong login token, CSRF tokens and
per-IP login rate limiting, but it also grants full control of the host.

## Reporting a vulnerability

Open a private security advisory on the repository, or contact the maintainers directly.
Please do not open a public issue for an unpatched vulnerability.
