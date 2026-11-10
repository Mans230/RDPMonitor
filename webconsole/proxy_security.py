"""Narrow request policy for an explicitly configured local Tailscale Serve proxy.

Forwarded headers establish transport context only, never an authenticated user.
"""
from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit

LOOPBACK_NAMES=frozenset(('127.0.0.1','localhost','[::1]'))


class ProxyRejected(ValueError):
    pass


@dataclass(frozen=True)
class ProxyContext:
    origin: str
    client_ip: str


def serve_context(*,bind,configured_origin,peer,host,forwarded_proto,forwarded_for,origin=None,method='GET'):
    if bind not in ('127.0.0.1','::1','localhost'):
        raise ProxyRejected('Proxy mode requires a loopback backend.')
    try:
        if not ipaddress.ip_address(peer).is_loopback:
            raise ValueError()
        parsed=urlsplit(configured_origin)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.ts.net') or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.port not in (None,443):
            raise ValueError()
    except ValueError:
        raise ProxyRejected('Invalid trusted Serve origin or peer.') from None
    expected='https://'+parsed.hostname.lower()
    if host.lower() not in (parsed.hostname.lower(),parsed.hostname.lower()+':443') or forwarded_proto!='https':
        raise ProxyRejected('Unexpected proxy host or transport.')
    # Serve replaces forwarding headers. A chain/list is deliberately rejected.
    try:
        client=ipaddress.ip_address(forwarded_for)
        nets=(ipaddress.ip_network('100.64.0.0/10'),ipaddress.ip_network('fd7a:115c:a1e0::/48'))
        if not any(client in network for network in nets):raise ValueError()
    except ValueError:
        raise ProxyRejected('Missing or invalid tailnet client address.') from None
    if method not in ('GET','HEAD','OPTIONS') and origin!=expected:
        raise ProxyRejected('Cross-origin proxy request rejected.')
    return ProxyContext(expected,str(client))
