import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rdp_monitor as rm


class MessageReadabilityTests(unittest.TestCase):
    def test_english_direction_and_arabic_direction_are_independent(self):
        text = rm.rtl('CPU: 7.5%\nالذاكرة: 46.7%\nUptime: 6d')
        self.assertEqual(text.splitlines(), ['CPU: 7.5%', rm.RLM + 'الذاكرة: 46.7%', 'Uptime: 6d'])
        self.assertEqual(rm.message_layout(rm.RLM + 'CPU: 7.5%'), 'CPU: 7.5%')

    def test_code_and_command_output_survive_layout_unchanged(self):
        code = '<pre>  CPU   RAM\n  العربية  12\n<b>literal</b>\nkeep\n</pre><code>مثال &lt;file&gt;</code>'
        formatted = rm.message_layout('<b>Status</b>\nReady\n' + code)
        self.assertTrue(formatted.startswith('<b>Status</b>\n\nReady\n'))
        self.assertTrue(formatted.endswith(code))
        self.assertEqual(rm.message_layout(formatted), formatted)

    def test_report_preserves_values_all_drives_and_escapes_names(self):
        with mock.patch.object(rm, 'get_usage', return_value=(7.5, 46.7, 5.6, 12)), \
             mock.patch.object(rm, 'get_disks', return_value=[('C:\\', 34, 132, 200), ('D:<data>', 50, 20, 40)]), \
             mock.patch.object(rm.psutil, 'users', return_value=[object()]), \
             mock.patch.object(rm, 'format_uptime', return_value='6d 4h 53m'), \
             mock.patch.dict(rm._net_speed, down=.5, up=.1):
            text = rm.format_report()
        for value in ['7.5%', '46.7%', '5.60 / 12.00 GB', '0.5 Mbps', '0.1 Mbps',
                      '34% used · 132 GB free', 'D:&lt;data&gt;', '6d 4h 53m']:
            self.assertIn(value, text)
        self.assertNotIn(rm.RLM, text)
        self.assertNotIn('Who', text)

    def test_missing_disk_data_is_explicit(self):
        with mock.patch.object(rm, 'get_usage', return_value=(0, 0, 0, 12)), \
             mock.patch.object(rm, 'get_disks', return_value=[]):
            self.assertIn('<pre>Disks: Unavailable</pre>', rm.format_report())

    def test_network_speed_and_cumulative_volume_keep_distinct_units(self):
        with mock.patch.object(rm.psutil, 'net_io_counters', return_value=SimpleNamespace(bytes_recv=2*1024**3, bytes_sent=1024**3)):
            text = rm.format_net_report()
        self.assertIn('Mbps', text)
        self.assertIn('2.00 GB', text)
        self.assertIn('counter reset', text)

    def test_alert_displays_independent_cpu_and_ram_warning_thresholds(self):
        with mock.patch.object(rm, 'alerts_muted', return_value=False), \
             mock.patch.dict(rm.config, cpu_alert_threshold=70, ram_alert_threshold=80, danger_threshold=90, critical_threshold=95), \
             mock.patch.object(rm, 'send_message') as send:
            rm.send_usage_alert(75, 40, 4.8, 12, 'warning')
        text = send.call_args.args[0]
        self.assertIn('CPU warning: 70%', text)
        self.assertIn('RAM warning: 80%', text)
        self.assertIn('<pre>', text)

    def test_process_cards_retain_pid_and_escape_process_names(self):
        with mock.patch.object(rm, 'get_top_processes', return_value=([('<worker>', 123, 7.5, 1024)], [])):
            text = rm.format_top_report()
        self.assertIn('&lt;worker&gt;', text)
        self.assertIn('PID 123', text)
        self.assertIn('No process data available.', text)
        self.assertIn('<pre>CPU · RAM · PID', text)

    def test_report_blocks_escape_payload_without_nested_formatting(self):
        text = rm.report_card('Test', ('Resources', [('Process', '<worker>&'), ('CPU', '7.5%')]))
        self.assertIn('<b>Resources</b>\n<pre>Process: &lt;worker&gt;&amp;\nCPU: 7.5%</pre>', text)
        self.assertNotIn('<pre><b>', text)

    def test_process_blocks_use_bounded_names_and_small_memory_in_mb(self):
        process = ('A' * 80, 1234, 7.5, 6)
        with mock.patch.object(rm, 'get_top_processes', return_value=([process], [process])):
            text = rm.format_top_report()
        self.assertEqual(text.count('<pre>'), 2)
        self.assertIn('6 MB', text)
        self.assertNotIn('0.01 GB', text)
        self.assertNotIn('A' * 29, text)
        self.assertIn('PID 1234', text)

    def test_long_uptime_and_short_durations(self):
        self.assertEqual(rm.format_duration((148*60+53)*60), '6d 4h 53m')
        self.assertEqual(rm.format_duration(30), 'Under 1m')
        self.assertEqual(rm.format_duration(-1), 'Under 1m')


if __name__ == '__main__':
    unittest.main()
