import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webconsole'))
from action_policy import CONFIRMED_ACTIONS, requires_confirmation


class ActionPolicyTests(unittest.TestCase):
    def test_browser_and_server_cover_the_same_action_families(self):
        html = (Path(__file__).resolve().parents[1]/'webconsole'/'webconsole_ui.html').read_text(encoding='utf-8')
        match = re.search(r'const CONFIRMED_ACTIONS=new Set\((\[.*?\])\)', html)
        self.assertIsNotNone(match)
        self.assertEqual(set(json.loads(match.group(1))), set(CONFIRMED_ACTIONS))

    def test_mutations_require_confirmation_and_read_only_variants_do_not(self):
        for action, body in [('service', {'mode':'stop'}), ('rdp', {'op':'panic'}),
                             ('automation', {'op':'add'}), ('trap', {'op':'del'}), ('send_file', {})]:
            with self.subTest(action=action):
                self.assertTrue(requires_confirmation(action, body))
        for action, body in [('service', {}), ('rdp', {'op':'rdp_status'}),
                             ('automation', {'op':'list'}), ('trap', {})]:
            with self.subTest(action=action):
                self.assertFalse(requires_confirmation(action, body))
