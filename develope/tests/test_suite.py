import json
import copy
import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rdp_suite

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backup" / "app"))
import scheduler as backup_scheduler  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class _StubTG:
    """Minimal Telegram stand-in that reports chosen delivery counts."""
    temp_session = False
    last_backup_info = ""

    def __init__(self, delivered=0, failed=0):
        self._delivered, self._failed = delivered, failed

    def is_configured(self):
        return True

    def send_file(self, path):
        return True

    def send_message(self, text):
        return True

    def reset_delivery(self):
        pass

    def wait_delivery(self, timeout=3600):
        return self._delivered, self._failed


class SuiteTests(unittest.TestCase):
    def setUp(self):
        import logger_utils
        import config_manager
        self._runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self._runtime.cleanup)
        root = Path(self._runtime.name)
        for module, name, path in (
                (logger_utils, "LOG_DIR", root / "logs"),
                (config_manager, "CONFIG_FILE", root / "config.json"),
                (backup_scheduler, "STATE_FILE", root / "last_run.json"),
                (backup_scheduler, "RESULT_FILE", root / "last_result.json")):
            patcher = mock.patch.object(module, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_backup_request_is_bounded_and_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            control = Path(td)
            with mock.patch.object(rdp_suite, "CONTROL_DIR", str(control)), \
                    mock.patch.object(rdp_suite, "CONTROL_REQUEST", str(control / "request.json")):
                request_id = rdp_suite.request_backup()
                body = json.loads((control / "request.json").read_text(encoding="utf-8"))
                self.assertEqual(body["action"], "backup")
                self.assertEqual(body["id"], request_id)
                with self.assertRaises(RuntimeError):
                    rdp_suite.request_backup()

    def test_archive_verification_ignores_only_generated_manifest(self):
        import zipfile
        import backup_engine
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "Backup_test.zip"
            manifest = "2026-01-01_00-00-00/manifest.txt"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(manifest, "index")
                zf.writestr("2026-01-01_00-00-00/C/inetpub/wwwroot/manifest.txt", "user file")
                zf.writestr("2026-01-01_00-00-00/C/data/notes.txt", "user file")
            ok, _msg = backup_engine.verify_archive(
                str(archive), expected_count=2, manifest_name=manifest)
            self.assertTrue(ok)

    def test_ok_result_records_success(self):
        cfg = {"backup": {"engine": "zip"}, "cloud": {"remotes": []}, "telegram": {},
               "monitoring": {}, "schedule": {"retry_count": 3, "retry_delay_minutes": 1}}
        recorded = []
        with mock.patch.object(backup_scheduler, "run_hook", return_value=True), \
                mock.patch.object(backup_scheduler, "_zip_job", return_value=("ok", "ok report")), \
                mock.patch.object(backup_scheduler, "record_successful_run",
                                  side_effect=lambda *a, **k: recorded.append(a)), \
                mock.patch.object(backup_scheduler.monitor, "ping"):
            result = backup_scheduler.run_full_backup(cfg)
        self.assertEqual(result, "ok")
        self.assertEqual(len(recorded), 1)

    def test_partial_result_is_not_recorded_as_success(self):
        cfg = {"backup": {"engine": "zip"}, "cloud": {"remotes": []}, "telegram": {},
               "monitoring": {}, "schedule": {"retry_count": 3, "retry_delay_minutes": 1}}
        recorded = []
        with mock.patch.object(backup_scheduler, "run_hook", return_value=True), \
                mock.patch.object(backup_scheduler, "_zip_job", return_value=("partial", "partial report")), \
                mock.patch.object(backup_scheduler, "record_successful_run",
                                  side_effect=lambda *a, **k: recorded.append(a)), \
                mock.patch.object(backup_scheduler.monitor, "ping"):
            result = backup_scheduler.run_full_backup(cfg)
        self.assertEqual(result, "partial")
        self.assertEqual(recorded, [])

    def test_encryption_fails_closed_without_pyzipper(self):
        import backup_engine
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.txt"
            src.write_text("data", encoding="utf-8")
            old_dir = backup_engine.BACKUP_DIR
            backup_engine.BACKUP_DIR = str(Path(td) / "out")
            try:
                with mock.patch.object(backup_engine, "HAS_PYZIPPER", False):
                    with self.assertRaises(ValueError):
                        backup_engine.create_backup(
                            {"backup": {"sources": [str(src)], "archive_password": "pw",
                                        "use_vss": False, "verify": False}})
            finally:
                backup_engine.BACKUP_DIR = old_dir

    def test_missing_source_aborts_backup(self):
        import backup_engine
        with tempfile.TemporaryDirectory() as td:
            old_dir = backup_engine.BACKUP_DIR
            backup_engine.BACKUP_DIR = str(Path(td) / "out")
            try:
                with self.assertRaises(ValueError):
                    backup_engine.create_backup(
                        {"backup": {"sources": [str(Path(td) / "does-not-exist")],
                                    "use_vss": False, "verify": False}})
            finally:
                backup_engine.BACKUP_DIR = old_dir

    def test_backup_restore_round_trip(self):
        import backup_engine
        import restore
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "a.txt").write_text("hello", encoding="utf-8")
            (src / "b.bin").write_bytes(b"\x00\x01\x02")
            old = backup_engine.BACKUP_DIR
            backup_engine.BACKUP_DIR = str(Path(td) / "out")
            try:
                files, status = backup_engine.create_backup(
                    {"backup": {"sources": [str(src)], "use_vss": False, "verify": True}})
                self.assertIn(status, ("ok", "partial"))
                dest = str(Path(td) / "restore")
                res = restore.restore_archive(files[0], dest)
                self.assertEqual(res["status"], "ok", res)
                found = list(Path(dest).rglob("a.txt"))
                self.assertTrue(found)
                self.assertEqual(found[0].read_text(encoding="utf-8"), "hello")
            finally:
                backup_engine.BACKUP_DIR = old

    def test_restore_rejects_zip_slip(self):
        import zipfile
        import restore
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "Backup_evil.zip"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("../evil.txt", "x")
            res = restore.restore_archive(str(arc), str(Path(td) / "dest"))
            self.assertEqual(res["status"], "error")

    def test_config_is_versioned(self):
        import config_manager
        old = config_manager.CONFIG_FILE
        with tempfile.TemporaryDirectory() as td:
            config_manager.CONFIG_FILE = str(Path(td) / "config.json")
            try:
                cfg = {"backup": {}, "cloud": {}, "telegram": {}, "monitoring": {},
                       "schedule": {}, "general": {}, "restic": {}}
                config_manager.save_config(cfg)
                self.assertEqual(config_manager.config_version(cfg),
                                 config_manager.SCHEMA_VERSION)
            finally:
                config_manager.CONFIG_FILE = old

    def _run_zip_job(self, delivered, failed):
        import backup_engine
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "src"
            src.mkdir()
            (src / "a.txt").write_text("hello", encoding="utf-8")
            old = backup_engine.BACKUP_DIR
            old_result = backup_scheduler.RESULT_FILE
            backup_engine.BACKUP_DIR = str(td / "out")
            backup_scheduler.RESULT_FILE = str(td / "last_result.json")
            try:
                cfg = {"backup": {"engine": "zip", "sources": [str(src)],
                                  "use_vss": False, "verify": True},
                       "telegram": {"send_file": True, "send_report": True,
                                    "direct_max_mb": 45, "verify_delivery": True,
                                    "delivery_timeout": 1},
                       "cloud": {"remotes": []},
                       "schedule": {"retry_count": 1, "retry_delay_minutes": 1},
                       "monitoring": {}}
                return backup_scheduler._zip_job(
                    cfg, _StubTG(delivered, failed), "manual",
                    datetime.datetime.now(), None, None)[0]
            finally:
                backup_engine.BACKUP_DIR = old
                backup_scheduler.RESULT_FILE = old_result

    def test_queued_but_undelivered_is_partial(self):
        self.assertEqual(self._run_zip_job(0, 0), "partial")

    def test_confirmed_delivery_is_ok(self):
        self.assertEqual(self._run_zip_job(1, 0), "ok")

    def test_delivery_failure_is_partial(self):
        self.assertEqual(self._run_zip_job(0, 1), "partial")

    def test_restore_rejects_missing_manifest(self):
        import zipfile
        import restore
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "Backup_n.zip"
            with zipfile.ZipFile(arc, "w") as z:
                z.writestr("s/C/a.txt", "hello")
            res = restore.restore_archive(str(arc), str(Path(td) / "d"))
            self.assertEqual(res["status"], "error")

    def test_restore_rejects_malformed_manifest(self):
        import zipfile
        import restore
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "Backup_b.zip"
            with zipfile.ZipFile(arc, "w") as z:
                z.writestr("s/manifest.txt", "garbage")
                z.writestr("s/C/a.txt", "hello")
            res = restore.restore_archive(str(arc), str(Path(td) / "d"))
            self.assertEqual(res["status"], "error")

    def test_restore_rejects_wrong_content_same_size(self):
        import zipfile
        import zlib
        import restore
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "Backup_w.zip"
            good_crc = zlib.crc32(b"hello") & 0xFFFFFFFF
            with zipfile.ZipFile(arc, "w") as z:
                z.writestr("s/manifest.txt",
                           "h\nc\ns/C/a.txt\t5\tC:/a.txt\t%08x\n" % good_crc)
                z.writestr("s/C/a.txt", "XXXXX")  # same size, wrong content
            res = restore.restore_archive(str(arc), str(Path(td) / "d"))
            self.assertEqual(res["status"], "error")

    def test_restore_refuses_nonempty_destination(self):
        import backup_engine
        import restore
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "a.txt").write_text("hello", encoding="utf-8")
            old = backup_engine.BACKUP_DIR
            backup_engine.BACKUP_DIR = str(Path(td) / "out")
            try:
                files, _ = backup_engine.create_backup(
                    {"backup": {"sources": [str(src)], "use_vss": False, "verify": True}})
                dest = str(Path(td) / "restore")
                self.assertEqual(restore.restore_archive(files[0], dest)["status"], "ok")
                self.assertEqual(restore.restore_archive(files[0], dest)["status"], "error")
            finally:
                backup_engine.BACKUP_DIR = old

    def test_config_revision_increments(self):
        import config_manager
        old = config_manager.CONFIG_FILE
        with tempfile.TemporaryDirectory() as td:
            config_manager.CONFIG_FILE = str(Path(td) / "config.json")
            try:
                cfg = {"backup": {}, "cloud": {}, "telegram": {}, "monitoring": {},
                       "schedule": {}, "general": {}, "restic": {}}
                config_manager.save_config(cfg)
                first = config_manager.config_revision(cfg)
                config_manager.save_config(cfg)
                second = config_manager.config_revision(cfg)
                self.assertEqual(second, first + 1)
            finally:
                config_manager.CONFIG_FILE = old

    

    def test_invalid_config_does_not_replace_running_settings(self):
        import main
        import config_manager

        class EndWatch(Exception):
            pass

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text("{}", encoding="utf-8")
            cfg = {"backup": {"sources": ["important-source"]}, "telegram": {}}
            sleeps = iter([None, EndWatch()])

            def advance(_):
                next_step = next(sleeps)
                if next_step is not None:
                    raise next_step
                path.write_text("{bad json", encoding="utf-8")

            with mock.patch.object(config_manager, "CONFIG_FILE", str(path)), \
                    mock.patch.object(main.time, "sleep", side_effect=advance), \
                    mock.patch.object(main.cloud_uploader, "configure") as configure:
                with self.assertRaises(EndWatch):
                    main._config_watch(cfg)
            self.assertEqual(cfg["backup"]["sources"], ["important-source"])
            configure.assert_not_called()

    def test_failed_link_message_is_partial(self):
        import backup_engine
        import cloud_uploader
        import config_manager

        class FailedMessageTG(_StubTG):
            def send_message(self, text):
                return False

        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "Backup_large.zip"
            archive.write_bytes(b"archive")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["cloud"].update(remotes=["drive:"], allow_share_links=True)
            cfg["telegram"].update(direct_max_mb=1, send_report=False)
            stats = {"size": 2 * 1024 * 1024, "count": 1, "encrypted": True,
                     "verified": True}
            with mock.patch.object(backup_engine, "create_backup",
                                   return_value=([str(archive)], "ok")), \
                    mock.patch.object(backup_engine, "LAST_STATS", stats), \
                    mock.patch.object(cloud_uploader, "is_available", return_value=True), \
                    mock.patch.object(cloud_uploader, "upload_to_cloud",
                                      return_value=[("drive:", True, "verified")]), \
                    mock.patch.object(cloud_uploader, "get_share_link",
                                      return_value={"drive:": "https://example.invalid/link"}):
                status, _ = backup_scheduler._zip_job(
                    cfg, FailedMessageTG(), "manual", datetime.datetime.now(), None, None)
            self.assertEqual(status, "partial")

    def test_failed_manifest_write_discards_backup(self):
        import backup_engine
        import config_manager
        import zipfile

        original = zipfile.ZipFile.writestr

        def fail_manifest(zf, name, data, *args, **kwargs):
            if str(name).endswith("/manifest.txt"):
                raise OSError("simulated manifest write failure")
            return original(zf, name, data, *args, **kwargs)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            (source / "file.txt").write_text("hello", encoding="utf-8")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["backup"]["sources"] = [str(source)]
            out = Path(td) / "out"
            with mock.patch.object(backup_engine, "BACKUP_DIR", str(out)), \
                    mock.patch.object(zipfile.ZipFile, "writestr", fail_manifest):
                files, status = backup_engine.create_backup(cfg)
            self.assertEqual((files, status), ([], "error"))
            self.assertEqual(list(out.glob("Backup_*.zip")), [])

    def test_generated_manifest_contains_file_crc(self):
        import backup_engine
        import config_manager
        import zipfile
        import zlib

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "file.txt"
            source.write_bytes(b"hello")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["backup"]["sources"] = [str(source)]
            with mock.patch.object(backup_engine, "BACKUP_DIR", str(Path(td) / "out")):
                files, status = backup_engine.create_backup(cfg)
            self.assertEqual(status, "ok")
            with zipfile.ZipFile(files[0]) as archive:
                name = next(n for n in archive.namelist() if n.endswith("/manifest.txt"))
                entry = archive.read(name).decode("utf-8").splitlines()[2].split("\t")
            self.assertEqual(int(entry[3], 16), zlib.crc32(b"hello"))

    def test_encrypted_backup_restore_round_trip_when_pyzipper_available(self):
        import backup_engine
        import config_manager
        import restore

        if not backup_engine.HAS_PYZIPPER:
            self.skipTest("pyzipper not installed")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "secret.txt"
            source.write_bytes(b"encrypted content")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["backup"].update(sources=[str(source)],
                                 archive_password="temporary-test-password")
            with mock.patch.object(backup_engine, "BACKUP_DIR", str(Path(td) / "out")):
                files, status = backup_engine.create_backup(cfg)
            self.assertEqual(status, "ok")
            result = restore.restore_archive(
                files[0], str(Path(td) / "restored"),
                password="temporary-test-password")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["checked"], 1)

    def test_partial_backup_does_not_prune_previous_local_copy(self):
        import backup_engine
        import config_manager

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            previous = out / "Backup_2026-01-01_03-00-00.zip"
            partial = out / "Backup_2026-01-02_03-00-00.zip"
            previous.write_bytes(b"previous-good")
            partial.write_bytes(b"new-partial")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["telegram"]["send_file"] = False
            with mock.patch.object(backup_engine, "BACKUP_DIR", str(out)), \
                    mock.patch.object(backup_engine, "create_backup",
                                      return_value=([str(partial)], "partial")), \
                    mock.patch.object(backup_engine, "LAST_STATS",
                                      {"size": len(b"new-partial"), "count": 1,
                                       "archive": str(partial), "signature": "same"}), \
                    mock.patch.object(backup_scheduler.monitor, "ping"), \
                    mock.patch.object(backup_scheduler, "record_successful_run"), \
                    mock.patch.object(backup_engine, "cleanup_old_local") as cleanup:
                result = backup_scheduler.run_full_backup(cfg, manual=True)
            self.assertEqual(result, "partial")
            self.assertTrue(previous.exists())
            cleanup.assert_not_called()

    def test_successful_delivery_prunes_only_after_job_is_ok(self):
        import backup_engine
        import config_manager

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            previous = out / "Backup_2026-01-01_03-00-00.zip"
            current = out / "Backup_2026-01-02_03-00-00.zip"
            previous.write_bytes(b"previous")
            current.write_bytes(b"current")
            cfg = copy.deepcopy(config_manager.DEFAULT_CONFIG)
            cfg["telegram"]["send_file"] = False
            cfg["backup"]["keep_local_copies"] = 1
            cfg["cloud"]["remotes"] = []          # isolate from the real cloud remote
            with mock.patch.object(backup_engine, "BACKUP_DIR", str(out)), \
                    mock.patch.object(backup_engine, "LOCAL_STATE_FILE",
                                      str(out / "local_state.json")), \
                    mock.patch.object(backup_engine, "RECENCY_GUARD", 0), \
                    mock.patch.object(backup_engine, "create_backup",
                                      return_value=([str(current)], "ok")), \
                    mock.patch.object(backup_engine, "LAST_STATS",
                                      {"size": len(b"current"), "count": 1,
                                       "archive": str(current), "signature": "same"}), \
                    mock.patch.object(backup_scheduler.monitor, "ping"), \
                    mock.patch.object(backup_scheduler, "record_successful_run"):
                result = backup_scheduler.run_full_backup(cfg, manual=True)
            self.assertEqual(result, "ok")
            self.assertFalse(previous.exists())
            self.assertTrue(current.exists())

    

    

    

    

    def test_failed_scheduled_attempt_is_not_repeated_after_restart(self):
        old_state = backup_scheduler.STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as td:
                backup_scheduler.STATE_FILE = str(Path(td) / "last_run.json")
                now = datetime.datetime.now().replace(hour=4, minute=0, second=0, microsecond=0)
                backup_scheduler.record_attempt(now)
                scheduler = backup_scheduler.DailyScheduler(
                    {"schedule": {"enabled": True, "time": "03:00"}})
                self.assertFalse(scheduler._due(now))
        finally:
            backup_scheduler.STATE_FILE = old_state


if __name__ == "__main__":
    unittest.main()
