"""Read local usage journals without starting the monitor or contacting Telegram."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_store import read_events, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", action="append", help="Journal path; may be repeated")
    args = parser.parse_args()
    paths = args.journal or [ROOT / "usage_audit.jsonl", ROOT / "webconsole" / "usage_audit.jsonl"]
    events = [event for path in paths for event in read_events(path)]
    print(json.dumps(summarize(events), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
