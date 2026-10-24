"""Regression tests: no live Windows actions, network, or runtime configuration."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rdp_monitor as rm


class UserActionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.cfg = mock.patch.object(rm, "config", {"user_management": True})
        self.cfg.start()
        self.addCleanup(self.cfg.stop)
        for name in ("ps_ok", "audit_record"):
            patcher = mock.patch.object(rm, name, return_value=True)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.users = [{"name": "owner", "enabled": True, "admin": True},
                      {"name": "operator", "enabled": True, "admin": False}]
        patcher = mock.patch.object(rm, "_local_users_detail", return_value=self.users)
        self.detail = patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_panel_user_mutations_require_enabled_setting(self):
        rm.config["user_management"] = False
        for action in ("add", "enable", "disable", "delete", "password", "rename"):
            with self.subTest(action=action):
                ok, _ = rm._dispatch_panel("user_action", {
                    "op": action, "name": "operator", "value": "Strong@123"})
                self.assertFalse(ok)
        self.ps_ok.assert_not_called()

    def test_panel_cannot_delete_disable_or_reset_last_admin(self):
        for action in ("delete", "disable", "password"):
            with self.subTest(action=action):
                ok, _ = rm.api_user_action(action, "owner", "Strong@123")
                self.assertFalse(ok)
        self.ps_ok.assert_not_called()

    def test_guard_refuses_exception_empty_or_missing_account(self):
        self.detail.side_effect = RuntimeError("inventory unavailable")
        self.assertFalse(rm.last_admin_guard("owner")[0])
        self.detail.side_effect = None
        for users in ([], [{"name": "other", "enabled": True, "admin": True}]):
            with self.subTest(users=users):
                self.detail.return_value = users
                self.assertFalse(rm.last_admin_guard("owner")[0])

    def test_non_admin_can_be_disabled_when_safety_check_succeeds(self):
        ok, _ = rm.api_user_action("disable", "operator")
        self.assertTrue(ok)
        self.ps_ok.assert_called_once()

    def test_admin_can_be_disabled_when_second_admin_exists(self):
        self.users.append({"name": "backup", "enabled": True, "admin": True})
        ok, _ = rm.api_user_action("disable", "owner")
        self.assertTrue(ok)
        self.ps_ok.assert_called_once()

    def test_panel_rejects_weak_password_before_windows(self):
        for action in ("add", "password"):
            with self.subTest(action=action):
                self.assertFalse(rm.api_user_action(action, "operator", "weak")[0])
        self.ps_ok.assert_not_called()


class StopPolling(BaseException):
    pass


class StrictInventoryTests(unittest.TestCase):
    def test_failed_empty_or_malformed_inventory_never_uses_fallback(self):
        cases = [(1, b"owner|1|1|-|-|-\n"), (0, b""),
                 (0, b"owner|1|1|-|-|-\nbroken row\n"),
                 (0, b"owner|unknown|1|-|-|-\n")]
        for code, output in cases:
            with self.subTest(code=code, output=output), \
                    mock.patch.object(rm.subprocess, "run", return_value=mock.Mock(
                        returncode=code, stdout=output)), \
                    mock.patch.object(rm, "get_local_users") as fallback:
                with self.assertRaises(RuntimeError):
                    rm._local_users_detail(strict=True)
                fallback.assert_not_called()

    def test_valid_strict_inventory_preserves_admin_and_enabled_flags(self):
        output = b"owner|1|1|-|-|-\noperator|0|0|-|-|-\n"
        with mock.patch.object(rm.subprocess, "run", return_value=mock.Mock(
                returncode=0, stdout=output)):
            users = rm._local_users_detail(strict=True)
        self.assertEqual([(u["name"], u["enabled"], u["admin"]) for u in users],
                         [("owner", True, True), ("operator", False, False)])

    def test_reports_keep_non_strict_fallback(self):
        with mock.patch.object(rm.subprocess, "run", side_effect=OSError("unavailable")), \
                mock.patch.object(rm, "get_local_users", return_value=[("owner", True)]):
            self.assertEqual(rm._local_users_detail()[0]["name"], "owner")


class TelegramQueueSecurityTests(unittest.TestCase):
    def run_updates(self, updates):
        response = mock.Mock()
        response.json.return_value = {"result": updates}
        with mock.patch.object(rm, "config", {"chat_id": "7", "telegram_token": "fake"}), \
                mock.patch.object(rm, "_cmd_rate", {}), \
                mock.patch.object(rm, "_cmd_queue", None), \
                mock.patch.object(rm.requests, "get", side_effect=[response, StopPolling()]), \
                mock.patch.object(rm.threading.Thread, "start"), \
                mock.patch.object(rm, "audit_record"), \
                mock.patch.object(rm, "record_usage"), \
                mock.patch.object(rm, "pend_take"), \
                mock.patch.object(rm, "send_message"), \
                mock.patch.object(rm, "tg_api", return_value={"ok": True}) as tg:
            with self.assertRaises(StopPolling):
                rm.telegram_loop()
            return rm._cmd_queue, tg.call_args_list

    def test_callback_commands_share_message_rate_limit(self):
        updates = [{"update_id": i, "callback_query": {
            "id": str(i), "from": {"id": 7}, "data": "run:/view"}}
            for i in range(rm.RATE_LIMIT_CMDS + 1)]
        pending, calls = self.run_updates(updates)
        self.assertEqual(pending.qsize(), rm.RATE_LIMIT_CMDS)
        self.assertTrue(any("rate limit" in c.kwargs.get("text", "").lower() for c in calls))

    def test_mixed_callback_and_text_share_one_budget(self):
        updates = [{"update_id": i, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 7}, "text": "/view"}}
            for i in range(rm.RATE_LIMIT_CMDS)]
        updates.append({"update_id": 100, "callback_query": {
            "id": "last", "from": {"id": 7}, "data": "cf:1234"}})
        pending, _ = self.run_updates(updates)
        self.assertEqual(pending.qsize(), rm.RATE_LIMIT_CMDS)

    def test_full_queue_rejects_callbacks_without_blocking_or_false_ack(self):
        with mock.patch.object(rm, "MAX_COMMAND_QUEUE", 2, create=True):
            updates = [{"update_id": i, "callback_query": {
                "id": str(i), "from": {"id": 7}, "data": "cf:1234"}}
                for i in range(3)]
            pending, calls = self.run_updates(updates)
        self.assertEqual(pending.maxsize, 2)
        self.assertEqual(pending.qsize(), 2)
        last = [c for c in calls if c.kwargs.get("callback_query_id") == "2"]
        self.assertEqual(len(last), 1)
        self.assertIn("busy", last[0].kwargs.get("text", "").lower())

    def test_full_queue_rejects_files_and_text_without_blocking(self):
        with mock.patch.object(rm, "MAX_COMMAND_QUEUE", 1, create=True):
            updates = [{"update_id": i, "message": {
                "chat": {"id": 7, "type": "private"}, "from": {"id": 7}, **payload}}
                for i, payload in enumerate([
                    {"text": "/view"}, {"document": {"file_id": "fake"}}, {"text": "/top"}])]
            pending, _ = self.run_updates(updates)
        self.assertEqual(pending.maxsize, 1)
        self.assertEqual(pending.qsize(), 1)

    def test_unauthorized_callback_never_queues(self):
        pending, _ = self.run_updates([{"update_id": 1, "callback_query": {
            "id": "no", "from": {"id": 999}, "data": "run:/view"}}])
        self.assertTrue(pending.empty())


if __name__ == "__main__":
    unittest.main()
