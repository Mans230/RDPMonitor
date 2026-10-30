import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel_setup import SetupService


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"backup": {"sources": ["old"]}, "cloud": {"remotes": ["old:"], "remote_folder": "keep"},
                    "schedule": {"mode": "daily", "time": "04:00", "retry_count": 7}}
        self.cm = SimpleNamespace(save_config=mock.Mock())
        self.m = SimpleNamespace(_backup_cfg=lambda: (self.cm, copy.deepcopy(self.cfg)),
            config={"rclone_remote": "old:Images"}, save_config=mock.Mock(return_value=True),
            _rclone_remotes=lambda: ["old:", "new:"], _rclone_run=mock.Mock(return_value=(True,"")),
            _rclone_register_config=mock.Mock())
        self.s = SetupService(self.m)

    def test_sources_validate_all_before_saving_and_never_delete_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                self.s.execute({"op":"sources","paths":[folder,folder+'/missing']},'x')
            self.cm.save_config.assert_not_called()
            self.s.execute({"op":"sources","paths":[folder,folder]},'x')
            self.assertEqual(self.cm.save_config.call_args.args[0]['backup']['sources'],[folder])
            self.assertTrue(os.path.isdir(folder))

    def test_schedule_rejects_invalid_time_and_preserves_retry_settings(self):
        for mode,value in [('daily','25:00'),('times','01:00,bad'),('interval','0')]:
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                self.s.execute({'op':'schedule','mode':mode,'value':value,'enabled':True},'x')
        self.cm.save_config.assert_not_called()
        self.s.execute({'op':'schedule','mode':'times','value':'18:00,03:00,03:00','enabled':False},'x')
        saved=self.cm.save_config.call_args.args[0]['schedule']
        self.assertEqual(saved['retry_count'],7)
        self.assertEqual(saved['times'],['03:00','18:00'])
        self.assertFalse(saved['enabled'])

    def test_used_remote_cannot_be_removed_and_existing_cannot_be_overwritten(self):
        for args in [{'op':'delete','name':'old'}, {'op':'create','name':'old','provider':'b2'}]:
            with self.assertRaises(ValueError):self.s.execute(args,'x')
        self.m._rclone_run.assert_not_called()

    def test_provider_options_cannot_inject_shell_commands(self):
        with self.assertRaises(ValueError):
            self.s.execute({'op':'create','name':'fresh','provider':'sftp','options':{'ssh':'powershell evil'}},'x')
        self.m._rclone_run.assert_not_called()

    def test_destination_validation_and_partial_save_rollback(self):
        with self.assertRaises(ValueError):
            self.s.execute({'op':'targets','image':'missing:Images','backups':[]},'x')
        with self.assertRaises(ValueError):
            self.s.execute({'op':'targets','image':'new:Images','backups':[],'folder':'../bad'},'x')
        with self.assertRaises(ValueError):
            self.s.execute({'op':'targets','image':'new:Images','backups':['new:wrong-folder']},'x')
        self.cm.save_config.assert_not_called()
        self.m.save_config.return_value=False
        with self.assertRaises(ValueError):
            self.s.execute({'op':'targets','image':'new:Images','backups':['new:'],'folder':'Backups'},'x')
        self.assertEqual(self.m.config['rclone_remote'],'old:Images')
        self.assertEqual(self.cm.save_config.call_args.args[0]['cloud'],self.cfg['cloud'])

    def test_remote_cli_arguments_are_validated_before_firewall_changes(self):
        self.m._run_webconsole_cli=mock.Mock(return_value=(0,'OK'))
        with self.assertRaises(ValueError):
            self.s.execute({'op':'remote','mode':'restricted','ips':['bad & anything']},'x')
        self.m._run_webconsole_cli.assert_not_called()
        with mock.patch('panel_setup.time.sleep'):
            self.s.execute({'op':'remote','mode':'restricted','ips':['203.0.113.1']},'x')
        self.m._run_webconsole_cli.assert_called_once_with(['remote-enable','--allow','203.0.113.1/32'])

    def test_provider_questions_resume_without_publishing_secret_answers(self):
        self.s.jobs['x']={'id':'x','state':'running'}
        response={'State':'next','Option':{'Name':'config_token','IsPassword':True,'Default':'secret-default'}}
        with mock.patch.object(self.s,'json_config',side_effect=[response,{'State':''}]) as run:
            thread=threading.Thread(target=self.s.run_create,args=(['config','create','fresh','drive'],'x'))
            thread.start()
            deadline=time.monotonic()+2
            while not self.s.jobs['x'].get('question') and time.monotonic()<deadline:time.sleep(.01)
            question=self.s.jobs['x']['question']
            self.assertEqual(question['default'],'')
            self.assertFalse(self.s.submit({'op':'answer','job':'x','question':'old','value':'secret-answer'})[0])
            self.assertTrue(self.s.submit({'op':'answer','job':'x','question':question['id'],'value':'secret-answer'})[0])
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIn('secret-answer',run.call_args.args[0])
            self.assertNotIn('secret',json.dumps(self.s.job_snapshot()).replace('"secret": true',''))

    def test_rclone_stdout_json_is_separate_from_stderr_notices(self):
        import subprocess
        self.m.subprocess=subprocess;self.m.NO_WINDOW=0
        self.m._rclone_exe=lambda:'rclone.exe';self.m._rclone_conf_path=lambda:'private.conf'
        self.m._decode_out=lambda b:b.decode()
        with mock.patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'{"State":""}',stderr=b'NOTICE secret')):
            self.assertEqual(self.s.json_config(['config','create']),{'State':''})
        with mock.patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=b'bad secret',stderr=b'bad secret')):
            with self.assertRaisesRegex(ValueError,'Provider configuration failed') as ctx:self.s.json_config([])
            self.assertNotIn('secret',str(ctx.exception))

    def test_image_actions_honor_permission_and_file_inventory(self):
        self.m._image_state={};self.m.image_list_files=lambda:[];self.m.image_start=mock.Mock()
        with self.assertRaises(ValueError):self.s.execute({'op':'image_start'},'x')
        with self.assertRaises(ValueError):self.s.execute({'op':'image_upload','path':'C:/unapproved'},'x')
        self.m.image_start.assert_not_called()

    def test_busy_job_rejects_duplicate_operations(self):
        self.s.jobs={'x':{'state':'running'}}
        self.assertFalse(self.s.submit({'op':'install'})[0])

    def test_server_browser_pages_and_selects_files_without_writing(self):
        self.m._list_drives=lambda:['C:\\']
        self.assertEqual(self.s.browse()['items'][0]['path'],'C:\\')
        with tempfile.TemporaryDirectory() as folder:
            for n in range(105):Path(folder,f'{n:03}.txt').touch()
            page=self.s.browse(folder)
            self.assertEqual(len(page['items']),100);self.assertEqual(page['next'],100)
            self.assertEqual(len(self.s.browse(folder,100)['items']),5)
            with self.assertRaises(ValueError):self.s.browse(folder+'/missing')
        self.cm.save_config.assert_not_called()

    def test_cancel_pending_provider_question_unblocks_it(self):
        event=threading.Event()
        self.s.answers['x']={'event':event,'question':'q'}
        self.assertTrue(self.s.submit({'op':'cancel','job':'x'})[0])
        self.assertTrue(event.is_set());self.assertIsNone(self.s.answers['x']['value'])
        self.assertFalse(self.s.submit({'op':'cancel','job':'unknown'})[0])

if __name__=='__main__':unittest.main()
