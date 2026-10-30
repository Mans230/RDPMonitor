"""Keep credentials out of console output, persisted logs and exported logs."""
import re


def redact(text):
    text = str(text)
    return re.sub(r"(?i)(?:bot)?\d{5,}:[A-Za-z0-9_-]{20,}", "[REDACTED_TELEGRAM_TOKEN]", text)


def scrub_file(path):
    """Scrub existing retained logs without creating an unredacted backup."""
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            old = stream.read()
        clean = redact(old)
        if clean != old:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(clean)
    except FileNotFoundError:
        pass
