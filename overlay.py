import json
import math
import shutil
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import config
import logger
import theme_utils

_BAR_COUNT = 5
_BAR_WIDTH = 3
_BAR_GAP = 3
_BAR_MAX_HEIGHT = 16
_BAR_MIN_HEIGHT = 4

_MARGIN = 20
_BOTTOM_MARGIN = 72  # extra clearance for a bottom-docked taskbar

# Which edges get anchored for each of the 9 grid positions. An axis with
# no anchored edge is centered by gtk-layer-shell automatically.
_ANCHOR_EDGES = {
    "top-left":      ("top", "left"),
    "top-center":    ("top",),
    "top-right":     ("top", "right"),
    "middle-left":   ("left",),
    "middle-center": (),
    "middle-right":  ("right",),
    "bottom-left":   ("bottom", "left"),
    "bottom-center": ("bottom",),
    "bottom-right":  ("bottom", "right"),
}

_layer_shell_missing_logged = False


def _layer_shell():
    """Import GtkLayerShell lazily, so a system missing it (it's a newer,
    separate package from core GTK3) doesn't stop Murmur from starting at
    all -- only the overlay itself, an optional feature, degrades. Returns
    None on failure and logs once, not on every show()."""
    global _layer_shell_missing_logged
    try:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell
        return GtkLayerShell
    except (ValueError, ImportError):
        if not _layer_shell_missing_logged:
            logger.log(
                "Recording overlay disabled: the gtk-layer-shell library "
                "is not installed. See README.md for the package to add.",
                level="ERROR",
            )
            _layer_shell_missing_logged = True
        return None


def _focused_monitor_info() -> tuple[str, str] | None:
    """(model, make) of the currently Hyprland-focused monitor -- a
    Hyprland concept Gdk doesn't expose on its own, so hyprctl is used
    just to answer "which one has focus"; matching it to a Gdk.Monitor
    (see _focused_gdk_monitor) is what actually lets gtk-layer-shell pin
    the overlay to the right output. Returns None if hyprctl is
    unavailable, fails, or reports no focused monitor -- e.g. on X11/other
    compositors/Windows, or a transient query error.
    """
    executable = shutil.which("hyprctl")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "monitors", "-j"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        monitors = json.loads(result.stdout)
        monitor = next((m for m in monitors if m.get("focused")), None)
        return (monitor["model"], monitor["make"]) if monitor else None
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _focused_gdk_monitor() -> Gdk.Monitor | None:
    """The Gdk.Monitor for the currently focused output, or None if it
    can't be determined (caller then lets gtk-layer-shell fall back to
    its own default output)."""
    info = _focused_monitor_info()
    if info is None:
        return None
    model, make = info
    display = Gdk.Display.get_default()
    if display is None:
        return None
    for i in range(display.get_n_monitors()):
        monitor = display.get_monitor(i)
        if monitor.get_model() == model and monitor.get_manufacturer() == make:
            return monitor
    return None


def _dim(hex_color: str, factor: float = 0.45) -> str:
    """Darken a hex color for the waveform's off-beat phase, preserving hue."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def _hex_to_unit_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return r / 255, g / 255, b / 255


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
    """A Wayland layer-shell HUD shown while recording.

    Built on gtk-layer-shell rather than a plain Tkinter popup: a
    Tkinter/X11 override-redirect window has no reliable way to pin
    itself to one monitor on a multi-monitor Wayland/Hyprland setup --
    confirmed live, it was positioned using a coordinate space (XWayland's
    own synthesized single-row layout) that disagreed with Hyprland's real
    monitor arrangement, and Hyprland separately relocated the window onto
    whichever monitor was actually focused shortly after it appeared,
    overriding any requested position. gtk-layer-shell surfaces are a
    native Wayland surface type that Hyprland places directly against a
    real output via the protocol itself, with no such translation or
    override involved.
    """

    def __init__(self):
        self._win: Gtk.Window | None = None
        self._bars: Gtk.DrawingArea | None = None
        self._label: Gtk.Label | None = None
        self._timer_id = None
        self._start_time = 0.0
        self._phase = 0
        self._bar_color = "#D94040"
        self._bar_color_dim = "#7a2020"

    def show(self):
        self._start_time = time.time()
        GLib.idle_add(self._create)

    def hide(self):
        GLib.idle_add(self._destroy)

    def _create(self):
        if self._win is not None:
            return False

        layer_shell = _layer_shell()
        if layer_shell is None:
            return False

        colors = _resolve_colors()
        self._bar_color = colors["bar"]
        self._bar_color_dim = colors["bar_dim"]

        win = Gtk.Window()
        win.set_name("murmur-overlay")
        win.set_decorated(False)
        win.set_resizable(False)
        layer_shell.init_for_window(win)
        layer_shell.set_layer(win, layer_shell.Layer.OVERLAY)
        layer_shell.set_keyboard_mode(win, layer_shell.KeyboardMode.NONE)

        monitor = _focused_gdk_monitor()
        if monitor is not None:
            layer_shell.set_monitor(win, monitor)

        edge_map = {
            "top": layer_shell.Edge.TOP,
            "bottom": layer_shell.Edge.BOTTOM,
            "left": layer_shell.Edge.LEFT,
            "right": layer_shell.Edge.RIGHT,
        }
        edges = _ANCHOR_EDGES.get(config.OVERLAY_POSITION, _ANCHOR_EDGES["bottom-right"])
        for name, gtk_edge in edge_map.items():
            anchored = name in edges
            layer_shell.set_anchor(win, gtk_edge, anchored)
            if anchored:
                margin = _BOTTOM_MARGIN if name == "bottom" else _MARGIN
                layer_shell.set_margin(win, gtk_edge, margin)

        css = Gtk.CssProvider()
        css.load_from_data(f"""
            #murmur-overlay {{
                background-color: {colors['bg']};
                border: 1px solid {colors['border']};
            }}
            #murmur-overlay label {{
                color: {colors['text']};
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }}
        """.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        win.add(box)

        bars_width = _BAR_COUNT * _BAR_WIDTH + (_BAR_COUNT - 1) * _BAR_GAP
        self._bars = Gtk.DrawingArea()
        self._bars.set_size_request(bars_width, _BAR_MAX_HEIGHT)
        self._bars.connect("draw", self._on_draw_bars)
        box.pack_start(self._bars, False, False, 0)

        self._label = Gtk.Label(label="0:00")
        box.pack_start(self._label, False, False, 0)

        self._win = win
        self._phase = 0
        win.show_all()
        self._timer_id = GLib.timeout_add(120, self._tick)
        return False

    def _on_draw_bars(self, _widget, cr):
        for i in range(_BAR_COUNT):
            # A staggered sine wave per bar -- the same "wave" motion the
            # splash screen's logo already uses, just driven from Python
            # instead of a CSS keyframe.
            level = (math.sin(self._phase * 0.5 + i * 0.9) + 1) / 2
            height = _BAR_MIN_HEIGHT + level * (_BAR_MAX_HEIGHT - _BAR_MIN_HEIGHT)
            x = i * (_BAR_WIDTH + _BAR_GAP)
            y_top = (_BAR_MAX_HEIGHT - height) / 2
            color = self._bar_color if level > 0.35 else self._bar_color_dim
            cr.set_source_rgb(*_hex_to_unit_rgb(color))
            cr.rectangle(x, y_top, _BAR_WIDTH, height)
            cr.fill()
        return False

    def _tick(self):
        if self._win is None:
            return False
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._label.set_text(f"{m}:{s:02d}")
        self._phase += 1
        self._bars.queue_draw()
        return True

    def _destroy(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if self._win is not None:
            self._win.destroy()
            self._win = None
        self._bars = None
        self._label = None
        return False
