"""Read-only RDP policy inventory. Local evidence never certifies external access."""
import ipaddress


COLLECT_PS = r"""
$ErrorActionPreference='Stop'
try {
  $rdp=Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp'
  $terminal=Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server'
  $port=[int]$rdp.PortNumber
  $profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore | ForEach-Object {
    @{name=$_.Name;enabled=$_.Enabled.ToString();default_inbound=$_.DefaultInboundAction.ToString()}
  })
  $active=@(Get-NetConnectionProfile | ForEach-Object {
    if ($_.NetworkCategory.ToString() -eq 'DomainAuthenticated') {'Domain'} else {$_.NetworkCategory.ToString()}
  } | Sort-Object -Unique)
  $rules=@(Get-NetFirewallRule -PolicyStore ActiveStore -TracePolicyStore -Direction Inbound | ForEach-Object {
    $r=$_
    if ($r.Enabled.ToString() -eq 'True' -or $r.Name -in @('RemoteDesktop-UserMode-In-TCP','RemoteDesktop-UserMode-In-UDP')) {
      $pf=$r | Get-NetFirewallPortFilter
      $hit=$false
      foreach ($p in @($pf.LocalPort)) {
        if ($p -eq 'Any' -or $p -eq [string]$port) {$hit=$true}
        elseif ($p -match '^(\d+)-(\d+)$' -and $port -ge [int]$Matches[1] -and $port -le [int]$Matches[2]) {$hit=$true}
      }
      if ($hit -and [string]$pf.Protocol -in @('Any','TCP','UDP','6','17','256')) {
        $af=$r | Get-NetFirewallAddressFilter
        $ap=$r | Get-NetFirewallApplicationFilter
        $sf=$r | Get-NetFirewallServiceFilter
        @{name=$r.Name;display_name=$r.DisplayName;enabled=$r.Enabled.ToString();action=$r.Action.ToString();
          protocol=[string]$pf.Protocol;ports=@($pf.LocalPort);remote=@($af.RemoteAddress);local=@($af.LocalAddress);
          program=[string]$ap.Program;service=[string]$sf.Service;profiles=$r.Profile.ToString();
          source=$r.PolicyStoreSource;source_type=$r.PolicyStoreSourceType.ToString()}
      }
    }
  })
  $listeners=@(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq $port} | ForEach-Object {$_.LocalAddress})
  @{port=$port;rdp_enabled=($terminal.fDenyTSConnections -eq 0);nla=($rdp.UserAuthentication -eq 1);
    service=(Get-Service -Name TermService).Status.ToString();listeners=$listeners;profiles=$profiles;
    active_profiles=$active;rules=@($rules | Select-Object -First 500);truncated=($rules.Count -gt 500)} |
    ConvertTo-Json -Depth 8 -Compress
} catch { Write-Error 'RDP policy inventory failed' -ErrorAction Continue; exit 1 }
"""


def enabled(value):
    """Do not treat the CIM enum's False=2 as a Python/PowerShell boolean."""
    if value is True or str(value).lower() == 'true':
        return True
    if value is False or str(value).lower() == 'false':
        return False
    return None


def values(value):
    return value if isinstance(value, list) else [value] if value is not None else []


def port_matches(ports, port):
    for item in values(ports):
        text = str(item).strip()
        if text.lower() == 'any' or text == str(port):
            return True
        try:
            lo, hi = text.split('-', 1)
            if int(lo) <= port <= int(hi):
                return True
        except (ValueError, TypeError):
            pass
    return False


def _intervals(addresses, version):
    result = []
    for raw in values(addresses):
        text = str(raw).strip()
        if text.lower() in ('any', '*'):
            return [(0, 2**(32 if version == 4 else 128)-1)]
        try:
            if '-' in text:
                lo, hi = (ipaddress.ip_address(part.strip()) for part in text.split('-', 1))
                if lo.version == hi.version == version and int(lo) <= int(hi):
                    result.append((int(lo), int(hi)))
            else:
                net = ipaddress.ip_network(text, strict=False)
                if net.version == version:
                    result.append((int(net.network_address), int(net.broadcast_address)))
        except ValueError:
            # Dynamic Windows address keywords cannot be resolved from this snapshot.
            continue
    merged = []
    for lo, hi in sorted(result):
        if merged and lo <= merged[-1][1]+1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def remote_scope(addresses):
    families, exempt = [], True
    for version, loop in ((4, '127.0.0.0/8'), (6, '::1/128')):
        ranges = _intervals(addresses, version)
        network = ipaddress.ip_network(loop)
        first, last = int(network.network_address), int(network.broadcast_address)
        maximum = 2**network.max_prefixlen-1
        required = [(0, first-1), (last+1, maximum)]
        if all(any(lo <= start and hi >= end for lo, hi in ranges) for start, end in required):
            families.append(version)
            exempt = exempt and not any(lo <= last and hi >= first for lo, hi in ranges)
    return families, bool(families) and exempt


def _profile_matches(rule, active):
    names = {name.strip().lower() for name in str(rule.get('profiles', '')).split(',')}
    return bool(active) and ('any' in names or bool(names & {str(name).lower() for name in active}))


def _rdp_application(rule):
    program = str(rule.get('program', '')).replace('/', '\\').lower()
    service = str(rule.get('service', '')).lower()
    return (program in ('any', '*', 'system') or program.endswith('\\svchost.exe')) and service in ('any', '*', 'termservice')


def analyze(data):
    result = dict(status='inconclusive', externally_verified=False, issues=[], blockers=[],
                  activation_blockers=[], scoped_blocks=[], allows=[], standard_rules={}, profiles=[], port=None)
    if not isinstance(data, dict):
        result['issues'].append('invalid_inventory')
        return result
    required = ('port', 'profiles', 'rules', 'active_profiles', 'listeners', 'service', 'rdp_enabled', 'nla', 'truncated')
    if any(key not in data for key in required):
        result['issues'].append('incomplete_inventory')
        return result
    if any(not isinstance(data[key], list) for key in ('profiles', 'rules', 'active_profiles', 'listeners')):
        result['issues'].append('invalid_inventory')
        return result
    if any(not isinstance(profile, dict) for profile in data['profiles']):
        result['issues'].append('invalid_profiles')
        return result
    port = data['port']
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        result['issues'].append('invalid_port')
        return result
    result.update(port=port, profiles=data['profiles'], service=data['service'],
                  listeners=data['listeners'], nla=data['nla'])
    incomplete = bool(data['truncated']) or not data['active_profiles'] or not data['profiles']
    known_profiles = {str(profile.get('name')).lower() for profile in data['profiles']}
    incomplete = incomplete or not {str(name).lower() for name in data['active_profiles']} <= known_profiles
    if incomplete:
        result['issues'].append('incomplete_inventory')
    if data['rdp_enabled'] is not True:
        result['issues'].append('rdp_disabled')
    if str(data['service']).lower() != 'running':
        result['issues'].append('termservice_not_running')
    if not any(_nonloopback(address) for address in data['listeners']):
        result['issues'].append('no_external_tcp_listener')
    if data['nla'] is not True:
        result['issues'].append('nla_disabled')
    for profile in data['profiles']:
        state = enabled(profile.get('enabled'))
        if state is None:
            incomplete = True
            result['issues'].append('unknown_profile_state')
        elif not state:
            result['issues'].append('firewall_profile_off:' + str(profile.get('name')))
    effective_profiles = [profile.get('name') for profile in data['profiles']
                          if enabled(profile.get('enabled')) is True
                          and str(profile.get('name')).lower() in {str(name).lower() for name in data['active_profiles']}]
    for rule in data['rules']:
        fields = ('name', 'enabled', 'action', 'protocol', 'ports', 'remote', 'local', 'program', 'service', 'profiles')
        if not isinstance(rule, dict) or any(key not in rule for key in fields):
            incomplete = True
            result['issues'].append('incomplete_rule_filters')
            continue
        if not rule['program'] or not rule['service']:
            incomplete = True
            result['issues'].append('incomplete_application_filters')
            continue
        name = str(rule.get('name', ''))
        state = enabled(rule.get('enabled'))
        if name in ('RemoteDesktop-UserMode-In-TCP', 'RemoteDesktop-UserMode-In-UDP'):
            result['standard_rules'][name] = state
        if state is None:
            incomplete = True
        if state is not True or not _profile_matches(rule, data['active_profiles']):
            continue
        effective = _profile_matches(rule, effective_profiles)
        if not port_matches(rule.get('ports'), port) or not _rdp_application(rule):
            continue
        protocol = str(rule.get('protocol', '')).lower()
        if protocol not in ('any', 'tcp', '6', '256'):
            continue
        if str(rule.get('action')).lower() == 'allow' and effective and not name.lower().startswith('remotedesktop-shadow'):
            result['allows'].append(rule)
        elif str(rule.get('action')).lower() == 'block':
            families, loopback_exempt = remote_scope(rule.get('remote'))
            details = dict(rule, families=families, loopback_exempt=loopback_exempt,
                           all_ports=any(str(p).lower() == 'any' for p in values(rule.get('ports'))),
                           group_policy=str(rule.get('source_type', '')).lower() == 'grouppolicy')
            local_any = any(str(item).lower() in ('any', '*') for item in values(rule.get('local')))
            if families and local_any and str(rule.get('program')).lower() in ('any', '*') and str(rule.get('service')).lower() in ('any', '*'):
                result['blockers' if effective else 'activation_blockers'].append(details)
            elif effective:
                result['scoped_blocks'].append(details)
    if not result['allows']:
        result['issues'].append('no_rdp_tcp_allow')
    result['status'] = ('blockers_found' if result['blockers'] else 'inconclusive' if incomplete else
                        'local_issues' if result['issues'] else 'external_verification_required')
    return result


def _nonloopback(address):
    try:
        return not ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def format_report(report):
    lines = ['RDP connectivity policy: ' + report['status'], 'Port: ' + str(report.get('port')),
             'External connectivity: NOT VERIFIED (local policy inventory only).']
    if 'service' in report:
        lines += ['TermService: ' + str(report['service']),
                  'TCP listeners: ' + ', '.join(report['listeners']), 'NLA: ' + str(report['nla'])]
    for profile in report['profiles']:
        lines.append('Profile ' + str(profile.get('name')) + ': enabled=' + str(profile.get('enabled')) +
                     ', default inbound=' + str(profile.get('default_inbound')))
    for name in ('RemoteDesktop-UserMode-In-TCP', 'RemoteDesktop-UserMode-In-UDP'):
        lines.append(name + ': ' + str(report['standard_rules'].get(name, 'absent')))
    lines.append('Potential RDP TCP allow rules: ' + str(len(report['allows'])) + ' (scope still applies).')
    lines.extend('Issue: ' + issue for issue in report['issues'])
    for label, blocks in (('BLOCKER', report['blockers']), ('ACTIVATION HAZARD', report['activation_blockers'])):
        for block in blocks[:15]:
            lines.append(label + ': ' + str(block.get('display_name') or block.get('name')) +
                         ' | IPv' + '/IPv'.join(map(str, block['families'])) +
                         ' | all ports=' + str(block['all_ports']) + ' | loopback exempt=' + str(block['loopback_exempt']) +
                         ' | source=' + str(block.get('source')) + ' (' + str(block.get('source_type')) + ')' +
                         ' | remote=' + ', '.join(map(str, values(block.get('remote')))))
            if block['group_policy']:
                lines.append('Group Policy sourced: contact the policy owner; local edits may be overridden.')
    lines.append('Additional scoped/conditional TCP block rules: ' + str(len(report['scoped_blocks'])))
    lines.append('Broad blocks that would apply after firewall activation: ' + str(len(report['activation_blockers'])))
    lines += ['Unknown, provider, GPO and sandbox policies are never disabled by this diagnostic.',
              'Verify from an authorized independent host to the actual address/port; loopback is insufficient.',
              'Timeout: filtering/path/loss possible; refused: listener or active rejection possible.',
              'TCP connected does not verify RDP authentication, NLA or user rights.']
    return '\n'.join(lines)
