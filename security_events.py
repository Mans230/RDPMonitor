"""Canonical addresses and bounded, fail-visible Windows Security log queries."""
import datetime
import ipaddress

MAX_EVENTS = 5000


def canonical_ip(value):
    try:
        address = ipaddress.ip_address(str(value).strip())
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except ValueError:
        return None


def canonical_target(value):
    ip = canonical_ip(value)
    if ip:
        return ip
    try:
        return str(ipaddress.ip_network(str(value).strip(), strict=False))
    except ValueError:
        return None


def usable_source(value):
    ip = canonical_ip(value)
    if not ip:
        return None
    address = ipaddress.ip_address(ip)
    return None if address.is_loopback or address.is_unspecified or address.is_multicast else ip


def event_timestamp(value):
    try:
        return datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def protected_target(value, trusted):
    target = canonical_target(value)
    if target is None:
        return True
    network = ipaddress.ip_network(target, strict=False)
    if network.network_address.is_loopback or network.network_address.is_unspecified or network.network_address.is_multicast:
        return True
    for item in trusted:
        ip = canonical_ip(item)
        if ip and ipaddress.ip_address(ip).version == network.version and ipaddress.ip_address(ip) in network:
            return True
    return False


def query(event_id, unit, amount, body):
    if unit not in ("Minutes", "Days"):
        raise ValueError("invalid event window")
    amount = max(1, min(20160, int(amount)))
    event_ids = ",".join(str(int(value)) for value in
                         (event_id if isinstance(event_id, (tuple, list)) else [event_id]))
    return (
        "$ErrorActionPreference='Stop'; "
        f"$st=(Get-Date).Add{unit}(-{amount}); "
        "try { $events=@(Get-WinEvent -FilterHashtable @{LogName='Security';"
        f"Id={event_ids};StartTime=$st}} -MaxEvents {MAX_EVENTS} -ErrorAction Stop) }} "
        "catch { if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { exit 0 }; "
        "Write-Error 'Security event query failed' -ErrorAction Continue; exit 1 }; "
        "$events | ForEach-Object { "
        "$event=$_; $x=[xml]$event.ToXml(); $d=@{}; "
        "$x.Event.EventData.Data | ForEach-Object { $d[$_.Name]=$_.'#text' }; "
        "$ip=$d['IpAddress']; " + body + " }"
    )


def failed_query(minutes, types):
    types = [t for t in str(types).split(",") if t.strip() in ("3", "10")]
    allowed = ",".join("'" + t.strip() + "'" for t in types) or "'10'"
    return query(4625, "Minutes", minutes,
        f"if ($ip -and @({allowed}) -contains $d['LogonType'] "
        "-and ($d['LogonType'] -ne '3' -or ((($d['LogonProcessName'] -like 'NtLmSsp*') "
        "-or (@('NTLM','Negotiate','Kerberos') -contains $d['AuthenticationPackageName'])) "
        "-and (-not $d['WorkstationName'])))) { "
        "Write-Output ($d['TargetUserName']+'|'+$ip+'|'"
        "+$event.TimeCreated.ToUniversalTime().ToString('o')+'|'+$event.RecordId) }")


def success_query(days=14, report=False):
    if report:
        fields = "$event.TimeCreated.ToUniversalTime().ToString('o')+'|'+$account+'|'+$ip+'|'+$event.RecordId"
    else:
        fields = "$ip+'|'+$account+'|'+$event.TimeCreated.ToUniversalTime().ToString('o')"
    return query(4624, "Days", days,
        "$account=$d['TargetUserName']; if ($d['TargetDomainName']) { "
        "$account=$d['TargetDomainName']+'\\'+$account }; "
        "if ($d['LogonType'] -eq '10' -and $ip) { Write-Output (" + fields + ") }")


def account_query():
    return query((4720, 4722, 4724, 4725, 4726, 4732, 4728), "Minutes", 3,
        "$member=$d['MemberName']; if (-not $member) { $member=$d['TargetUserName'] }; "
        "$group=if ($d['MemberName']) { $d['TargetUserName'] } else { '-' }; "
        "$actor=$d['SubjectUserName']; if ($d['SubjectDomainName']) { "
        "$actor=$d['SubjectDomainName']+'\\'+$actor }; "
        "Write-Output ($event.Id.ToString()+'|'+$member+'|'+$group+'|'+$actor+'|'"
        "+$event.TimeCreated.ToUniversalTime().ToString('o')+'|'+$event.RecordId+'|'+$d['TargetSid'])")
