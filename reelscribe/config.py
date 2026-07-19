"""User configuration, stored as JSON at ~/.reelscribe.json.

Keys:
    library      absolute path to the library root (the folder that contains Videos/)
    whisper_model  faster-whisper model name (default: small.en)
    cookies_from_browser  optional browser name for yt-dlp cookie extraction
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path(os.environ.get("REELSCRIBE_CONFIG", Path.home() / ".reelscribe.json"))

DEFAULTS: Dict[str, Any] = {
    "library": None,
    "whisper_model": "small.en",
    "cookies_from_browser": None,
}


def load() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    known = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(known, indent=2) + "\n", encoding="utf-8")


def set_value(key: str, value: Any) -> Dict[str, Any]:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown config key: {key}. Known keys: {', '.join(DEFAULTS)}")
    cfg = load()
    cfg[key] = value
    save(cfg)
    return cfg
