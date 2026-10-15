"""English message catalog loader.

Contract (do NOT change):
    from i18n import tr, set_language, get_language
    tr("some.key", name="x")   -> translated, .format(**kwargs) applied
    set_language("en")
    get_language() -> "en"

Strings live in strings_en.json next to this file.
Missing keys fall back to the key itself.
"""
import json
import os

DEFAULT_LANGUAGE = "en"
_current_language = DEFAULT_LANGUAGE
_strings = {"en": {}}
_loaded = False


def _load():
    global _loaded
    base = os.path.dirname(os.path.abspath(__file__))
    for lang in ("en",):
        path = os.path.join(base, f"strings_{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _strings[lang] = json.load(f)
        except Exception:
            _strings[lang] = {}
    _loaded = True


def set_language(lang: str) -> None:
    global _current_language
    _current_language = DEFAULT_LANGUAGE


def get_language() -> str:
    return _current_language


def tr(key: str, **kwargs) -> str:
    if not _loaded:
        _load()
    text = _strings.get(_current_language, {}).get(key)
    if text is None:
        text = _strings.get("en", {}).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
