"""Application configuration, persisted to config.json next to the app."""
import json
import os
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ACTIVITY_LOG_PATH = ROOT / "activity_log.json"

DEFAULTS = {
    "archive_root": str(ROOT / "Archive"),
    "ollama_url": "http://localhost:11434",
    "model": "gemma4:e2b",
    "mode": "review",          # "review" | "auto"
    "language_hint": "auto",   # "auto" | "ar" | "en"
    "max_tree_depth": 6,
    "recent_limit": 50,
}

_lock = Lock()
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        data = dict(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass
        _cache = data
    return _cache


def get(key: str, default=None):
    with _lock:
        return _load().get(key, default)


def all_settings() -> dict:
    with _lock:
        return dict(_load())


def update(**kwargs) -> dict:
    global _cache
    with _lock:
        data = _load()
        for k, v in kwargs.items():
            if k in DEFAULTS and v is not None:
                data[k] = v
        CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _cache = data
        return dict(data)
