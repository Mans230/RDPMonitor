"""Real ES256 signatures and none attestation; no verification mocks."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webconsole'))
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (AttestationObject, AttestedCredentialData,
                           AuthenticatorData, CollectedClientData)
from passkey_auth import Passkeys, PasskeyError
from proxy_security import serve_context, ProxyRejected


class Authenticator:
    def __init__(self, origin):
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = os.urandom(32)
        self.credential = AttestedCredentialData.create(bytes(16), self.id,
            ES256.from_cryptography_key(self.key.public_key()))
        self.handle = None

    def response(self, options, register=False, *, origin=None, uv=True, counter=1, cross_origin=False):
        p = options['publicKey']
        origin = origin or self.origin
        client = CollectedClientData.create('webauthn.create' if register else 'webauthn.get',
            p['challenge'], origin, cross_origin=cross_origin)
        rp = p['rp']['id'] if register else p['rpId']
        flags = AuthenticatorData.FLAG.UP
        if uv: flags |= AuthenticatorData.FLAG.UV
        if register:
            flags |= AuthenticatorData.FLAG.AT
            self.handle = websafe_decode(p['user']['id'])
        auth = AuthenticatorData.create(hashlib.sha256(rp.encode()).digest(), flags,
            0 if register else counter, self.credential if register else b'')
        result = {'clientDataJSON': websafe_encode(client)}
        if register:
            result['attestationObject'] = websafe_encode(AttestationObject.create('none', auth, {}))
        else:
            result.update(authenticatorData=websafe_encode(auth),
                signature=websafe_encode(self.key.sign(auth + client.hash, ec.ECDSA(hashes.SHA256()))),
                userHandle=websafe_encode(self.handle))
        return {'id': websafe_encode(self.id), 'rawId': websafe_encode(self.id),
                'type': 'public-key', 'response': result}


class PasskeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = 1000
        self.store = Passkeys(Path(self.temp.name) / 'keys.db', 'https://host.tail.ts.net', lambda: self.clock)
        self.auth = Authenticator(self.store.origin)

    def enroll(self, actor='owner'):
        options, cookie = self.store.begin('register', '100.64.1.1')
        result = self.store.complete('register', cookie, '100.64.1.1', self.auth.response(options, True))
        self.assertFalse(result['approved'])
        self.assertFalse(self.store.has_keys())
        return self.store.approve(result['pending_id'], actor)

    def test_enrollment_approval_login_revocation_and_replay(self):
        fingerprint = self.enroll()
        options, cookie = self.store.begin('login', '100.64.1.1')
        response = self.auth.response(options)
        result = self.store.complete('login', cookie, '100.64.1.1', response)
        self.assertEqual(result, {'actor': 'owner', 'credential_hash': 'passkey:' + fingerprint})
        with self.assertRaises(PasskeyError):
            self.store.complete('login', cookie, '100.64.1.1', response)
        self.store.revoke(fingerprint)
        self.assertFalse(self.store.active(fingerprint, 'owner'))
        with self.assertRaises(PasskeyError): self.store.begin('login', '100.64.1.1')

    def test_wrong_origin_missing_uv_bad_signature_and_counter_are_rejected(self):
        self.enroll()
        for kwargs in ({'origin': 'https://attacker.test'}, {'uv': False}, {}):
            options, cookie = self.store.begin('login', '100.64.1.1')
            response = self.auth.response(options, **kwargs)
            if not kwargs: response['response']['signature'] = websafe_encode(b'bad signature')
            with self.assertRaises(PasskeyError):
                self.store.complete('login', cookie, '100.64.1.1', response)
        for count in (2, 2):
            options, cookie = self.store.begin('login', '100.64.1.1')
            response = self.auth.response(options, counter=count)
            if count == 2 and not hasattr(self, 'logged_in'):
                self.store.complete('login', cookie, '100.64.1.1', response)
                self.logged_in = True
            else:
                with self.assertRaises(PasskeyError):
                    self.store.complete('login', cookie, '100.64.1.1', response)

    def test_address_expiry_pending_expiry_and_origin_change(self):
        options, cookie = self.store.begin('register', 'a')
        response = self.auth.response(options, True)
        with self.assertRaises(PasskeyError): self.store.complete('register', cookie, 'b', response)
        self.clock += 121
        with self.assertRaises(PasskeyError): self.store.complete('register', cookie, 'a', response)
        options, cookie = self.store.begin('register', 'a')
        result = self.store.complete('register', cookie, 'a', self.auth.response(options, True))
        self.clock += 601
        with self.assertRaises(PasskeyError): self.store.approve(result['pending_id'])
        with self.assertRaises(PasskeyError): Passkeys(self.store.path, 'https://other.tail.ts.net')

    def test_operator_role_is_assigned_locally(self):
        self.enroll('operator:alice')
        options, cookie = self.store.begin('login', 'a')
        result = self.store.complete('login', cookie, 'a', self.auth.response(options))
        self.assertEqual(result['actor'], 'operator:alice')

    def test_pending_registration_login_requests_approval_not_another_passkey(self):
        options, cookie = self.store.begin('register', 'a')
        result = self.store.complete('register', cookie, 'a', self.auth.response(options, True))
        with self.assertRaisesRegex(PasskeyError, 'waiting for approval') as error:
            self.store.begin('login', 'a')
        self.assertIn('Do not create another', str(error.exception))
        self.store.approve(result['pending_id'])
        options, cookie = self.store.begin('login', 'a')
        self.assertEqual(self.store.complete('login', cookie, 'a', self.auth.response(options))['actor'], 'owner')

    def test_challenge_queue_is_bounded(self):
        for _ in range(8): self.store.begin('register', 'a')
        with self.assertRaises(PasskeyError): self.store.begin('register', 'a')

    def test_registration_requires_correct_origin_and_device_verification(self):
        for kwargs in ({'uv': False}, {'origin': 'https://bad.test'}, {'cross_origin': True}):
            options, cookie = self.store.begin('register', 'a')
            with self.assertRaises(PasskeyError):
                self.store.complete('register', cookie, 'a', self.auth.response(options, True, **kwargs))
        self.assertEqual(self.store.pending(), [])

    def test_wrong_user_handle_and_cross_origin_assertion_are_rejected(self):
        self.enroll()
        for change in ('handle', 'cross_origin'):
            options, cookie = self.store.begin('login', 'a')
            response = self.auth.response(options, cross_origin=change == 'cross_origin')
            if change == 'handle': response['response']['userHandle'] = websafe_encode(b'wrong user')
            with self.assertRaises(PasskeyError): self.store.complete('login', cookie, 'a', response)

    def test_authenticators_without_counters_can_sign_multiple_fresh_challenges(self):
        self.enroll()
        for _ in range(2):
            options, cookie = self.store.begin('login', 'a')
            self.store.complete('login', cookie, 'a', self.auth.response(options, counter=0))


class ProxyTests(unittest.TestCase):
    def test_only_exact_local_serve_context_is_accepted(self):
        args = dict(bind='127.0.0.1', configured_origin='https://host.tail.ts.net',
            peer='127.0.0.1', host='host.tail.ts.net', forwarded_proto='https',
            forwarded_for='100.64.1.1', origin='https://host.tail.ts.net', method='POST')
        self.assertEqual(serve_context(**args).client_ip, '100.64.1.1')
        for change in ({'bind': '0.0.0.0'}, {'peer': '199.47.241.111'}, {'host': 'attacker.test'},
                       {'forwarded_proto': 'http'}, {'forwarded_for': '100.64.1.1, 1.2.3.4'},
                       {'forwarded_for': '1.2.3.4'}, {'origin': None}, {'origin': 'https://attacker.test'}):
            with self.subTest(change=change), self.assertRaises(ProxyRejected):
                serve_context(**(args | change))


class PasskeyHTTPTests(unittest.TestCase):
    def setUp(self):
        os.environ['RDPWC_NO_INIT'] = '1'
        import RDPWebConsole as wc
        self.wc = wc
        self.saved = {name: getattr(wc, name) for name in ('STATE', 'BIND', 'AUDIT_FILE', 'USAGE_FILE')}
        self.old_token = os.environ.get('RDPWC_TOKEN')
        os.environ['RDPWC_TOKEN'] = 'test-internal-secret'
        self.temp = tempfile.TemporaryDirectory()
        wc.BIND = '127.0.0.1'
        wc._sessions.clear(); wc._login_attempts.clear()
        wc.AUDIT_FILE = str(Path(self.temp.name) / 'audit.jsonl')
        wc.USAGE_FILE = str(Path(self.temp.name) / 'usage.jsonl')
        self.server = wc.LimitedThreadingHTTPServer(('127.0.0.1', 0), wc.Handler)
        self.port = self.server.server_address[1]
        self.origin = f'http://localhost:{self.port}'
        wc.STATE = dict(auth_mode='passkey', passkey_origin=self.origin, passkey_local_test=True,
                        passkey_db=str(Path(self.temp.name) / 'keys.db'))
        self.store = wc.passkey_store()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        for name, value in self.saved.items(): setattr(self.wc, name, value)
        self.wc._passkey_store = None
        if self.old_token is None: os.environ.pop('RDPWC_TOKEN', None)
        else: os.environ['RDPWC_TOKEN'] = self.old_token
        self.temp.cleanup()

    def request(self, method, path, body=None, cookie='', headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Host': f'localhost:{self.port}', 'Origin': self.origin, 'Cookie': cookie,
             'Content-Type': 'application/json'} | (headers or {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result[0], result[1], json.loads(result[2]) if result[2] else {}

    def test_http_enroll_approve_login_csrf_operator_permissions_and_revoke(self):
        auth = Authenticator(self.origin)
        _, h, options = self.request('POST', '/api/auth/register/begin', {})
        cookie = h['Set-Cookie'].split(';')[0]
        status, _, result = self.request('POST', '/api/auth/register/complete',
            {'credential': auth.response(options, True)}, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(self.request('GET', '/api/session')[0], 401)
        fingerprint = self.store.approve(result['pending_id'], 'operator:alice')
        _, h, options = self.request('POST', '/api/auth/login/begin', {})
        status, h, login = self.request('POST', '/api/auth/login/complete',
            {'credential': auth.response(options)}, h['Set-Cookie'].split(';')[0])
        self.assertEqual(status, 200)
        self.assertEqual(login['actor'], 'operator:alice')
        cookie = h['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly; SameSite=Strict', h['Set-Cookie'])
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 200)
        self.assertEqual(self.request('POST', '/api/logout', {}, cookie)[0], 403)
        self.assertEqual(self.request('GET', '/api/setup', cookie=cookie)[0], 403)
        self.store.revoke(fingerprint)
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 401)

    def test_token_links_and_untrusted_origin_cannot_bypass_passkeys(self):
        self.assertEqual(self.request('POST', '/api/login', {'token': 'test-internal-secret'})[0], 403)
        self.assertEqual(self.request('POST', '/api/auth/register/begin', {}, headers={'Origin': 'https://bad.test'})[0], 403)
        import hmac
        import time
        exp = str(int(time.time()) + 60)
        otp = hmac.new(b'test-internal-secret', exp.encode(), hashlib.sha256).hexdigest()
        c = http.client.HTTPConnection('127.0.0.1', self.port)
        c.request('GET', '/?otp=' + otp + '&exp=' + exp)
        r = c.getresponse(); r.read()
        self.assertEqual(r.status, 200)
        self.assertIsNone(r.getheader('Set-Cookie'))
        c.close()

    def test_proxy_secure_cookie_and_host_policy(self):
        wc = self.wc
        wc.STATE.update(trusted_proxy_origin='https://host.tail.ts.net',
                        passkey_origin='https://host.tail.ts.net',
                        passkey_db=str(Path(self.temp.name) / 'proxy.db'), passkey_local_test=False)
        self.assertEqual(self.request('GET', '/api/auth/config')[0], 421)
        headers = {'Host': 'host.tail.ts.net', 'Origin': 'https://host.tail.ts.net',
                   'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '100.64.1.1'}
        status, h, _ = self.request('POST', '/api/auth/register/begin', {}, headers=headers)
        self.assertEqual(status, 200)
        self.assertIn('; Secure', h['Set-Cookie'])
        self.assertIn('Strict-Transport-Security', h)
        auth = Authenticator('https://host.tail.ts.net')
        # Begin again to retain the actual browser options for the full login.
        _, h, options = self.request('POST', '/api/auth/register/begin', {}, headers=headers)
        _, _, result = self.request('POST', '/api/auth/register/complete',
            {'credential': auth.response(options, True)}, h['Set-Cookie'].split(';')[0], headers)
        fingerprint = wc.passkey_store().approve(result['pending_id'])
        _, h, options = self.request('POST', '/api/auth/login/begin', {}, headers=headers)
        status, h, login = self.request('POST', '/api/auth/login/complete',
            {'credential': auth.response(options)}, h['Set-Cookie'].split(';')[0], headers)
        self.assertEqual(status, 200)
        self.assertIn('; Secure', h['Set-Cookie'])
        cookie = h['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie, headers=headers)[0], 200)
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie,
            headers=headers | {'X-Forwarded-For': '100.64.1.2'})[0], 401)
        # Login again to check immediate owner-session revocation too.
        _, h, options = self.request('POST', '/api/auth/login/begin', {}, headers=headers)
        _, h, _ = self.request('POST', '/api/auth/login/complete',
            {'credential': auth.response(options, counter=2)}, h['Set-Cookie'].split(';')[0], headers)
        cookie = h['Set-Cookie'].split(';')[0]
        wc.passkey_store().revoke(fingerprint)
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie, headers=headers)[0], 401)
        self.assertEqual(self.request('POST', '/api/auth/register/begin', {}, headers=headers | {'Origin': 'https://bad.test'})[0], 421)
