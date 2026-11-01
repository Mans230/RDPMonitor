"""Release-based, transactional updates for the Windows RDP Suite.

Trust boundary: HTTPS GitHub releases from this fixed repository, with the
GitHub asset SHA256, tag commit and successful main-branch CI all verified.
This is integrity checking, not a separate publisher-signature scheme.
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid
import zipfile

REPO = "Mans230/RDPMonitor"
API = "https://api.github.com/repos/" + REPO
ASSET = "rdpmonitor-update.zip"
MAX_ZIP = 20 * 1024 * 1024
REQUIRED = {"rdp_monitor.py", "rdp_suite.py", "suite_update.py", "requirements.lock.txt",
            "webconsole/RDPWebConsole.py", "webconsole/webconsole_ui.html"}
TASKS = ("RDPSuite", "RDPSuiteBoot", "RDPSuiteBackup")


class BusyError(RuntimeError):
    pass


def allowed_path(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        return False
    parts = PurePosixPath(name).parts
    if name.startswith("/") or any(p in (".", "..") or p.startswith(".") for p in parts):
        return False
    reserved = {"CON", "PRN", "AUX", "NUL", *["COM%d" % n for n in range(1, 10)], *["LPT%d" % n for n in range(1, 10)]}
    if any(p.endswith((".", " ")) or p.split(".")[0].upper() in reserved for p in parts):
        return False
    if PurePosixPath(name).as_posix() != name:
        return False
    if len(parts) == 1:
        return name.endswith(".py") or name in {"requirements.txt", "requirements.lock.txt"}
    if len(parts) == 2 and parts[0] == "webconsole":
        return PurePosixPath(name).suffix in {".py", ".html", ".css", ".js"}
    if len(parts) == 3 and parts[:2] == ("backup", "app"):
        return name.endswith(".py")
    return name in {"backup/requirements.txt", "scripts/install_suite.ps1", "scripts/install_updates.ps1"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {} if default is None else default


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                                 "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                                capture_output=True, creationflags=0x08000000)
        if result.returncode:
            raise RuntimeError("Cannot protect update storage permissions.")


@contextlib.contextmanager
def update_lock(path):
    with open(path, "a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():stream.write(b"0");stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BusyError("An update or protected operation is already running.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Manager:
    def __init__(self, root=None, protect=True):
        self.root = Path(root or Path(__file__).parent).resolve()
        self.home = self.root / "control" / "updates"
        self.protect = protect

    def prepare(self):
        if self.protect:
            private_dir(self.home)
        else:
            self.home.mkdir(parents=True, exist_ok=True)

    def status(self):
        settings = read_json(self.home / "settings.json", {"enabled": False, "interval_hours": 24})
        state = read_json(self.home / "status.json")
        version = read_json(self.root / ".production-version.json")
        return {"settings": settings, "state": state, "current": version.get("commit"),
                "source": "https://github.com/" + REPO + "/releases", "installed": (self.home / "installed.json").exists(),
                "next_check": (state.get("checked_at", 0) + settings["interval_hours"] * 3600) if settings["enabled"] else None}

    def configure(self, enabled, hours=24):
        if not isinstance(enabled, bool) or not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= 168:
            raise ValueError("Use on/off and an interval of 1–168 hours.")
        self.prepare()
        atomic(self.home / "settings.json", {"enabled": enabled, "interval_hours": int(hours)})

    def queue(self, operation):
        if operation not in {"check", "apply"}:
            raise ValueError("Choose check or apply.")
        self.prepare()
        path = self.home / "request.json"
        with update_lock(self.home / "queue.lock"):
            previous = read_json(path)
            if previous and time.time() - previous.get("created", 0) < 3600:
                raise ValueError("An update request is already pending.")
            request = {"id": uuid.uuid4().hex, "operation": operation, "created": time.time()}
            atomic(path, request)
        # Release the queue lock before waking the independent task; it may
        # consume the request before schtasks itself returns.
        try:
            result = subprocess.run(["schtasks", "/Run", "/TN", "RDPSuiteUpdate"], capture_output=True,
                                    timeout=15, creationflags=0x08000000 if os.name == "nt" else 0)
            if result.returncode:raise RuntimeError()
        except Exception:
            with update_lock(self.home / "queue.lock"):
                if read_json(path).get("id") == request["id"]:path.unlink(missing_ok=True)
            raise RuntimeError("Updater task could not start. Run python rdp_suite.py install as Administrator.") from None
        return "Update request queued; follow status. Installation restarts the bot and panel."

    def state(self, phase, message, **extra):
        previous = read_json(self.home / "status.json")
        previous.update(phase=phase, message=message, updated=time.time(), **extra)
        atomic(self.home / "status.json", previous)

    @staticmethod
    def fetch(url, limit=MAX_ZIP):
        import requests
        hosts = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
                raise ValueError("Update URL is outside the trusted HTTPS hosts.")
            with requests.get(url, headers={"User-Agent": "RDPMonitor-Updater", "Accept": "application/vnd.github+json"},
                              timeout=(15, 90), stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = response.headers.get("Location", "")
                    continue
                if response.status_code == 404:
                    raise LookupError("No published suite update is available yet.")
                response.raise_for_status()
                chunks, size = [], 0
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > limit:
                        raise ValueError("Update download exceeds its size limit.")
                    chunks.append(block)
                return b"".join(chunks)
        raise ValueError("Too many update download redirects.")

    def release(self):
        release = json.loads(self.fetch(API + "/releases/latest", 2 * 1024 * 1024))
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease") or not re.fullmatch(r"suite-\d+-[a-f0-9]{12}", tag):
            raise ValueError("Latest release is not a stable suite update.")
        assets = [a for a in release.get("assets", []) if a.get("name") == ASSET]
        if len(assets) != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", assets[0].get("digest") or ""):
            raise ValueError("Release has no unique SHA256-verified update asset.")
        asset = assets[0]
        expected = "https://github.com/" + REPO + "/releases/download/" + tag + "/" + ASSET
        if asset.get("browser_download_url", "").lower() != expected.lower() or not 0 < int(asset.get("size", 0)) <= MAX_ZIP:
            raise ValueError("Release asset URL or size is invalid.")
        payload = self.fetch(asset["browser_download_url"])
        if sha(payload) != asset["digest"].split(":", 1)[1]:
            raise ValueError("Release checksum mismatch; nothing was installed.")
        manifest, files = self.unpack(payload)
        commit = manifest["commit"]
        if tag != "suite-%d-%s" % (manifest["sequence"], commit[:12]):
            raise ValueError("Release tag and package identity do not match.")
        ref = json.loads(self.fetch(API + "/git/ref/tags/" + tag, 1024 * 1024))
        if ref.get("object", {}).get("type") != "commit" or ref["object"].get("sha") != commit:
            raise ValueError("Release tag does not point to the package commit.")
        runs = json.loads(self.fetch(API + "/actions/workflows/tests.yml/runs?head_sha=" + commit + "&event=push&status=success&per_page=5", 2 * 1024 * 1024))
        if not any(r.get("head_sha") == commit and r.get("head_branch") == "main" and r.get("conclusion") == "success" for r in runs.get("workflow_runs", [])):
            raise ValueError("The release has no completed successful main-branch validation.")
        return manifest, files, tag

    @staticmethod
    def unpack(payload):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(entries) > 300 or len(set(n.casefold() for n in names)) != len(names) or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
                raise ValueError("Invalid update archive size or duplicate names.")
            if "manifest.json" not in names or any(n != "manifest.json" and not allowed_path(n) for n in names):
                raise ValueError("Update archive attempts to replace a protected path.")
            if any(i.file_size > 5 * 1024 * 1024 or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in entries):
                raise ValueError("Invalid update entry size or symbolic link.")
            manifest = json.loads(archive.read("manifest.json"))
            files = manifest.get("files", {})
            if (manifest.get("schema") != 1 or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("commit", ""))
                    or not isinstance(manifest.get("sequence"), int) or manifest["sequence"] < 1
                    or not isinstance(files, dict) or not REQUIRED <= set(files)
                    or set(names) != set(files) | {"manifest.json"}):
                raise ValueError("Incomplete update manifest.")
            contents = {}
            for name, digest in files.items():
                data = archive.read(name)
                if not re.fullmatch(r"[a-f0-9]{64}", str(digest)) or sha(data) != digest:
                    raise ValueError("Update file checksum mismatch.")
                if name.endswith(".py"):
                    compile(data, name, "exec")
                contents[name] = data
            return manifest, contents

    def run(self, runtime):
        self.prepare()
        with update_lock(self.home / "run.lock"):
            self.recover(runtime)
            request_path = self.home / "request.json"
            with update_lock(self.home / "queue.lock"):
                request = read_json(request_path)
                request_path.unlink(missing_ok=True)
            manual = request.get("operation") if time.time() - request.get("created", 0) < 3600 else None
            settings = self.status()["settings"]
            old_state = read_json(self.home / "status.json")
            due = time.time() - old_state.get("checked_at", 0) >= settings["interval_hours"] * 3600
            if not manual and (not settings["enabled"] or not due):
                return
            self.state("checking", "Checking the latest validated release.", checked_at=time.time())
            try:
                manifest, files, tag = self.release()
                version = read_json(self.root / ".production-version.json")
                if version.get("commit") == manifest["commit"]:
                    self.state("current", "Bot and panel are up to date.", available=manifest["commit"], release=tag)
                    return
                if manifest["sequence"] <= version.get("release_sequence", 0):
                    raise ValueError("Refusing to downgrade to an older release.")
                current = version.get("commit", "")
                if re.fullmatch(r"[a-f0-9]{40}", current):
                    comparison = json.loads(self.fetch(API + "/compare/" + current + "..." + manifest["commit"], 2 * 1024 * 1024))
                    if comparison.get("status") != "ahead":
                        raise ValueError("Release is older than or diverges from this installation.")
                if old_state.get("failed_commit") == manifest["commit"] and not manual:
                    self.state("blocked", "This release previously failed; use a manual retry or wait for another release.")
                    return
                installed_lock = self.root / "requirements.lock.txt"
                if not installed_lock.exists() or files["requirements.lock.txt"].replace(b"\r\n", b"\n") != installed_lock.read_bytes().replace(b"\r\n", b"\n"):
                    self.state("manual_required", "Dependencies changed. Install this release manually; running code was preserved.", available=manifest["commit"], release=tag)
                    return
                self.state("available", "A validated bot + panel update is available.", available=manifest["commit"], release=tag)
                if manual == "check" or not manual and not settings["enabled"]:
                    return
                reason = runtime.busy_reason()
                if reason:
                    self.state("deferred", reason + " Update will retry on the next hourly task run.", checked_at=0)
                    return
                self.install(manifest, files, runtime)
            except LookupError as exc:
                self.state("no_release", str(exc))
            except Exception as exc:
                # Never publish response bodies, provider URLs or process output.
                if read_json(self.home / "status.json").get("phase") != "rolled_back":
                    message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Network or local update operation failed."
                    self.state("error", message + " Running settings were retained.")
                raise

    def target(self, name):
        target = (self.root / name).resolve()
        if not allowed_path(name) or not target.is_relative_to(self.root):
            raise ValueError("Unsafe deployment target.")
        # A junction/symlink inside the install could otherwise redirect writes.
        for parent in [self.root / name, *(self.root / name).parents]:
            if parent == self.root:
                break
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ValueError("Update target crosses a link or junction.")
        return target

    def install(self, manifest, files, runtime):
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(update_lock(self.home / "activity.lock"))
            except BusyError:
                self.state("deferred", "Backup or image work is active; installation deferred.", checked_at=0)
                return
            self._install(manifest, files, runtime)

    def _install(self, manifest, files, runtime):
        checkpoint = self.home / ("rollback-" + uuid.uuid4().hex)
        checkpoint.mkdir()
        present = []
        for name in files:
            target = self.target(name)
            if target.exists():
                saved = checkpoint / name;saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved);present.append(name)
        # Keep private configuration rollback copies, but never ship/overwrite
        # them with a release package.
        config_names = ["config.json", "backup/config.json", "webconsole/webconsole_state.json", ".production-version.json"]
        for name in config_names:
            target = self.root / name
            if target.exists():
                saved = checkpoint / name;saved.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(target, saved)
        tasks = runtime.capture()
        journal = {"schema": 1, "phase": "applying", "checkpoint": checkpoint.name,
                   "files": list(files), "present": present, "tasks": tasks, "commit": manifest["commit"]}
        atomic(self.home / "journal.json", journal)
        self.state("applying", "Installing the validated release. Bot and panel will restart.")
        try:
            if runtime.busy_reason():raise RuntimeError("An operation started before installation.")
            runtime.stop(tasks)
            reason = runtime.busy_reason()
            if reason:
                raise RuntimeError("A backup or image started while stopping tasks.")
            for name, data in files.items():
                target = self.target(name);target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + ".update-new");temp.write_bytes(data);os.replace(temp, target)
            self.state("restarting", "Verifying the new bot and HTTPS panel.")
            runtime.start(tasks)
            runtime.health()
            version = read_json(self.root / ".production-version.json")
            version.update(commit=manifest["commit"], release_sequence=manifest["sequence"], deployed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), update_checkpoint=str(checkpoint))
            atomic(self.root / ".production-version.json", version)
            journal["phase"] = "complete";atomic(self.home / "journal.json", journal)
            self.state("installed", "Bot and panel updated successfully.", installed=manifest["commit"], failed_commit=None)
        except Exception:
            self.restore(journal, runtime)
            self.state("rolled_back", "The new release did not pass health checks. Previous code and settings were restored.", failed_commit=manifest["commit"])
            raise

    def restore(self, journal, runtime):
        checkpoint = self.home / str(journal.get("checkpoint", ""))
        if not re.fullmatch(r"rollback-[a-f0-9]{32}", checkpoint.name) or checkpoint.parent != self.home:
            raise ValueError("Invalid rollback checkpoint.")
        runtime.stop(journal["tasks"])
        for name in journal["files"]:
            target = self.target(name)
            if name in journal["present"]:
                shutil.copy2(checkpoint / name, target)
            else:
                target.unlink(missing_ok=True)
        for name in ("config.json", "backup/config.json", "webconsole/webconsole_state.json", ".production-version.json"):
            saved = checkpoint / name
            if saved.exists():shutil.copy2(saved, self.root / name)
        runtime.start(journal["tasks"]);runtime.health()
        journal["phase"] = "restored";atomic(self.home / "journal.json", journal)

    def recover(self, runtime):
        journal = read_json(self.home / "journal.json")
        if journal.get("phase") == "applying":
            self.restore(journal, runtime)
            self.state("rolled_back", "Recovered an interrupted update.", failed_commit=journal["commit"])


class WindowsRuntime:
    def __init__(self, root):
        self.root = Path(root)
        if os.name != "nt":
            raise RuntimeError("Automatic installation requires Windows scheduled tasks.")
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise PermissionError("Automatic installation requires Administrator/SYSTEM.")

    def ps(self, text):
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; " + text],
                                capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        if result.returncode:raise RuntimeError("Scheduled task operation failed.")
        return result.stdout

    def capture(self):
        # State is an enum in PowerShell JSON; query its stable string explicitly.
        result = json.loads(self.ps("Get-ScheduledTask -TaskName RDPSuite,RDPSuiteBoot,RDPSuiteBackup | ForEach-Object { @{name=$_.TaskName;state=$_.State.ToString()} } | ConvertTo-Json -Compress"))
        tasks = {t["name"]: t["state"] for t in result}
        if set(tasks) != set(TASKS):raise RuntimeError("Suite tasks are missing.")
        return tasks

    def busy_reason(self):
        backup = read_json(self.root / "backup/control/status.json")
        image = read_json(self.root / "image_state.json")
        if backup.get("state") == "running":return "Backup is running."
        if image.get("phase") in {"imaging", "uploading"}:return "A system image operation is running."
        control = self.root / "control"
        reads = {"suite_update_get", "settings_get", "setup_get", "setup_jobs", "setup_browse", "users_list", "traffic_get", "rdp_status"}
        for path in [*control.glob("request-*.json"), *control.glob("*.processing"), control / "request.json"]:
            if not path.exists():continue
            request = read_json(path)
            if request.get("action") not in reads:
                return "An administrative request is running."
        if (self.root / "backup/control/request.json").exists():return "A backup is queued."
        return ""

    def stop(self, tasks):
        runtime = read_json(self.root / "suite_user.pid.json")
        backup = read_json(self.root / "backup/control/status.json")
        self.ps("Get-ScheduledTask -TaskName RDPSuite,RDPSuiteBoot,RDPSuiteBackup | ForEach-Object { Disable-ScheduledTask -InputObject $_ | Out-Null; Stop-ScheduledTask -InputObject $_ }")
        import psutil
        for pid in [runtime.get("supervisor"), *runtime.get("children", {}).values(), backup.get("pid")]:
            if not pid:continue
            try:
                process = psutil.Process(int(pid))
                command = " ".join(process.cmdline()).lower()
                if str(self.root).lower() not in command or not process.name().lower().startswith("python"):
                    raise RuntimeError("Unexpected runtime process identity.")
                process.terminate();process.wait(10)
            except psutil.NoSuchProcess:pass

    def start(self, tasks):
        enabled = [name for name in TASKS if tasks.get(name) != "Disabled"]
        hosting = "RDPSuite" if tasks.get("RDPSuite") == "Running" else "RDPSuiteBoot"
        if hosting not in enabled:raise RuntimeError("No enabled runtime task to restart.")
        # Keep the boot fallback disabled until the desktop runtime has passed
        # its stop-boot handoff, avoiding two startups at a minute boundary.
        for name in enabled:
            if name != "RDPSuiteBoot" or hosting == "RDPSuiteBoot":
                self.ps("Enable-ScheduledTask -TaskName '" + name + "' | Out-Null")
        try:
            self.ps("Start-ScheduledTask -TaskName '" + hosting + "'")
        except RuntimeError:
            if hosting != "RDPSuite" or "RDPSuiteBoot" not in enabled:raise
            self.ps("Enable-ScheduledTask -TaskName RDPSuiteBoot | Out-Null; Start-ScheduledTask -TaskName RDPSuiteBoot")
        if hosting == "RDPSuite" and "RDPSuiteBoot" in enabled:
            time.sleep(3)
            self.ps("Enable-ScheduledTask -TaskName RDPSuiteBoot | Out-Null")
        if tasks.get("RDPSuiteBackup") == "Running":self.ps("Start-ScheduledTask -TaskName RDPSuiteBackup")

    def health(self):
        import requests
        import psutil
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                runtime = read_json(self.root / "suite_user.pid.json")
                monitor_pid = runtime["children"]["monitor"]
                if time.time() - runtime["updated"] > 15 or not psutil.pid_exists(monitor_pid):raise ValueError()
                # Test the monitor mailbox as well as the web listener.
                state = read_json(self.root / "webconsole/webconsole_state.json")
                bind = state.get("bind", "127.0.0.1");remote = bind not in ("127.0.0.1", "::1", "localhost")
                url = ("https" if remote else "http") + "://127.0.0.1:" + str(state.get("port", 8399))
                with requests.Session() as session:
                    session.verify = state.get("tls_cert") if remote else True
                    # DPAPI stays in memory; credentials never enter commands/logs.
                    sys.path.insert(0, str(self.root))
                    import rdp_monitor
                    token = rdp_monitor.webconsole_token()
                    response = session.post(url + "/api/login", json={"token": token}, timeout=5)
                    response.raise_for_status();csrf = response.json()["csrf"]
                    try:
                        response = session.get(url + "/api/settings", timeout=15)
                        response.raise_for_status()
                        if not response.json().get("groups"):raise ValueError()
                    finally:session.post(url + "/api/logout", json={}, headers={"X-CSRF-Token": csrf}, timeout=5)
                return
            except Exception:time.sleep(2)
        raise RuntimeError("New bot/panel health check did not pass.")


def main():
    manager = Manager()
    operation = sys.argv[1] if len(sys.argv) > 1 else "status"
    if operation == "status":print(json.dumps(manager.status(), indent=2));return
    if operation == "init":
        manager.prepare()
        if not (manager.home / "settings.json").exists():manager.configure(False)
        atomic(manager.home / "installed.json", {"task": "RDPSuiteUpdate"});return
    if operation in {"on", "off"}:
        manager.configure(operation == "on", int(sys.argv[2]) if len(sys.argv)>2 else 24);return
    if operation in {"check", "apply"}:print(manager.queue(operation));return
    if operation == "--scheduled":
        manager.run(WindowsRuntime(manager.root));return
    raise ValueError("Use status, on, off, check or apply.")


if __name__ == "__main__":
    try:main()
    except Exception:
        print("Suite update failed; inspect control/updates/status.json locally.", file=sys.stderr)
        sys.exit(1)
