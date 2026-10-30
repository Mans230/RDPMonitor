import copy
import unittest
from unittest import mock
import rdp_monitor as rm
from resource_alerts import ResourceAlertPolicy


class AlertsQueryTests(unittest.TestCase):
    def test_user_failure_and_invalid_json_are_not_empty_success(self):
        for response in (mock.Mock(returncode=1, stdout=b""),
                         mock.Mock(returncode=0, stdout=b"invalid"),
                         mock.Mock(returncode=0, stdout=b'[{}]')):
            with mock.patch.object(rm.subprocess, "run", return_value=response):
                ok, error = rm.api_users_list()
                self.assertFalse(ok)
                self.assertIsInstance(error, str)
        with mock.patch.object(rm.subprocess, "run", side_effect=OSError("failed")):
            self.assertFalse(rm.api_users_list()[0])

    def test_valid_empty_query_is_distinct_from_failure(self):
        with mock.patch.object(rm.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=b'[]')):
            self.assertEqual(rm.api_users_list(), (True, []))

    def test_failed_remote_query_offers_retry_without_creation_advice(self):
        with mock.patch.object(rm, "_rclone_run", return_value=(False, "query failed")), \
                mock.patch.object(rm, "send_buttons") as send:
            rm.rclone_remotes_menu()
        text, rows = send.call_args.args
        self.assertIn("query failed", text)
        self.assertNotIn("None yet", text)
        self.assertIn(("Retry", "rc:list"), rows[0])

    def test_critical_bypasses_mute_but_does_not_repeat_each_sample(self):
        cfg = copy.deepcopy(rm.DEFAULT_CONFIG)
        policy = ResourceAlertPolicy()
        self.assertIsNone(policy.observe(85, 10, 10000, cfg, muted=True))
        self.assertEqual(policy.observe(99, 10, 10001, cfg, muted=True)["level"], "critical")
        self.assertIsNone(policy.observe(99, 10, 10002, cfg, muted=True))
        with mock.patch.object(rm, "alerts_muted", return_value=True), \
                mock.patch.object(rm, "send_message") as send, \
                mock.patch.object(rm, "config", cfg):
            rm.send_usage_alert(99, 10, 1, 10, "critical")
            send.assert_called_once()

    def test_settings_explain_effective_reminder_and_hold_times(self):
        with mock.patch.object(rm, "config", copy.deepcopy(rm.DEFAULT_CONFIG)):
            interval = next(x for g in rm.settings_snapshot() for x in g["items"] if x["key"] == "interval")
        self.assertEqual(interval["value"], 300)
        self.assertIn("1800s", interval["help"])
        self.assertIn("120s", interval["help"])
        self.assertIn("critical bypasses mute", interval["help"])
