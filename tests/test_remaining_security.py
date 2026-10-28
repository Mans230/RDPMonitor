import contextlib
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import rdp_monitor as rm


class AccountConcurrencyTests(unittest.TestCase):
    def test_web_and_telegram_cannot_disable_both_remaining_admins(self):
        users = {"alpha": True, "beta": True}
        inventory_count = 0
        inventory_lock = threading.Lock()
        both_read = threading.Event()
        start = threading.Event()
        errors = []
        def inventory(**kwargs):
            nonlocal inventory_count
            snapshot = [{"name": n, "enabled": enabled, "admin": True}
                        for n, enabled in users.items()]
            with inventory_lock:
                inventory_count += 1
                if inventory_count == 2:
                    both_read.set()
            both_read.wait(0.08)
            return snapshot
        def disable_web(script, **kwargs):
            users["alpha"] = False
            return True
        def disable_telegram(args, **kwargs):
            users["beta"] = False
            return 0, ""
        def run(fn):
            try:
                start.wait(1)
                fn()
            except BaseException as exc:
                errors.append(exc)
        with mock.patch.object(rm, "config", {"user_management": True}), \
                mock.patch.object(rm, "_local_users_detail", side_effect=inventory), \
                mock.patch.object(rm, "ps_ok", side_effect=disable_web), \
                mock.patch.object(rm, "run_net", side_effect=disable_telegram), \
                mock.patch.object(rm, "send_message"), mock.patch.object(rm, "audit_record"):
            threads = [threading.Thread(target=run, args=(fn,)) for fn in (
                lambda: rm.api_user_action("disable", "alpha"),
                lambda: rm.handle_command("/disableuser beta confirm"))]
            for thread in threads:
                thread.start()
            start.set()
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sum(users.values()), 1)


class AllDiagnosticDeadlineTests(unittest.TestCase):
    def test_hardening_report_returns_report_instead_of_empty_capture(self):
        with mock.patch.object(rm, "harden_report", return_value="FAKE_NLA_REPORT"):
            ok, text = rm.api_diag("harden")
        self.assertTrue(ok)
        self.assertIn("FAKE_NLA_REPORT", text)

    def test_other_diagnostics_cannot_hold_the_mailbox_past_deadline(self):
        release, finished = threading.Event(), threading.Event()
        def slow():
            try:
                release.wait(0.3)
                return "done"
            finally:
                finished.set()
        with mock.patch.object(rm, "_PANEL_JOB_DEADLINE", 0.02), \
                mock.patch.object(rm, "_PANEL_JOB_SLOTS", threading.BoundedSemaphore(1)), \
                mock.patch.object(rm, "format_netstat", side_effect=slow):
            try:
                ok, text = rm.api_diag("netstat")
                self.assertFalse(ok)
                self.assertIn("did not finish", text)
            finally:
                release.set()
                self.assertTrue(finished.wait(1))

