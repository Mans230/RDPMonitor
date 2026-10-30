import copy
import unittest
from unittest import mock

import rdp_monitor as rm
from bot_catalog import OWNERS
from resource_alerts import ResourceAlertPolicy


class BotCatalogTests(unittest.TestCase):
    def test_each_visible_command_has_one_owner(self):
        seen = []
        for page, (_, items) in rm.MENU_PAGES.items():
            if page == "root":
                continue
            seen.extend(data[4:].split()[0] for _, data in items if data.startswith("cmd:"))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertNotIn("/token", seen)
        self.assertEqual(set(rm.COMMAND_INFO) - set(OWNERS), set())

    def test_opening_command_card_does_not_execute_even_safe_commands(self):
        with mock.patch.object(rm, "handle_command") as run, mock.patch.object(rm, "send_buttons"), \
                mock.patch.object(rm, "send_message"):
            rm.show_command_info("/view")
        run.assert_not_called()

    def test_every_catalog_command_opens_a_card_without_executing(self):
        with mock.patch.object(rm, "handle_command") as run, \
                mock.patch.object(rm, "send_buttons") as buttons, \
                mock.patch.object(rm, "send_message"), mock.patch.object(rm, "_pending", {}):
            for command in rm.COMMAND_INFO:
                if command == "/noop":
                    continue
                with self.subTest(command=command):
                    buttons.reset_mock()
                    rm.show_command_info(command)
                    self.assertTrue(buttons.called)
                    self.assertIn("Usage:", buttons.call_args.args[0])
                    rows = buttons.call_args.args[1]
                    for row in rows:
                        for _, data in row:
                            self.assertLessEqual(len(data.encode("utf-8")), 64)
            run.assert_not_called()

    def test_legacy_execute_button_requires_new_review_then_one_confirmation(self):
        with mock.patch.object(rm, "handle_command") as run, \
                mock.patch.object(rm, "send_buttons") as buttons, \
                mock.patch.object(rm, "send_message"), mock.patch.object(rm, "_pending", {}):
            rm.handle_run_callback("/panic on confirm")
            run.assert_not_called()
            callback = buttons.call_args.args[1][0][0][1]
            self.assertTrue(callback.startswith("cf:"))
            rm.handle_pending(callback[3:])
            run.assert_called_once_with("/panic on confirm")
            rm.handle_pending(callback[3:])
            run.assert_called_once()

    def test_read_only_run_button_executes_once_after_review(self):
        with mock.patch.object(rm, "handle_command") as run, \
                mock.patch.object(rm, "send_buttons") as buttons, \
                mock.patch.object(rm, "send_message"), mock.patch.object(rm, "_pending", {}):
            rm.show_command_info("/view")
            callback = buttons.call_args.args[1][0][0][1]
            self.assertTrue(callback.startswith("rv:"))
            rm.handle_reviewed_command(callback[3:])
            rm.handle_reviewed_command(callback[3:])
            run.assert_called_once_with("/view")

    def test_telegram_registry_has_valid_unique_commands_and_descriptions(self):
        self.assertLessEqual(len(rm.BOT_MENU), 100)
        self.assertEqual(len(rm.BOT_MENU), len({item['command'] for item in rm.BOT_MENU}))
        for item in rm.BOT_MENU:
            self.assertRegex(item['command'], r'^[a-z0-9_]{1,32}$')
            self.assertTrue(1 <= len(item['description']) <= 256)


class UnifiedResourceAlertTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(rm.DEFAULT_CONFIG)
        self.policy = ResourceAlertPolicy()

    def test_threshold_and_spike_produce_one_combined_decision(self):
        self.assertIsNone(self.policy.observe(10, 10, 10000, self.config))
        notice = self.policy.observe(90, 75, 10050, self.config)
        self.assertEqual(notice["kind"], "threshold")
        self.assertIsNotNone(notice["spike"])
        self.assertIsNone(self.policy.observe(91, 75, 10055, self.config))

    def test_downgrade_is_not_treated_as_escalation(self):
        self.policy.observe(99, 10, 10000, self.config)
        self.assertIsNone(self.policy.observe(85, 10, 10005, self.config))
        self.assertIsNone(self.policy.observe(60, 10, 10010, self.config))

    def test_real_escalation_is_immediate_and_recovery_is_sent_once(self):
        self.policy.observe(55, 10, 10000, self.config)
        self.assertEqual(self.policy.observe(99, 10, 10005, self.config)["level"], "critical")
        self.assertIsNone(self.policy.observe(10, 10, 10010, self.config))
        notice = self.policy.observe(10, 10, 10190, self.config)
        self.assertEqual(notice["kind"], "recovery")
        self.assertEqual(notice["peak_cpu"], 99)
        self.assertEqual(notice["duration"], 190)
        self.assertIsNone(self.policy.observe(10, 10, 10195, self.config))

    def test_screenshot_fluctuation_produces_no_notifications(self):
        self.config["ram_alert_threshold"] = 50
        for index in range(300):
            ram = (50.6, 48.5, 50.4, 48.0)[index % 4]
            self.assertIsNone(self.policy.observe(3, ram, 10000+index*5, self.config))

    def test_sustained_warning_and_brief_dips_stay_one_incident(self):
        self.config["ram_alert_threshold"] = 50
        self.assertIsNone(self.policy.observe(10, 51, 10000, self.config))
        self.assertEqual(self.policy.observe(10, 51, 10120, self.config)["kind"], "threshold")
        for index in range(100):
            self.assertIsNone(self.policy.observe(10, (49, 51)[index % 2],
                                                  10125+index*5, self.config))
        self.assertIsNone(self.policy.observe(10, 44, 10700, self.config))
        self.assertIsNone(self.policy.observe(10, 49, 10870, self.config))
        self.assertIsNone(self.policy.observe(10, 44, 10875, self.config))
        self.assertEqual(self.policy.observe(10, 44, 11055, self.config)["kind"], "recovery")

    def test_muted_incident_never_emits_orphan_recovery(self):
        self.assertIsNone(self.policy.observe(99, 10, 10000, self.config, muted=True))
        self.assertIsNone(self.policy.observe(10, 10, 10010, self.config))
        self.assertIsNone(self.policy.observe(10, 10, 10190, self.config))

    def test_reminder_is_limited_and_downgrade_never_realerts(self):
        self.policy.observe(99, 10, 10000, self.config)
        self.assertIsNone(self.policy.observe(99, 10, 10900, self.config))
        self.assertEqual(self.policy.observe(99, 10, 11800, self.config)["kind"], "threshold")
        self.assertIsNone(self.policy.observe(85, 10, 14000, self.config))
