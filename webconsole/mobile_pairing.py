"""Ephemeral PKCE handoffs. No browser cookie or credential leaves its channel."""
import base64
import collections
import hashlib
import hmac
import re
import secrets
import threading
import time
from urllib.parse import urlencode

REDIRECT = 'io.github.mans230.rdpmonitor://auth/callback'
READ_PATHS = frozenset(('/api/session', '/api/stats', '/api/history', '/api/bandwidth/usage'))
MANAGE_PATHS = READ_PATHS | frozenset(('/api/bandwidth/connections', '/api/security', '/api/proc',
    '/api/sysinfo', '/api/netstat', '/api/services', '/api/backup', '/api/suite-update',
    '/api/setup', '/api/setup/jobs', '/api/setup/browse', '/api/rdp', '/api/settings',
    '/api/traps', '/api/automation', '/api/users', '/api/diag', '/api/audit', '/api/usage', '/api/docs'))


class PairingError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def challenge(verifier):
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
        raise PairingError('Invalid app verifier.')
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')


def match_code(challenge_value):
    value = hashlib.sha256(challenge_value.encode('ascii')).hexdigest()[:8].upper()
    return value[:4] + '-' + value[4:]


class Pairings:
    def __init__(self, clock=time.monotonic, capacity=128):
        self.clock, self.capacity = clock, capacity
        self.lock = threading.Lock()
        self.pending, self.codes = {}, {}
        self.attempts = collections.OrderedDict()

    def _prune(self):
        now = self.clock()
        for mapping in (self.pending, self.codes):
            for key in list(mapping):
                if mapping[key]['expires'] <= now:
                    del mapping[key]
        for key in list(self.attempts):
            if self.attempts[key][0] + 60 <= now:
                del self.attempts[key]

    def _limit(self, addr):
        now = self.clock()
        start, count = self.attempts.get(addr, (now, 0))
        if count >= 20:
            raise PairingError('Too many pairing attempts. Retry in a minute.', 429)
        if addr not in self.attempts and len(self.attempts) >= self.capacity * 2:
            raise PairingError('Pairing is busy. Retry later.', 429)
        self.attempts[addr] = (start, count + 1)

    def begin(self, body, addr, origin):
        scope = body.get('scope', 'monitoring:read')
        if scope not in ('monitoring:read', 'administration'):
            raise PairingError('Invalid app permission scope.')
        if (body.get('redirect_uri') != REDIRECT or body.get('code_challenge_method') != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', str(body.get('code_challenge', '')))
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', str(body.get('state', '')))):
            raise PairingError('Invalid app pairing request.')
        with self.lock:
            self._prune()
            self._limit(addr)
            if len(self.pending) + len(self.codes) >= self.capacity:
                raise PairingError('Pairing is busy. Retry later.', 429)
            request_id = secrets.token_urlsafe(24)
            self.pending[request_id] = dict(challenge=body['code_challenge'], state=body['state'],
                                           addr=addr, origin=origin, scope=scope, expires=self.clock() + 600)
            return {'authorization_url': origin + '/mobile/authorize?' + urlencode({'request': request_id}),
                    'confirmation_code': match_code(body['code_challenge'])}

    def describe(self, request_id, addr, origin):
        with self.lock:
            self._prune()
            row = self.pending.get(request_id)
            if not row or row['addr'] != addr or row['origin'] != origin:
                raise PairingError('App request expired or belongs to another device. Start again.', 404)
            return {'confirmation_code': match_code(row['challenge']), 'scope': row['scope'],
                    'expires_in': max(0, int(row['expires'] - self.clock()))}

    def consent(self, request_id, addr, origin, actor, credential, approve):
        with self.lock:
            self._prune()
            row = self.pending.get(request_id)
            if not row or row['addr'] != addr or row['origin'] != origin:
                raise PairingError('App request expired or belongs to another device. Start again.', 404)
            del self.pending[request_id]
            if not approve:
                return {'ok': True, 'denied': True}
            code = secrets.token_urlsafe(32)
            # Retain only the code digest; browser consent expires after 60 seconds.
            self.codes[hashlib.sha256(code.encode()).hexdigest()] = dict(row, actor=actor,
                credential=credential, expires=min(row['expires'], self.clock() + 60))
            return {'ok': True, 'redirect_uri': REDIRECT + '?' + urlencode({'state': row['state'], 'code': code})}

    def exchange(self, body, addr, origin):
        if body.get('redirect_uri') != REDIRECT:
            raise PairingError('Invalid app callback.')
        code = body.get('code', '')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code):
            raise PairingError('Invalid app authorization code.')
        expected = challenge(body.get('code_verifier'))
        with self.lock:
            self._prune()
            self._limit(addr)
            key = hashlib.sha256(code.encode()).hexdigest()
            row = self.codes.get(key)
            if (not row or row['addr'] != addr or row['origin'] != origin
                    or not hmac.compare_digest(expected, row['challenge'])):
                raise PairingError('App sign-in expired or could not be verified.', 403)
            del self.codes[key]  # Consume atomically after successful verification.
            return row['actor'], row['credential'], row['scope']
