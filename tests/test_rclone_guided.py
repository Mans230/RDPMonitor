import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rdp_monitor as rm


class RcloneMigrationTests(unittest.TestCase):
    def setUp(self):
        self.old_config = rm.config
        rm.config = copy.deepcopy(rm.DEFAULT_CONFIG)

    def tearDown(self):
        rm.config = self.old_config

    def test_suite_managed_rclone_replaces_existing_old_install_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "backup" / "rclone" / "rclone.exe"
            old = root / "old-install" / "rclone.exe"
            local.parent.mkdir(parents=True)
            old.parent.mkdir(parents=True)
            local.write_bytes(b"new")
            old.write_bytes(b"old")
            rm.config["rclone_path"] = str(old)
            with mock.patch.object(rm, "BACKUP_DIR", str(root / "backup")), \
                    mock.patch.object(rm, "save_config") as save, \
                    mock.patch.object(rm, "_rclone_register_config") as register:
                found = rm._find_rclone()
            self.assertEqual(os.path.normcase(found), os.path.normcase(str(local)))
            self.assertEqual(os.path.normcase(rm.config["rclone_path"]),
                             os.path.normcase(str(local)))
            save.assert_called_once_with()
            register.assert_called_once_with()


class RcloneGuidedMenuTests(unittest.TestCase):
    def setUp(self):
        self.old_config = rm.config
        rm.config = copy.deepcopy(rm.DEFAULT_CONFIG)
        rm.config["rclone_remote"] = "gdrive:RDPMonitor-Images"

    def tearDown(self):
        rm.config = self.old_config

    @staticmethod
    def callbacks(rows):
        return [data for row in rows for _label, data in row]

    def test_main_menu_uses_buttons_instead_of_command_wall(self):
        with mock.patch.object(rm, "_rclone_exe", return_value=r"C:\suite\rclone.exe"), \
                mock.patch.object(rm, "_rclone_version", return_value="rclone v1.75.2"), \
                mock.patch.object(rm, "_rclone_remotes", return_value=["gdrive:"]), \
                mock.patch.object(rm, "send_buttons") as send:
            rm.rclone_menu()
        text, rows = send.call_args.args
        callbacks = self.callbacks(rows)
        self.assertIn("Choose an action below", text)
        self.assertNotIn("/rclone auth", text)
        self.assertIn("rc:gdrive", callbacks)
        self.assertIn("rc:onedrive", callbacks)
        self.assertIn("rc:dropbox", callbacks)
        self.assertTrue(all(len(data.encode("utf-8")) <= 64 for data in callbacks))

    def test_provider_button_requires_one_confirmation_then_starts_sign_in(self):
        with mock.patch.object(rm, "_pending", {}), \
                mock.patch.object(rm, "send_buttons") as send, \
                mock.patch.object(rm, "_rclone_start_authorize") as authorize:
            rm.rclone_guided_callback("rc:onedrive")
            callback = send.call_args.args[1][0][0][1]
            self.assertTrue(callback.startswith("cf:"))
            rm.handle_pending(callback[3:])
            rm.handle_pending(callback[3:])
        authorize.assert_called_once_with("onedrive", "onedrive")

    def test_remote_card_exposes_test_use_remove_without_typing(self):
        with mock.patch.object(rm, "_pending", {}), \
                mock.patch.object(rm, "_rclone_remotes", return_value=["gdrive:"]), \
                mock.patch.object(rm, "send_buttons") as send:
            rm.rclone_remotes_menu()
            remote_callback = send.call_args.args[1][0][0][1]
            self.assertTrue(remote_callback.startswith("rr:"))
            rm.rclone_guided_callback(remote_callback)
            callbacks = self.callbacks(send.call_args.args[1])
        self.assertTrue(any(data.startswith("sc:") for data in callbacks))
        self.assertTrue(any(data.startswith("rs:") for data in callbacks))
        self.assertTrue(any(data.startswith("rd:") for data in callbacks))
        self.assertTrue(all(len(data.encode("utf-8")) <= 64 for data in callbacks))

    def test_use_button_confirms_default_image_destination(self):
        rm.config["rclone_remote"] = ""
        with mock.patch.object(rm, "_pending", {}), \
                mock.patch.object(rm, "send_buttons") as send, \
                mock.patch.object(rm, "rclone_set") as set_target:
            rm.rclone_remote_card("gdrive:")
            use_callback = next(data for data in self.callbacks(send.call_args.args[1])
                                if data.startswith("rs:"))
            rm.rclone_guided_callback(use_callback)
            confirm_callback = send.call_args.args[1][0][0][1]
            rm.handle_pending(confirm_callback[3:])
        set_target.assert_called_once_with(["gdrive:RDPMonitor-Images"])


if __name__ == "__main__":
    unittest.main()
