# Bot categories, controls and RDP security review

This follow-up builds on the security/audit changes in PR #8. Deploy the complete
reviewed code bundle, including `bot_catalog.py`, `resource_alerts.py` and
`security_events.py`; replacing only `rdp_monitor.py` is unsupported.

## Commands and alerts

`bot_catalog.py` is the category source for `/menu`, `/help`, the Telegram command
picker and the generated command reference. Categories cover resources, network,
accounts/sessions, RDP security, program automation, backup/restore, cloud/images,
device actions, diagnostics, settings, panel and help. Each visible command has one
owner. `/start`, `/getlog` and `/token` remain aliases; old category buttons still
resolve. Directly typed commands keep their existing syntax.

System CPU/RAM thresholds are configured through `/set`. A spike and high usage in
the same sample produce one combined notification. A decrease in severity does
not count as escalation; increases are immediate, repeats wait at least 15 minutes,
and recovery is sent once. `/watch` is different: it applies a RAM limit in MB to
a named process, under Programs & services. It is not a second system CPU monitor.

Opening a command card does not run it. Cards show purpose, usage, effect and the
selected command. Run/Confirm buttons are single-use and expire after the existing
30-minute pending-action lifetime. Old `run:` buttons also enter review, including
buttons that contain the text `confirm`. Parameterized commands can still be typed
with their arguments. Existing command-specific confirmation checks remain.
Telegram draws its native button borders; the bot controls labels and review flow.

Web action buttons have press/focus/busy states and 44px phone touch targets. While
an action is pending its button is disabled, marked `aria-busy` and labelled
Working. Matching in-flight action payloads share one request. Success, preparation
failure, authentication expiry and network failure restore the original control.
This is UI request suppression, not persistent server-side idempotency.

## Defects and corrections

- Duplicate resource notifications: combine spike and threshold decisions; compare
  severity ranks rather than treating every level change as escalation.
- Automatic subnet escalation ignored `subnetblock`: require that setting before
  adding an IPv4 `/24` block. Refuse any target covering a manually trusted IP.
- Repeated/old failed events inflated counts: use event UTC time, the configured
  failure window and record IDs; distinguish events with the same timestamp.
- Invalid sources entered protection state: canonicalize IPv4, IPv6 and mapped
  IPv4; ignore loopback, unspecified and multicast sources.
- Query failures looked like empty results: distinguish no matching events from
  failed Security log access and preserve prior state on failure.
- Successful-source learning used poll time and could overwrite the latest account
  with an older event: retain the newest observed account and event timestamp.
- Failed session snapshots looked like logout: retain the previous snapshot and
  report verified session appearance/disappearance/state changes with observation
  time. These observations are not exact Windows logon/logoff event times.
- Account events could collide within a minute: include record IDs and full UTC
  timestamps; recognize the local Administrators SID independently of its name.
- Unblock/panic release could treat failed verification as rule absence: require
  an explicit successful count of zero and retain recorded state otherwise.
- Lockdown/allow-list release and panel wrappers could announce success despite
  failure: propagate failure and keep the previous recorded restriction. Refuse
  to reopen RDP if a previous active allow-list has lost its addresses.
- Block-list persistence failure could be swallowed: raise on atomic-write failure
  and attempt rollback of a newly created block. Report rollback failure explicitly.
- Windows mutex handles could be truncated on 64-bit Windows: declare pointer-sized
  handle arguments and release only a mutex whose ownership was acquired.
- Panel IP block/unblock had separate implementations: route both through the
  monitor's shared validation, firewall and tracking code.

## Event scope and remaining limits

`/logins` reports successful remote-interactive logons (4624, type 10) from the
last three days: UTC event time, domain/account, source IP and event record ID.
Learned source history uses 14 days. Failed-logon scans use the configured window;
account-change scans use three minutes. Each query scans at most 5,000 events,
newest first. Heavy bursts, outages, cleared logs and disabled auditing can lose
events; this is polling, not a durable Security log subscription or a forensic
ledger. Existing learned history remains until replaced/expired.

The default failed-logon type is 10. Optional type 3 matching is a heuristic for
NLA and can include other network authentication: it is not proof of RDP. A
successful login from a new IP is an observation, not proof the account is safe.
Learned addresses do not become lockdown trust unless explicitly enabled.

Blocks retain the existing scope: inbound traffic from the source, not only RDP.
Subnet blocks cover 256 IPv4 addresses and can affect unrelated clients. Manual
management addresses are exempt from automatic IP/subnet blocking. Provider ACLs,
GPO rules and other security products still require effective-policy verification.
Partial firewall failure can leave policy requiring manual inspection; retaining
recorded state does not prove a complete rollback. This tool does not replace
MFA, account lockout policy or a VPN.

## Validation performed and required

Automated regressions exercise every command's review card without dispatching
it, unique category ownership, Telegram registry constraints, legacy-button review,
single-use Run/Confirm, resource policy, event parsing/window/deduplication, trust
exemptions, threshold blocking, failed snapshots/queries, persistence rollback,
release failures and Win64 mutex signatures. Native mutations and Telegram traffic
are mocked. PowerShell's actual parser validates generated queries without running
their ASTs. JavaScript tests execute the real action helpers with fake fetch.

Chromium inspection compares isolated button states using the actual page CSS at
1440, 768 and 390px. It does not certify every dashboard tab. The component fixture
has intentional unused space; the existing login page's gradient/shadow findings
are outside this control-state change. No application style or palette was redrawn.

No live account, firewall, power, installation or bot commands were executed on the
working server. Full handler execution for all commands is not claimed. Before
deployment, use a disposable Windows VM and separate bot credentials to execute
each command family, check localized sessions/account events, induce real logon
failures, verify effective firewall rules and test recovery through a provider
console. Follow [validation and rollback](VALIDATION.md).
