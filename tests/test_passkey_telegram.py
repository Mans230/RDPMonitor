from pathlib import Path
import tempfile
import unittest
from unittest import mock

import rdp_monitor as rm
from test_passkey_auth import Authenticator
from webconsole.passkey_auth import Passkeys, PasskeyError


class TelegramPasskeyApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.store = Passkeys(Path(self.temp.name) / 'keys.db', 'https://server.tail.ts.net', lambda: self.now)
        self.auth = Authenticator(self.store.origin)
        options, nonce = self.store.begin('register', 'tailnet-client')
        self.request = self.store.complete('register', nonce, 'tailnet-client',
                                           self.auth.response(options, True), 'My <phone>')['pending_id']
        self.patches = [mock.patch.object(rm, 'panel_passkeys', return_value=self.store),
                        mock.patch.object(rm, 'private_panel_url', return_value=self.store.origin + '/'),
                        mock.patch.object(rm, 'config', {'chat_id': '101', 'trusted_user_ids': ['202']}),
                        mock.patch.object(rm, 'audit_record'),
                        mock.patch.object(rm, 'tg_api', return_value={'ok': True})]
        for patch in self.patches:
            patch.start(); self.addCleanup(patch.stop)

    def callback(self, op='a', user=101, chat=101, kind='private'):
        return {'id': 'callback-fixture', 'from': {'id': user},
                'data': 'pk:' + op + ':' + self.request,
                'message': {'message_id': 7, 'chat': {'id': chat, 'type': kind}}}

    def test_notification_goes_only_to_primary_owner_once_with_matching_buttons(self):
        rm.notify_panel_passkeys(); rm.notify_panel_passkeys()
        calls = [c for c in rm.tg_api.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs['chat_id'], '101')
        self.assertIn('My &lt;phone&gt;', calls[0].kwargs['text'])
        buttons = calls[0].kwargs['reply_markup']['inline_keyboard'][0]
        self.assertEqual(buttons[0]['callback_data'], 'pk:a:' + self.request)
        self.assertEqual(buttons[1]['callback_data'], 'pk:r:' + self.request)
        self.assertFalse(self.store.has_keys())

    def test_owner_approval_allows_login_without_creating_another_key(self):
        rm.handle_panel_passkey_callback(self.callback())
        self.assertTrue(self.store.has_keys())
        options, nonce = self.store.begin('login', 'tailnet-client')
        result = self.store.complete('login', nonce, 'tailnet-client', self.auth.response(options))
        self.assertEqual(result['actor'], 'owner')
        rm.handle_panel_passkey_callback(self.callback())  # Replay cannot approve a second time.
        self.assertIn('expired or was already handled', rm.tg_api.call_args.kwargs['text'])

    def test_trusted_operator_different_chat_and_group_callbacks_cannot_approve(self):
        for args in ({'user': 202}, {'chat': 202}, {'kind': 'group'}, {'user': 999}):
            with self.subTest(args=args):
                rm.handle_panel_passkey_callback(self.callback(**args))
                self.assertFalse(self.store.has_keys())
                self.assertIn('Only the primary owner', rm.tg_api.call_args.kwargs['text'])

    def test_rejection_and_expiry_never_create_credentials(self):
        rm.handle_panel_passkey_callback(self.callback('r'))
        self.assertFalse(self.store.has_keys()); self.assertEqual(self.store.pending(), [])
        with self.assertRaises(PasskeyError): self.store.approve(self.request)

    def test_expired_request_cannot_be_approved_from_an_old_button(self):
        self.now += 601
        rm.handle_panel_passkey_callback(self.callback())
        self.assertFalse(self.store.has_keys())
        self.assertIn('expired', rm.tg_api.call_args.kwargs['text'])

    def test_failed_send_and_abandoned_lease_can_retry_without_duplicate_claims(self):
        first = self.store.claim_notifications()
        self.assertEqual(len(first), 1)
        self.assertEqual(self.store.claim_notifications(), [])
        self.now += 61
        self.assertEqual(len(self.store.claim_notifications()), 1)
        self.store.notification_result(self.request, False)
        rm.tg_api.return_value = {'ok': False}
        rm.notify_panel_passkeys()
        rm.tg_api.return_value = {'ok': True}
        rm.notify_panel_passkeys()
        self.assertEqual(self.store.claim_notifications(), [])

    def test_group_primary_chat_sends_no_approval_message(self):
        rm.config['chat_id'] = '-123'
        rm.notify_panel_passkeys()
        rm.tg_api.assert_not_called()
