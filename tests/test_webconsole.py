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
    def test_public_firewall_scope_uses_supported_family_specific_ranges(self):
        from unittest import mock
        with mock.patch.object(wc, "run_cmd", return_value=(0, "OK")) as run:
            ok, _ = wc.firewall_apply(["0.0.0.0/0"], 8399)
        self.assertTrue(ok)
        args = run.call_args.args[0]
        self.assertIn("remoteip=0.0.0.0/1,128.0.0.0/1", args)
        self.assertNotIn("remoteip=any", args)

    @classmethod
    def setUpClass(cls):
        cls._saved = {name: getattr(wc, name) for name in
                      ("BIND", "TOKEN", "EXEC_ENABLED", "DOWNLOADS_ENABLED", "AUDIT_FILE", "USAGE_FILE")}
        cls._saved_token_env = os.environ.get("RDPWC_TOKEN")
        os.environ["RDPWC_TOKEN"] = "unit-test-token"
        cls._audit_dir = tempfile.TemporaryDirectory()
        wc.AUDIT_FILE = str(Path(cls._audit_dir.name) / "audit.jsonl")
        wc.USAGE_FILE = str(Path(cls._audit_dir.name) / "usage.jsonl")
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
        _, _, prepared = self.request("POST", "/api/action", {
            "action": "prepare", "target": "run_command", "cmd": "whoami"},
            {"Cookie": cookie, "X-CSRF-Token": csrf})
        status, _headers, data = self.request(
            "POST", "/api/action", {"action": "run_command", "cmd": "whoami", "nonce": prepared["nonce"]},
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

    def test_all_user_operations_require_server_confirmation(self):
        from unittest import mock
        cookie, csrf = self.login()
        with mock.patch.object(wc, "panel_request", return_value=(True, "done")) as dispatch, \
                mock.patch.object(wc, "audit"):
            for op in ("add", "enable", "disable", "delete", "password", "rename"):
                with self.subTest(op=op):
                    status, _, _ = self.request("POST", "/api/action", {
                        "action": "user", "op": op, "name": "operator", "value": "Test@123",
                        "confirm": True}, {"Cookie": cookie, "X-CSRF-Token": csrf})
                    self.assertEqual(status, 400)
            dispatch.assert_not_called()

    def test_user_confirmation_is_bound_to_payload_and_single_use(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        payload = {"op": "password", "name": "operator", "value": "Fake@123"}
        with mock.patch.object(wc, "panel_request", return_value=(True, "done")) as dispatch, \
                mock.patch.object(wc, "audit"):
            status, _, prepared = self.request("POST", "/api/action", {
                "action": "prepare", "target": "user", **payload}, headers)
            self.assertEqual(status, 200)
            command = {"action": "user", **payload, "nonce": prepared["nonce"]}
            self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 200)
            self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 400)
            dispatch.assert_called_once_with("user_action", payload)

    def test_user_confirmation_rejects_any_changed_field(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        payload = {"op": "password", "name": "operator", "value": "Fake@123"}
        with mock.patch.object(wc, "panel_request", return_value=(True, "done")) as dispatch:
            for key, value in (("op", "add"), ("name", "other"), ("value", "Other@123")):
                with self.subTest(key=key):
                    status, _, prepared = self.request("POST", "/api/action", {
                        "action": "prepare", "target": "user", **payload}, headers)
                    self.assertEqual(status, 200)
                    command = {"action": "user", **payload, key: value, "nonce": prepared["nonce"]}
                    self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 400)
            dispatch.assert_not_called()

    def test_user_confirmation_cannot_cross_sessions_or_expiry(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        payload = {"op": "delete", "name": "operator", "value": ""}
        status, _, prepared = self.request("POST", "/api/action", {
            "action": "prepare", "target": "user", **payload}, headers)
        self.assertEqual(status, 200)
        command = {"action": "user", **payload, "nonce": prepared["nonce"]}
        other_cookie, other_csrf = self.login()
        with mock.patch.object(wc, "panel_request") as dispatch:
            self.assertEqual(self.request("POST", "/api/action", command, {
                "Cookie": other_cookie, "X-CSRF-Token": other_csrf})[0], 400)
            sid = cookie.split("=", 1)[1]
            with wc._session_lock:
                wc._sessions[sid]["confirm"][prepared["nonce"]]["expires"] = time.time() - 1
            self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 400)
            dispatch.assert_not_called()

    def test_confirmation_storage_is_bounded(self):
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        for _ in range(16):
            self.assertEqual(self.request("POST", "/api/action", {
                "action": "prepare", "target": "shutdown"}, headers)[0], 200)
        self.assertEqual(self.request("POST", "/api/action", {
            "action": "prepare", "target": "shutdown"}, headers)[0], 429)

    def test_power_confirmation_still_works_once(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        status, _, prepared = self.request("POST", "/api/action", {
            "action": "prepare", "target": "shutdown"}, headers)
        self.assertEqual(status, 200)
        with mock.patch.object(wc, "act_shutdown", return_value=True) as shutdown:
            command = {"action": "shutdown", "nonce": prepared["nonce"]}
            self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 200)
            self.assertEqual(self.request("POST", "/api/action", command, headers)[0], 400)
            shutdown.assert_called_once()

    def test_other_sensitive_actions_reject_missing_nonce_before_dispatch(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        bodies = [
            {"action": "kill", "pids": [999999]},
            {"action": "run_command", "cmd": "FAKE_COMMAND"},
            {"action": "restore", "name": "fake.zip"},
            {"action": "rdp", "op": "panic", "mode": "on"},
            {"action": "settings_set", "key": "exec", "value": "on", "confirm": True},
            {"action": "update_now", "confirm": True},
        ]
        with mock.patch.object(wc, "act_kill", return_value=(0, [])) as kill, \
                mock.patch.object(wc, "act_run_command", return_value=(True, "fake")) as run, \
                mock.patch.object(wc, "act_restore", return_value=(True, "fake")) as restore, \
                mock.patch.object(wc, "panel_request", return_value=(True, "fake")) as panel, \
                mock.patch.object(wc, "audit"):
            for body in bodies:
                with self.subTest(action=body["action"]):
                    self.assertEqual(self.request("POST", "/api/action", body, headers)[0], 400)
            for target in (kill, run, restore, panel):
                target.assert_not_called()

    def test_named_operator_login_is_attributed_and_revoked_live(self):
        from unittest import mock
        token = "FAKE_OPERATOR_TOKEN"
        records = {"alice": {"token_sha256": wc.hashlib.sha256(token.encode()).hexdigest()}}
        with mock.patch.object(wc, "operator_records", return_value=records):
            status, headers, data = self.request("POST", "/api/login", {"token": token})
            self.assertEqual(status, 200)
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            sid = cookie.split("=", 1)[1]
            self.assertEqual(wc._sessions[sid]["actor"], "operator:alice")
            self.assertEqual(self.request("GET", "/api/stats", headers={"Cookie": cookie})[0], 200)
            records.clear()
            self.assertEqual(self.request("GET", "/api/stats", headers={"Cookie": cookie})[0], 401)
        events = wc.read_events(wc.USAGE_FILE)
        self.assertTrue(any(e["actor"] == "operator:alice" and e["action"] == "login" for e in events))
        self.assertNotIn(token, json.dumps(events))
        self.assertNotIn(sid, json.dumps(events))

    def test_operator_cli_stores_only_hash_and_removes_credentials(self):
        import io
        from unittest import mock
        state = {}
        with mock.patch.object(wc, "STATE", state), \
                mock.patch.object(wc, "atomic_write") as write, \
                mock.patch.object(wc, "harden_file", return_value=True), \
                mock.patch.object(wc.secrets, "token_urlsafe", return_value="FAKE_TOKEN"), \
                mock.patch.object(wc.sys, "stdout", io.StringIO()), \
                mock.patch.object(wc.sys, "argv", ["panel", "operator-add", "alice"]):
            self.assertEqual(wc.main(), 0)
            self.assertNotIn("FAKE_TOKEN", json.dumps(state))
            self.assertEqual(state["operators"]["alice"]["token_sha256"],
                             wc.hashlib.sha256(b"FAKE_TOKEN").hexdigest())
            with mock.patch.object(wc.sys, "argv", ["panel", "operator-remove", "alice"]):
                self.assertEqual(wc.main(), 0)
            self.assertNotIn("alice", state["operators"])
            self.assertEqual(write.call_count, 2)

    def test_generic_confirmation_is_bound_to_arguments_and_action(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        with mock.patch.object(wc, "act_kill", return_value=(1, [])) as kill:
            status, _, prepared = self.request("POST", "/api/action", {
                "action": "prepare", "target": "kill", "pids": [111]}, headers)
            self.assertEqual(status, 200)
            self.assertEqual(self.request("POST", "/api/action", {
                "action": "kill", "pids": [222], "nonce": prepared["nonce"]}, headers)[0], 400)
            kill.assert_not_called()
            status, _, prepared = self.request("POST", "/api/action", {
                "action": "prepare", "target": "kill", "pids": [111]}, headers)
            self.assertEqual(self.request("POST", "/api/action", {
                "action": "kill", "pids": [111], "nonce": prepared["nonce"]}, headers)[0], 200)
            kill.assert_called_once_with([111])

    def test_read_only_rdp_status_needs_no_confirmation(self):
        from unittest import mock
        cookie, csrf = self.login()
        with mock.patch.object(wc, "panel_request", return_value=(True, "status")), \
                mock.patch.object(wc, "audit"):
            self.assertEqual(self.request("POST", "/api/action", {
                "action": "rdp", "op": "rdp_status"}, {"Cookie": cookie, "X-CSRF-Token": csrf})[0], 200)

    def test_all_confirmed_user_operations_dispatch_without_retaining_passwords(self):
        from unittest import mock
        cookie, csrf = self.login()
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        with mock.patch.object(wc, "panel_request", return_value=(True, "done")) as dispatch, \
                mock.patch.object(wc, "audit"):
            for op in ("add", "enable", "disable", "delete", "password", "rename"):
                with self.subTest(op=op):
                    payload = {"op": op, "name": "operator", "value": "FakeSecret@123"}
                    status, _, prepared = self.request("POST", "/api/action", {
                        "action": "prepare", "target": "user", **payload}, headers)
                    self.assertEqual(status, 200)
                    sid = cookie.split("=", 1)[1]
                    with wc._session_lock:
                        record = dict(wc._sessions[sid]["confirm"][prepared["nonce"]])
                    self.assertNotIn("FakeSecret@123", json.dumps(record))
                    self.assertEqual(self.request("POST", "/api/action", {
                        "action": "user", **payload, "nonce": prepared["nonce"]}, headers)[0], 200)
                    dispatch.assert_called_with("user_action", payload)

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
