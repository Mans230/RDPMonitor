import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite_update as update


def package(changes=None):
    files = {name: b"# fixture\n" if name.endswith('.py') else b"fixture\n" for name in update.REQUIRED}
    files['requirements.lock.txt'] = b'fixed==1\n'
    files.update(changes or {})
    manifest = {'schema':1,'commit':'b'*40,'sequence':2,'files':{name:update.sha(data) for name,data in files.items()}}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('manifest.json',json.dumps(manifest))
        for name,data in files.items():archive.writestr(name,data)
    return stream.getvalue(),manifest,files


class Runtime:
    def __init__(self, fail=False, busy=''):
        self.fail=fail;self.busy=busy;self.stops=0;self.starts=0;self.health_calls=0
    def busy_reason(self):return self.busy
    def capture(self):return {'RDPSuite':'Running','RDPSuiteBoot':'Ready','RDPSuiteBackup':'Running'}
    def stop(self,tasks):self.stops+=1
    def start(self,tasks):self.starts+=1
    def health(self):
        self.health_calls+=1
        if self.fail and self.health_calls==1:raise RuntimeError('new release unhealthy')


class SuiteUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manager=update.Manager(self.root,protect=False);self.manager.prepare()
        (self.root/'requirements.lock.txt').write_text('fixed==1\n')

    def test_protected_paths_and_windows_aliases_are_never_package_targets(self):
        for name in ['../config.json','config.json','webconsole/webconsole_state.json','backup/config.json','webconsole/tls/key.pem','control/updates/settings.json','C:/evil.py','webconsole/../evil.py','webconsole\\evil.py','CON.py','webconsole/NUL.js','webconsole//x.py']:
            with self.subTest(name=name):self.assertFalse(update.allowed_path(name))
        self.assertTrue(update.allowed_path('suite_update.py'))
        self.assertTrue(update.allowed_path('backup/app/main.py'))

    def test_package_hashes_paths_and_python_syntax_are_checked_before_extraction(self):
        payload,manifest,files=package()
        self.assertEqual(update.Manager.unpack(payload)[0],manifest)
        for contents in [{'config.json':b'credential'},{'rdp_monitor.py':b'not valid python !'}]:
            with self.assertRaises((ValueError,SyntaxError)):update.Manager.unpack(package(contents)[0])
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest))
            for name,value in files.items():archive.writestr(name,value+b'tampered' if name=='rdp_monitor.py' else value)
        with self.assertRaisesRegex(ValueError,'checksum'):update.Manager.unpack(data.getvalue())

    def test_default_is_opt_in_and_invalid_configuration_is_rejected(self):
        self.assertFalse(self.manager.status()['settings']['enabled'])
        for enabled,hours in [('true',24),(True,0),(True,169),(True,1.5),(True,True)]:
            with self.assertRaises(ValueError):self.manager.configure(enabled,hours)
        self.manager.configure(True,24)
        self.assertTrue(self.manager.status()['settings']['enabled'])

    def test_transaction_installs_code_and_retains_private_config_and_history(self):
        _,manifest,files=package()
        (self.root/'rdp_monitor.py').write_text('# old')
        (self.root/'config.json').write_text('{"secret":"private"}')
        (self.root/'traffic.json').write_text('{"keep":true}')
        runtime=Runtime();self.manager.install(manifest,files,runtime)
        self.assertEqual((self.root/'config.json').read_text(),'{"secret":"private"}')
        self.assertEqual((self.root/'traffic.json').read_text(),'{"keep":true}')
        self.assertEqual(update.read_json(self.root/'.production-version.json')['commit'],'b'*40)
        self.assertEqual(runtime.health_calls,1)
        self.assertEqual(self.manager.status()['state']['phase'],'installed')

    def test_failed_health_restores_old_code_config_version_and_removes_new_code(self):
        _,manifest,files=package()
        (self.root/'rdp_monitor.py').write_text('# previous')
        (self.root/'config.json').write_text('{"secret":"old"}')
        update.atomic(self.root/'.production-version.json',{'commit':'a'*40})
        runtime=Runtime(fail=True)
        original=runtime.health
        def health():
            if runtime.health_calls==0:(self.root/'config.json').write_text('{"secret":"migrated"}')
            original()
        runtime.health=health
        with self.assertRaises(RuntimeError):self.manager.install(manifest,files,runtime)
        self.assertEqual((self.root/'rdp_monitor.py').read_text(),'# previous')
        self.assertEqual((self.root/'config.json').read_text(),'{"secret":"old"}')
        self.assertFalse((self.root/'suite_update.py').exists())
        self.assertEqual(update.read_json(self.root/'.production-version.json')['commit'],'a'*40)
        self.assertEqual(runtime.health_calls,2)
        self.assertEqual(self.manager.status()['state']['phase'],'rolled_back')

    def test_interrupted_transaction_recovers_before_checking_any_release(self):
        _,manifest,files=package();(self.root/'rdp_monitor.py').write_text('# old')
        with mock.patch.object(self.manager,'restore',side_effect=SystemExit):
            with self.assertRaises(SystemExit):self.manager.install(manifest,files,Runtime(fail=True))
        self.assertEqual((self.root/'rdp_monitor.py').read_bytes(),files['rdp_monitor.py'])
        self.manager.recover(Runtime())
        self.assertEqual((self.root/'rdp_monitor.py').read_text(),'# old')

    def test_automatic_run_defers_busy_jobs_but_manual_check_never_stops_runtime(self):
        _,manifest,files=package();self.manager.configure(True,1)
        with mock.patch.object(self.manager,'release',return_value=(manifest,files,'fixture')):
            runtime=Runtime(busy='Backup is running.');self.manager.run(runtime)
            self.assertEqual(runtime.stops,0);self.assertEqual(self.manager.status()['state']['phase'],'deferred')
            update.atomic(self.manager.home/'request.json',{'operation':'check','created':__import__('time').time()})
            self.manager.run(Runtime())
            self.assertEqual(self.manager.status()['state']['phase'],'available')
            self.assertFalse((self.root/'.production-version.json').exists())

    def test_dependency_change_requires_manual_installation(self):
        _,manifest,files=package({'requirements.lock.txt':b'changed==2'})
        self.manager.configure(True,1)
        with mock.patch.object(self.manager,'release',return_value=(manifest,files,'fixture')):
            runtime=Runtime();self.manager.run(runtime)
        self.assertEqual(runtime.stops,0);self.assertEqual(self.manager.status()['state']['phase'],'manual_required')

    def test_same_release_does_not_restart_anything(self):
        _,manifest,files=package();self.manager.configure(True)
        update.atomic(self.root/'.production-version.json',{'commit':manifest['commit']})
        with mock.patch.object(self.manager,'release',return_value=(manifest,files,'fixture')):
            runtime=Runtime();self.manager.run(runtime)
        self.assertEqual(runtime.stops,0);self.assertEqual(self.manager.status()['state']['phase'],'current')

    def test_download_url_rejects_non_https_local_hosts_and_embedded_credentials(self):
        for url in ['http://github.com/a','https://127.0.0.1/a','https://evil.example/a','https://user:secret@github.com/a','https://github.com:8399/a']:
            with self.subTest(url=url),self.assertRaises(ValueError):self.manager.fetch(url)

    def test_release_asset_digest_tag_and_successful_ci_are_all_required(self):
        payload,manifest,_=package();tag='suite-2-'+manifest['commit'][:12]
        release={'tag_name':tag,'assets':[{'id':123,'url':update.API+'/releases/assets/123','name':update.ASSET,'digest':'sha256:'+update.sha(payload),'size':len(payload),'browser_download_url':'https://github.com/'+update.REPO+'/releases/download/'+tag+'/'+update.ASSET}]}
        replies=[json.dumps(release).encode(),payload,json.dumps({'object':{'type':'commit','sha':manifest['commit']}}).encode(),json.dumps({'workflow_runs':[{'head_sha':manifest['commit'],'head_branch':'main','conclusion':'success'}]}).encode()]
        with mock.patch.object(self.manager,'fetch',side_effect=replies):self.assertEqual(self.manager.release()[0],manifest)
        bad=json.loads(json.dumps(release));bad['assets'][0]['digest']='sha256:'+'0'*64
        with mock.patch.object(self.manager,'fetch',side_effect=[json.dumps(bad).encode(),payload]):
            with self.assertRaisesRegex(ValueError,'checksum'):self.manager.release()
        replies[-1]=b'{"workflow_runs":[]}'
        with mock.patch.object(self.manager,'fetch',side_effect=replies):
            with self.assertRaisesRegex(ValueError,'validation'):self.manager.release()

    def test_queue_failure_does_not_leave_an_unexecutable_request(self):
        with mock.patch('subprocess.run',side_effect=OSError('missing scheduler')):
            with self.assertRaises(RuntimeError):self.manager.queue('apply')
        self.assertFalse((self.manager.home/'request.json').exists())

    def test_old_or_divergent_release_never_replaces_a_manual_installation(self):
        _,manifest,files=package();self.manager.configure(True)
        update.atomic(self.root/'.production-version.json',{'commit':'c'*40})
        with mock.patch.object(self.manager,'release',return_value=(manifest,files,'fixture')),mock.patch.object(self.manager,'fetch',return_value=b'{"status":"behind"}'):
            runtime=Runtime()
            with self.assertRaises(ValueError):self.manager.run(runtime)
        self.assertEqual(runtime.stops,0)

    def test_previously_failed_release_is_not_retried_automatically(self):
        _,manifest,files=package();self.manager.configure(True)
        self.manager.state('rolled_back','failed',failed_commit=manifest['commit'])
        with mock.patch.object(self.manager,'release',return_value=(manifest,files,'fixture')):
            runtime=Runtime();self.manager.run(runtime)
        self.assertEqual(runtime.stops,0);self.assertEqual(self.manager.status()['state']['phase'],'blocked')

    def test_activity_lease_prevents_installation_from_interrupting_a_backup(self):
        _,manifest,files=package();runtime=Runtime()
        with update.update_lock(self.manager.home/'activity.lock'):
            self.manager.install(manifest,files,runtime)
        self.assertEqual(runtime.stops,0)
        self.assertEqual(self.manager.status()['state']['phase'],'deferred')

    def test_backup_worker_honors_the_same_cross_process_installation_lease(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backup'/'app'))
        import scheduler
        with mock.patch.object(scheduler.backup_engine,'TOOL_ROOT',str(self.root/'backup')),mock.patch.object(scheduler,'_run_full_backup_unlocked',return_value='ok') as job:
            with update.update_lock(self.manager.home/'activity.lock'):
                self.assertEqual(scheduler.run_full_backup({}),'busy')
            job.assert_not_called()
            self.assertEqual(scheduler.run_full_backup({}),'ok')

    def test_saved_github_credential_is_machine_encrypted_and_not_in_status(self):
        import rdp_monitor
        token='github_pat_fixture_1234567890'
        with mock.patch.object(rdp_monitor,'dpapi_protect',return_value='encrypted-fixture') as protect,mock.patch.object(rdp_monitor,'dpapi_unprotect',return_value=token):
            self.manager.credential(token)
            protect.assert_called_once_with(token,machine=True)
            self.assertNotIn(token,(self.manager.home/'github.json').read_text())
            self.assertNotIn(token,json.dumps(self.manager.status()))
            self.assertTrue(self.manager.status()['credential_saved'])
            self.assertEqual(self.manager.credential(),token)
            self.manager.credential('');self.assertFalse(self.manager.status()['credential_saved'])

    def test_github_credential_is_never_forwarded_to_download_redirects(self):
        first=mock.MagicMock();first.status_code=302;first.headers={'Location':'https://release-assets.githubusercontent.com/fixture'}
        second=mock.MagicMock();second.status_code=200;second.iter_content.return_value=[b'archive']
        first.__enter__.return_value=first;second.__enter__.return_value=second
        with mock.patch.object(self.manager,'credential',return_value='private-fixture-token'),mock.patch('requests.get',side_effect=[first,second]) as get:
            self.assertEqual(self.manager.fetch(update.API+'/releases/assets/123',accept='application/octet-stream'),b'archive')
        self.assertEqual(get.call_args_list[0].kwargs['headers']['Authorization'],'Bearer private-fixture-token')
        self.assertNotIn('Authorization',get.call_args_list[1].kwargs['headers'])


if __name__=='__main__':unittest.main()
