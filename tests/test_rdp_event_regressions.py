import contextlib
import copy
import ctypes
import datetime
import json
import shutil
import subprocess
import time
import unittest
from unittest import mock

import rdp_monitor as rm

ORIGINAL_SAVE_BLOCKED = rm.save_blocked


def result(text="", code=0):
    return mock.Mock(stdout=text.encode(), stderr=b"fixture error" if code else b"", returncode=code)


class RdpEventRegressions(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        cfg = copy.deepcopy(rm.DEFAULT_CONFIG)
        cfg.update(failed_login_block=False, subnetblock=False, lockdown=False,
                   failed_login_window=15, rdp_allowed_ips=["198.51.100.10"])
        for name, value in (("config", cfg), ("_seen_4625", {}), ("_failed_logins", {}),
                            ("_blocked", {}), ("_learn_alerts_ready", True)):
            self.stack.enter_context(mock.patch.object(rm, name, value))
        for name in ("save_config", "load_blocked", "save_blocked", "audit_record", "send_message", "send_buttons"):
            setattr(self, name, self.stack.enter_context(mock.patch.object(rm, name)))
        self.native = self.stack.enter_context(mock.patch.object(rm.subprocess, "run", return_value=result()))
        self.netsh = self.stack.enter_context(mock.patch.object(rm, "_netsh", return_value=(True, "")))
        self.stack.enter_context(mock.patch.object(rm, "_blocked_file_guard", side_effect=contextlib.nullcontext))

    def stamp(self, age=0):
        return datetime.datetime.fromtimestamp(time.time()-age, datetime.timezone.utc).isoformat()

    def row(self, ip="203.0.113.23", user="guest", age=0, record=None):
        text = f"{user}|{ip}|{self.stamp(age)}"
        return text + (f"|{record}" if record is not None else "") + "\n"

    def test_disabled_subnet_option_never_escalates_existing_ip_block(self):
        rm._blocked["203.0.113.23"] = time.time()
        self.native.return_value = result(self.row())
        with mock.patch.object(rm, "block_subnet", return_value=(True, "added")) as subnet:
            rm._check_failed_logons_impl()
        subnet.assert_not_called()

    def test_failed_query_never_counts_stdout_as_real_events(self):
        self.native.return_value = result(self.row(), code=1)
        rm._check_failed_logons_impl()
        self.assertEqual(rm._failed_logins, {})
        self.netsh.assert_not_called()

    def test_old_events_do_not_refresh_the_failure_window(self):
        self.native.return_value = result(self.row(age=20*60))
        rm._check_failed_logons_impl()
        self.assertEqual(rm._failed_logins, {})

    def test_record_ids_distinguish_events_with_identical_millisecond(self):
        row = self.row().strip()
        self.native.return_value = result(row+"|101\n"+row+"|102\n")
        rm._check_failed_logons_impl()
        self.assertIn("203.0.113.23", rm._failed_logins)
        self.assertEqual(len(rm._failed_logins["203.0.113.23"]["times"]), 2)
        rm._check_failed_logons_impl()
        self.assertEqual(len(rm._failed_logins["203.0.113.23"]["times"]), 2)

    def test_invalid_or_unsafe_source_addresses_are_ignored(self):
        self.native.return_value = result("".join(self.row(ip=ip) for ip in (
            "not-an-ip", "127.0.0.2", "0.0.0.0", "224.0.0.1")))
        rm._check_failed_logons_impl()
        self.assertEqual(rm._failed_logins, {})

    def test_manually_trusted_source_cannot_be_automatically_blocked(self):
        rm.config.update(failed_login_block=True, failed_login_block_threshold=1, trap_users=["decoy"])
        self.native.return_value = result(self.row(ip="198.51.100.10", user="decoy"))
        rm._check_failed_logons_impl()
        self.netsh.assert_not_called()

    def test_unblock_failed_verification_preserves_tracking(self):
        rm._blocked["203.0.113.23"] = 1
        self.native.return_value = result("", code=1)
        self.assertFalse(rm.unblock_ip("203.0.113.23"))
        self.assertIn("203.0.113.23", rm._blocked)

    def test_tracking_write_failure_rolls_back_new_block(self):
        self.save_blocked.side_effect = OSError("disk full")
        ok, message = rm.block_ip("203.0.113.23")
        self.assertFalse(ok)
        self.assertNotIn("203.0.113.23", rm._blocked)
        self.assertIn("rolled back", message)
        self.assertIn("delete", self.netsh.call_args.args[0])

    def test_real_save_blocked_reports_atomic_write_failure(self):
        # Use the actual function while keeping all native mutations mocked.
        with mock.patch.object(rm, "_atomic_write_json", return_value=False):
            with self.assertRaises(OSError):
                ORIGINAL_SAVE_BLOCKED()

    def test_lockdown_release_failure_keeps_recorded_state(self):
        rm.config.update(lockdown_until=time.time()+600, rdp_allow_pre_active=True,
                         rdp_allow_active=True)
        before = copy.deepcopy(rm.config)
        with mock.patch.object(rm, "apply_rdp_allow", return_value=False):
            self.assertFalse(rm.lockdown_release())
        self.assertEqual(rm.config, before)
        self.save_config.assert_not_called()

    def test_lockdown_release_does_not_open_rdp_when_previous_list_was_lost(self):
        rm.config.update(rdp_allow_pre_active=True, rdp_allowed_ips=[])
        with mock.patch.object(rm, "apply_rdp_allow") as apply:
            self.assertFalse(rm.lockdown_release())
            apply.assert_not_called()

    def test_panel_security_wrappers_do_not_report_failed_release_as_success(self):
        with mock.patch.object(rm, "lockdown_release", return_value=False):
            self.assertFalse(rm.api_lockdown("off")[0])
        rm.config["panic_active"] = True
        with mock.patch.object(rm, "panic_off"):
            self.assertFalse(rm.api_panic("off")[0])
        rm.config["panic_active"] = False
        with mock.patch.object(rm, "panic_on"):
            self.assertFalse(rm.api_panic("on")[0])

    def test_panel_and_bot_preserve_allowlist_when_release_fails(self):
        rm.config["rdp_allow_active"] = True
        before = copy.deepcopy(rm.config)
        with mock.patch.object(rm, "apply_rdp_allow", return_value=False):
            self.assertFalse(rm.api_rdp_allow_clear()[0])
            rm.handle_command("/rdpallow clear confirm")
        self.assertEqual(rm.config, before)
        self.save_config.assert_not_called()

    def test_allowlist_release_requires_verified_rule_removal(self):
        with mock.patch.object(rm, "_firewall_rule_count", return_value=None), \
                mock.patch.object(rm, "_create_general_rdp_rule") as broad:
            self.assertFalse(rm.apply_rdp_allow([]))
            broad.assert_not_called()

    def test_failed_logons_block_only_at_threshold_and_only_once(self):
        rm.config.update(failed_login_block=True, failed_login_block_threshold=2)
        self.native.return_value = result(self.row(record=1))
        with mock.patch.object(rm, "block_ip", return_value=(True, "added")) as block:
            rm._check_failed_logons_impl()
            block.assert_not_called()
            self.native.return_value = result(self.row(record=1)+self.row(record=2))
            rm._check_failed_logons_impl()
            block.assert_called_once_with("203.0.113.23")
            rm._check_failed_logons_impl()
            block.assert_called_once()

    def test_panic_release_failed_verification_preserves_active_state(self):
        rm.config["panic_active"] = True
        self.native.return_value = result("", code=1)
        rm.panic_off()
        self.assertTrue(rm.config["panic_active"])

    def test_previously_blocked_subnet_can_be_unblocked_explicitly(self):
        rm._blocked["203.0.113.0/24"] = 1
        self.native.return_value = result("0")
        self.assertTrue(rm.unblock_ip("203.0.113.0/24"))
        self.assertNotIn("203.0.113.0/24", rm._blocked)

    def test_subnet_block_cannot_cover_a_manual_trust_address(self):
        ok, _ = rm.block_subnet("198.51.100.66")
        self.assertFalse(ok)
        self.netsh.assert_not_called()

    def test_learn_query_failure_does_not_change_trusted_history(self):
        before = {"198.51.100.88": {"t": time.time(), "u": "owner"}}
        rm.config["learned_ips"] = copy.deepcopy(before)
        self.native.return_value = result("", code=1)
        self.assertIsNone(rm.learn_successful_ips())
        self.assertEqual(rm.config["learned_ips"], before)
        self.save_config.assert_not_called()

    def test_learning_keeps_latest_account_and_exact_event_time(self):
        newest = self.stamp(30)
        older = self.stamp(90)
        self.native.return_value = result(f"203.0.113.23|latest|{newest}\n203.0.113.23|older|{older}\n")
        rm.learn_successful_ips()
        row = rm.config["learned_ips"]["203.0.113.23"]
        self.assertEqual(row["u"], "latest")
        self.assertAlmostEqual(row["t"], datetime.datetime.fromisoformat(newest).timestamp(), places=2)

    def test_login_report_does_not_describe_query_failure_as_no_logins(self):
        self.native.return_value = result("", code=1)
        rm._logins_job(10)
        self.assertIn("failed", str(self.send_message.call_args).lower())

    def test_failed_event_query_uses_configured_window(self):
        rm.config["failed_login_window"] = 19
        self.assertIn("AddMinutes(-19)", rm._failed_logon_ps())

    def test_account_query_failure_does_not_initialize_baseline(self):
        self.native.return_value = result("", code=1)
        with mock.patch.object(rm, "_acct_baseline", False), mock.patch.object(rm, "_seen_acct", {}):
            rm._check_account_events_impl()
            self.assertFalse(rm._acct_baseline)

    def test_localized_admin_group_uses_sid_and_record_ids_distinguish_events(self):
        row = f"4732|new-member|LocalizedGroup|DOMAIN/owner|{self.stamp()}"
        self.native.return_value = result(row+"|101|S-1-5-32-544\n"+row+"|102|S-1-5-32-544\n")
        with mock.patch.object(rm, "_acct_baseline", True), mock.patch.object(rm, "_seen_acct", {}):
            rm._check_account_events_impl()
            self.assertEqual(len(rm._seen_acct), 2)
            text = self.send_buttons.call_args.args[0]
            self.assertIn("Change to device accounts", text)
            self.assertIn("record 101", text)
            self.assertIn("record 102", text)
            self.send_buttons.reset_mock()
            rm._check_account_events_impl()
            self.send_buttons.assert_not_called()

    def test_security_display_escapes_untrusted_account_names(self):
        self.native.return_value = result(self.row(user="<b>attacker</b>"))
        rm._check_failed_logons_impl()
        self.assertNotIn("<b>attacker</b>", self.send_buttons.call_args.args[0])


class SessionObservationTests(unittest.TestCase):
    def test_failed_snapshot_does_not_emit_false_logout(self):
        with mock.patch.object(rm, "_known_sessions", {"owner"}), \
                mock.patch.object(rm.subprocess, "run", return_value=result("", code=1)), \
                mock.patch.object(rm.psutil, "users", side_effect=RuntimeError("unavailable")), \
                mock.patch.object(rm, "send_message") as send:
            rm.check_sessions()
            self.assertEqual(rm._known_sessions, {"owner"})
            send.assert_not_called()


class BlockedMutexTests(unittest.TestCase):
    def test_win64_handle_is_not_truncated_and_only_acquired_mutex_is_released(self):
        for wait, releases in ((0, 1), (0x80, 1), (0x102, 0)):
            with self.subTest(wait=wait):
                kernel = mock.Mock()
                kernel.CreateMutexW.return_value = 2**40
                kernel.WaitForSingleObject.return_value = wait
                with mock.patch.object(rm.ctypes, "windll", mock.Mock(kernel32=kernel), create=True):
                    if releases:
                        with rm._blocked_file_guard():
                            pass
                    else:
                        with self.assertRaises(TimeoutError):
                            with rm._blocked_file_guard():
                                self.fail("timed out mutex must not grant ownership")
                self.assertEqual(kernel.WaitForSingleObject.argtypes[0], ctypes.c_void_p)
                self.assertEqual(kernel.ReleaseMutex.call_count, releases)
                kernel.CloseHandle.assert_called_once_with(2**40)


class SecurityQuerySyntaxTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell parser is unavailable")
    def test_generated_security_queries_parse_without_executing_them(self):
        scripts = [rm._failed_logon_ps(), rm.PS_SUCCESS_LOGON, rm.PS_LOGIN_LOG, rm.PS_ACCOUNT_EVENTS]
        parser = (
            "$scripts=([Console]::In.ReadToEnd() | ConvertFrom-Json); "
            "foreach ($script in $scripts) { $tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseInput($script,[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Output $_.Message }; exit 1 } }"
        )
        completed = subprocess.run(["powershell", "-NoProfile", "-Command", parser],
                                   input=json.dumps(scripts).encode(), capture_output=True,
                                   timeout=30, creationflags=rm.NO_WINDOW)
        self.assertEqual(completed.returncode, 0, completed.stdout.decode(errors="replace"))
