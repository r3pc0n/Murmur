from pathlib import Path

import webview

import logger
import theme_utils
from theme_utils import apply_title_bar_theme

_UI = Path(__file__).parent / "ui" / "log.html"


class LogAPI:
    def get_log(self) -> list:
        return list(logger.get_buffer())

    def get_theme(self) -> dict:
        return theme_utils.theme_payload()

    def clear_log(self):
        logger.clear_buffer()

    def open_history(self):
        logger.open_history()

    def get_startup_log(self) -> list[str]:
        return logger.get_startup_log_lines()

    def open_startup_log(self):
        logger.open_startup_log()


class LogWindow:
    def __init__(self):
        self._window: webview.Window | None = None

    def open(self):
        if self._window:
            try:
                self._window.show()
                return
            except Exception:
                self._window = None

        api = LogAPI()
        self._window = webview.create_window(
            "Murmur Activity",
            url=str(_UI),
            js_api=api,
            width=580,
            height=420,
            background_color=theme_utils.initial_background_color(),
        )
        self._window.events.loaded += lambda: apply_title_bar_theme(self._window)
        self._window.events.closed += self._on_closed

    def _on_closed(self):
        self._window = None
