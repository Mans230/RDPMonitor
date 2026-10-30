import copy
from datetime import date, datetime
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from bandwidth import TrafficLedger, adapter_rates, usage_summary
import rdp_monitor as rm


class BandwidthAccountingTests(unittest.TestCase):
    def test_fresh_baseline_never_attributes_boot_totals_to_today(self):
        ledger = TrafficLedger({}, 10, 1000)
        self.assertEqual(ledger.observe({'eth': {'bytes_sent': 50000, 'bytes_recv': 90000}}, 1000), (0, 0))
        self.assertEqual(ledger.observe({'eth': {'bytes_sent': 51000, 'bytes_recv': 92000}}, 1030), (2000, 1000))

    def test_restart_resumes_from_atomic_snapshot_without_double_counting(self):
        ledger = TrafficLedger({}, 10, 1000)
        ledger.observe({'eth': {'bytes_sent': 100, 'bytes_recv': 200}}, 1000)
        ledger.observe({'eth': {'bytes_sent': 200, 'bytes_recv': 500}}, 1030)
        resumed = TrafficLedger(ledger.snapshot(), 10, 1090)
        self.assertEqual(resumed.observe({'eth': {'bytes_sent': 300, 'bytes_recv': 700}}, 1090), (200, 100))
        row = next(iter(resumed.days.values()))
        self.assertEqual(row['down'] * 1024**2, 500)
        self.assertEqual(row['up'] * 1024**2, 200)

    def test_reboot_reset_and_new_adapters_rebaseline_without_spikes(self):
        ledger = TrafficLedger({}, 10, 1000)
        ledger.observe({'eth': {'bytes_sent': 1000, 'bytes_recv': 2000}}, 1000)
        self.assertEqual(ledger.observe({'eth': {'bytes_sent': 1, 'bytes_recv': 2},
                                        'vpn': {'bytes_sent': 99999, 'bytes_recv': 99999}}, 1030), (0, 0))
        self.assertEqual(ledger.meta['reset_events'], 1)
        rebooted = TrafficLedger(ledger.snapshot(), 20, 1060)
        self.assertEqual(rebooted.observe({'eth': {'bytes_sent': 9000, 'bytes_recv': 9000}}, 1060), (0, 0))

    def test_legacy_history_is_preserved_and_marked_as_estimates(self):
        saved = {'days': {'2026-10-01': {'down': 2, 'up': 1}}, 'boot': 10, 'last': [999, 999]}
        ledger = TrafficLedger(saved, 10, 1000)
        self.assertTrue(ledger.meta['legacy_history'])
        self.assertEqual(ledger.days, saved['days'])
        self.assertIsNone(ledger.previous)

    def test_cross_midnight_gap_is_visible_in_quality_metadata(self):
        before = datetime(2026, 10, 1, 23, 0).timestamp()
        ledger = TrafficLedger({}, 10, before)
        counters = {'eth': {'bytes_sent': 1, 'bytes_recv': 2}}
        ledger.observe(counters, before)
        ledger.observe(counters, before + 7200)
        self.assertEqual(ledger.meta['cross_day_gaps'], 1)

    def test_cycle_boundaries_units_and_missing_records(self):
        result = usage_summary({'2026-09-28': {'down': 1024, 'up': 512},
                                '2026-10-01': {'down': 1024, 'up': 0},
                                '2026-10-29': {'down': 9999, 'up': 0}}, 4, 28, date(2026, 10, 2))
        self.assertEqual(result['cycle_start'], '2026-09-28')
        self.assertEqual(result['cycle_end'], '2026-10-28')
        self.assertEqual(result['cycle']['total'], 2560 * 1024**2)
        self.assertEqual(result['quota_percent'], 62.5)
        self.assertEqual(result['today']['total'], 0)
        self.assertEqual(len(result['days']), 2)
        self.assertEqual(usage_summary({}, 0, 28, date(2026, 1, 1))['cycle_start'], '2025-12-28')

    def test_rates_detect_reset_and_real_zero_is_distinct_from_no_sample(self):
        current = {'eth': {'bytes_sent': 30, 'bytes_recv': 70}}
        self.assertIsNone(adapter_rates({}, current, 2)['eth']['down'])
        self.assertEqual(adapter_rates(current, current, 2)['eth']['down'], 0)
        self.assertTrue(adapter_rates({'eth': {'bytes_sent': 50, 'bytes_recv': 80}}, current, 2)['eth']['reset'])

    def test_malformed_history_is_preserved_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'traffic.json'
            path.write_text('{invalid')
            with mock.patch.object(rm, 'TRAFFIC_FILE', str(path)), \
                    mock.patch.object(rm, '_traffic', {}), mock.patch.object(rm, '_traffic_ledger', None), \
                    mock.patch.object(rm, '_traffic_load_error', None):
                rm.load_traffic()
                self.assertIsNotNone(rm._traffic_load_error)
                self.assertFalse(rm.save_traffic())
            self.assertEqual(path.read_text(), '{invalid')
