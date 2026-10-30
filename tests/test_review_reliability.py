import concurrent.futures
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import rdp_monitor as rm
from safe_logging import redact, scrub_file
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webconsole"))
os.environ["RDPWC_NO_INIT"] = "1"
import RDPWebConsole as wc


class ReliabilityTests(unittest.TestCase):
    def test_tokens_are_redacted_in_console_file_and_retained_logs(self):
        secret = "123456789:" + "A" * 35
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.log"
            path.write_text("https://api.telegram.org/bot" + secret + "/getUpdates")
            scrub_file(path)
            console = io.StringIO()
            with mock.patch.object(rm, "LOG_FILE", str(path)):
                rm._TeeWriter(console).write("request failed: " + secret)
            self.assertNotIn(secret, path.read_text())
            self.assertNotIn(secret, console.getvalue())
            self.assertIn("REDACTED", console.getvalue())

    def test_import_does_not_break_later_asyncio_import(self):
        result = subprocess.run([sys.executable, "-c",
            "import subprocess; original = subprocess.Popen; import rdp_monitor; "
            "import asyncio; assert subprocess.Popen is original"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_concurrent_requests_have_independent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            seen = set()
            def worker():
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    while not stop.is_set():
                        for path in Path(directory).glob("request-*.json"):
                            if path.name in seen:
                                continue
                            seen.add(path.name)
                            claimed = str(path) + ".processing"
                            try:
                                path.rename(claimed)
                            except FileNotFoundError:
                                continue
                            executor.submit(rm._process_panel_request,
                                            json.loads(Path(claimed).read_text()), claimed)
                        time.sleep(.01)
            def dispatch(action, args):
                time.sleep(.35 if action == "slow" else .01)
                return True, action
            with mock.patch.object(wc, "MONITOR_CONTROL_DIR", directory), \
                    mock.patch.object(rm, "MONITOR_CONTROL_DIR", directory), \
                    mock.patch.object(rm, "_dispatch_panel", side_effect=dispatch):
                thread = threading.Thread(target=worker)
                thread.start()
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                        slow = executor.submit(wc.panel_request, "slow", timeout=1)
                        fast = executor.submit(wc.panel_request, "fast", timeout=.3)
                        self.assertEqual(fast.result(), (True, "fast"))
                        self.assertEqual(slow.result(), (True, "slow"))
                finally:
                    stop.set()
                    thread.join()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_expired_mutation_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claimed"
            path.touch()
            with mock.patch.object(rm, "_dispatch_panel") as dispatch:
                rm._process_panel_request({"id": "a" * 32, "expires": time.time() - 1}, str(path))
                dispatch.assert_not_called()
            self.assertFalse(path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_machine_scope_round_trip(self):
        value = "unit-test-credential"
        self.assertEqual(rm.dpapi_unprotect(rm.dpapi_protect(value, machine=True)), value)
        self.assertEqual(wc.dpapi_unprotect(wc.dpapi_protect(value, machine=True)), value)
