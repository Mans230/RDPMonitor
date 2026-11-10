import unittest
from unittest import mock
import rdp_monitor as rm
from private_panel import validated_url

PRIVATE = {'bind':'127.0.0.1','auth_mode':'passkey', 'trusted_proxy_origin':'https://server.tail.ts.net', 'passkey_origin':'https://server.tail.ts.net'}

class PrivatePanelBotTests(unittest.TestCase):
    def test_panel_sends_only_private_link_and_never_decrypts_credentials(self):
        with mock.patch.object(rm,'private_panel_settings',return_value=PRIVATE), mock.patch.object(rm,'webconsole_token') as token, mock.patch.object(rm,'panel_hosts') as hosts, mock.patch.object(rm,'send_url_buttons') as buttons, mock.patch.object(rm,'send_message'):
            rm.send_panel_info()
            self.assertEqual(rm.panel_login_url('199.47.241.111'),'https://server.tail.ts.net/')
            rm.send_panel_status()
        token.assert_not_called(); hosts.assert_not_called()
        text,rows=buttons.call_args.args
        self.assertEqual(rows,[[('Open private panel','https://server.tail.ts.net/')],[('Panel status','run:/panelstatus')]])
        self.assertIn('Tailscale',text); self.assertIn('passkey',text)
        self.assertNotIn('otp=',str(buttons.call_args))

    def test_all_retired_public_commands_are_disabled_even_after_confirmation(self):
        for args in ('direct','open','any','public','on','off','allow 1.2.3.4','direct confirm','on confirm'):
            with self.subTest(args=args), mock.patch.object(rm,'_run_webconsole_cli') as cli, mock.patch.object(rm,'send_message') as message, mock.patch.object(rm,'send_buttons') as buttons:
                rm.handle_command('/panelremote '+args)
                cli.assert_not_called(); buttons.assert_not_called()
                self.assertIn('Tailscale',message.call_args.args[0])

    def test_old_token_commands_callbacks_and_setup_cannot_disclose_a_token(self):
        with mock.patch.object(rm,'webconsole_token') as token, mock.patch.object(rm,'dpapi_unprotect') as decrypt, mock.patch.object(rm,'send_message') as message:
            for command in ('/paneltoken','/token'):
                rm.handle_command(command)
                self.assertIn('no longer sent',message.call_args.args[0])
            rm.send_panel_token()
            ok,result=rm._dispatch_panel('setup_token',{})
            self.assertFalse(ok)
            self.assertNotIn('token_enc',str(result))
        token.assert_not_called(); decrypt.assert_not_called()

    def test_missing_or_unsafe_config_has_no_public_or_token_fallback(self):
        invalid=[{},PRIVATE|{'auth_mode':'token'},PRIVATE|{'bind':'0.0.0.0'},PRIVATE|{'passkey_origin':'https://different.tail.ts.net'}]
        for origin in ('http://server.tail.ts.net','https://server.tail.ts.net/?otp=secret','https://secret@server.tail.ts.net','https://199.47.241.111:8399','https://server.tail.ts.net.evil.test','https://server.tail.ts.net#secret','https://server.tail.ts.net:443','https://server..ts.net'):
            invalid.append(PRIVATE|{'trusted_proxy_origin':origin,'passkey_origin':origin})
        for state in invalid:
            with self.subTest(state=state):
                self.assertIsNone(validated_url(state))
                with mock.patch.object(rm,'private_panel_settings',return_value=state), mock.patch.object(rm,'webconsole_token') as token, mock.patch.object(rm,'send_message') as message, mock.patch.object(rm,'send_url_buttons') as buttons:
                    rm.send_panel_info()
                    buttons.assert_not_called(); token.assert_not_called()
                    self.assertIn('not configured',message.call_args.args[0])

    def test_token_commands_are_hidden_from_menu(self):
        from bot_catalog import telegram_menu,help_text
        commands={item['command'] for item in telegram_menu(rm.COMMAND_INFO)}
        self.assertNotIn('paneltoken',commands); self.assertNotIn('token',commands)
        self.assertNotIn('/paneltoken',help_text(rm.COMMAND_INFO))
