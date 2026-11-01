"""Build a code-only suite release. Runtime configuration never enters assets."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suite_update import allowed_path, sha, REQUIRED


def build(destination, commit, sequence):
    files = {}
    for name in subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines():
        if allowed_path(name):files[name] = (ROOT / name).read_bytes()
    if not REQUIRED <= set(files):raise ValueError("Missing update components")
    manifest = {"schema": 1, "commit": commit, "sequence": int(sequence),
                "files": {name: sha(data) for name, data in files.items()}}
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():archive.writestr(name, data)
    return manifest


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3])
