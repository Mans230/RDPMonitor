import copy
import json
import shutil
import subprocess
import unittest
from unittest import mock

import rdp_monitor as rm


class ExistingFirewallReportTests(unittest.TestCase):
    def test_failed_query_cannot_produce_a_successful_firewall_report(self):
        result = mock.Mock(returncode=1, stdout=b'---P---\nPublic|True\n---R---\n3389', stderr=b'denied')
        with mock.patch.object(rm.subprocess, 'run', return_value=result):
            ok, text = rm._api_diag_inline('firewall')
        self.assertFalse(ok)

    def test_invalid_json_inventory_is_inconclusive(self):
        with mock.patch.object(rm.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=b'not-json')):
            self.assertEqual(rm.get_firewall_report()['status'], 'inconclusive')

    def test_panel_report_returns_hard_failure_for_active_broad_block(self):
        data = snapshot()
        data['rules'].append(dict(data['rules'][0], name='test-block', action='Block', service='Any'))
        result = mock.Mock(returncode=0, stdout=json.dumps(data).encode())
        with mock.patch.object(rm.subprocess, 'run', return_value=result):
            ok, text = rm._api_diag_inline('firewall')
        self.assertFalse(ok)
        self.assertIn('BLOCKER: test-block', text)
        self.assertIn('External connectivity: NOT VERIFIED', text)

    def test_guard_reads_false_enum_string_and_aborts_before_mutation_on_unknown_policy(self):
        result = mock.Mock(returncode=0, stdout=b'Public|False')
        with mock.patch.object(rm.subprocess, 'run', return_value=result) as query, \
                mock.patch.object(rm, 'get_firewall_report', return_value={'status':'inconclusive'}), \
                mock.patch.object(rm, 'send_message'), mock.patch.object(rm, '_netsh') as native, \
                mock.patch.object(rm, '_create_general_rdp_rule') as allow:
            rm.check_firewall_guard()
        native.assert_not_called()
        allow.assert_not_called()
        self.assertIn('Enabled.ToString()', query.call_args.args[0][-1])

    def test_guard_does_not_activate_known_broad_block_on_disabled_profile(self):
        result = mock.Mock(returncode=0, stdout=b'Public|False')
        from rdp_connectivity import analyze
        data = snapshot()
        data['profiles'][0]['enabled'] = 'False'
        data['rules'].append(dict(data['rules'][0], action='Block', service='Any'))
        with mock.patch.object(rm.subprocess, 'run', return_value=result), \
                mock.patch.object(rm, 'get_firewall_report', return_value=analyze(data)), \
                mock.patch.object(rm, 'send_message'), mock.patch.object(rm, '_netsh') as native, \
                mock.patch.object(rm, '_create_general_rdp_rule') as allow:
            rm.check_firewall_guard()
        native.assert_not_called()
        allow.assert_not_called()


def snapshot():
    return dict(port=3389, rdp_enabled=True, nla=True, service='Running',
                listeners=['0.0.0.0', '::'], active_profiles=['Public'],
                profiles=[dict(name='Public', enabled='True', default_inbound='Block')],
                rules=[dict(name='RemoteDesktop-UserMode-In-TCP', enabled='True', action='Allow',
                            protocol='TCP', ports=['3389'], remote=['Any'], local=['Any'],
                            program='Any', service='TermService', profiles='Any',
                            source='PersistentStore', source_type='Local')], truncated=False)


class ConnectivityPolicyTests(unittest.TestCase):
    def analyze(self, data):
        from rdp_connectivity import analyze
        return analyze(data)

    def test_shadow_rule_never_counts_as_a_client_logon_rule(self):
        data = snapshot()
        data['rules'][0]['name'] = 'RemoteDesktop-Shadow-In-TCP'
        self.assertIn('no_rdp_tcp_allow', self.analyze(data)['issues'])

    def test_false_enum_string_does_not_count_as_enabled(self):
        data = snapshot()
        data['rules'][0]['enabled'] = 'False'
        self.assertIn('no_rdp_tcp_allow', self.analyze(data)['issues'])

    def test_local_policy_never_proves_external_connectivity(self):
        report = self.analyze(snapshot())
        self.assertEqual(report['status'], 'external_verification_required')
        self.assertFalse(report['externally_verified'])

    def test_custom_registry_port_and_port_range_are_respected(self):
        data = snapshot()
        data['port'] = 33990
        data['rules'][0]['ports'] = ['33000-34000']
        report = self.analyze(data)
        self.assertEqual(report['status'], 'external_verification_required')
        self.assertEqual(report['port'], 33990)

    def test_incident_shape_blocks_nonloopback_but_excludes_loopback(self):
        data = snapshot()
        block = copy.deepcopy(data['rules'][0])
        block.update(name='unrelated-management-policy', action='Block', protocol='Any',
                     ports=['Any'], service='Any',
                     remote=['0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255',
                             '::', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'])
        data['rules'].append(block)
        report = self.analyze(data)
        self.assertEqual(report['status'], 'blockers_found')
        self.assertTrue(report['blockers'][0]['loopback_exempt'])
        self.assertTrue(report['blockers'][0]['all_ports'])

    def test_disabled_or_inactive_profile_block_is_not_effective(self):
        for updates in ({'enabled':'False'}, {'profiles':'Private'}):
            data = snapshot()
            block = dict(data['rules'][0], action='Block', service='Any', **updates)
            data['rules'].append(block)
            self.assertEqual(self.analyze(data)['blockers'], [])

    def test_scoped_ip_block_is_reported_without_claiming_every_client_is_blocked(self):
        data = snapshot()
        data['rules'].append(dict(data['rules'][0], action='Block', service='Any', remote=['203.0.113.9']))
        report = self.analyze(data)
        self.assertEqual(report['blockers'], [])
        self.assertEqual(len(report['scoped_blocks']), 1)

    def test_gpo_block_preserves_policy_source_and_requires_policy_owner(self):
        data = snapshot()
        data['rules'].append(dict(data['rules'][0], action='Block', service='Any',
                                  source='example.test/RDP policy', source_type='GroupPolicy'))
        block = self.analyze(data)['blockers'][0]
        self.assertTrue(block['group_policy'])
        self.assertEqual(block['source'], 'example.test/RDP policy')

    def test_custom_allowlist_rule_can_replace_disabled_builtin_rule(self):
        data = snapshot()
        data['rules'][0]['enabled'] = 'False'
        data['rules'].append(dict(data['rules'][0], name='RDPMonitor RDP Allow TCP', enabled='True',
                                  remote=['198.51.100.10']))
        self.assertNotIn('no_rdp_tcp_allow', self.analyze(data)['issues'])

    def test_missing_or_truncated_inventory_is_inconclusive(self):
        for data in ({}, dict(snapshot(), truncated=True), dict(snapshot(), active_profiles=[]),
                     dict(snapshot(), rules=[{'enabled':'True'}]), dict(snapshot(), rules='invalid'),
                     dict(snapshot(), profiles=[{'name':'Private','enabled':'True'}])):
            self.assertEqual(self.analyze(data)['status'], 'inconclusive')

    def test_other_program_service_and_port_blocks_do_not_claim_rdp_block(self):
        for updates in ({'program':r'C:\other.exe'}, {'service':'OtherService'}, {'ports':['3390']}):
            data = snapshot()
            block = dict(data['rules'][0], action='Block')
            block.update(updates)
            data['rules'].append(block)
            self.assertEqual(self.analyze(data)['blockers'], [])

    def test_disabled_firewall_profile_cannot_enforce_a_block(self):
        data = snapshot()
        data['profiles'][0]['enabled'] = 'False'
        data['rules'].append(dict(data['rules'][0], action='Block', service='Any'))
        report = self.analyze(data)
        self.assertEqual(report['blockers'], [])
        self.assertIn('firewall_profile_off:Public', report['issues'])
        self.assertEqual(len(report['activation_blockers']), 1)

    @unittest.skipUnless(shutil.which('powershell'), 'Windows PowerShell parser unavailable')
    def test_collector_parses_without_executing_native_queries(self):
        from rdp_connectivity import COLLECT_PS
        parser = ("$text=[Console]::In.ReadToEnd(); $tokens=$null; $errors=$null; "
                  "[System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)|Out-Null; "
                  "if($errors.Count){$errors | ForEach-Object {Write-Output $_.Message};exit 1}")
        completed = subprocess.run(['powershell','-NoProfile','-Command',parser], input=COLLECT_PS.encode(),
                                   capture_output=True, timeout=30, creationflags=rm.NO_WINDOW)
        self.assertEqual(completed.returncode, 0, completed.stdout.decode(errors='replace'))
