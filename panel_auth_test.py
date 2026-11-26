"""Isolated, local-admin-only runner. Never starts bot/workers or host actions."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import socket
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'test-runtime' / 'panel-auth'
sys.path.insert(0, str(ROOT / 'webconsole'))


def protect_runtime():
    if os.name == 'nt' and not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Run from an elevated local administrator terminal.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        subprocess.run(['icacls', str(RUNTIME), '/inheritance:r', '/grant:r',
                        '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                       check=True, capture_output=True, creationflags=0x08000000)
    else:
        RUNTIME.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='http://localhost:18499',
                        help='Exact HTTPS .ts.net Serve origin, or local TEST default')
    parser.add_argument('--mobile-pairing', action='store_true', help='Enable isolated TEST app pairing and read-only metrics')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('run')
    commands.add_parser('pending')
    approve = commands.add_parser('approve')
    approve.add_argument('request_id')
    revoke = commands.add_parser('revoke')
    revoke.add_argument('fingerprint')
    args = parser.parse_args()
    from passkey_auth import Passkeys
    from proxy_security import serve_context
    origin = args.origin
    local = origin == 'http://localhost:18499'
    if not local:
        parsed = urlsplit(origin)
        serve_context(bind='127.0.0.1', configured_origin=origin, peer='127.0.0.1',
                      host=parsed.netloc, forwarded_proto='https', forwarded_for='100.64.0.1')
        if origin != 'https://' + parsed.hostname:
            raise ValueError('Use the exact canonical HTTPS Serve origin, without path or port.')
    protect_runtime()
    origin_id = hashlib.sha256(origin.encode()).hexdigest()[:16]
    store = Passkeys(RUNTIME / ('passkeys-' + origin_id + '.sqlite3'), origin)
    if args.command == 'pending':
        print(json.dumps(store.pending(), indent=2))
        return
    if args.command == 'approve':
        print('Approved owner credential:', store.approve(args.request_id))
        return
    if args.command == 'revoke':
        store.revoke(args.fingerprint)
        print('Credential revoked; its sessions are rejected on the next request.')
        return
    os.environ['RDPWC_NO_INIT'] = '1'
    os.environ['RDPWC_TOKEN'] = secrets.token_urlsafe(32)  # internal HMAC only
    os.environ['RDPWC_RDPDIR'] = str(RUNTIME)
    import RDPWebConsole as wc
    wc.BIND = '127.0.0.1'
    wc.STATE = {'auth_mode': 'passkey', 'passkey_origin': origin,
                'passkey_db': str(store.path), 'passkey_local_test': local,
                'trusted_proxy_origin': '' if local else origin,
                'mobile_pairing_enabled': args.mobile_pairing, 'mobile_test_runner': True}
    wc.EXEC_ENABLED = wc.DOWNLOADS_ENABLED = False
    wc.AUDIT_FILE = str(RUNTIME / 'audit.jsonl')
    wc.USAGE_FILE = str(RUNTIME / 'usage.jsonl')
    sample_lock = threading.Lock()
    previous = [None, None]
    cpu_ready = [False]

    def sample_readonly():
        """TEST metrics only; no shell, bot, mailbox, production config or worker."""
        import psutil
        with sample_lock:
            now = time.time()
            if wc.LIVE and now - wc.LIVE['ts'] < 1:
                return
            vm = psutil.virtual_memory()
            disks = []
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append(dict(mount=part.mountpoint, pct=usage.percent, free=usage.free))
                except OSError:
                    continue
            procs = []
            for process in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    info = process.info
                    procs.append(dict(pid=info['pid'], name=info['name'], cpu=None,
                                      rss=info['memory_info'].rss if info['memory_info'] else None))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            try:
                net = psutil.net_io_counters()
                old_t, old = previous
                elapsed = now - old_t if old_t else 0
                down = (net.bytes_recv - old.bytes_recv) / elapsed if old and elapsed > 0 and net.bytes_recv >= old.bytes_recv else None
                up = (net.bytes_sent - old.bytes_sent) / elapsed if old and elapsed > 0 and net.bytes_sent >= old.bytes_sent else None
                previous[:] = [now, net]
            except Exception:
                down = up = None; previous[:] = [None, None]
            cpu = psutil.cpu_percent()
            cpu_value = cpu if cpu_ready[0] else None
            cpu_ready[0] = True
            sample = dict(ts=now, hostname=socket.gethostname(), cpu={'pct': cpu_value},
                          ram=dict(pct=vm.percent, used=vm.used, total=vm.total), disks=disks,
                          procs=sorted(procs, key=lambda row: -(row['rss'] or 0))[:40],
                          sessions=None, down_bps=down, up_bps=up)
            with wc._lock:
                wc.LIVE.clear(); wc.LIVE.update(sample)
                wc.HIST.append(dict(t=now, c=sample['cpu']['pct'], r=vm.percent))
                wc.HIST[:] = wc.HIST[-361:]

    class TestHandler(wc.Handler):
        def do_POST(self):
            if urlsplit(self.path).path == '/api/action':
                self.close_connection = True
                return self._json(403, {'error': 'TEST: host-management actions are disabled.'})
            return super().do_POST()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/api/stats', '/api/history') and args.mobile_pairing and self._session()[1]:
                sample_readonly()
            if (path.startswith('/api/') and not path.startswith('/api/mobile/v1/')
                    and path not in ('/api/auth/config', '/api/session', '/api/stats', '/api/history')):
                return self._json(503, {'error': 'TEST: live integrations are disabled.'})
            return super().do_GET()

    server = wc.LimitedThreadingHTTPServer(('127.0.0.1', 18499), TestHandler)
    # Non-secret descriptor for a separately configured TEST bot. No bot is started.
    access_path = RUNTIME / 'access.json'
    pending_path = RUNTIME / 'access.json.tmp'
    pending_path.write_text(json.dumps({
        'bind': wc.BIND, 'port': 18499, 'auth_mode': 'passkey',
        'passkey_origin': origin, 'trusted_proxy_origin': '' if local else origin,
    }), encoding='utf-8')
    os.replace(pending_path, access_path)
    print('TEST only. Open:', origin)
    if args.mobile_pairing:
        print('TEST app consent:', origin + '/mobile/authorize')
    print('Register a device, match the displayed request ID with `pending`, then approve locally.')
    print('Bot, live integrations and host actions are disabled. Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
