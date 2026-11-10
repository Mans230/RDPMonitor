"""Local administrator operations for private access; no chat credentials."""
from pathlib import Path
from private_panel import validated_url


def execute(wc, argv):
    command = argv[0]
    if command == 'private-enable':
        if len(argv) != 2:
            raise ValueError('Usage: private-enable https://machine.tailnet.ts.net')
        origin = argv[1]
        candidate = dict(wc.STATE, bind='127.0.0.1', auth_mode='passkey',
                         passkey_origin=origin, trusted_proxy_origin=origin)
        if not validated_url(candidate):
            raise ValueError('An exact HTTPS Tailscale Serve origin is required.')
        from passkey_auth import Passkeys
        candidate['passkey_db'] = str(Path(wc.BASE_DIR) / 'panel-passkeys.sqlite3')
        candidate['passkey_local_test'] = False
        if not wc.harden_private_storage():
            raise PermissionError('Could not protect private credential storage.')
        Passkeys(candidate['passkey_db'], origin)  # Validate dependencies/origin before saving.
        wc.atomic_write(wc.STATE_FILE, candidate)
        if not wc.harden_file(wc.STATE_FILE):
            raise PermissionError('Could not protect panel state.')
        print('Private access configured. Restart the panel, configure Serve for its loopback port, and enroll a passkey.')
        print('The public firewall rule must be disabled after the private route is verified.')
        return 0
    if not wc.passkey_mode():
        raise ValueError('Private Passkey mode is not configured.')
    store = wc.passkey_store()
    if command == 'passkey-pending' and len(argv) == 1:
        import json
        print(json.dumps(store.pending(), indent=2))
    elif command == 'passkey-approve' and len(argv) == 2:
        print('Approved owner key:', store.approve(argv[1]))
    elif command == 'passkey-revoke' and len(argv) == 2:
        store.revoke(argv[1])
        print('Key revoked; its sessions will be rejected on their next request.')
    else:
        raise ValueError('Use passkey-pending | passkey-approve REQUEST_ID | passkey-revoke FINGERPRINT')
    return 0
