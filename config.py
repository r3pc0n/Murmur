import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import app_paths

_SOURCE_DIR = Path(__file__).parent
_SETTINGS_FILE, _ENV_FILE, _LEGACY_SETTINGS_FILE, _LEGACY_ENV_FILE = (
    app_paths.config_files(_SOURCE_DIR)
)
load_dotenv(_ENV_FILE if _ENV_FILE.exists() else _LEGACY_ENV_FILE)

_DEFAULTS: dict = {
    "PUSH_TO_TALK_KEY": "f9",
    "AUDIO_DEVICE": None,
    "WHISPER_MODEL": "large-v3",
    "WHISPER_DEVICE": "cuda",
    "WHISPER_COMPUTE_TYPE": "float16",
    "WHISPER_LANGUAGE": "",
    "WHISPER_SERVER_AUTOSTART": False,
    "TRANSCRIPTION_MODE": "local",
    "REMOTE_WHISPER_URL": "",
    "REMOTE_WHISPER_API_KEY": "",
    "CLOUD_PROVIDER": "voxtral",
    "CLOUD_VOXTRAL_MODEL": "voxtral-mini-latest",
    "CLOUD_API_KEY": "",
    "AI_CLEANUP_ENABLED": True,
    "ANTHROPIC_API_KEY": "",
    "BEEP_ENABLED": True,
    "SHOW_OVERLAY": True,
    "AUTO_START": False,
    "WORD_CORRECTIONS": {},
    "USER_PROFILE": "",
    "TRANSCRIPTION_STYLE": "none",
    "CUSTOM_STYLE_PROMPT": "",
    "SAVED_SERVERS": [],
    "CLEANUP_BASE_PROMPT": "",
    "CLEANUP_EXTRA_INSTRUCTIONS": "",
}

# Non-configurable constants
SAMPLE_RATE = 16000
MIN_RECORDING_SAMPLES = 4800
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


def uses_default_whisper_runtime() -> bool:
    """Return whether the effective Whisper runtime still matches defaults."""
    return all(
        globals().get(key) == _DEFAULTS[key]
        for key in ("WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE")
    )


def _load() -> dict:
    data = dict(_DEFAULTS)
    settings_file = _SETTINGS_FILE if _SETTINGS_FILE.exists() else _LEGACY_SETTINGS_FILE
    if settings_file.exists():
        with open(settings_file) as f:
            data.update(json.load(f))
    env_key = os.getenv("ANTHROPIC_API_KEY")
    if env_key:
        data["ANTHROPIC_API_KEY"] = env_key
    cloud_env_key = os.getenv("MURMUR_CLOUD_API_KEY")
    if cloud_env_key:
        data["CLOUD_API_KEY"] = cloud_env_key
    return data


def save(updates: dict):
    current = _load()
    current.update(updates)
    # Don't persist an API key to disk if it came from .env
    if os.getenv("ANTHROPIC_API_KEY"):
        current.pop("ANTHROPIC_API_KEY", None)
    if os.getenv("MURMUR_CLOUD_API_KEY"):
        current.pop("CLOUD_API_KEY", None)
    serialized = json.dumps(current, indent=2)
    if sys.platform == "win32":
        with open(_SETTINGS_FILE, "w") as f:
            f.write(serialized)
    else:
        app_paths.atomic_write_text(_SETTINGS_FILE, serialized)
    _apply(current)


def initialize_storage():
    """Migrate legacy Linux config once and refresh effective settings."""
    if sys.platform != "win32":
        app_paths.initialize_linux_config(_SOURCE_DIR)
        load_dotenv(_ENV_FILE, override=False)
        _apply(_load())


def _apply(data: dict):
    g = globals()
    for k, v in data.items():
        g[k] = v


_apply(_load())
