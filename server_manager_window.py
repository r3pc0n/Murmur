import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import webview

import config
import logger
import theme_utils
from theme_utils import apply_title_bar_theme

_SERVER_DIR   = Path(__file__).parent / "server"
_VENV_PYTHON  = _SERVER_DIR / "venv" / (
    "Scripts" if sys.platform == "win32" else "bin"
) / ("python.exe" if sys.platform == "win32" else "python")
_SERVER_SCRIPT = _SERVER_DIR / "faster_whisper_server.py"
_REQUIREMENTS  = _SERVER_DIR / "requirements.txt"
_ENV_FILE      = _SERVER_DIR / ".env"
_ENV_EXAMPLE   = _SERVER_DIR / ".env.example"
_UI            = Path(__file__).parent / "ui" / "server.html"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _is_installed() -> bool:
    return _VENV_PYTHON.exists() and _SERVER_SCRIPT.exists()


def _get_local_ip() -> str | None:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _get_tailscale_ip() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-NetIPAddress | Where-Object {$_.IPAddress -like '100.*'} "
             "| Select-Object -First 1 -ExpandProperty IPAddress"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        ip = result.stdout.strip()
        return ip if ip else None
    except Exception:
        return None


def _get_api_key() -> str:
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("MURMUR_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val and val != "vervang-dit-met-een-sterk-wachtwoord":
                    return val
    return ""


def _open_firewall_port():
    if sys.platform != "win32":
        return
    try:
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=Murmur Whisper Server"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if "Murmur Whisper Server" in check.stdout:
            return
        subprocess.run(
            ["powershell", "-Command",
             "Start-Process powershell "
             "-ArgumentList '-NoProfile -Command "
             'New-NetFirewallRule -DisplayName \\"Murmur Whisper Server\\" '
             "-Direction Inbound -Protocol TCP -LocalPort 8765 "
             '-Action Allow -ErrorAction SilentlyContinue\' '
             "-Verb RunAs -Wait"],
            creationflags=_NO_WINDOW,
        )
        logger.log("Firewall rule added: port 8765 open for inbound connections.", level="OK")
    except Exception as e:
        logger.log(f"Firewall rule could not be added: {e}", level="ERROR")


class ServerAPI:
    def __init__(self, get_server_running, start_server, stop_server):
        self._get_server_running = get_server_running
        self._start_server = start_server
        self._stop_server = stop_server
        self._window: webview.Window | None = None

    def _set_window(self, win: webview.Window):
        self._window = win

    def get_state(self) -> dict:
        installed = _is_installed()
        running = self._get_server_running() if installed else False
        return {
            "platform":    sys.platform,
            "installed":   installed,
            "running":     running,
            "local_ip":    _get_local_ip(),
            "tailscale_ip": _get_tailscale_ip(),
            "api_key":     _get_api_key(),
            "autostart":   config.WHISPER_SERVER_AUTOSTART,
        }

    def is_running(self) -> bool:
        return self._get_server_running()

    def get_theme(self) -> dict:
        return theme_utils.theme_payload()

    def start_server(self):
        self._start_server()

    def stop_server(self):
        self._stop_server()

    def set_autostart(self, value: bool):
        config.save({"WHISPER_SERVER_AUTOSTART": value})
        state = "ingeschakeld" if value else "uitgeschakeld"
        logger.log(f"Whisper Server autostart {state}.", level="INFO")

    def generate_key(self) -> dict:
        key = secrets.token_hex(32)
        try:
            if _ENV_FILE.exists():
                lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
                new_lines, replaced = [], False
                for line in lines:
                    if line.startswith("MURMUR_API_KEY="):
                        new_lines.append(f"MURMUR_API_KEY={key}")
                        replaced = True
                    else:
                        new_lines.append(line)
                if not replaced:
                    new_lines.append(f"MURMUR_API_KEY={key}")
                _ENV_FILE.write_text("\n".join(new_lines), encoding="utf-8")
            else:
                _ENV_FILE.write_text(f"MURMUR_API_KEY={key}\n", encoding="utf-8")
            logger.log("Whisper Server API key generated and saved.", level="OK")
            if self._get_server_running():
                self._stop_server()
                self._start_server()
                logger.log("Whisper Server restarted with new API key.", level="OK")
        except Exception as e:
            logger.log(f"API key save failed: {e}", level="ERROR")
        return self.get_state()

    def copy_to_clipboard(self, text: str):
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            pass

    def install_server(self):
        def _run():
            def status(msg):
                if self._window:
                    try:
                        self._window.evaluate_js(
                            f"updateInstallStatus({repr(msg)})"
                        )
                    except Exception:
                        pass

            try:
                status("Creating virtual environment…")
                result = subprocess.run(
                    ["python", "-m", "venv", str(_SERVER_DIR / "venv")],
                    capture_output=True, text=True,
                    creationflags=_NO_WINDOW,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"Venv creation failed:\n{result.stderr}")

                status("Installing dependencies (faster-whisper, FastAPI, uvicorn)…\nThis may take a few minutes.")
                result = subprocess.run(
                    [str(_VENV_PYTHON), "-m", "pip", "install",
                     "-r", str(_REQUIREMENTS), "--quiet"],
                    capture_output=True, text=True,
                    creationflags=_NO_WINDOW,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"pip install failed:\n{result.stderr}")

                if not _ENV_FILE.exists() and _ENV_EXAMPLE.exists():
                    shutil.copy(_ENV_EXAMPLE, _ENV_FILE)

                status("Configuring Windows Firewall for port 8765…")
                _open_firewall_port()

            except Exception as e:
                logger.log(f"Server install failed: {e}", level="ERROR")
                if self._window:
                    try:
                        msg = str(e).replace("'", "\\'")
                        self._window.evaluate_js(
                            f"updateInstallStatus('Installation failed: {msg}')"
                        )
                    except Exception:
                        pass

        import threading
        threading.Thread(target=_run, daemon=True).start()


class ServerManagerWindow:
    def __init__(self, get_server_running, start_server, stop_server):
        self._get_server_running = get_server_running
        self._start_server = start_server
        self._stop_server = stop_server
        self._window: webview.Window | None = None

    def open(self):
        if self._window:
            try:
                self._window.show()
                return
            except Exception:
                self._window = None

        api = ServerAPI(
            get_server_running=self._get_server_running,
            start_server=self._start_server,
            stop_server=self._stop_server,
        )
        self._window = webview.create_window(
            "Murmur Server",
            url=str(_UI),
            js_api=api,
            width=480,
            height=660,
            resizable=False,
            background_color=theme_utils.initial_background_color(),
        )
        self._window.events.loaded += lambda: api._set_window(self._window)
        self._window.events.loaded += lambda: apply_title_bar_theme(self._window)
        self._window.events.closed += self._on_closed

    def _on_closed(self):
        self._window = None
