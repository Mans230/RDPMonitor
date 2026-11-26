"""Job admission and ACL failure regressions; no native commands are executed."""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backup" / "app"))
import rdp_monitor as rm
import config_manager as cm


class DiagnosticAdmissionTests(unittest.TestCase):
    def test_timed_out_job_holds_capacity_until_it_really_exits(self):
        release, finished = threading.Event(), threading.Event()
        capacity = threading.BoundedSemaphore(1)
        def slow():
            try:
                release.wait(2)
            finally:
                finished.set()
        with mock.patch.object(rm, "_PANEL_JOB_SLOTS", capacity, create=True):
            try:
                self.assertFalse(rm._run_captured_job(slow, deadline=0.02)[0])
                second = mock.Mock()
                ok, out = rm._run_captured_job(second, deadline=0.1)
                self.assertFalse(ok)
                self.assertIn("busy", out.lower())
                second.assert_not_called()
            finally:
                release.set()
                self.assertTrue(finished.wait(1))
                self.assertTrue(capacity.acquire(timeout=1))
                capacity.release()
            self.assertTrue(rm._run_captured_job(lambda: None, deadline=1)[0])

    def test_exception_releases_job_capacity(self):
        with mock.patch.object(rm, "_PANEL_JOB_SLOTS", threading.BoundedSemaphore(1), create=True):
            def fail():
                raise ValueError("fake failure")
            self.assertFalse(rm._run_captured_job(fail, deadline=1)[0])
            self.assertTrue(rm._run_captured_job(lambda: None, deadline=1)[0])

    def test_thread_start_failure_releases_capacity(self):
        capacity = threading.BoundedSemaphore(1)
        with mock.patch.object(rm, "_PANEL_JOB_SLOTS", capacity, create=True):
            with mock.patch.object(rm.threading.Thread, "start", side_effect=RuntimeError("no thread")):
                with self.assertRaises(RuntimeError):
                    rm._run_captured_job(lambda: None)
            self.assertTrue(capacity.acquire(blocking=False))
            capacity.release()


class AclFailureTests(unittest.TestCase):
    def test_success_is_reported(self):
        with mock.patch.object(cm.os.path, "exists", return_value=True), \
                mock.patch.object(cm.subprocess, "run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(cm.harden_path("fake-config.json"))

    def test_nonzero_exit_warns_and_reports_failure(self):
        with mock.patch.object(cm.os.path, "exists", return_value=True), \
                mock.patch.object(cm.subprocess, "run", return_value=mock.Mock(returncode=5)):
            with self.assertWarnsRegex(RuntimeWarning, "ACL"):
                self.assertFalse(cm.harden_path("fake-config.json"))

    def test_exception_warns_and_reports_failure(self):
        with mock.patch.object(cm.os.path, "exists", return_value=True), \
                mock.patch.object(cm.subprocess, "run", side_effect=OSError("fake error")):
            with self.assertWarnsRegex(RuntimeWarning, "ACL"):
                self.assertFalse(cm.harden_path("fake-config.json"))

    def test_optional_missing_file_is_skipped_without_running_icacls(self):
        with mock.patch.object(cm.os.path, "exists", return_value=False), \
                mock.patch.object(cm.subprocess, "run") as run:
            self.assertTrue(cm.harden_path("absent-config.json"))
            run.assert_not_called()

    def test_aggregate_failure_does_not_skip_other_assets(self):
        with mock.patch.object(cm, "harden_path", side_effect=[False] + [True] * 5) as harden:
            self.assertFalse(cm.harden_backup_assets({}))
            self.assertEqual(harden.call_count, 6)
