"""Exercise every catalog command without network, OS mutations or Telegram sends.

This is a presentation audit, not an end-to-end test of destructive operations.
Run from the repository root; stdout is a JSON evidence report.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import rdp_monitor as bot
from bot_messages import message_pages
from suite_update import Manager
sys.path.insert(0, str(ROOT/'backup/app'))


def audit():
    report = []
    with tempfile.TemporaryDirectory(prefix='bot-presentation-') as fixture, ExitStack() as patches:
        fixture = Path(fixture).resolve()
        # Redirect every repository-owned runtime path into the disposable fixture.
        for name, value in list(vars(bot).items()):
            if isinstance(value, str) and value.lower().startswith(str(ROOT).lower()):
                patches.enter_context(mock.patch.object(bot, name, str(fixture)+value[len(str(ROOT)):]))
        original = copy.deepcopy(bot.DEFAULT_CONFIG)
        original.update(telegram_token='fixture', chat_id='fixture',
                        user_management=True, exec_enabled=True)
        messages, jobs, calls = [], [], []

        def api(method, **kwargs):
            if method in ('sendMessage', 'editMessageText'):
                messages.append({'text': kwargs.get('text', ''), 'buttons': kwargs.get('reply_markup', {})})
            return {'ok': True, 'result': {'message_id': 1}}

        class Thread:
            def __init__(self, target=None, args=(), kwargs=None, **unused):
                self.target, self.args, self.kwargs = target, args, kwargs or {}
            def start(self):
                name = getattr(self.target, '__name__', 'job')
                jobs.append(name)
                if name in {'send_daily_report', 'temp_job', '_sysinfo_job', '_fw_job',
                            '_diagnose_job', '_logstats_job', 'nettest_job', 'updates_job',
                            '_logins_job', 'startup_job', 'bigfiles_job', 'harden_report',
                            '_export_job', 'config_backup_job', 'speedtest_job'}:
                    self.target(*self.args, **self.kwargs)
            def join(self, *args): pass
            def is_alive(self): return False

        def blocked(*args, **kwargs):
            calls.append('blocked external operation')
            raise RuntimeError('Unavailable in presentation fixture')

        for name, value in {
            'tg_api': api, '_alert_targets': lambda: ['fixture'],
            'get_usage': lambda: (7.5, 46.7, 5.6, 12),
            'get_disks': lambda: [('C:\\', 34, 132, 200)],
            'get_top_processes': lambda n=10: ([('worker.exe', i+1, 7.5, 574) for i in range(n)],
                                              [('worker.exe', i+1, 7.5, 574) for i in range(n)]),
            'get_rdp_sessions': lambda **kw: [{'user': 'fixture-user', 'state': 'Active', 'id': '1'}],
            'get_rdp_ips': lambda: ['192.0.2.1'],
            '_local_users_detail': lambda **kw: [{'name': 'fixture-user', 'admin': False, 'enabled': True,
                                               'pwlastset': '-', 'pwexpires': 'never', 'lastlogon': '-'}],
            'get_temps': lambda: {'CPU': 42}, 'take_screenshot': lambda: None,
            'make_chart': lambda *a: None,
            'stats_since': lambda *a: {'cpu_avg': 7.5, 'cpu_max': 20, 'ram_avg': 46.7, 'ram_max': 55, 'points': 60},
            'save_config': lambda: None, 'audit_record': lambda *a: None,
            'run_speedtest': lambda: (20, 100, 10),
            '_send_file_once': lambda kind, chat, path, caption: messages.append({'text':caption,'attachment':kind}) or True,
        }.items():
            patches.enter_context(mock.patch.object(bot, name, value))
        patches.enter_context(mock.patch.object(bot.threading, 'Thread', Thread))
        patches.enter_context(mock.patch.object(bot.subprocess, 'run', side_effect=lambda *a, **k:
            subprocess.CompletedProcess(a, 1, stdout=b'', stderr=b'Fixture: Windows query unavailable')))
        patches.enter_context(mock.patch.object(bot.subprocess, 'Popen', side_effect=blocked))
        patches.enter_context(mock.patch.object(bot.requests.sessions.Session, 'request', side_effect=blocked))
        patches.enter_context(mock.patch.object(bot.time, 'sleep', return_value=None))
        patches.enter_context(mock.patch.object(tempfile, 'tempdir', str(fixture)))
        patches.enter_context(mock.patch.object(bot.psutil, 'users', return_value=[SimpleNamespace(name='fixture-user')]))
        patches.enter_context(mock.patch.object(bot.psutil, 'net_io_counters', return_value=SimpleNamespace(bytes_recv=2*1024**3, bytes_sent=1024**3)))
        patches.enter_context(mock.patch.object(bot.psutil, 'net_connections', return_value=[]))
        patches.enter_context(mock.patch('suite_update.Manager', side_effect=lambda root=None: Manager(root or fixture)))
        for method in ('kill', 'terminate', 'suspend', 'resume', 'send_signal'):
            patches.enter_context(mock.patch.object(bot.psutil.Process, method, side_effect=blocked))

        # Process-wide final barrier, beyond the mocked interfaces above.
        barrier = {'enabled': True}
        def guard(event, args):
            if not barrier['enabled']:
                return
            if event in ('subprocess.Popen', 'os.system', 'socket.connect', 'os.startfile'):
                raise RuntimeError('OS/network mutation blocked by audit fixture')
            if event == 'open':
                path, mode, flags = args
                writing = (mode and any(c in mode for c in 'wax+')) or (flags and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
                if writing and isinstance(path, (str, bytes)) and not Path(os.fsdecode(path)).resolve().is_relative_to(fixture):
                    raise RuntimeError('Write outside disposable fixture blocked')
            if event in ('os.remove', 'os.rmdir', 'os.rename', 'os.mkdir'):
                for path in args[:2 if event == 'os.rename' else 1]:
                    if isinstance(path, (str, bytes)) and not Path(os.fsdecode(path)).resolve().is_relative_to(fixture):
                        raise RuntimeError('Filesystem mutation outside fixture blocked')
        sys.addaudithook(guard)
        try:
            cases = sorted(bot.COMMAND_INFO) + [
                '/top cpu 1', '/top cpu 2', '/top ram 1', '/top ram 2', '/top invalid',
                '/exec whoami', '/kill worker.exe', '/run notepad', '/logoff 1',
                '/adduser fixture-user', '/deluser fixture-user', '/disableuser fixture-user',
                '/enableuser fixture-user', '/renameuser fixture-user renamed-user',
                '/panic on', '/rdpallow apply', '/lockdown now', '/harden fix',
                '/svc restart Spooler', '/restore fixture.zip', '/backsrc remove 1',
                '/backupschedule off', '/image start', '/suiteupdate now',
                '/panelremote direct', '/set cpu invalid', '/traffic 30']
            for command in cases:
                bot.config = copy.deepcopy(original)
                messages.clear(); jobs.clear(); calls.clear()
                error = None
                try:
                    bot.handle_command(command)
                except Exception as exc:
                    error = type(exc).__name__ + ': ' + str(exc)
                response = list(messages)
                # Every command gets an actual documentation and review-card pass too.
                docs = bot.docs_card_text(command.split()[0])
                messages.clear()
                try:
                    bot.show_command_info(command)
                except Exception as exc:
                    error = error or type(exc).__name__ + ': ' + str(exc)
                report.append({'command': command, 'error': error,
                    'responses': response, 'background_jobs_simulated': list(jobs),
                    'docs_pages': len(message_pages(docs)), 'review_responses': list(messages),
                    'responded': bool(response or jobs),
                    'mutation_executed': False})
        finally:
            barrier['enabled'] = False
    return {'mode': 'isolated presentation fixtures; OS/network mutations blocked',
            'commands': report, 'count': len(report),
            'errors': [r['command'] for r in report if r['error']],
            'no_response': [r['command'] for r in report if not r['responded']]}


if __name__ == '__main__':
    # Some existing diagnostics print status; keep stdout machine readable.
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        result = audit()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    sys.exit(bool(result['errors'] or result['no_response']))
