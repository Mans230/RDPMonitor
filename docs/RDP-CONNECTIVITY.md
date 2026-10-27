# RDP connectivity diagnosis

The supplied 2026-10-27 incident report describes working RDP services/listeners
with disabled native client-logon rules and a broad inbound block excluding
loopback. That is evidence supplied by the operator, not an independently rerun
diagnosis or proof of the current host state. Its referenced `RdpMgmt.ps1` and
external-probe artifacts are not present in this repository.

## Read-only behavior

`/firewall` and the panel's existing firewall diagnostic share a structured local
inventory from `rdp_connectivity.py`. They query the actual registry RDP port,
TermService, TCP listener addresses, NLA setting, active network categories and
effective firewall profiles/rules. Enabled states are compared as strings;
`[bool]` conversion must not be used on the firewall CIM enum (False can be 2).

The inventory uses `ActiveStore` with `TracePolicyStore` so the report can show
rule origin, including Group Policy. Microsoft's [Get-NetFirewallRule reference](https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule)
explains the difference between effective ActiveStore and the default persistent
store. [Windows Firewall rule precedence](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)
describes ordinary block/allow behavior; specialized authenticated IPsec bypass
rules require additional analysis and are not modeled by this report.

Native rule state is reported by locale-stable names
`RemoteDesktop-UserMode-In-TCP` and `RemoteDesktop-UserMode-In-UDP`.
`RemoteDesktop-Shadow-*` cannot count as client-logon authorization. Custom
RDPMonitor allow-list rules can legitimately replace disabled native rules.
An allow rule's port alone is never called an open/reachable port: service,
application, profile, address scope and blocking policy also matter.

Broad blocks are identified by protocol/port/application/service/local-address
scope and coverage of non-loopback IPv4 or IPv6 addresses. Address lists, CIDRs
and address ranges are supported, including everything-except-loopback patterns.
Other scoped/conditional TCP blocks are counted separately; a block for one
source must not be described as blocking every client. UDP rule state is shown,
but a missing UDP rule alone does not imply TCP RDP is unavailable.

## Results and their limits

- `blockers_found`: broad active TCP policy blockers identified for the reported
  address families. Inspect effective policy before claiming connectivity.
- `local_issues`: local configuration/security findings, such as no suitable
  potential TCP allow, no non-loopback listener, stopped TermService or NLA off.
- `inconclusive`: query failure, invalid/missing metadata, unknown enum state or
  truncated inventory. No healthy result may be inferred.
- `external_verification_required`: no modeled local issue found. This is **not**
  externally verified, authenticated or end-to-end healthy.

Every result sets `externally_verified=false`. The panel diagnostic's success
flag is true only for the final state above; it means no modeled local issue,
not successful external connection. The diagnostic never contacts a public probe,
uploads policy or accepts a loopback TCP test as external evidence.

This is a conservative inventory, not a complete Windows Filtering Platform
simulator. Dynamic address keywords, IPsec bypass, package/user/interface filters,
per-source decisions, third-party products, provider policy and authentication
rights still need investigation. A custom allow is only a potential allow; its
scope still applies. At most 500 matching rules are serialized; truncation is
explicit and inconclusive. Collection failure/timeouts discard partial output.

## Guard and repair boundaries

The existing automatic firewall guard now reads profile enum states correctly.
Before activating disabled profiles it inventories effective policy and stops
if inventory is inconclusive or broad blocks would apply after activation. A
disabled profile's rules are not falsely reported as currently enforced; their
activation hazards are reported separately.

No external, unknown, provider, GPO or sandbox rule is disabled, deleted or
bypassed. The diagnostic performs no repair, group-wide enable, registry write,
NLA enable, service restart or network-policy change. The previously existing
guard may still restore this tool's own access rules and activate profiles when
its preflight permits. Rule ownership/authorization must be established separately
before any repair. Do not use blanket group enabling to bypass an active IP
allow-list. GPO issues belong with the policy owner.

## Independent verification and incident attribution

From an authorized independent host, test the actual destination address and
registry port. Record probe origin, destination, UTC timestamp and result. Public
probe use can disclose the destination and requires a separately chosen service.
Do not automatically replay the incident's rule toggling on a working host.

A timeout suggests filtering, routing, loss or a silent endpoint; it does not
locate the fault by itself. A refusal can mean no listener or active rejection.
A successful TCP connection proves TCP reachability at that time, not successful
RDP negotiation, NLA or user rights. Authenticate separately when authorized.
Loopback success never establishes reachability from another network.

The reported rule name alone does not establish which program or person created
it. These source changes neither attribute that rule to RDPMonitor nor reproduce
the report's external results. Review appropriate installation/audit records for
attribution without disabling an environment isolation policy.

## Validation and deployment

Tests reproduce the supplied rule shapes using synthetic policy data. Native
mutations and Telegram are mocked. A regression first demonstrated the old
firewall diagnostic accepting a failed query. Windows PowerShell's parser checks
the collector syntax without executing its native queries. No live Firewall,
account, power or external-probe actions were run for this change.

Deploy the complete reviewed revision, including `rdp_connectivity.py`, after
the parent PRs. On a disposable Windows VM, verify filter serialization, disabled
native TCP plus enabled Shadow, custom RDP ports/allow-lists, GPO origin, enum
states, all-address/loopback-exempt/scoped blocks and disabled-profile activation
hazards. Verify external access from an independent authorized host. Follow the
[validation and rollback procedure](VALIDATION.md).
