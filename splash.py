import ctypes
import sys
from pathlib import Path

import webview

import theme_utils
from theme_utils import apply_title_bar_theme

_UI = Path(__file__).parent / "ui" / "splash.html"


class SplashAPI:
    def get_status(self):
        return "Starting up..."

    def get_theme(self) -> dict:
        return theme_utils.theme_payload()


class SplashScreen:
    def __init__(self):
        self._window: webview.Window | None = None

    def create(self) -> webview.Window:
        w, h = 320, 160
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            x = (user32.GetSystemMetrics(0) - w) // 2
            y = (user32.GetSystemMetrics(1) - h) // 2
        else:
            x = y = None
        api = SplashAPI()
        self._window = webview.create_window(
            "Murmur",
            url=str(_UI),
            js_api=api,
            width=w,
            height=h,
            x=x,
            y=y,
            resizable=False,
            frameless=True,
            on_top=True,
            background_color=theme_utils.initial_background_color(default="#1c1c1e"),
        )
        self._window.events.loaded += lambda: apply_title_bar_theme(self._window)
        return self._window

    def update_status(self, text: str, percent: int | None = None):
        if not self._window:
            return
        safe = text.replace("\\", "\\\\").replace("'", "\\'")
        js = f"var el = document.getElementById('status'); if (el) el.textContent = '{safe}';"
        js += "var f = document.querySelector('.bar-fill');"
        if percent is None:
            js += "if (f) f.classList.remove('determinate');"
        else:
            pct = max(0, min(100, percent))
            js += f"if (f) {{ f.classList.add('determinate'); f.style.width = '{pct}%'; }}"
        self._window.evaluate_js(js)

    def hide(self):
        if self._window:
            # Stop infinite CSS animations before hiding — on Linux, WebKitGTK
            # does not pause rendering for hidden windows, so the animations keep
            # driving the renderer at ~60 fps and peg a CPU core.
            self._window.evaluate_js(
                "document.querySelectorAll('.bar,.bar-fill')"
                ".forEach(function(e){e.style.animation='none';});"
            )
            self._window.hide()
            # Keep window alive to hold the webview event loop open
