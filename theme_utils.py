import ctypes
import ctypes.wintypes
import json
import sys
import threading
from pathlib import Path

import config

_OMARCHY_STATE_DIR = Path.home() / ".local/state/omarchy/current"
_BUNDLED_PALETTES_PATH = Path(__file__).parent / "themes" / "omarchy_palettes.json"
_DEFAULT_BACKGROUND_COLOR = "#232326"

_bundled_cache: dict | None = None


def _is_light_mode() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False


def _dwm_set(hwnd, is_dark: bool):
    # DWMWA_USE_IMMERSIVE_DARK_MODE
    val = ctypes.c_int(1 if is_dark else 0)
    for attr in (20, 19):
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)
        ) == 0:
            break

    # DWMWA_CAPTION_COLOR (attr 35, Windows 11+): set explicit caption colour.
    # This cannot be overridden by WebView2's internal compositor.
    # COLORREF format: 0x00BBGGRR
    # DWMWA_CAPTION_COLOR_NONE = 0xFFFFFFFE → revert to system default (dark mode)
    DWMWA_CAPTION_COLOR = 35
    if is_dark:
        color = ctypes.c_uint(0xFFFFFFFE)   # system default (dark)
    else:
        color = ctypes.c_uint(0x00F3F6F9)   # warm light, matches bg-surface
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color)
    )

    # Force non-client area redraw
    SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)


def _apply_for_title(title: str, is_dark: bool):
    import os
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, _):
        dpid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dpid))
        if dpid.value == pid:
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value == title:
                _dwm_set(hwnd, is_dark)
        return True

    ctypes.windll.user32.EnumWindows(_cb, 0)


def apply_title_bar_theme(win):
    """Match the DWM title bar colour to the system light/dark preference.

    Delayed by 250 ms so WebView2 finishes its own compositor setup first.
    """
    if sys.platform != "win32":
        return
    try:
        title = win.title
    except Exception:
        return

    is_dark = not _is_light_mode()

    def _run():
        _apply_for_title(title, is_dark)

    threading.Timer(0.25, _run).start()


def is_omarchy() -> bool:
    return (_OMARCHY_STATE_DIR / "theme.name").exists()


def _bundled_palettes() -> dict:
    global _bundled_cache
    if _bundled_cache is None:
        try:
            _bundled_cache = json.loads(_BUNDLED_PALETTES_PATH.read_text(encoding="utf-8"))
        except Exception:
            _bundled_cache = {}
    return _bundled_cache


def _prettify_theme_name(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


def available_theme_options() -> list[dict]:
    """Options for the Settings appearance picker: system, Omarchy-live
    (only when actually on Omarchy), then every bundled theme by name."""
    options = [{"value": "system", "label": "Follow system light/dark"}]
    if is_omarchy():
        options.append({"value": "omarchy", "label": "Follow Omarchy theme"})
    for slug in sorted(_bundled_palettes()):
        options.append({"value": slug, "label": _prettify_theme_name(slug)})
    return options


def _read_omarchy_live_colors() -> dict | None:
    colors_path = _OMARCHY_STATE_DIR / "theme" / "colors.toml"
    if not colors_path.exists():
        return None
    try:
        import tomllib  # stdlib 3.11+; this call path is Linux-only.
        with open(colors_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _map_palette_to_css_vars(colors: dict) -> dict:
    """Map an Omarchy colors.toml dict onto Murmur's own CSS custom
    properties. --border/--border-mid are deliberately left alone: they're
    already purely mode-driven in the stylesheet, not theme-color-driven."""
    accent = colors.get("accent", "#C8922A")
    r, g, b = _hex_to_rgb(accent)
    return {
        "--bg-base":     colors.get("darker_background", "#1c1c1e"),
        "--bg-surface":  colors.get("background", "#232326"),
        "--bg-raised":   colors.get("lighter_background", "#2a2a2d"),
        "--bg-hover":    colors.get("selection", "#34343a"),
        "--bg-input":    colors.get("dark_background", "#1a1a1c"),
        "--accent":      accent,
        "--accent-dim":  f"rgba({r},{g},{b},0.18)",
        "--accent-glow": f"rgba({r},{g},{b},0.09)",
        "--text-pri":    colors.get("bright_foreground", "#ffffff"),
        "--text-sec":    colors.get("light_foreground", "#bbbbbb"),
        "--text-muted":  colors.get("dark_foreground", "#888888"),
        "--text-accent": accent,
        "--green":       colors.get("green", "#a9b665"),
        "--red":         colors.get("red", "#ea6962"),
        "--amber":       colors.get("yellow", accent),
    }


def resolve_theme() -> tuple[str, dict | None]:
    """Return (mode, overrides) for the currently configured THEME setting.
    overrides is None for "system" mode, meaning: defer entirely to the
    existing prefers-color-scheme-driven [data-theme] CSS, unchanged."""
    theme = config.THEME

    if theme == "omarchy":
        colors = _read_omarchy_live_colors()
        if colors is None:
            return "system", None
        return colors.get("mode", "dark"), _map_palette_to_css_vars(colors)

    if theme != "system":
        colors = _bundled_palettes().get(theme)
        if colors is not None:
            return colors.get("mode", "dark"), _map_palette_to_css_vars(colors)

    return "system", None


def theme_payload() -> dict:
    mode, overrides = resolve_theme()
    return {"mode": mode, "overrides": overrides}


def initial_background_color(default: str = _DEFAULT_BACKGROUND_COLOR) -> str:
    """The right static hex for a window's background_color= at creation.
    `default` is what today's hardcoded value already was for that window,
    used only in "system" mode where there's no specific palette to draw from."""
    _, overrides = resolve_theme()
    return overrides["--bg-surface"] if overrides else default


def apply_theme_to_window(window):
    """Push the current theme to an already-open window (settings-save and
    the Omarchy watcher below both funnel through here)."""
    try:
        window.evaluate_js(f"applyThemeOverrides({json.dumps(theme_payload())})")
    except Exception:
        pass


def _start_linux_theme_watcher(get_open_windows):
    """Poll for a live Omarchy theme switch every 2 s (same cadence as the
    Windows watcher below) and push it to all open windows. Only meaningful
    in "omarchy" mode -- "system" is already live via prefers-color-scheme,
    and a named bundled theme is static by definition."""
    if not is_omarchy():
        return

    theme_name_path = _OMARCHY_STATE_DIR / "theme.name"
    try:
        last_mtime = [theme_name_path.stat().st_mtime]
    except OSError:
        last_mtime = [None]

    def _watch():
        while True:
            threading.Event().wait(2)
            if config.THEME != "omarchy":
                continue
            try:
                mtime = theme_name_path.stat().st_mtime
            except OSError:
                continue
            if mtime != last_mtime[0]:
                last_mtime[0] = mtime
                try:
                    for win in get_open_windows():
                        apply_theme_to_window(win)
                except Exception:
                    pass

    threading.Thread(target=_watch, daemon=True).start()


def start_theme_watcher(get_open_windows):
    """Poll system theme every 2 s and reapply title bar to all open windows.

    get_open_windows: callable returning a list of pywebview Window objects.
    """
    if sys.platform != "win32":
        _start_linux_theme_watcher(get_open_windows)
        return

    import os
    pid = os.getpid()
    _last = [_is_light_mode()]

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _enum_cb(hwnd, _):
        dpid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dpid))
        if dpid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value in _open_titles:
                _dwm_set(hwnd, _current_dark[0])
        return True

    _open_titles = set()
    _current_dark = [not _last[0]]

    def _watch():
        while True:
            threading.Event().wait(2)
            now_light = _is_light_mode()
            if now_light != _last[0]:
                _last[0] = now_light
                _current_dark[0] = not now_light
                try:
                    wins = get_open_windows()
                    _open_titles.clear()
                    for w in wins:
                        try:
                            _open_titles.add(w.title)
                        except Exception:
                            pass
                    ctypes.windll.user32.EnumWindows(_enum_cb, 0)
                except Exception:
                    pass

    threading.Thread(target=_watch, daemon=True).start()
