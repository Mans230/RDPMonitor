# Targeted reliability fixes

- Do not prune previous local ZIP backups until the complete ZIP job and all configured deliveries succeed. Honor `keep_local_copies` even when source signatures match.
- Reject a failed or absent archive manifest; record the actual ZIP entry CRC where present.
- Preserve the running backup configuration if a disk edit produces invalid JSON.
- Treat a failed Telegram share-link message as partial delivery, not success.
- Preserve an active RDP IP allow-list on uninstall by default, without re-enabling broad allow rules or permissive inbound defaults. Cleanup refuses a missing/corrupt saved configuration. `--remove-allowlist` explicitly removes the restriction; verify effective firewall rules from provider-console access.
- Added regression tests covering these failure cases and encrypted backup/restore. The suite passes 57 tests on the review machine.

Not verified by these tests: live firewall rules, Windows scheduled tasks and SYSTEM behavior, VSS, cloud credentials, actual encrypted ZIPs, and off-host recovery. The bundled `rclone.exe` is unsigned; obtain and verify a trusted release independently before production use.
