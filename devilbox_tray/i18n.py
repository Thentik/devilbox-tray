"""
i18n minimaliste basée sur des fichiers JSON dans devilbox_tray/locales/.

Ajouter une langue = déposer un fichier `xx.json` (copie de en.json traduite),
avec une clé spéciale "_name" pour le nom affiché. Rien d'autre à modifier.
"""

import json
from importlib import resources

_FALLBACK = "en"
_current = _FALLBACK
_cache = {}


def _load(code: str) -> dict:
    if code in _cache:
        return _cache[code]
    data = {}
    try:
        path = resources.files("devilbox_tray.locales").joinpath(f"{code}.json")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    _cache[code] = data
    return data


def available_languages() -> dict:
    """Retourne {code: nom_affiché} pour toutes les locales embarquées."""
    langs = {}
    try:
        for res in resources.files("devilbox_tray.locales").iterdir():
            if res.name.endswith(".json"):
                code = res.name[:-5]
                langs[code] = _load(code).get("_name", code)
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    return dict(sorted(langs.items()))


def set_language(code: str):
    """Active une langue. 'auto' => langue système, fallback anglais."""
    global _current
    if code == "auto":
        try:
            from PySide6.QtCore import QLocale
            code = QLocale.system().name().split("_")[0]
        except Exception:
            code = _FALLBACK
    if not _load(code):
        code = _FALLBACK
    _current = code
    _load(_FALLBACK)


def tr(key: str, **kwargs) -> str:
    text = _load(_current).get(key) or _load(_FALLBACK).get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
