import json
import os
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webconsole"))
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from private_panel import monitor_health
from suite_update import WindowsRuntime, allowed_path, REQUIRED


class PrivateRolloutTests(unittest.TestCase):
    def test_unconfigured_normal_startup_never_starts_legacy_token_server(self):
        import RDPWebConsole as wc
        with mock.patch.object(wc, 'STATE', {'bind': '0.0.0.0'}), \
                mock.patch.object(wc, 'acquire_instance_lock') as lock, \
                mock.patch('sys.argv', ['RDPWebConsole.py']), mock.patch('builtins.print'):
            self.assertEqual(wc.main(), 1)
            lock.assert_not_called()

    def test_private_endpoint_is_used_by_suite_status_and_open(self):
        import rdp_suite
        state = {'bind': '127.0.0.1', 'auth_mode': 'passkey',
                 'trusted_proxy_origin': 'https://server.tail.ts.net',
                 'passkey_origin': 'https://server.tail.ts.net'}
        with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(state))):
            self.assertEqual(rdp_suite._webconsole_endpoint(), ('https://server.tail.ts.net/', ''))

    def test_private_panel_refuses_a_public_bind_at_startup(self):
        import RDPWebConsole as wc
        with mock.patch.object(wc, 'STATE', {'auth_mode': 'passkey'}), \
                mock.patch.object(wc, 'BIND', '0.0.0.0'), \
                mock.patch.object(wc, 'acquire_instance_lock', return_value=True), \
                mock.patch.object(wc, 'harden_private_storage') as harden, \
                mock.patch('sys.argv', ['RDPWebConsole.py']), mock.patch('builtins.print'):
            self.assertEqual(wc.main(), 1)
            harden.assert_not_called()

    def test_local_configuration_validates_before_saving_and_preserves_settings(self):
        from webconsole.private_cli import execute
        with tempfile.TemporaryDirectory() as folder:
            saved = []
            wc = SimpleNamespace(STATE={'port': 8399, 'exec_enabled': False}, BASE_DIR=folder,
                STATE_FILE=str(Path(folder) / 'state.json'), harden_private_storage=lambda: True,
                harden_file=lambda p: True, atomic_write=lambda p, s: saved.append(s))
            with mock.patch('builtins.print'):
                with self.assertRaises(ValueError): execute(wc, ['private-enable', 'https://evil.test'])
                self.assertFalse(saved)
                self.assertEqual(execute(wc, ['private-enable', 'https://server.tail.ts.net']), 0)
            self.assertEqual(saved[0]['bind'], '127.0.0.1')
            self.assertEqual(saved[0]['auth_mode'], 'passkey')
            self.assertEqual(saved[0]['port'], 8399)
            self.assertFalse(saved[0]['exec_enabled'])
            self.assertNotIn('token', saved[0])

    def test_private_updater_health_never_uses_a_login_token(self):
        import rdp_monitor
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'webconsole').mkdir()
            (root / 'suite_user.pid.json').write_text(json.dumps({
                'children': {'monitor': os.getpid()}, 'updated': time.time()}))
            (root / 'webconsole' / 'webconsole_state.json').write_text(json.dumps({
                'bind': '127.0.0.1', 'auth_mode': 'passkey',
                'passkey_origin': 'https://server.tail.ts.net',
                'trusted_proxy_origin': 'https://server.tail.ts.net'}))
            response = mock.Mock()
            response.json.return_value = {'auth': 'passkey', 'ok': True}
            with mock.patch('requests.get', return_value=response) as get, \
                    mock.patch('requests.Session') as session, \
                    mock.patch('private_panel.monitor_health') as mailbox, \
                    mock.patch.object(rdp_monitor, 'webconsole_token') as token:
                WindowsRuntime(root).health()
                token.assert_not_called(); session.assert_not_called()
                get.assert_called_once_with('https://server.tail.ts.net/health', timeout=10)
                mailbox.assert_called_once_with(root)

    def test_mailbox_probe_binds_result_to_random_request_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control = root / 'control'; control.mkdir()
            stop = threading.Event()
            def worker():
                while not stop.wait(0.01):
                    for request in control.glob('request-*.json'):
                        data = json.loads(request.read_text())
                        result = control / ('result-' + data['id'] + '.json')
                        result.write_text(json.dumps({'id': data['id'], 'ok': True,
                                                      'out': {'groups': ['fixture']}}))
                        return
            thread = threading.Thread(target=worker, daemon=True); thread.start()
            try: monitor_health(root, timeout=2)
            finally: stop.set(); thread.join(2)
            self.assertEqual(list(control.iterdir()), [])
            with self.assertRaises(RuntimeError): monitor_health(root, timeout=0.01)
            self.assertEqual(list(control.iterdir()), [])

    def test_release_requires_helpers_and_never_ships_test_runner_or_credentials(self):
        self.assertIn('webconsole/passkey_auth.py', REQUIRED)
        self.assertIn('webconsole/private_cli.py', REQUIRED)
        self.assertIn('requirements-passkey.txt', REQUIRED)
        self.assertFalse(allowed_path('panel_auth_test.py'))
        self.assertFalse(allowed_path('webconsole/panel-passkeys.sqlite3'))
        self.assertFalse(allowed_path('test-runtime/panel-auth/access.json'))
