import html
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_messages import message_pages
import rdp_monitor as bot


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(); self.text = ''; self.stack = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        assert self.stack.pop() == tag
    def handle_data(self, data): self.text += data


class MobilePagesTests(unittest.TestCase):
    def test_long_nested_html_preserves_every_character_and_balances_pages(self):
        text = '<b>Report</b>\n<pre>' + html.escape(('worker <one> & RAM\n' * 100) + 'الذاكرة 12 GB') + '</pre>'
        pages = message_pages(text)
        restored = ''
        for page in pages:
            parser = Visible(); parser.feed(page)
            self.assertFalse(parser.stack)
            self.assertLess(len(page), 3900)
            restored += parser.text
        original = Visible(); original.feed(text)
        self.assertEqual(restored, original.text)
        self.assertGreater(len(pages), 1)

    def test_link_targets_and_entities_are_never_split(self):
        pages = message_pages('<a href="https://example.com/?x=1&amp;y=2">'+ ('A&amp;B ' * 500) + '</a>')
        self.assertTrue(all('href="https://example.com/?x=1&amp;y=2"' in p for p in pages))
        for page in pages:
            parser = Visible(); parser.feed(page); self.assertFalse(parser.stack)

    def test_wrapped_rows_count_toward_mobile_page_height(self):
        pages = message_pages('<pre>'+'x'*200+'</pre>', rows=3, columns=20)
        self.assertEqual(len(pages), 4)
        self.assertTrue(all(len(p.removeprefix('<pre>').removesuffix('</pre>'))<=60 for p in pages))

    def test_invalid_legacy_html_falls_back_without_losing_text(self):
        text = '<b>unfinished & data'
        self.assertEqual(html.unescape(''.join(message_pages(text))), text)

    def test_paging_edits_only_the_original_chat_and_does_not_execute_commands(self):
        with mock.patch.object(bot, '_message_views', {}), \
             mock.patch.object(bot, '_alert_targets', return_value=['123']), \
             mock.patch.object(bot, 'tg_api', return_value={'ok':True, 'result':{'message_id':1}}) as api, \
             mock.patch.object(bot, 'handle_command') as execute:
            self.assertTrue(bot.send_paged_message('<pre>'+('line\n'*50)+'</pre>'))
            token = next(iter(bot._message_views))
            callback = {'id':'cb', 'data':f'pg:{token}:1', 'message':{'chat':{'id':123}, 'message_id':1}}
            bot.handle_message_page(callback)
            self.assertTrue(any(c.args[0]=='editMessageText' for c in api.call_args_list))
            api.reset_mock()
            callback['message']['chat']['id'] = 456
            bot.handle_message_page(callback)
            self.assertEqual([c.args[0] for c in api.call_args_list], ['answerCallbackQuery'])
            callback['message']['chat']['id'] = 123
            bot._message_views[token]['time'] -= 601
            api.reset_mock(); bot.handle_message_page(callback)
            self.assertEqual([c.args[0] for c in api.call_args_list], ['answerCallbackQuery'])
            execute.assert_not_called()

    def test_top_defaults_to_five_cpu_processes_and_offers_memory_and_next_page(self):
        processes = [(f'worker{i}', i, 7.5, 574) for i in range(1,11)]
        with mock.patch.object(bot, 'get_top_processes', return_value=(processes,processes)), \
             mock.patch.object(bot, 'send_buttons') as send:
            bot.send_top_report()
            text, rows = send.call_args.args
            self.assertIn('worker5', text); self.assertNotIn('worker6', text)
            self.assertNotIn('By memory', text)
            self.assertIn('tp:ram:1', str(rows)); self.assertIn('tp:cpu:2', str(rows))
            bot.send_top_report(['ram','2'])
            text = send.call_args.args[0]
            self.assertIn('worker6', text); self.assertIn('worker10', text)
            self.assertNotIn('worker5', text)

    def test_idle_process_is_excluded_and_cpu_uses_total_machine_capacity(self):
        idle = mock.Mock(info={'pid':0, 'name':'System Idle Process', 'memory_info':None})
        worker = mock.Mock(info={'pid':123, 'name':'worker', 'memory_info':SimpleNamespace(rss=1024**2)})
        worker.cpu_percent.return_value = 400
        with mock.patch.object(bot.psutil, 'process_iter', return_value=[idle,worker]), \
             mock.patch.object(bot.psutil, 'cpu_count', return_value=8), \
             mock.patch.object(bot.time, 'sleep'):
            cpu, ram = bot.get_top_processes()
        self.assertEqual(cpu, [('worker',123,50,1)])
        self.assertEqual(ram, cpu)
        idle.cpu_percent.assert_not_called()

    def test_normal_snapshot_fits_one_mobile_page(self):
        with mock.patch.object(bot, 'get_usage', return_value=(7.5,46.7,5.6,12)), \
             mock.patch.object(bot, 'get_disks', return_value=[('C:\\',34,132,200)]), \
             mock.patch.object(bot.psutil, 'users', return_value=[object()]):
            self.assertEqual(len(message_pages(bot.message_layout(bot.format_report()))), 1)

    def test_failed_queries_do_not_claim_clean_or_empty_results(self):
        failed = subprocess.CompletedProcess([], 1, b'', b'Unavailable')
        with mock.patch.object(bot.subprocess, 'run', return_value=failed), \
             mock.patch.object(bot, 'send_message') as send:
            self.assertIsNone(bot.fetch_diagnosis_events(60))
            for job in (bot.bigfiles_job, bot.startup_job, bot.updates_job):
                send.reset_mock(); job()
                self.assertIn('[X]', send.call_args.args[0])
                self.assertNotIn('no pending restart', send.call_args.args[0])

    def test_missing_backup_progress_is_not_reported_as_active(self):
        with mock.patch.object(bot, '_read_json', return_value={}):
            self.assertNotIn('Backup in progress', bot.backup_progress_text())

    def test_every_catalog_command_and_argument_case_has_a_safe_response(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/audit_bot_messages.py')],
                                cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(set(bot.COMMAND_INFO), {c['command'] for c in report['commands'] if ' ' not in c['command']})
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['no_response'], [])
        self.assertTrue(all(not c['mutation_executed'] for c in report['commands']))
        for case in report['commands']:
            if ' ' not in case['command']:
                for response in case['review_responses']:
                    self.assertEqual(len(message_pages(response['text'])), 1, case['command'])


if __name__ == '__main__':
    unittest.main()
