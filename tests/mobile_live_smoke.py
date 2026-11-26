"""One-shot loopback TEST integration; creates and revokes its own fixture key."""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'webconsole'), str(ROOT / 'tests')]
from test_passkey_auth import Authenticator
from passkey_auth import Passkeys
from mobile_pairing import REDIRECT, challenge

origin = 'http://localhost:18499'
def request(method, path, body=None, cookie='', csrf=''):
    client = http.client.HTTPConnection('localhost', 18499, timeout=15)
    client.request(method, path, json.dumps(body) if body is not None else None,
                   {'Origin': origin, 'Content-Type': 'application/json', 'Cookie': cookie, 'X-CSRF-Token': csrf})
    response = client.getresponse()
    raw = response.read()
    status, headers = response.status, dict(response.getheaders())
    client.close()
    return status, headers, json.loads(raw)

assert request('GET', '/api/auth/config')[2]['test_mode'] is True
db = ROOT / 'test-runtime/panel-auth' / ('passkeys-' + hashlib.sha256(origin.encode()).hexdigest()[:16] + '.sqlite3')
store = Passkeys(db, origin)
auth = Authenticator(origin)
fingerprint = None
try:
    status, headers, options = request('POST', '/api/auth/register/begin', {})
    assert status == 200
    status, _, result = request('POST', '/api/auth/register/complete',
        {'credential': auth.response(options, True), 'label': 'Automated TEST fixture - revoked after verification'},
        headers['Set-Cookie'].split(';')[0])
    assert status == 200
    fingerprint = store.approve(result['pending_id'])
    _, headers, options = request('POST', '/api/auth/login/begin', {})
    status, headers, login = request('POST', '/api/auth/login/complete',
        {'credential': auth.response(options)}, headers['Set-Cookie'].split(';')[0])
    assert status == 200
    cookie = headers['Set-Cookie'].split(';')[0]
    verifier = secrets.token_urlsafe(32)
    status, _, pairing = request('POST', '/api/mobile/v1/pairings', dict(code_challenge=challenge(verifier),
        code_challenge_method='S256', state=secrets.token_urlsafe(32), redirect_uri=REDIRECT))
    assert status == 201
    request_id = parse_qs(urlsplit(pairing['authorization_url']).query)['request'][0]
    status, _, consent = request('POST', '/api/mobile/v1/consent', dict(request=request_id, approve=True), cookie, login['csrf'])
    assert status == 200
    code = parse_qs(urlsplit(consent['redirect_uri']).query)['code'][0]
    status, headers, native = request('POST', '/api/mobile/v1/exchange', dict(code=code, code_verifier=verifier, redirect_uri=REDIRECT))
    assert status == 200
    mobile = headers['Set-Cookie'].split(';')[0]
    status, _, stats = request('GET', '/api/stats', cookie=mobile)
    assert status == 200 and stats['ts'] > 0 and stats['ram']['total'] > 0 and stats['disks']
    assert request('POST', '/api/action', {'action': 'reboot'}, mobile, native['csrf'])[0] == 403
    assert request('POST', '/api/logout', {}, mobile, native['csrf'])[0] == 200
    assert request('GET', '/api/stats', cookie=mobile)[0] == 401
    print(json.dumps(dict(result='PASS', source='isolated loopback TEST, real psutil readings',
        cpu_pct=stats['cpu']['pct'], ram_pct=stats['ram']['pct'], disks=len(stats['disks']), processes=len(stats['procs']),
        host_actions='denied', logout='revoked', physical_android='not tested')))
finally:
    if fingerprint:
        store.revoke(fingerprint)
