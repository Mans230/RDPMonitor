import concurrent.futures
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest import mock

import rdp_monitor as rm
from audit_store import append_event, read_events, summarize
from diagnostic_runtime import deadline_scope


class UsageJournalTests(unittest.TestCase):
    def test_audit_writer_failure_does_not_interrupt_telegram_control(self):
        with mock.patch.object(rm, "append_event", side_effect=OSError("fake")), \
                mock.patch("builtins.print"):
            self.assertIsNone(rm.record_usage("7", "/view", "queued", "test"))

    def test_rotation_retains_bounded_recent_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.jsonl"
            for i in range(6):
                append_event(path, source="test", actor="alice", action=str(i), status="ok",
                             max_bytes=1, backups=2)
            events = read_events(path, backups=2)
            self.assertEqual([e["action"] for e in events], ["3", "4", "5"])
            self.assertEqual(summarize(events)["by_actor"], {"alice": 3})

    def test_concurrent_events_are_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.jsonl"
            def emit(i):
                append_event(path, source="test", actor="alice", action="view", status="ok")
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(emit, range(40)))
            self.assertEqual(len(read_events(path)), 40)

    def test_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(Path, "open", side_effect=PermissionError("fake")):
            with self.assertWarnsRegex(RuntimeWarning, "audit"):
                self.assertIsNone(append_event(Path(directory)/"usage.jsonl", source="test",
                                              actor="alice", action="view", status="ok"))

    def test_telegram_worker_records_identity_and_duration_without_arguments(self):
        class StopWorker(BaseException):
            pass
        pending = mock.Mock()
        pending.get.side_effect = [(rm.handle_command, ("/exec FAKE_SECRET confirm",), "7", "req-1"),
                                   StopWorker()]
        with mock.patch.object(rm, "_cmd_queue", pending), \
                mock.patch.object(rm, "handle_command") as command, \
                mock.patch.object(rm, "record_usage") as record:
            pending.get.side_effect = [(command, ("/exec FAKE_SECRET confirm",), "7", "req-1"), StopWorker()]
            with self.assertRaises(StopWorker):
                rm._command_worker()
        args = record.call_args.args
        self.assertEqual(args[:4], ("7", "/exec", "completed", "req-1"))
        self.assertGreaterEqual(args[4], 0)
        self.assertNotIn("FAKE_SECRET", repr(record.call_args))
        pending.task_done.assert_called_once()

    def test_legacy_audit_scrubs_complete_sensitive_payloads(self):
        for command in ("/adduser alice FAKE_SECRET admin", "/password alice FAKE_SECRET",
                        "run:/exec echo FAKE_SECRET", "/rclone token drive drive FAKE_SECRET"):
            self.assertNotIn("FAKE_SECRET", rm._scrub_secrets(command))


class DiagnosticSubprocessTests(unittest.TestCase):
    def test_subprocess_timeout_is_clamped_to_remaining_budget(self):
        with mock.patch.object(rm, "_orig_sub_run") as native, deadline_scope(1):
            rm._quiet_run(["FAKE"], timeout=600)
        self.assertGreater(native.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(native.call_args.kwargs["timeout"], 1)

    def test_expired_deadline_never_starts_subprocess(self):
        with mock.patch.object(rm, "_orig_sub_run") as native, deadline_scope(0):
            with self.assertRaises(TimeoutError):
                rm._quiet_run(["FAKE"])
        native.assert_not_called()

    def test_non_diagnostic_subprocess_timeout_is_unchanged(self):
        with mock.patch.object(rm, "_orig_sub_run") as native:
            rm._quiet_run(["FAKE"], timeout=600)
        self.assertEqual(native.call_args.kwargs["timeout"], 600)


class UpstreamRedactionTests(unittest.TestCase):
    def test_sensitive_values_of_all_json_types_are_masked(self):
        data = {"credentials": {"nested": "FAKE_SECRET"}, "api_key": 12345,
                "passwords": ["FAKE_SECRET"], "normal": "visible"}
        masked = rm._redact_config(data)
        self.assertNotIn("FAKE_SECRET", json.dumps(masked))
        self.assertEqual(masked["api_key"], "***redacted***")
        self.assertEqual(masked["normal"], "visible")
        for key in ("api_hash", "authorization", "connection_string"):
            self.assertEqual(rm._redact_config({key: "FAKE_SECRET"})[key], "***redacted***")

    def test_bot_file_uses_same_redaction_as_panel(self):
        captured = {}
        def send(path, *args):
            captured["text"] = Path(path).read_text(encoding="utf-8")
            return False
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rm, "config", {"api_key": "FAKE_SECRET"}), \
                mock.patch.object(rm.tempfile, "tempdir", directory), \
                mock.patch.object(rm, "send_document", side_effect=send):
            rm.config_backup_job()
        self.assertNotIn("FAKE_SECRET", captured["text"])
