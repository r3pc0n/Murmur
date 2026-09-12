import os
import sys

if sys.platform != "win32":
    # WebKitGTK's GPU-accelerated compositing teardown has hit a confirmed
    # heap-corruption bug in NVIDIA's proprietary driver twice on this exact
    # machine (SIGSEGV 2026-08-18, SIGABRT 2026-09-12, both diagnosed via
    # coredumpctl/gdb with the fault inside libnvidia-gpucomp.so's atexit
    # cleanup). Murmur's windows are simple HTML/CSS with nothing GPU-bound,
    # so force software compositing to avoid that code path entirely rather
    # than wait on an upstream driver fix.
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

# ── Heavy imports ─────────────────────────────────────────────────────────────
import ctypes
import re
import subprocess
import threading
from pathlib import Path

import pystray
import webview
from PIL import Image, ImageDraw

import config
import app_paths
import hotkeys
import logger
from log_window import LogWindow
from overlay import RecordingOverlay
from server_manager_window import ServerManagerWindow
from paster import paste_text
from recorder import Recorder
from settings_window import SettingsWindow
from splash import SplashScreen
import theme_utils
from theme_utils import start_theme_watcher
from transcriber import Transcriber

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── Window icon (transparent background, amber bars) ─────────────────────────

def _build_transparent_ico() -> str:
    import tempfile
    heights_ratio = [0.25, 0.45, 0.65, 0.85, 0.65, 0.45, 0.25]
    sizes = [16, 32, 48, 256]
    images = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bar_w = max(2, int(size * 0.08))
        gap   = max(1, int(size * 0.045))
        n     = len(heights_ratio)
        total_w = n * bar_w + (n - 1) * gap
        sx    = (size - total_w) // 2
        cy    = size // 2
        inner_h = size * 0.72
        bar_r = max(1, bar_w // 2)
        for i, ratio in enumerate(heights_ratio):
            h = max(2, int(inner_h * ratio))
            x = sx + i * (bar_w + gap)
            d.rounded_rectangle(
                [x, cy - h // 2, x + bar_w - 1, cy + h // 2],
                radius=bar_r, fill="#C8922A",
            )
        images.append(img)
    # gdk-pixbuf on Linux does not support compressed .ico files; use .png instead.
    if sys.platform == "win32":
        tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
        tmp.close()
        images[0].save(tmp.name, format="ICO", append_images=images[1:],
                       sizes=[(s, s) for s in sizes])
    else:
        icon_path = app_paths.runtime_directory() / f"window-icon-{os.getpid()}.png"
        images[-1].save(icon_path, format="PNG")  # use the largest size (256px)
        return str(icon_path)
    return tmp.name


# ── Audio feedback ────────────────────────────────────────────────────────────

def _beep(frequency: int, duration_ms: int):
    if not config.BEEP_ENABLED:
        return
    if sys.platform == "win32":
        import winsound
        winsound.Beep(frequency, duration_ms)
    else:
        import numpy as np
        import sounddevice as sd
        n = int(44100 * duration_ms / 1000)
        t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
        tone = (np.sin(2 * np.pi * frequency * t) * 0.3).astype(np.float32)
        sd.play(tone, 44100)


# ── Single instance ───────────────────────────────────────────────────────────
_mutex = None
_lock_file = None
_hotkey_backend = None

def _ensure_single_instance():
    global _mutex, _lock_file
    if sys.platform == "win32":
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\MurmurSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:
            sys.exit(0)
    else:
        import fcntl
        lock_path = app_paths.instance_lock_path()
        _lock_file = open(lock_path, "w")
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(0)


# ── State ─────────────────────────────────────────────────────────────────────
_recording   = False
_processing  = False
_icon: pystray.Icon | None = None
_server_proc: subprocess.Popen | None = None
_overlay: RecordingOverlay | None = None

recorder    = Recorder()
transcriber = Transcriber()
cleaner     = None

settings_win: SettingsWindow | None = None
log_win: LogWindow | None = None
server_manager_win: ServerManagerWindow | None = None
splash: SplashScreen | None = None


# ── Cleaner ───────────────────────────────────────────────────────────────────

def _load_cleaner():
    global cleaner
    cleaner = None
    if config.AI_CLEANUP_ENABLED and config.ANTHROPIC_API_KEY:
        from cleaner import Cleaner
        cleaner = Cleaner()
        logger.log("AI cleanup enabled (Claude Haiku).", level="INFO")
    else:
        logger.log("AI cleanup disabled.", level="INFO")


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _make_icon(recording=False, processing=False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if recording:
        color = "#D94040"
    elif processing:
        color = "#C8922A"
    else:
        color = theme_utils.tray_idle_color()
    heights = [14, 24, 38, 52, 38, 24, 14]
    bar_w, gap = 6, 3
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    sx = (64 - total_w) // 2
    cy = 32
    for i, h in enumerate(heights):
        x = sx + i * (bar_w + gap)
        d.rounded_rectangle([x, cy - h // 2, x + bar_w - 1, cy + h // 2],
                             radius=2, fill=color)
    return img


def _gtk_dispatch(fn):
    """Schedule fn on the GTK main thread. Required for all pystray/GTK calls
    that originate from recording/hotkey threads on Linux."""
    if sys.platform != "win32":
        from gi.repository import GLib
        GLib.idle_add(lambda: fn() or False)
    else:
        fn()


def _update_icon():
    if not _icon:
        return
    new_icon = _make_icon(recording=_recording, processing=_processing)
    if sys.platform != "win32":
        _gtk_dispatch(lambda: setattr(_icon, "icon", new_icon))
    else:
        _icon.icon = new_icon


# ── Recording ─────────────────────────────────────────────────────────────────

def _on_press():
    global _recording
    if _recording or _processing:
        return
    _recording = True
    _update_icon()
    _beep(880, 80)
    recorder.start()
    if config.SHOW_OVERLAY and _overlay:
        _overlay.show()


def _on_release():
    global _recording, _processing
    if not _recording:
        return
    audio = recorder.stop()
    _recording = False
    if _overlay:
        _overlay.hide()

    samples = len(audio) if audio is not None else 0
    if audio is None or samples == 0:
        logger.log("No audio captured — check your microphone input in Settings → Audio.", level="ERROR")
        _beep(220, 400)
        _update_icon()
        return
    if samples < config.MIN_RECORDING_SAMPLES:
        logger.log("Recording too short — hold the key a little longer.", level="ERROR")
        _beep(440, 120)
        _update_icon()
        return

    _processing = True
    _update_icon()
    threading.Thread(target=_process, args=(audio,), daemon=True).start()


def _apply_corrections(text: str) -> str:
    corrections = config.WORD_CORRECTIONS
    if not corrections:
        return text
    for wrong, right in corrections.items():
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', right, text, flags=re.IGNORECASE)
    return text


def _process(audio):
    global _processing
    try:
        text, language = transcriber.transcribe(audio)
        if not text:
            logger.log("Transcription returned empty result.", level="ERROR")
            return
        logger.log(f"Transcribed ({language}): {text}")
        text = _apply_corrections(text)
        if cleaner and config.AI_CLEANUP_ENABLED:
            text = cleaner.clean(text, language)
            logger.log(f"Cleaned: {text}", level="RESULT")
        else:
            logger.log(f"Result: {text}", level="RESULT")
        paste_text(text)
        _beep(660, 80)
    except Exception as e:
        logger.log(f"Error: {e}", level="ERROR")
        _beep(300, 250)
    finally:
        _processing = False
        _update_icon()


# ── Global hotkey backend ─────────────────────────────────────────────────────

def _start_hotkey_backend():
    global _hotkey_backend
    try:
        _hotkey_backend = hotkeys.create_backend(
            config.PUSH_TO_TALK_KEY, _on_press, _on_release
        )
        _hotkey_backend.start()
        logger.log(
            f"Hotkey backend: {_hotkey_backend.name} ({config.PUSH_TO_TALK_KEY.upper()}).",
            level="INFO",
        )
    except hotkeys.HotkeyError as e:
        _hotkey_backend = None
        logger.log(f"Global hotkey unavailable: {e}", level="ERROR")


def _stop_hotkey_backend():
    global _hotkey_backend
    if _hotkey_backend is not None:
        _hotkey_backend.stop()
        _hotkey_backend = None


# ── Whisper server ────────────────────────────────────────────────────────────

def _server_port_in_use() -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", 8765)) == 0


def _server_running() -> bool:
    if _server_proc is not None and _server_proc.poll() is None:
        return True
    return _server_port_in_use()


def _start_whisper_server():
    global _server_proc
    if _server_running():
        return
    script = Path(__file__).parent / "server" / "faster_whisper_server.py"
    venv_bin = "Scripts" if sys.platform == "win32" else "bin"
    python_name = "python.exe" if sys.platform == "win32" else "python"
    python = Path(__file__).parent / "server" / "venv" / venv_bin / python_name
    if not python.exists() or not script.exists():
        logger.log("Whisper Server: files not found. Run the server setup first.", level="ERROR")
        return
    _server_proc = subprocess.Popen(
        [str(python), str(script)],
        cwd=str(script.parent),
        creationflags=_NO_WINDOW,
    )
    logger.log("Whisper Server gestart op poort 8765.", level="OK")
    if _icon:
        _gtk_dispatch(_icon.update_menu)


def _stop_whisper_server():
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None
    if sys.platform == "win32":
        subprocess.run(
            ["powershell", "-Command",
             "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "
             "'*faster_whisper_server*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            creationflags=_NO_WINDOW, capture_output=True,
        )
    else:
        subprocess.run(["pkill", "-f", "faster_whisper_server"], capture_output=True)
    logger.log("Whisper Server gestopt.", level="OK")
    if _icon:
        _gtk_dispatch(_icon.update_menu)


# ── Window openers ────────────────────────────────────────────────────────────

def _open_settings():
    if settings_win:
        threading.Thread(target=settings_win.open, daemon=True).start()


def _open_log():
    if log_win:
        threading.Thread(target=log_win.open, daemon=True).start()


def _open_server_manager():
    if server_manager_win:
        threading.Thread(target=server_manager_win.open, daemon=True).start()


def _get_open_windows():
    wins = []
    for w in [settings_win, log_win, server_manager_win]:
        if w and w._window:
            wins.append(w._window)
    return wins


def _on_settings_saved(updates: dict):
    _load_cleaner()
    if "PUSH_TO_TALK_KEY" in updates:
        _stop_hotkey_backend()
        _start_hotkey_backend()
        logger.log(f"Hotkey updated to: {config.PUSH_TO_TALK_KEY}", level="INFO")
    if "THEME" in updates:
        for win in _get_open_windows():
            theme_utils.apply_theme_to_window(win)
        _update_icon()
    logger.log("Settings saved.", level="INFO")


# ── Restart / Quit ────────────────────────────────────────────────────────────

def _release_lock():
    global _mutex, _lock_file
    if sys.platform == "win32":
        if _mutex:
            ctypes.windll.kernel32.CloseHandle(_mutex)
            _mutex = None
    else:
        if _lock_file:
            import fcntl
            fcntl.flock(_lock_file, fcntl.LOCK_UN)
            _lock_file.close()
            _lock_file = None


def _restart():
    _release_lock()
    _stop_hotkey_backend()
    if _icon:
        _icon.stop()
    for win in list(webview.windows):
        try:
            win.destroy()
        except Exception:
            pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _quit():
    _stop_hotkey_backend()
    if _server_running():
        _stop_whisper_server()
    if _icon:
        _icon.stop()
    for win in list(webview.windows):
        try:
            win.destroy()
        except Exception:
            pass


# ── Overlay (plain tkinter in its own thread) ─────────────────────────────────

def _start_overlay_thread():
    global _overlay
    import tkinter as tk

    ready = threading.Event()

    def _run():
        global _overlay
        tk_root = tk.Tk()
        tk_root.withdraw()
        _overlay = RecordingOverlay(tk_root)
        ready.set()
        tk_root.mainloop()

    threading.Thread(target=_run, daemon=True).start()
    ready.wait(timeout=3)


# ── Background init ───────────────────────────────────────────────────────────

def _background_init():
    global _icon

    logger.log_startup("=== Murmur startup ===")
    logger.log_startup(f"Model: {config.WHISPER_MODEL} | Device: {config.WHISPER_DEVICE} | Compute: {config.WHISPER_COMPUTE_TYPE}")
    logger.log_startup(f"Mode: {config.TRANSCRIPTION_MODE} | Server autostart: {config.WHISPER_SERVER_AUTOSTART} | AI cleanup: {config.AI_CLEANUP_ENABLED}")

    if config.WHISPER_SERVER_AUTOSTART:
        if splash:
            splash.update_status("Starting Whisper Server...")
        logger.log_startup("Starting Whisper Server...")
        _start_whisper_server()
        logger.log_startup("Whisper Server process launched.")

    if splash:
        splash.update_status(f"Loading speech model ({config.WHISPER_MODEL})...")
    logger.log_startup(f"Loading speech model ({config.WHISPER_MODEL} on {config.WHISPER_DEVICE})...")
    transcriber.load()
    logger.log_startup("Speech model ready.")

    if splash:
        splash.update_status("Loading AI cleanup..." if config.AI_CLEANUP_ENABLED else "Almost ready...")
    logger.log_startup("Loading AI cleanup..." if config.AI_CLEANUP_ENABLED else "AI cleanup disabled.")
    _load_cleaner()
    logger.log_startup("Startup complete.")

    key = config.PUSH_TO_TALK_KEY.upper()
    logger.log(f"Ready. Hold {key} to record, release to transcribe and paste.", level="INFO")

    menu = pystray.Menu(
        pystray.MenuItem("Murmur", None, enabled=False),
        pystray.MenuItem(f"Hold {key} to record", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings",         lambda icon, item: _open_settings()),
        pystray.MenuItem("Activity log",     lambda icon, item: _open_log()),
        pystray.MenuItem("Open history",     lambda icon, item: logger.open_history()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Whisper Server...", lambda icon, item: _open_server_manager()),
        pystray.MenuItem(
            lambda item: "● Server running" if _server_running() else "○ Server stopped",
            None, enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart", lambda icon, item: threading.Thread(target=_restart, daemon=True).start()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: _quit()),
    )
    _icon = pystray.Icon("murmur", _make_icon(), "Murmur", menu)

    _start_hotkey_backend()

    if sys.platform == "win32":
        _icon.run_detached()
    else:
        # pywebview already owns the GTK main loop. Initialise pystray on that
        # thread in detached mode so its AppIndicator backend shares the loop.
        # pystray handles both AppIndicator3 and AyatanaAppIndicator3.
        from gi.repository import GLib

        def _init_pystray_on_gtk_thread():
            try:
                _icon.run_detached()
            except Exception as e:
                logger.log(f"Tray icon init error: {e}", level="ERROR")
            return False  # idle_add: run once

        GLib.idle_add(_init_pystray_on_gtk_thread)

    if splash:
        splash.hide()

    start_theme_watcher(_get_open_windows, on_change=_update_icon)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global settings_win, log_win, server_manager_win, splash

    config.initialize_storage()
    logger.initialize_storage()

    if sys.platform != "win32":
        from gi.repository import GLib
        GLib.set_prgname("murmur")
        GLib.set_application_name("Murmur")
        import ctypes as _ct
        try:
            _ct.cdll.LoadLibrary("libX11.so.6").XInitThreads()
        except Exception:
            pass

    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MurmurLabs.Murmur.1")

    _ensure_single_instance()

    settings_win = SettingsWindow(on_save=_on_settings_saved, on_restart=_restart)
    log_win = LogWindow()
    server_manager_win = ServerManagerWindow(
        get_server_running=_server_running,
        start_server=_start_whisper_server,
        stop_server=_stop_whisper_server,
    )

    splash = SplashScreen()
    splash.create()

    _start_overlay_thread()

    _icon_path = _build_transparent_ico()

    def _on_start():
        if sys.platform != "win32":
            from gi.repository import GLib, Gtk
            GLib.idle_add(
                lambda: Gtk.Window.set_default_icon_from_file(_icon_path) and False
            )
        threading.Thread(target=_background_init, daemon=True).start()

    try:
        webview.start(func=_on_start, icon=_icon_path, debug=False)
    finally:
        if sys.platform != "win32":
            try:
                Path(_icon_path).unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
