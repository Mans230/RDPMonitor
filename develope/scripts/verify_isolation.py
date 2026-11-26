"""Read-only verification of the source snapshot and the unchanged live source."""
import hashlib
import json
from pathlib import Path


def main():
    development = Path(__file__).resolve().parents[1]
    baseline = development / ".baseline"
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    changed = []
    for relative, expected in manifest.items():
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Invalid snapshot path")
        for label, root in (("original", development.parent), ("snapshot", baseline)):
            path = root / rel
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                failures.append(f"{label}: {relative}")
        path = development / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            changed.append(relative)
    print(f"Checked {len(manifest)} original files and their baseline copies.")
    print("Modified development source: " + ", ".join(changed))
    if failures:
        print("INTEGRITY CHECK FAILED\n" + "\n".join(failures))
        return 1
    print("PASS: original source and baseline snapshot are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
