import ctypes
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import rdp_monitor as rm  # noqa: E402


class Result:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.old_config = rm.config
        rm.config = {
            "rdp_port": 3389,
            "rdp_allowed_ips": ["198.51.100.10"],
            "learned_ips": {},
            "learn_for_lockdown": False,
            "rdpallow_disabled_rules": [],
            "pre_default_inbound": {},
        }

    def tearDown(self):
        rm.config = self.old_config

    def test_lockdown_never_trusts_current_connection(self):
        rm.config["learned_ips"] = {
            "198.51.100.20": {"t": time.time(), "u": "owner"}}
        with mock.patch.object(rm, "get_rdp_ips",
                               return_value=["203.0.113.66"]):
            self.assertEqual(rm.lockdown_ips(), ["198.51.100.10"])
            rm.config["learn_for_lockdown"] = True
            self.assertEqual(rm.lockdown_ips(),
                             ["198.51.100.10", "198.51.100.20"])

    

    def test_trusted_firewall_rules_are_explicit_tcp_and_udp(self):
        calls = []

        def fake_netsh(args):
            calls.append(args)
            return True, ""

        with mock.patch.object(rm, "_netsh", side_effect=fake_netsh), \
                mock.patch.object(rm, "ps_ok", return_value=True):
            ok, _ = rm._create_trusted_rules(3389, ["198.51.100.10"])
        self.assertTrue(ok)
        adds = [" ".join(c) for c in calls if "add" in c]
        self.assertTrue(any("protocol=TCP" in c for c in adds))
        self.assertTrue(any("protocol=UDP" in c for c in adds))

    def test_unblock_keeps_tracking_when_rule_remains(self):
        rm._blocked = {"203.0.113.8": time.time()}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(rm, "BLOCKED_FILE", os.path.join(td, "blocked.json")), \
                mock.patch.object(rm, "_netsh", return_value=(True, "")), \
                mock.patch.object(rm.subprocess, "run", return_value=Result(b"1")):
            self.assertFalse(rm.unblock_ip("203.0.113.8"))
        self.assertIn("203.0.113.8", rm._blocked)

    def test_unblock_clears_tracking_when_rule_is_gone(self):
        rm._blocked = {"203.0.113.8": time.time()}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(rm, "BLOCKED_FILE", os.path.join(td, "blocked.json")), \
                mock.patch.object(rm, "_netsh", return_value=(True, "")), \
                mock.patch.object(rm.subprocess, "run", return_value=Result(b"0")):
            self.assertTrue(rm.unblock_ip("203.0.113.8"))
        self.assertNotIn("203.0.113.8", rm._blocked)

    def test_firewall_transaction_persists_rule_ids(self):
        scans = iter([(["termservice-rule-id"], []), ([], [])])
        with mock.patch.object(rm, "_delete_trusted_rules"), \
                mock.patch.object(rm, "_create_trusted_rules", return_value=(True, "")), \
                mock.patch.object(rm, "_netsh", return_value=(True, "")), \
                mock.patch.object(rm, "_scan_broad_rules", side_effect=lambda *a, **k: next(scans)), \
                mock.patch.object(rm, "_set_rule_enabled", return_value=True), \
                mock.patch.object(rm, "save_config"), \
                mock.patch.object(rm.subprocess, "run", return_value=Result(b"")):
            self.assertTrue(rm.apply_rdp_allow(["198.51.100.10"]))
        self.assertEqual(rm.config["rdpallow_disabled_rules"],
                         ["termservice-rule-id"])

    @unittest.skipUnless(sys.platform == "win32", "Windows mutex test")
    def test_named_mutex_blocks_second_instance(self):
        old_handle = rm._instance_mutex
        old_base = rm.BASE_DIR
        rm._instance_mutex = None
        rm.BASE_DIR = old_base + "_test_" + str(os.getpid())
        try:
            self.assertTrue(rm.acquire_instance_lock())
            self.assertFalse(rm.acquire_instance_lock())
        finally:
            if rm._instance_mutex:
                ctypes.windll.kernel32.CloseHandle(rm._instance_mutex)
            rm._instance_mutex = old_handle
            rm.BASE_DIR = old_base

    def test_valid_ip_is_strict(self):
        for good in ("203.0.113.5", "::1", "2001:db8::1", "0.0.0.0"):
            self.assertTrue(rm._valid_ip(good), good)
        for bad in ("a1", ":::", "1.2.3", "999.1.1.1", "1.2.3.4;rm",
                    "", "1.2.3.4/24", "1.2.3.4.5"):
            self.assertFalse(rm._valid_ip(bad), bad)

    def test_pending_ids_do_not_collide(self):
        old_pending = dict(rm._pending)
        old_seq = rm._pend_seq
        try:
            rm._pending.clear()
            rm._pend_seq = 65534
            ids = {rm.pend_store({"n": i}) for i in range(3)}
            self.assertEqual(len(ids), 3)
        finally:
            rm._pending.clear()
            rm._pending.update(old_pending)
            rm._pend_seq = old_seq

    def test_unified_backup_request_uses_control_file(self):
        with tempfile.TemporaryDirectory() as td:
            req = os.path.join(td, "request.json")
            with mock.patch.object(rm, "BACKUP_CONTROL_DIR", td), \
                    mock.patch.object(rm, "BACKUP_REQUEST", req), \
                    mock.patch.object(rm, "audit_record"):
                ok, rid = rm.queue_backup_request()
                self.assertTrue(ok)
                body = json.loads(Path(req).read_text(encoding="utf-8"))
                self.assertEqual(body["action"], "backup")
                self.assertEqual(body["id"], rid)
                self.assertNotIn("path", body)
                ok2, _ = rm.queue_backup_request()
                self.assertFalse(ok2)

    def test_webconsole_url_is_local(self):
        with mock.patch.object(rm, "WEBCONSOLE_STATE", "does-not-exist.json"):
            self.assertEqual(rm.webconsole_url(), "http://127.0.0.1:8399/")

    

    def test_uninstall_preserves_active_allowlist_and_disabled_broad_rules(self):
        rm.config.update(rdp_allow_active=True,
                         rdpallow_disabled_rules=["original-broad-rule"],
                         pre_default_inbound={"Public": "Allow"})
        with mock.patch.object(rm.sys, "argv", ["rdp_monitor.py", "--cleanup"]), \
                mock.patch.object(rm, "_rdp_registry_port", return_value=3389), \
                mock.patch.object(rm, "_netsh", return_value=(True, "")) as netsh, \
                mock.patch.object(rm, "_enable_saved_rule") as enable, \
                mock.patch.object(rm, "_create_general_rdp_rule") as broad, \
                mock.patch.object(rm, "ps_ok") as ps:
            self.assertTrue(rm._cleanup_system_changes())
        enable.assert_not_called()
        broad.assert_not_called()
        ps.assert_not_called()
        deleted = [" ".join(call.args[0]) for call in netsh.call_args_list]
        self.assertFalse(any(rm.RDP_ALLOW_TCP_RULE in cmd or
                             rm.RDP_ALLOW_UDP_RULE in cmd for cmd in deleted))

    def test_opening_allowlist_on_uninstall_requires_explicit_option(self):
        rm.config.update(rdp_allow_active=True,
                         rdpallow_disabled_rules=["original-broad-rule"])
        with mock.patch.object(rm.sys, "argv", ["rdp_monitor.py", "--cleanup",
                                                "--remove-allowlist"]), \
                mock.patch.object(rm, "_rdp_registry_port", return_value=3389), \
                mock.patch.object(rm, "_netsh", return_value=(True, "")), \
                mock.patch.object(rm, "_enable_saved_rule", return_value=True) as enable, \
                mock.patch.object(rm, "_create_general_rdp_rule", return_value=(True, "")) as broad:
            self.assertTrue(rm._cleanup_system_changes())
        enable.assert_called_once_with("original-broad-rule")
        broad.assert_called_once_with(3389)

    def test_cleanup_refuses_invalid_config_before_touching_firewall(self):
        with tempfile.TemporaryDirectory() as td:
            config_file = os.path.join(td, "config.json")
            Path(config_file).write_text("{invalid", encoding="utf-8")
            with mock.patch.object(rm, "CONFIG_FILE", config_file), \
                    mock.patch.object(rm.sys, "argv", ["rdp_monitor.py", "--cleanup"]), \
                    mock.patch.object(rm, "_cleanup_system_changes") as cleanup:
                self.assertEqual(rm.main(), 1)
            cleanup.assert_not_called()


class PanelDiagReadOnlyTests(unittest.TestCase):
    """The WebConsole read-only reports must reuse bot logic without Telegram."""

    def setUp(self):
        self.old_config = rm.config
        rm.config = {
            "rdp_port": 3389,
            "telegram_token": "123456:ABCDEF-secret-token",
            "telegram_token_enc": "DPAPI-BLOB-SHOULD-NOT-LEAK",
            "rdp_allowed_ips": [],
        }

    def tearDown(self):
        rm.config = self.old_config

    def test_report_returns_text(self):
        with mock.patch.object(rm, "stats_since", return_value={
                "cpu_avg": 41.2, "cpu_max": 88.0, "ram_avg": 55.5,
                "ram_max": 79.0, "points": 1200}):
            ok, out = rm.api_diag("report")
        self.assertTrue(ok)
        self.assertIn("Daily report", out)
        self.assertIn("1200", out)

    def test_configbackup_redacts_secrets(self):
        ok, out = rm.api_diag("configbackup")
        self.assertTrue(ok)
        self.assertNotIn("DPAPI-BLOB-SHOULD-NOT-LEAK", out)
        data = json.loads(out)
        self.assertEqual(data["telegram_token_enc"], "***redacted***")
        self.assertTrue(data["telegram_token"].startswith("***"))
        self.assertFalse(data["telegram_token"].endswith("secret-token"))

    def test_botlog_reads_tail_without_telegram(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rdp_monitor.log"
            p.write_text("line-one\nline-two\n", encoding="utf-8")
            with mock.patch.object(rm, "LOG_FILE", str(p)):
                ok, out = rm.api_diag("botlog")
        self.assertTrue(ok)
        self.assertIn("line-two", out)

    def test_dumps_reports_none_when_empty(self):
        with mock.patch.object(rm, "_crash_dumps", return_value=[]):
            ok, out = rm.api_diag("dumps")
        self.assertTrue(ok)
        self.assertIn("No recent crash dump", out)

    def test_nettest_requires_a_host(self):
        ok, out = rm.api_diag("nettest", "")
        self.assertFalse(ok)
        self.assertIn("host", out)

    def test_logins_captures_job_output(self):
        def fake_job(n):
            rm.send_message("2026-10-14 09:00 | Administrator | 203.0.113.7")
        with mock.patch.object(rm, "_logins_job", side_effect=fake_job):
            ok, out = rm.api_diag("logins")
        self.assertTrue(ok)
        self.assertIn("Administrator", out)

    def test_unknown_diag_is_rejected(self):
        ok, _ = rm.api_diag("not-a-real-op")
        self.assertFalse(ok)


class PanelSettingsTests(unittest.TestCase):
    """apply_setting is the one validated path for /set and the panel."""

    def setUp(self):
        self.old_config = rm.config
        rm.config = {
            "cpu_alert_threshold": 50, "disk_threshold": 90,
            "exec_enabled": False, "instance_name": "",
        }
        self._saved = []
        p = mock.patch.object(rm, "save_config",
                              lambda: self._saved.append(dict(rm.config)))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        rm.config = self.old_config

    def test_int_bounds_are_enforced(self):
        ok, msg = rm.apply_setting("cpu", "0")
        self.assertFalse(ok)
        self.assertIn("between 1 and 100", msg)
        self.assertEqual(rm.config["cpu_alert_threshold"], 50)

    def test_valid_int_applies_and_saves(self):
        ok, _ = rm.apply_setting("cpu", "72")
        self.assertTrue(ok)
        self.assertEqual(rm.config["cpu_alert_threshold"], 72)
        self.assertEqual(len(self._saved), 1)

    def test_bool_toggle(self):
        ok, _ = rm.apply_setting("exec", "on")
        self.assertTrue(ok)
        self.assertTrue(rm.config["exec_enabled"])

    def test_multiword_name_is_preserved(self):
        ok, _ = rm.apply_setting("name", "prod web 02")
        self.assertTrue(ok)
        self.assertEqual(rm.config["instance_name"], "prod web 02")

    def test_name_length_is_rejected(self):
        ok, _ = rm.apply_setting("name", "x" * 60)
        self.assertFalse(ok)

    def test_unknown_key_is_rejected(self):
        ok, _ = rm.apply_setting("nope", "1")
        self.assertFalse(ok)

    def test_snapshot_shape(self):
        groups = rm.settings_snapshot()
        self.assertTrue(groups)
        keys = [i["key"] for g in groups for i in g["items"]]
        self.assertIn("cpu", keys)
        self.assertIn("exec", keys)
        for g in groups:
            for i in g["items"]:
                self.assertIn(i["type"], ("int", "bool", "text"))


class PanelSecurityActionTests(unittest.TestCase):
    """_dispatch_panel security actions reuse bot logic without Telegram."""

    def setUp(self):
        self.old_config = rm.config
        rm.config = {"rdp_port": 3389, "trap_users": [], "muted_until": 0}
        self._saved = []
        p = mock.patch.object(rm, "save_config",
                              lambda: self._saved.append(dict(rm.config)))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        rm.config = self.old_config

    def test_block_subnet_requires_confirmation(self):
        ok, out = rm._dispatch_panel("block_subnet", {"ip": "203.0.113.7"})
        self.assertFalse(ok)
        self.assertIn("confirmation", out)

    def test_set_rdp_port_rejects_out_of_range(self):
        ok, out = rm._dispatch_panel("set_rdp_port", {"port": 70000, "confirm": True})
        self.assertFalse(ok)
        self.assertIn("between 1024 and 65535", out)

    def test_trap_add_list_remove(self):
        ok, _ = rm._dispatch_panel("trap", {"op": "add", "name": "admin"})
        self.assertTrue(ok)
        self.assertIn("admin", rm.config["trap_users"])
        ok, items = rm._dispatch_panel("trap", {"op": "list"})
        self.assertTrue(ok)
        self.assertEqual(items, ["admin"])
        rm._dispatch_panel("trap", {"op": "del", "name": "admin"})
        self.assertEqual(rm.config["trap_users"], [])

    def test_mute_sets_and_clears(self):
        ok, _ = rm._dispatch_panel("mute", {"minutes": 60})
        self.assertTrue(ok)
        self.assertGreater(rm.config["muted_until"], 0)
        ok, _ = rm._dispatch_panel("mute", {"off": True})
        self.assertTrue(ok)
        self.assertEqual(rm.config["muted_until"], 0)

    def test_cancel_restart_uses_shutdown_without_telegram(self):
        with mock.patch.object(rm.subprocess, "run", return_value=Result()) as run, \
                mock.patch.object(rm, "send_message") as send:
            ok, out = rm._dispatch_panel("cancel_restart", {})
        self.assertTrue(ok)
        self.assertIn("cancelled", out)
        send.assert_not_called()
        self.assertIn("shutdown", run.call_args[0][0][0])


class PanelAutomationTests(unittest.TestCase):
    """Automation lists, test alert, update gate and file sending."""

    def setUp(self):
        self.old_config = rm.config
        rm.config = {"watch": [], "keepalive": [], "svcwatch": [],
                     "exec_enabled": False, "update_url": "", "update_hash": ""}
        p = mock.patch.object(rm, "save_config", lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        rm.config = self.old_config

    def test_watch_add_list_del(self):
        ok, _ = rm._dispatch_panel("automation", {"list": "watch", "op": "add",
                                                  "name": "chrome", "ram_mb": 4096})
        self.assertTrue(ok)
        self.assertEqual(rm.config["watch"], [{"name": "chrome", "ram_mb": 4096}])
        ok, items = rm._dispatch_panel("automation", {"list": "watch", "op": "list"})
        self.assertEqual(len(items), 1)
        rm._dispatch_panel("automation", {"list": "watch", "op": "del", "name": "chrome"})
        self.assertEqual(rm.config["watch"], [])

    def test_keepalive_custom_run_needs_exec(self):
        ok, out = rm._dispatch_panel("automation", {"list": "keepalive", "op": "add",
                                                    "name": "svc", "run": "svc.exe"})
        self.assertFalse(ok)
        self.assertIn("exec", out)
        rm.config["exec_enabled"] = True
        ok, _ = rm._dispatch_panel("automation", {"list": "keepalive", "op": "add",
                                                  "name": "svc", "run": "svc.exe"})
        self.assertTrue(ok)
        self.assertEqual(rm.config["keepalive"][0]["run"], "svc.exe")

    def test_svcwatch_add(self):
        ok, _ = rm._dispatch_panel("automation", {"list": "svcwatch", "op": "add",
                                                  "name": "W32Time"})
        self.assertTrue(ok)
        self.assertEqual(rm.config["svcwatch"], [{"name": "W32Time"}])

    def test_unknown_list_rejected(self):
        ok, _ = rm._dispatch_panel("automation", {"list": "nope", "op": "list"})
        self.assertFalse(ok)

    def test_update_requires_confirmation_and_config(self):
        ok, out = rm._dispatch_panel("update_now", {})
        self.assertFalse(ok)
        self.assertIn("confirmation", out)
        ok, out = rm._dispatch_panel("update_now", {"confirm": True})
        self.assertFalse(ok)
        self.assertIn("not configured", out)

    def test_send_file_missing(self):
        ok, out = rm._dispatch_panel("send_file", {"path": "Z:\\nope\\missing.txt"})
        self.assertFalse(ok)
        self.assertIn("not found", out)

    def test_test_alert_sends_message(self):
        with mock.patch.object(rm, "send_message") as send:
            ok, _ = rm._dispatch_panel("test_alert", {})
        self.assertTrue(ok)
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
