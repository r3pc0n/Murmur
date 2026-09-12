import math
import time
import tkinter as tk

import config
import theme_utils

_BAR_COUNT = 5
_BAR_WIDTH = 3
_BAR_GAP = 3
_BAR_MAX_HEIGHT = 16
_BAR_MIN_HEIGHT = 4

_MARGIN = 20
_BOTTOM_MARGIN = 72  # extra clearance for a bottom-docked taskbar

_POSITIONS = {
    "top-left":      lambda sw, sh, w, h: (_MARGIN, _MARGIN),
    "top-center":    lambda sw, sh, w, h: ((sw - w) // 2, _MARGIN),
    "top-right":     lambda sw, sh, w, h: (sw - w - _MARGIN, _MARGIN),
    "middle-left":   lambda sw, sh, w, h: (_MARGIN, (sh - h) // 2),
    "middle-center": lambda sw, sh, w, h: ((sw - w) // 2, (sh - h) // 2),
    "middle-right":  lambda sw, sh, w, h: (sw - w - _MARGIN, (sh - h) // 2),
    "bottom-left":   lambda sw, sh, w, h: (_MARGIN, sh - h - _BOTTOM_MARGIN),
    "bottom-center": lambda sw, sh, w, h: ((sw - w) // 2, sh - h - _BOTTOM_MARGIN),
    "bottom-right":  lambda sw, sh, w, h: (sw - w - _MARGIN, sh - h - _BOTTOM_MARGIN),
}


def _position(sw: int, sh: int, w: int, h: int) -> tuple[int, int]:
    fn = _POSITIONS.get(config.OVERLAY_POSITION, _POSITIONS["bottom-right"])
    return fn(sw, sh, w, h)


def _dim(hex_color: str, factor: float = 0.45) -> str:
    """Darken a hex color for the waveform's off-beat phase, preserving hue."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def _resolve_colors() -> dict:
    _, overrides = theme_utils.resolve_theme()
    if overrides:
        accent = overrides["--accent"]
        return {
            "bg": overrides["--bg-surface"],
            "border": accent,
            "text": overrides["--text-pri"],
            "bar": accent,
            "bar_dim": _dim(accent),
        }
    return {
        "bg": "#1c1c1e", "border": "#3a3a3e", "text": "#f0f0f0",
        "bar": "#D94040", "bar_dim": "#7a2020",
    }


class RecordingOverlay:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._win: tk.Toplevel | None = None
        self._timer_id = None
        self._start_time = 0.0
        self._phase = 0

    def show(self):
        self._start_time = time.time()
        self._root.after(0, self._create)

    def hide(self):
        self._root.after(0, self._destroy)

    def _create(self):
        if self._win and self._win.winfo_exists():
            return

        colors = _resolve_colors()
        self._bar_color = colors["bar"]
        self._bar_color_dim = colors["bar_dim"]

        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.92)
        win.configure(bg=colors["bg"])

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        w, h = 102, 49
        x, y = _position(sw, sh, w, h)
        win.geometry(f"{w}x{h}+{x}+{y}")

        # A theme-colored 1px border via highlightthickness, rather than a
        # nested-frame trick -- the standard Tkinter way to add one.
        frame = tk.Frame(
            win, bg=colors["bg"], padx=14, pady=12,
            highlightthickness=1, highlightbackground=colors["border"],
            highlightcolor=colors["border"],
        )
        frame.pack(fill="both", expand=True)

        bars_width = _BAR_COUNT * _BAR_WIDTH + (_BAR_COUNT - 1) * _BAR_GAP
        self._canvas = tk.Canvas(
            frame, width=bars_width, height=_BAR_MAX_HEIGHT,
            bg=colors["bg"], highlightthickness=0,
        )
        self._canvas.pack(side="left", padx=(0, 10))

        self._label = tk.Label(
            frame, text="0:00", fg=colors["text"],
            bg=colors["bg"], font=("Segoe UI", 12),
        )
        self._label.pack(side="left")

        self._win = win
        self._phase = 0
        self._tick()

    def _draw_bars(self):
        self._canvas.delete("all")
        for i in range(_BAR_COUNT):
            # A staggered sine wave per bar -- the same "wave" motion the
            # splash screen's logo already uses, just driven from Python
            # instead of a CSS keyframe.
            level = (math.sin(self._phase * 0.5 + i * 0.9) + 1) / 2
            height = _BAR_MIN_HEIGHT + level * (_BAR_MAX_HEIGHT - _BAR_MIN_HEIGHT)
            x = i * (_BAR_WIDTH + _BAR_GAP)
            y_top = (_BAR_MAX_HEIGHT - height) / 2
            y_bottom = y_top + height
            color = self._bar_color if level > 0.35 else self._bar_color_dim
            self._canvas.create_rectangle(
                x, y_top, x + _BAR_WIDTH, y_bottom, fill=color, outline="",
            )

    def _tick(self):
        if not self._win or not self._win.winfo_exists():
            return
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._label.config(text=f"{m}:{s:02d}")
        self._draw_bars()
        self._phase += 1
        self._timer_id = self._win.after(120, self._tick)

    def _destroy(self):
        if self._win and self._win.winfo_exists():
            if self._timer_id:
                try:
                    self._win.after_cancel(self._timer_id)
                except Exception:
                    pass
            self._win.destroy()
        self._win = None
        self._timer_id = None
