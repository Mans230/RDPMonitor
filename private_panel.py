"""Public access metadata only: no credential decryption or signed login links."""
import re
from urllib.parse import urlsplit


def validated_url(state):
    if not isinstance(state, dict) or state.get('auth_mode') != 'passkey':
        return None
    if state.get('bind') not in ('127.0.0.1', '::1', 'localhost'):
        return None
    origin = state.get('trusted_proxy_origin')
    if not isinstance(origin, str) or state.get('passkey_origin') != origin:
        return None
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port is not None or parsed.path or parsed.query or parsed.fragment
                or not host.endswith('.ts.net') or len(host) > 253
                or origin != 'https://' + host
                or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                           for label in host.split('.'))):
            return None
        return origin + '/'
    except ValueError:
        return None


def monitor_health(root, timeout=15):
    """Probe the local ACL-protected mailbox; never create an HTTP auth bypass."""
    import json
    import secrets
    import time
    from pathlib import Path
    control = Path(root) / 'control'
    control.mkdir(parents=True, exist_ok=True)
    rid = secrets.token_hex(16)
    request = control / ('request-' + rid + '.json')
    result = control / ('result-' + rid + '.json')
    temporary = control / ('request-' + rid + '.tmp')
    try:
        temporary.write_text(json.dumps({'id': rid, 'action': 'settings_get', 'args': {},
            'created': time.time(), 'expires': time.time() + timeout}), encoding='utf-8')
        temporary.replace(request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = json.loads(result.read_text(encoding='utf-8'))
                if data.get('id') == rid and data.get('ok') is True and data.get('out', {}).get('groups'):
                    return
            except (OSError, ValueError, AttributeError):
                pass
            time.sleep(0.1)
        raise RuntimeError('Monitor mailbox health check failed')
    finally:
        for path in (temporary, request, result):
            path.unlink(missing_ok=True)
