"""TEST credentials only: real WebAuthn signatures and owner consent over HTTP."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webconsole'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mobile_pairing import Pairings, PairingError, REDIRECT, challenge, match_code
import test_passkey_auth as passkey_fixtures
from test_passkey_auth import Authenticator


class PairingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.pairings = Pairings(clock=lambda: self.now, capacity=3)
        self.origin, self.addr = 'https://test.tail.ts.net', '100.64.1.1'
        self.verifier = secrets.token_urlsafe(32)
        self.body = dict(code_challenge=challenge(self.verifier), code_challenge_method='S256',
                         redirect_uri=REDIRECT, state=secrets.token_urlsafe(32))

    def begin(self):
        result = self.pairings.begin(self.body, self.addr, self.origin)
        request_id = parse_qs(urlsplit(result['authorization_url']).query)['request'][0]
        return request_id, result

    def approved(self):
        request_id, _ = self.begin()
        result = self.pairings.consent(request_id, self.addr, self.origin, 'owner', 'passkey:test', True)
        code = parse_qs(urlsplit(result['redirect_uri']).query)['code'][0]
        return dict(code=code, code_verifier=self.verifier, redirect_uri=REDIRECT)

    def test_exact_callback_strong_state_and_s256_required(self):
        for changes in ({'redirect_uri': 'https://evil.test'}, {'code_challenge_method': 'plain'},
                        {'state': 'short'}, {'code_challenge': '+' * 43}):
            with self.subTest(changes=changes), self.assertRaises(PairingError):
                self.pairings.begin(self.body | changes, self.addr, self.origin)

    def test_code_matches_challenge_and_request_has_no_credentials(self):
        request_id, result = self.begin()
        self.assertEqual(result['confirmation_code'], match_code(self.body['code_challenge']))
        self.assertEqual(self.pairings.describe(request_id, self.addr, self.origin)['scope'], 'monitoring:read')
        self.assertNotIn('code_verifier', json.dumps(self.pairings.pending))
        self.assertNotIn('credential', result)

    def test_deny_expiry_wrong_address_and_wrong_origin(self):
        request_id, _ = self.begin()
        for addr, origin in [('100.64.1.2', self.origin), (self.addr, 'https://other.tail.ts.net')]:
            with self.assertRaises(PairingError): self.pairings.describe(request_id, addr, origin)
        self.pairings.consent(request_id, self.addr, self.origin, 'owner', 'passkey:test', False)
        with self.assertRaises(PairingError): self.pairings.describe(request_id, self.addr, self.origin)
        request_id, _ = self.begin(); self.now += 601
        with self.assertRaises(PairingError): self.pairings.describe(request_id, self.addr, self.origin)

    def test_wrong_verifier_cannot_redeem_and_valid_code_is_single_use(self):
        body = self.approved()
        with self.assertRaises(PairingError):
            self.pairings.exchange(body | {'code_verifier': 'a' * 43}, self.addr, self.origin)
        with self.assertRaises(PairingError): self.pairings.exchange(body, '100.64.1.2', self.origin)
        self.assertEqual(self.pairings.exchange(body, self.addr, self.origin), ('owner', 'passkey:test'))
        with self.assertRaises(PairingError): self.pairings.exchange(body, self.addr, self.origin)

    def test_approved_code_expires_and_parallel_exchange_has_one_winner(self):
        body = self.approved(); self.now += 61
        with self.assertRaises(PairingError): self.pairings.exchange(body, self.addr, self.origin)
        body = self.approved()
        def redeem(_):
            try: self.pairings.exchange(body, self.addr, self.origin); return True
            except PairingError: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(redeem, range(8))), 1)

    def test_capacity_and_rate_limits_are_bounded(self):
        for _ in range(3): self.begin()
        with self.assertRaises(PairingError) as error: self.begin()
        self.assertEqual(error.exception.status, 429)
        self.assertLessEqual(len(self.pairings.pending), 3)
        self.now += 601
        self.begin()


class MobileHTTPTests(unittest.TestCase):
    def setUp(self):
        passkey_fixtures.PasskeyHTTPTests.setUp(self)
        self.saved_mobile = self.wc._mobile_pairings
        self.wc._mobile_pairings = Pairings()
        self.origin = 'https://android-test.tail.ts.net'
        self.wc.STATE.update(passkey_origin=self.origin, trusted_proxy_origin=self.origin,
                             passkey_local_test=False, mobile_pairing_enabled=True,
                             passkey_db=str(Path(self.temp.name) / 'mobile-proxy.db'))
        self.store = self.wc.passkey_store()
        self.proxy = {'Host': 'android-test.tail.ts.net', 'Origin': self.origin,
                      'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '100.64.1.1'}

    def tearDown(self):
        self.wc._mobile_pairings = self.saved_mobile
        passkey_fixtures.PasskeyHTTPTests.tearDown(self)

    def request(self, method, path, body=None, cookie='', headers=None):
        return passkey_fixtures.PasskeyHTTPTests.request(self, method, path, body, cookie, self.proxy | (headers or {}))

    def owner(self, actor='owner'):
        auth = Authenticator(self.origin)
        _, headers, options = self.request('POST', '/api/auth/register/begin', {})
        status, _, result = self.request('POST', '/api/auth/register/complete',
            {'credential': auth.response(options, True)}, headers['Set-Cookie'].split(';')[0])
        self.assertEqual(status, 200)
        # Approval is ONLY for this generated fixture key, in a temporary TEST DB.
        fingerprint = self.store.approve(result['pending_id'], actor)
        _, headers, options = self.request('POST', '/api/auth/login/begin', {})
        status, headers, result = self.request('POST', '/api/auth/login/complete',
            {'credential': auth.response(options)}, headers['Set-Cookie'].split(';')[0])
        self.assertEqual(status, 200)
        return headers['Set-Cookie'].split(';')[0], result['csrf'], fingerprint

    def pairing(self):
        verifier = secrets.token_urlsafe(32)
        body = dict(code_challenge=challenge(verifier), code_challenge_method='S256',
                    state=secrets.token_urlsafe(32), redirect_uri=REDIRECT)
        status, _, data = self.request('POST', '/api/mobile/v1/pairings', body)
        self.assertEqual(status, 201)
        request_id = parse_qs(urlsplit(data['authorization_url']).query)['request'][0]
        return verifier, request_id

    def test_full_signed_passkey_consent_exchange_monitoring_revoke(self):
        cookie, csrf, fingerprint = self.owner()
        verifier, request_id = self.pairing()
        path = '/api/mobile/v1/request?request=' + request_id
        self.assertEqual(self.request('GET', path)[0], 401)
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 200)
        consent = dict(request=request_id, approve=True)
        self.assertEqual(self.request('POST', '/api/mobile/v1/consent', consent, cookie)[0], 403)
        status, _, data = self.request('POST', '/api/mobile/v1/consent', consent, cookie, {'X-CSRF-Token': csrf})
        self.assertEqual(status, 200)
        code = parse_qs(urlsplit(data['redirect_uri']).query)['code'][0]
        exchange = dict(code=code, code_verifier=verifier, redirect_uri=REDIRECT)
        status, headers, data = self.request('POST', '/api/mobile/v1/exchange', exchange)
        self.assertEqual(status, 200)
        self.assertIn('; Secure', headers['Set-Cookie']); self.assertIn('HttpOnly', headers['Set-Cookie'])
        mobile_cookie = headers['Set-Cookie'].split(';')[0]
        self.assertNotEqual(cookie, mobile_cookie)
        self.assertEqual(data['scope'], 'monitoring:read')
        self.assertEqual(self.request('GET', '/api/stats', cookie=mobile_cookie)[0], 200)
        self.assertEqual(self.request('GET', '/api/setup', cookie=mobile_cookie)[0], 403)
        self.assertEqual(self.request('GET', '/api/mobile/v1/sessions', cookie=mobile_cookie)[0], 403)
        self.assertEqual(self.request('POST', '/api/action', {'action': 'reboot'}, mobile_cookie,
            {'X-CSRF-Token': data['csrf']})[0], 403)
        self.assertEqual(self.request('POST', '/api/mobile/v1/exchange', exchange)[0], 403)
        _, _, sessions = self.request('GET', '/api/mobile/v1/sessions', cookie=cookie)
        self.assertEqual(len(sessions['items']), 1)
        self.assertNotIn(mobile_cookie.split('=')[1], json.dumps(sessions))
        self.assertEqual(self.request('POST', '/api/mobile/v1/revoke', {'id': sessions['items'][0]['id']},
            cookie, {'X-CSRF-Token': csrf})[0], 200)
        self.assertEqual(self.request('GET', '/api/stats', cookie=mobile_cookie)[0], 401)

    def test_disabled_origin_no_consent_and_revoked_passkey(self):
        self.wc.STATE['mobile_pairing_enabled'] = False
        self.assertFalse(self.request('GET', '/health')[2]['mobile_pairing'])
        self.assertEqual(self.request('POST', '/api/mobile/v1/pairings', {})[0], 404)
        self.wc.STATE['mobile_pairing_enabled'] = True
        cookie, csrf, fingerprint = self.owner()
        verifier, request_id = self.pairing()
        self.assertEqual(self.request('POST', '/api/mobile/v1/consent', {'request': request_id, 'approve': True},
            cookie, {'Origin': 'https://evil.test', 'X-CSRF-Token': csrf})[0], 421)
        _, _, data = self.request('POST', '/api/mobile/v1/consent', {'request': request_id, 'approve': True},
            cookie, {'X-CSRF-Token': csrf})
        self.store.revoke(fingerprint)
        code = parse_qs(urlsplit(data['redirect_uri']).query)['code'][0]
        self.assertEqual(self.request('POST', '/api/mobile/v1/exchange',
            dict(code=code, code_verifier=verifier, redirect_uri=REDIRECT))[0], 403)

    def test_operator_cannot_approve_and_mobile_can_sign_out(self):
        cookie, csrf, _ = self.owner('operator:test')
        _, request_id = self.pairing()
        self.assertEqual(self.request('POST', '/api/mobile/v1/consent',
            {'request': request_id, 'approve': True}, cookie, {'X-CSRF-Token': csrf})[0], 403)
        cookie, csrf, _ = self.owner()
        verifier, request_id = self.pairing()
        _, _, data = self.request('POST', '/api/mobile/v1/consent', {'request': request_id, 'approve': True},
                                 cookie, {'X-CSRF-Token': csrf})
        code = parse_qs(urlsplit(data['redirect_uri']).query)['code'][0]
        _, headers, result = self.request('POST', '/api/mobile/v1/exchange',
            dict(code=code, code_verifier=verifier, redirect_uri=REDIRECT))
        mobile = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('POST', '/api/logout', {}, mobile)[0], 403)
        self.assertEqual(self.request('POST', '/api/logout', {}, mobile, {'X-CSRF-Token': result['csrf']})[0], 200)
        self.assertEqual(self.request('GET', '/api/stats', cookie=mobile)[0], 401)


if __name__ == '__main__': unittest.main()
