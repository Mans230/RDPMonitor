import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webconsole"))
# Import without requiring Administrator rights or writing the real state/ACL.
os.environ["RDPWC_NO_INIT"] = "1"
import RDPWebConsole as wc  # noqa: E402


class WebConsoleSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved = {name: getattr(wc, name) for name in
                      ("BIND", "TOKEN", "EXEC_ENABLED", "DOWNLOADS_ENABLED", "AUDIT_FILE")}
        cls._saved_token_env = os.environ.get("RDPWC_TOKEN")
        os.environ["RDPWC_TOKEN"] = "unit-test-token"
        cls._audit_dir = tempfile.TemporaryDirectory()
        wc.AUDIT_FILE = str(Path(cls._audit_dir.name) / "audit.jsonl")
        wc.BIND = "127.0.0.1"
        wc.TOKEN = "unit-test-token"
        wc.EXEC_ENABLED = False
        wc.DOWNLOADS_ENABLED = False
        wc._sessions.clear()
        wc._login_attempts.clear()
        cls.server = wc.LimitedThreadingHTTPServer(("127.0.0.1", 0), wc.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for name, value in cls._saved.items():
            setattr(wc, name, value)
        if cls._saved_token_env is None:
            os.environ.pop("RDPWC_TOKEN", None)
        else:
            os.environ["RDPWC_TOKEN"] = cls._saved_token_env
        cls._audit_dir.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        h = dict(headers or {})
        if payload is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=payload, headers=h)
        r = c.getresponse()
        data = r.read()
        result = (r.status, dict(r.getheaders()),
                  json.loads(data.decode()) if data else {})
        c.close()
        return result

    def login(self):
        status, headers, data = self.request(
            "POST", "/api/login", {"token": "unit-test-token"})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        return cookie, data["csrf"]

    def test_api_requires_authenticated_session(self):
        status, headers, _ = self.request("GET", "/api/stats")
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

    def test_token_never_needed_in_url(self):
        status, _headers, _ = self.request(
            "GET", "/api/stats?token=unit-test-token")
        self.assertEqual(status, 401)
        status, _headers, _ = self.request(
            "POST", "/api/login", {"token": "wrong"})
        self.assertEqual(status, 401)
        cookie, _csrf = self.login()
        status, _headers, _ = self.request(
            "GET", "/api/stats", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

    def test_post_requires_csrf_and_exec_defaults_off(self):
        cookie, csrf = self.login()
        status, _headers, _ = self.request(
            "POST", "/api/action", {"action": "run_command", "cmd": "whoami"},
            {"Cookie": cookie})
        self.assertEqual(status, 403)
        status, _headers, data = self.request(
            "POST", "/api/action", {"action": "run_command", "cmd": "whoami"},
            {"Cookie": cookie, "X-CSRF-Token": csrf})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])

    def test_destructive_action_needs_server_nonce(self):
        cookie, csrf = self.login()
        status, _headers, data = self.request(
            "POST", "/api/action", {"action": "shutdown", "confirm": True},
            {"Cookie": cookie, "X-CSRF-Token": csrf})
        self.assertEqual(status, 400)
        self.assertIn("confirmation", data["error"])

    def test_request_body_limit(self):
        status, _headers, _ = self.request(
            "POST", "/api/login", {"token": "x" * (wc.MAX_BODY + 1)})
        self.assertEqual(status, 413)

    def test_file_download_disabled(self):
        cookie, _csrf = self.login()
        status, _headers, _ = self.request(
            "GET", "/api/file?path=C:/Windows/win.ini",
            headers={"Cookie": cookie})
        self.assertEqual(status, 403)

    def test_login_rate_limiter_blocks_and_clears(self):
        wc._login_attempts.clear()
        for _ in range(10):
            wc.login_record_failure("203.0.113.9")
        self.assertTrue(wc.login_rate_limited("203.0.113.9"))
        wc.login_clear_failures("203.0.113.9")
        self.assertFalse(wc.login_rate_limited("203.0.113.9"))

    def test_current_token_reloads_after_rotation(self):
        old_state = wc.STATE_FILE
        old_cache = dict(wc._token_cache)
        env = os.environ.pop("RDPWC_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as td:
                wc.STATE_FILE = str(Path(td) / "state.json")
                wc._token_cache.update({"mtime": 0.0, "value": None})
                Path(wc.STATE_FILE).write_text(
                    json.dumps({"token_enc": wc.dpapi_protect("tok-a")}), encoding="utf-8")
                self.assertEqual(wc.current_token(), "tok-a")
                time.sleep(0.02)
                Path(wc.STATE_FILE).write_text(
                    json.dumps({"token_enc": wc.dpapi_protect("tok-b")}), encoding="utf-8")
                os.utime(wc.STATE_FILE, None)
                self.assertEqual(wc.current_token(), "tok-b")
        finally:
            wc.STATE_FILE = old_state
            wc._token_cache.update(old_cache)
            if env is not None:
                os.environ["RDPWC_TOKEN"] = env

    def test_path_in_roots_rejects_outside_paths(self):
        self.assertFalse(wc.path_in_roots("C:\\Other\\secret.txt", ["C:\\RDPMonitor"]))
        self.assertTrue(wc.path_in_roots("C:\\RDPMonitor\\sub\\a.txt", ["C:\\RDPMonitor"]))
        if os.name == "nt":
            self.assertTrue(wc.path_in_roots("c:\\rdpmonitor\\sub\\a.txt", ["C:\\RDPMonitor"]))

    def test_ip_validation(self):
        self.assertEqual(wc.valid_ip("203.0.113.5"), "203.0.113.5")
        self.assertIsNone(wc.valid_ip("1.2.3.4&action=allow"))

    

    

    def test_backup_request_uses_fixed_control_file(self):
        old = (wc.BACKUP_DIR, wc.BACKUP_CONTROL_DIR, wc.BACKUP_REQUEST,
               wc.BACKUP_STATUS)
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / "app").mkdir()
                (root / "app" / "main.py").write_text("# test", encoding="utf-8")
                wc.BACKUP_DIR = str(root)
                wc.BACKUP_CONTROL_DIR = str(root / "control")
                wc.BACKUP_REQUEST = str(root / "control" / "request.json")
                wc.BACKUP_STATUS = str(root / "control" / "status.json")
                ok, request_id = wc.act_backup_now()
                self.assertTrue(ok)
                self.assertTrue(request_id)
                body = json.loads(Path(wc.BACKUP_REQUEST).read_text(encoding="utf-8"))
                self.assertEqual(body["action"], "backup")
                self.assertNotIn("path", body)
        finally:
            (wc.BACKUP_DIR, wc.BACKUP_CONTROL_DIR, wc.BACKUP_REQUEST,
             wc.BACKUP_STATUS) = old

    def test_legacy_state_migration_disables_dangerous_features(self):
        old_path = wc.STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as td:
                wc.STATE_FILE = str(Path(td) / "state.json")
                Path(wc.STATE_FILE).write_text(json.dumps({
                    "token": "legacy-token",
                    "bind": "0.0.0.0",
                    "exec_enabled": True,
                    "downloads_enabled": True,
                }), encoding="utf-8")
                state = wc.get_state()
                self.assertNotIn("token", state)
                self.assertFalse(state["exec_enabled"])
                self.assertFalse(state["downloads_enabled"])
        finally:
            wc.STATE_FILE = old_path


if __name__ == "__main__":
    unittest.main()
