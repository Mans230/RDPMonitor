import unittest
from unittest import mock

import rdp_monitor as rm


class DirectPanelTests(unittest.TestCase):
    def test_all_public_aliases_require_confirmation(self):
        for alias in ("direct", "open", "any", "public"):
            with self.subTest(alias=alias), mock.patch.object(rm, "panel_remote") as run, \
                    mock.patch.object(rm, "send_buttons") as buttons:
                rm.handle_command("/panelremote " + alias)
                run.assert_not_called()
                self.assertIn("any IPv4", buttons.call_args.args[0])

    def test_confirmed_direct_mode_uses_persistent_https_command(self):
        with mock.patch.object(rm, "_run_webconsole_cli", return_value=(0, "enabled")) as cli, \
                mock.patch.object(rm, "send_message"), mock.patch.object(rm, "audit_record"), \
                mock.patch.object(rm.time, "sleep"), mock.patch.object(rm, "send_panel_info") as info:
            rm.handle_command("/panelremote direct confirm")
        cli.assert_called_once_with(["remote-enable", "--allow", "0.0.0.0/0"])
        info.assert_called_once_with()

    def test_panel_links_contain_no_login_credentials(self):
        with mock.patch.object(rm, "webconsole_token", return_value="secret"), \
                mock.patch.object(rm, "webconsole_bind", return_value="0.0.0.0"), \
                mock.patch.object(rm, "webconsole_scheme", return_value="https"), \
                mock.patch.object(rm, "webconsole_port", return_value=8399), \
                mock.patch.object(rm, "panel_hosts", return_value=[("External", "199.47.241.111")]), \
                mock.patch.object(rm, "send_url_buttons") as buttons:
            rm.send_panel_info()
        text, rows = buttons.call_args.args
        self.assertEqual(rows[0][0][1], "https://199.47.241.111:8399/")
        self.assertNotIn("secret", str(buttons.call_args))
        self.assertIn("sign-in", text)

    def test_local_mode_does_not_advertise_unreachable_external_links(self):
        with mock.patch.object(rm, "webconsole_token", return_value="secret"), \
                mock.patch.object(rm, "webconsole_bind", return_value="127.0.0.1"), \
                mock.patch.object(rm, "panel_hosts", return_value=[("External", "199.47.241.111")]), \
                mock.patch.object(rm, "send_url_buttons") as buttons:
            rm.send_panel_info()
        self.assertNotIn("199.47.241.111", str(buttons.call_args))
