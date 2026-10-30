"""Panel setup workflows. The monitor remains the sole configuration writer."""
import copy
import ipaddress
import json
import os
import re
import threading
import time
import uuid


class SetupService:
    def __init__(self, monitor):
        self.m = monitor
        self.lock = threading.Lock()
        self.jobs = {}
        self.answers = {}
        self.processes = {}

    def browse(self, path="", offset=0):
        if not path:
            return {"path": "", "parent": "", "items": [{"path": d, "name": d, "directory": True} for d in self.m._list_drives()], "next": None}
        path = os.path.abspath(os.path.expandvars(str(path)))
        if not os.path.isdir(path):
            raise ValueError("Folder not found on the server.")
        offset = max(0, min(100000, int(offset)))
        with os.scandir(path) as scan:
            entries = sorted(scan, key=lambda entry: entry.name.lower())
        items = []
        for entry in entries[offset:offset+100]:
            try:
                items.append({"path": entry.path, "name": entry.name, "directory": entry.is_dir()})
            except OSError:
                continue
        parent = os.path.dirname(path.rstrip("\\/"))
        if parent == path or len(path.rstrip("\\/")) == 2:
            parent = ""
        return {"path": path, "parent": parent, "items": items, "next": offset+100 if len(entries)>offset+100 else None}

    def job_snapshot(self):
        with self.lock:
            return copy.deepcopy(list(self.jobs.values()))

    def snapshot(self):
        m = self.m
        _cm, cfg = m._backup_cfg()
        healthy, version = m._rclone_health(m._rclone_exe())
        remotes, error = [], ""
        if healthy:
            try:
                remotes = m._rclone_remotes()
            except RuntimeError:
                error = "Could not list remotes. Saved destinations are retained."
        state = m._read_json(m.WEBCONSOLE_STATE, {})
        images = []
        for path in m.image_list_files():
            try:
                images.append({"path": path, "size": os.path.getsize(path), "modified": os.path.getmtime(path)})
            except OSError:
                continue
        st = m._image_state
        with self.lock:
            jobs = copy.deepcopy(list(self.jobs.values()))
        return {"cloud": {"healthy": healthy, "version": version, "remotes": remotes,
                          "error": error, "image_target": m.config.get("rclone_remote", ""),
                          "backup_targets": cfg.get("cloud", {}).get("remotes", []),
                          "folder": cfg.get("cloud", {}).get("remote_folder", "VPS-Backups")},
                "backup": {"sources": cfg.get("backup", {}).get("sources", []),
                           "schedule": cfg.get("schedule", {}),
                           "timezone": time.tzname[0]},
                "images": {"enabled": bool(m.config.get("image_enabled")), "files": images,
                           "phase": st.get("phase"), "file": st.get("vhdx"),
                           "remote": st.get("remote"), "percent": st.get("upload_pct"),
                           "detail": m._panel_text(m.image_progress_line()) if st.get("phase") == "imaging" else st.get("upload_detail", "")},
                "remote": {"bind": state.get("bind", "127.0.0.1"), "port": state.get("port", 8399),
                           "allowed_ips": state.get("allowed_ips", []), "https": bool(state.get("tls_cert"))},
                "jobs": jobs}

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}", value):
            raise ValueError("Remote name must contain 1–40 letters, digits, dots, underscores or hyphens.")
        return value

    def target(self, value):
        if not isinstance(value, str) or len(value) > 300 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\r\n]*", value) or any(ord(c)<32 for c in value):
            raise ValueError("Choose a destination such as gdrive:Server-backups.")
        if value.split(":", 1)[0] + ":" not in self.m._rclone_remotes():
            raise ValueError("That remote is not configured. Refresh the remote list.")
        return value

    def submit(self, args):
        """One bounded worker; no credentials retained in job records or output."""
        op = args.get("op")
        if op == "cancel":
            with self.lock:
                ident = args.get("job")
                if ident in self.answers:
                    self.answers[ident]["value"] = None
                    self.answers[ident]["event"].set()
                    return True, "Cancellation requested."
                proc = self.processes.get(ident)
                if proc:
                    proc.kill()
                    return True, "Sign-in cancellation requested."
            return False, "This operation cannot be cancelled here. Image operations have their own Stop button."
        if op == "answer":
            with self.lock:
                pending = self.answers.get(args.get("job"))
                if not pending or pending["question"] != args.get("question"):
                    return False, "This question expired. Refresh the operation status."
                value = args.get("value")
                if not isinstance(value, str) or len(value) > 16000:
                    return False, "Answer is too long."
                pending["value"] = value
                pending["event"].set()
            return True, "Answer submitted."
        if op not in {"install", "create", "authorize", "client", "test", "delete", "targets", "sources", "schedule", "image_start", "image_upload", "image_stop", "image_link", "remote"}:
            return False, "Unknown setup operation."
        with self.lock:
            if any(j["state"] == "running" for j in self.jobs.values()):
                return False, "Another setup operation is running. Wait for it to finish."
            ident = uuid.uuid4().hex
            self.jobs = {k: v for k, v in list(self.jobs.items())[-7:]}
            self.jobs[ident] = {"id": ident, "op": op, "state": "running", "started": time.time(), "message": "Starting…"}
        threading.Thread(target=self._worker, args=(ident, copy.deepcopy(args)), daemon=True).start()
        return True, {"job": ident}

    def _worker(self, ident, args):
        m = self.m
        m._capture_begin()
        try:
            result = self.execute(args, ident)
            captured = m._capture_end()
            # Captured bot helpers use [X] for failures. Never report these as success.
            if "[X]" in captured or "failed" in captured.lower():
                raise ValueError(m._panel_text(captured)[-1200:])
            message = result or m._panel_text(captured) or "Saved."
            state = "done"
        except Exception as exc:
            m._capture_end()
            message, state = str(exc), "error"
        with self.lock:
            self.jobs[ident].update(state=state, message=m.redact_log(message)[:2000], finished=time.time())
            self.jobs[ident].pop("auth_url", None)
            self.jobs[ident].pop("question", None)
            self.answers.pop(ident, None)
            self.processes.pop(ident, None)
        m.audit_record("Panel setup %s: %s" % (args.get("op"), state))

    def execute(self, a, ident):
        m, op = self.m, a["op"]
        if op == "install":
            m.rclone_install(force=True)
            return "Verified rclone v1.74.4 installation finished. Refresh to see its health."
        if op in {"create", "authorize", "client", "delete"}:
            name = self.name(a.get("name"))
            existing = m._rclone_remotes()
            if op in {"create", "authorize"} and name + ":" in existing:
                raise ValueError("This remote already exists. Choose another name; existing credentials were preserved.")
            if op == "delete":
                _cm, cfg = m._backup_cfg()
                used = [m.config.get("rclone_remote", "")] + cfg.get("cloud", {}).get("remotes", [])
                if any(t.split(":", 1)[0] == name for t in used):
                    raise ValueError("Remove this remote from image and backup targets first.")
                self.run_config(["config", "delete", name])
                return "Remote removed."
            if op == "client":
                if name + ":" not in existing:
                    raise ValueError("Choose an existing remote.")
                cid, secret = str(a.get("client_id", "")).strip(), str(a.get("client_secret", "")).strip()
                if not cid or not secret or max(len(cid), len(secret)) > 4096:
                    raise ValueError("Client ID and secret are required.")
                self.run_config(["config", "update", name, "client_id", cid, "client_secret", secret])
                return "OAuth client saved. Reauthorize using a new remote name or import its token."
            provider = a.get("provider")
            if provider not in {"drive", "onedrive", "dropbox", "s3", "b2", "sftp", "ftp", "webdav"}:
                raise ValueError("Choose a supported provider.")
            options = a.get("options") or {}
            if not isinstance(options, dict) or len(options) > 30:
                raise ValueError("Options must be a JSON object with up to 30 entries.")
            kv = []
            for key, val in options.items():
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or not isinstance(val, str) or len(val) > 12000:
                    raise ValueError("Provider options must contain simple names and string values.")
                allowed = {"drive": {"client_id", "client_secret", "scope", "root_folder_id", "team_drive"},
                           "onedrive": {"client_id", "client_secret", "drive_id", "drive_type", "region"},
                           "dropbox": {"client_id", "client_secret"},
                           "s3": {"provider", "access_key_id", "secret_access_key", "endpoint", "region", "acl", "storage_class"},
                           "b2": {"account", "key", "endpoint"},
                           "sftp": {"host", "user", "pass", "port", "key_file", "key_file_pass"},
                           "ftp": {"host", "user", "pass", "port", "tls"},
                           "webdav": {"url", "vendor", "user", "pass"}}
                if key not in allowed[provider]:
                    raise ValueError("That provider option is not supported by this setup form.")
                kv += [key, val]
            if op == "authorize":
                if provider not in {"drive", "onedrive", "dropbox"}:
                    raise ValueError("Browser sign-in is available for Google Drive, OneDrive and Dropbox.")
                token = self.authorize(provider, options, ident)
                kv = [x for x in kv] + ["token", token]
            elif provider in {"drive", "onedrive", "dropbox"}:
                token = json.loads(str(a.get("token", "")))
                if not isinstance(token, dict) or not token.get("access_token"):
                    raise ValueError("Paste the OAuth JSON containing access_token.")
                kv += ["token", json.dumps(token)]
            elif not kv:
                raise ValueError("Provider options are required.")
            self.run_create(["config", "create", name, provider] + kv, ident)
            m._rclone_register_config()
            return "Remote created. Test it before selecting a destination."
        if op == "test":
            target = self.target(a.get("target"))
            ok, _out = m._rclone_run(["lsd", target], timeout=60)
            if not ok:
                raise ValueError("Connection test failed. Check provider permissions and destination; credentials were preserved.")
            return "Destination is reachable."
        if op == "targets":
            image = str(a.get("image", "")).strip()
            targets = a.get("backups")
            if not isinstance(targets, list) or len(targets) > 20:
                raise ValueError("Choose up to 20 backup destinations.")
            targets = list(dict.fromkeys(self.target(t) for t in targets))
            if any(t.split(":", 1)[1] for t in targets):
                raise ValueError("Backup destinations must be remote names such as gdrive:. Set their folder in the separate folder field.")
            if image:
                self.target(image)
            cm, cfg = m._backup_cfg()
            folder = str(a.get("folder", cfg.get("cloud", {}).get("remote_folder", "VPS-Backups"))).strip("/")
            if len(folder) > 300 or ".." in folder.split("/") or "\n" in folder or "\r" in folder:
                raise ValueError("Enter a relative cloud folder without '..'.")
            previous = m.config.get("rclone_remote", "")
            previous_cloud = copy.deepcopy(cfg.get("cloud", {}))
            cfg.setdefault("cloud", {}).update(remotes=targets, remote_folder=folder)
            cm.save_config(cfg)
            m.config["rclone_remote"] = image
            if not m.save_config():
                m.config["rclone_remote"] = previous
                cfg["cloud"] = previous_cloud
                cm.save_config(cfg)
                raise ValueError("Could not save the image destination.")
            return "Image and backup destinations saved."
        if op == "sources":
            paths = a.get("paths")
            if not isinstance(paths, list) or len(paths) > 100 or any(not isinstance(p, str) or len(p) > 1000 for p in paths):
                raise ValueError("Enter up to 100 source paths, one per line.")
            paths = list(dict.fromkeys(os.path.abspath(os.path.expandvars(p.strip().strip('"'))) for p in paths if p.strip()))
            if any(not os.path.exists(p) for p in paths):
                raise ValueError("A source does not exist on the server. Nothing was changed.")
            cm, cfg = m._backup_cfg()
            cfg.setdefault("backup", {})["sources"] = paths
            cm.save_config(cfg)
            return "Backup sources saved. Files were not deleted."
        if op == "schedule":
            mode = a.get("mode")
            if mode not in {"daily", "interval", "times"} or not isinstance(a.get("enabled"), bool):
                raise ValueError("Choose a schedule mode and enabled state.")
            cm, cfg = m._backup_cfg()
            schedule = dict(cfg.get("schedule", {}), enabled=a["enabled"], mode=mode)
            if mode == "interval":
                hours = int(a.get("value", 0))
                if not 1 <= hours <= 168:
                    raise ValueError("Interval must be 1–168 hours.")
                schedule["interval_hours"] = hours
            else:
                parts = str(a.get("value", "")).split(",")
                if (mode == "daily" and len(parts) != 1) or not 1 <= len(parts) <= 24:
                    raise ValueError("Enter HH:MM, or up to 24 comma-separated times.")
                times = []
                for part in parts:
                    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", part.strip()):
                        raise ValueError("Use 24-hour times in HH:MM format.")
                    times.append(part.strip())
                schedule["time" if mode == "daily" else "times"] = times[0] if mode == "daily" else sorted(set(times))
            cfg["schedule"] = schedule
            cm.save_config(cfg)
            return "Schedule saved in the server timezone; the worker reloads it automatically."
        if op.startswith("image_"):
            if op == "image_link":
                path = a.get("path")
                if path not in m.image_list_files() or not m.config.get("rclone_remote"):
                    raise ValueError("Choose an existing image and configure its cloud destination first.")
                m.image_link([path])
                return None
            if op == "image_stop":
                proc, phase = m._image_state.get("proc"), m._image_state.get("phase")
                if not proc or phase not in {"imaging", "uploading"}:
                    raise ValueError("No image operation is running.")
                proc.kill()
                m._image_state["phase"] = "done" if phase == "uploading" else None
                m._persist_image_state()
                return "Operation stopped. Partial local or remote files are retained."
            if m._image_state.get("phase") in {"imaging", "uploading"}:
                raise ValueError("An image operation is already running.")
            if op == "image_start":
                if not m.config.get("image_enabled"):
                    raise ValueError("Enable system imaging in Settings first.")
                m.image_start()
            else:
                path = a.get("path")
                if path not in m.image_list_files():
                    raise ValueError("Image not found. Refresh the list.")
                if not m.config.get("rclone_remote"):
                    raise ValueError("Save an image cloud target first.")
                m.image_upload([path])
            return "Image operation submitted. Its progress appears below."
        if op == "remote":
            mode = a.get("mode")
            if mode == "local":
                command = ["remote-disable"]
            elif mode == "public":
                command = ["remote-enable", "--allow", "0.0.0.0/0"]
            elif mode == "restricted":
                items = a.get("ips")
                if not isinstance(items, list) or not 1 <= len(items) <= 30:
                    raise ValueError("Enter at least one allowed IP or CIDR.")
                networks = [str(ipaddress.ip_network(i.strip(), strict=False)) for i in items]
                command = ["remote-enable", "--allow", ",".join(networks)]
            else:
                raise ValueError("Choose local, public or restricted access.")
            # Give the queued response time to reach the browser before CLI restarts it.
            time.sleep(2)
            rc, out = m._run_webconsole_cli(command)
            if rc:
                raise ValueError("Panel access update failed: " + m.redact_log(out)[-600:])
            return "Access settings saved. The panel restarted; reopen its address and sign in again."

    def run_config(self, command):
        ok, _out = self.m._rclone_run(command, timeout=120)
        if not ok:
            raise ValueError("rclone could not save this configuration. Check provider fields; existing credentials were preserved where possible.")

    def run_create(self, command, ident):
        """Continue provider questions (e.g. OneDrive drive selection) in the panel."""
        name = command[2]
        for _ in range(30):
            response = self.json_config(command + ["--non-interactive", "--obscure"])
            if not isinstance(response, dict) or "State" not in response:
                raise ValueError("rclone returned no completion state. Test the remote before using it.")
            if response.get("Error"):
                raise ValueError("The provider rejected this setup answer. Remove the unfinished remote and retry.")
            if not response["State"]:
                return
            option = response.get("Option") or {}
            question = uuid.uuid4().hex
            event = threading.Event()
            sensitive = bool(option.get("IsPassword")) or any(k in str(option.get("Name", "")).lower() for k in ("token", "secret", "password"))
            with self.lock:
                self.answers[ident] = {"question": question, "event": event}
                self.jobs[ident]["question"] = {"id": question, "name": str(option.get("Name", "Provider choice"))[:80],
                    "secret": sensitive, "required": bool(option.get("Required")),
                    "default": "" if sensitive else str(option.get("Default", ""))[:1000],
                    "choices": [] if sensitive else [{"value": str(e.get("Value", ""))[:1000], "label": str(e.get("Help", e.get("Value", "")))[:500]} for e in option.get("Examples", [])[:100]]}
                self.jobs[ident]["message"] = "The provider needs another choice. Answer below to continue."
            if not event.wait(600):
                raise ValueError("Provider question expired after 10 minutes. Remove the unfinished remote and retry.")
            with self.lock:
                value = self.answers.pop(ident)["value"]
                self.jobs[ident].pop("question", None)
            if value is None:
                raise ValueError("Setup cancelled. An unfinished remote may remain; remove it before retrying.")
            command = ["config", "update", name, "--continue", "--state", response["State"], "--result", value]
        raise ValueError("Provider setup exceeded 30 questions. Remove the unfinished remote and retry.")

    def json_config(self, command):
        m = self.m
        try:
            result = m.subprocess.run([m._rclone_exe(), "--config", m._rclone_conf_path()] + command,
                                      capture_output=True, timeout=120, creationflags=m.NO_WINDOW,
                                      stdin=m.subprocess.DEVNULL)
            if result.returncode:
                raise ValueError()
            return json.loads(m._decode_out(result.stdout))
        except Exception:
            # stderr may contain normal NOTICE lines or credentials; do not append
            # it to the JSON protocol or publish provider output in job records.
            raise ValueError("Provider configuration failed. Check its fields and retry with a new remote name.") from None

    def authorize(self, provider, options, ident):
        """OAuth output contains credentials. Expose only the localhost sign-in URL."""
        m = self.m
        command = [m._rclone_exe(), "authorize", provider]
        if options.get("client_id"):
            command += [options["client_id"], options.get("client_secret", "")]
        try:
            proc = m.subprocess.Popen(command, stdout=m.subprocess.PIPE, stderr=m.subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace", creationflags=m.NO_WINDOW)
        except Exception:
            raise ValueError("Could not start the sign-in process. Check the rclone installation.") from None
        with self.lock:
            self.processes[ident] = proc
        lines = []
        def reader():
            for line in proc.stdout:
                if sum(map(len, lines)) < 128000:
                    lines.append(line)
                match = re.search(r"http://127\.0\.0\.1:\d+/auth\?[^\s]+", line)
                if match:
                    with self.lock:
                        self.jobs[ident].update(auth_url=match.group(0), message="Sign in using the browser on the server (via RDP). This link cannot receive the callback on your phone.")
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            proc.wait(timeout=600)
        except m.subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=10)
            raise ValueError("Sign-in timed out after 10 minutes. Retry or import an OAuth token.")
        thread.join(5)
        match = re.search(r"\{.*\}", "".join(lines), flags=re.S)
        if proc.returncode or not match:
            raise ValueError("Sign-in was not completed. Retry or import an OAuth token.")
        token = json.loads(match.group(0))
        if not isinstance(token, dict) or not token.get("access_token"):
            raise ValueError("Provider returned no usable token.")
        return json.dumps(token)
