import sys
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rdp_monitor as bot


class UnifiedUpdateCommandTests(unittest.TestCase):
    def test_unconfirmed_update_only_shows_suite_confirmation(self):
        with mock.patch('suite_update.Manager') as manager, mock.patch.object(bot, 'send_buttons') as send:
            bot.handle_command('/update')
        manager.assert_not_called()
        self.assertIn('bot and web panel', send.call_args.args[0])

    def test_confirmed_update_queues_suite_without_url_and_never_runs_single_file_updater(self):
        with mock.patch.dict(bot.config, update_url='', update_hash=''), \
             mock.patch('suite_update.Manager') as manager, \
             mock.patch.object(bot, 'update_self') as legacy, \
             mock.patch.object(bot, 'send_message') as send:
            manager.return_value.queue.return_value = 'Suite installation queued'
            bot.handle_command('/update confirm')
        manager.return_value.queue.assert_called_once_with('apply')
        legacy.assert_not_called()
        self.assertIn('queued', send.call_args.args[0])

    def test_queue_failure_is_shown_instead_of_claiming_installation(self):
        with mock.patch('suite_update.Manager') as manager, mock.patch.object(bot, 'send_message') as send:
            manager.return_value.queue.side_effect = RuntimeError('Updater task is not installed')
            bot.handle_command('/update confirm')
        self.assertIn('[X]', send.call_args.args[0])
        self.assertIn('not installed', send.call_args.args[0])

    def test_update_review_and_docs_describe_the_unified_release(self):
        with mock.patch.object(bot, 'send_buttons') as send:
            bot.show_command_info('/update')
        self.assertIn('bot + web panel', send.call_args.args[0])
        self.assertNotIn('configured HTTPS URL', bot.docs_card_text('/update'))


if __name__ == '__main__': unittest.main()
