"""Capture/check exact installed runtime dependencies for this Python/platform."""
import argparse
import importlib.metadata as metadata
from pathlib import Path
import platform
import sys
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def requirements(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            yield from requirements(path.parent / line[3:].strip())
        else:
            yield Requirement(line)


def installed_closure():
    pending = list(requirements(ROOT / "requirements.txt"))
    versions, expanded = {}, {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate():
            continue
        if requirement.url:
            raise ValueError("Direct URL requirements need an explicit artifact lock")
        name = canonicalize_name(requirement.name)
        dist = metadata.distribution(name)
        version = dist.version
        if requirement.specifier and version not in requirement.specifier:
            raise ValueError(f"Installed {name}=={version} does not satisfy {requirement}")
        versions[name] = version
        extras = set(requirement.extras) | expanded.get(name, set())
        if name in expanded and extras == expanded[name]:
            continue
        expanded[name] = extras
        for raw in dist.requires or []:
            dependency = Requirement(raw)
            if dependency.marker and not any(dependency.marker.evaluate({"extra": extra})
                                             for extra in extras | {""}):
                continue
            dependency.marker = None
            pending.append(dependency)
    return [f"{name}=={versions[name]}" for name in sorted(versions)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the installed snapshot")
    args = parser.parse_args()
    pins = installed_closure()
    lock = ROOT / "requirements.lock.txt"
    if args.write:
        header = ("# Installed runtime dependency snapshot; no packages were installed.\n"
                  f"# Target: {platform.python_implementation()} {platform.python_version()}, "
                  f"{sys.platform}, {platform.machine()}\n"
                  "# Use a matching isolated environment. Pins do not verify wheel hashes.\n")
        lock.write_text(header + "\n".join(pins) + "\n", encoding="utf-8")
    recorded = [line.strip() for line in lock.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    if recorded != pins:
        raise SystemExit("Dependency snapshot differs from this environment")
    print(f"PASS: {len(pins)} exact runtime dependency versions match the installed environment.")


if __name__ == "__main__":
    main()
