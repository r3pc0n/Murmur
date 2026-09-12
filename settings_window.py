import sys
import threading
from pathlib import Path

import webview

import autostart
import cleaner
import config
import hotkeys
import theme_utils
from recorder import get_device_names
from theme_utils import apply_title_bar_theme

_UI = Path(__file__).parent / "ui" / "settings.html"


class SettingsAPI:
    def __init__(self, on_save=None, on_restart=None):
        self._on_save = on_save
        self._on_restart = on_restart
        self._capturing = False

    def get_config(self) -> dict:
        current = config.AUDIO_DEVICE
        return {
            "PUSH_TO_TALK_KEY":       hotkeys.normalize_hotkey(config.PUSH_TO_TALK_KEY),
            "HOTKEY_CAPTURE_MODE":    hotkeys.capture_mode(),
            "HOTKEY_OPTIONS":         hotkeys.hotkey_options(),
            "AUTO_START":             autostart.is_enabled(),
            "AUDIO_DEVICE":           current,
            "WHISPER_MODEL":          config.WHISPER_MODEL,
            "WHISPER_DEVICE":         config.WHISPER_DEVICE,
            "WHISPER_LANGUAGE":       config.WHISPER_LANGUAGE,
            "TRANSCRIPTION_MODE":     config.TRANSCRIPTION_MODE,
            "REMOTE_WHISPER_URL":     config.REMOTE_WHISPER_URL,
            "REMOTE_WHISPER_API_KEY": config.REMOTE_WHISPER_API_KEY,
            "SAVED_SERVERS":          list(config.SAVED_SERVERS),
            "CLOUD_PROVIDER":         config.CLOUD_PROVIDER,
            "CLOUD_VOXTRAL_MODEL":    config.CLOUD_VOXTRAL_MODEL,
            "CLOUD_API_KEY":          config.CLOUD_API_KEY,
            "AI_CLEANUP_ENABLED":     config.AI_CLEANUP_ENABLED,
            "ANTHROPIC_API_KEY":      config.ANTHROPIC_API_KEY,
            "BEEP_ENABLED":           config.BEEP_ENABLED,
            "SHOW_OVERLAY":           config.SHOW_OVERLAY,
            "THEME":                  config.THEME,
            "THEME_OPTIONS":          theme_utils.available_theme_options(),
            "TRANSCRIPTION_STYLE":    config.TRANSCRIPTION_STYLE,
            "CUSTOM_STYLE_PROMPT":    config.CUSTOM_STYLE_PROMPT,
            "USER_PROFILE":           config.USER_PROFILE,
            "WORD_CORRECTIONS":            dict(config.WORD_CORRECTIONS),
            "CLEANUP_BASE_PROMPT":         config.CLEANUP_BASE_PROMPT,
            "CLEANUP_EXTRA_INSTRUCTIONS":  config.CLEANUP_EXTRA_INSTRUCTIONS,
            "CLEANUP_DEFAULT_BASE_PROMPT": cleaner.DEFAULT_BASE_PROMPT,
        }

    def get_devices(self) -> list:
        return get_device_names()

    def get_theme(self) -> dict:
        return theme_utils.theme_payload()

    def capture_hotkey(self) -> str:
        if hotkeys.capture_mode() == "select":
            return ""
        if self._capturing:
            return ""
        self._capturing = True
        try:
            if sys.platform == "win32":
                import keyboard
                key = keyboard.read_key(suppress=True)
            else:
                from pynput import keyboard as _pk
                captured = [None]

                def on_press(k):
                    try:
                        captured[0] = k.name if hasattr(k, "name") else k.char
                    except AttributeError:
                        captured[0] = str(k)
                    return False

                with _pk.Listener(on_press=on_press) as lst:
                    lst.join()
                key = captured[0] or "f9"
            return key
        finally:
            self._capturing = False

    def save_server(self, name: str, url: str, api_key: str) -> list:
        servers = [s for s in config.SAVED_SERVERS if s["name"] != name]
        servers.append({"name": name, "url": url, "api_key": api_key})
        config.save({"SAVED_SERVERS": servers})
        return list(config.SAVED_SERVERS)

    def delete_server(self, name: str) -> list:
        servers = [s for s in config.SAVED_SERVERS if s["name"] != name]
        config.save({"SAVED_SERVERS": servers})
        return list(config.SAVED_SERVERS)

    def save_settings(self, updates: dict, restart: bool = False):
        auto = updates.pop("AUTO_START", None)
        if "PUSH_TO_TALK_KEY" in updates:
            updates["PUSH_TO_TALK_KEY"] = hotkeys.normalize_hotkey(
                updates["PUSH_TO_TALK_KEY"]
            )
        config.save(updates)
        if auto is not None:
            autostart.set_enabled(bool(auto))
        if self._on_save:
            self._on_save(updates)
        if restart and self._on_restart:
            threading.Thread(target=self._on_restart, daemon=True).start()


class SettingsWindow:
    def __init__(self, on_save=None, on_restart=None):
        self._on_save = on_save
        self._on_restart = on_restart
        self._window: webview.Window | None = None

    def open(self):
        if self._window:
            try:
                self._window.show()
                return
            except Exception:
                self._window = None

        api = SettingsAPI(on_save=self._on_save, on_restart=self._on_restart)
        self._window = webview.create_window(
            "Murmur Settings",
            url=str(_UI),
            js_api=api,
            width=740,
            height=540,
            min_size=(600, 420),
            background_color=theme_utils.initial_background_color(),
        )
        self._window.events.loaded += lambda: apply_title_bar_theme(self._window)
        self._window.events.closed += self._on_closed

    def _on_closed(self):
        self._window = None
