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
