import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

import app_paths


class HotkeyError(RuntimeError):
    pass


_MURMUR_DESCRIPTION = "Murmur push-to-talk"
_HYPRLAND_KEYS = tuple(f"f{i}" for i in range(1, 13))
_SELECTABLE_KEYS = (
    *_HYPRLAND_KEYS,
    *tuple("abcdefghijklmnopqrstuvwxyz"),
    *tuple("0123456789"),
    "space",
    "page_up",
    "page_down",
)
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "super")
_HYPRLAND_MODIFIERS = {"ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT", "super": "SUPER"}
_HYPRLAND_MODMASKS = {"shift": 1, "ctrl": 4, "alt": 8, "super": 64}
_HYPRLAND_MODIFIER_KEYS = {
    "ctrl": ("Control_L", "Control_R"),
    "alt": ("Alt_L", "Alt_R"),
    "shift": ("Shift_L", "Shift_R"),
    "super": ("Super_L", "Super_R"),
}
_HOTKEY_TRACE_ENV = "MURMUR_HOTKEY_TRACE"
_HOTKEY_SOCKET_RE = re.compile(r"^hotkey-(\d+)-([0-9a-f]+)\.sock$")


def _trace_hotkey(path: str | None, stage: str, event: str, detail: str = ""):
    """Append one opt-in diagnostic record without affecting hotkey delivery."""
    if not path:
        return
    line = f"{time.time_ns()} pid={os.getpid()} stage={stage} event={event}"
    if detail:
        line += f" detail={detail}"
    line += "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8", errors="replace"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _hyprland_event_socket_path() -> Path | None:
    """Hyprland's event stream (distinct from the `hyprctl` command socket).
    Emits a "configreloaded>>" line on every `hyprctl reload` -- including the
    one Omarchy runs after every theme switch, which otherwise silently wipes
    Murmur's runtime-only `hl.bind()` registration (see
    HyprlandHotkeyBackend._watch_config_reloads)."""
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature:
        return None
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "hypr" / signature / ".socket2.sock"


def detect_backend(
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    hyprctl_available: bool | None = None,
) -> str:
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ

    if platform == "win32":
        return "windows"
    if not platform.startswith("linux"):
        raise HotkeyError(f"Global hotkeys are unsupported on platform {platform!r}.")

    session_type = environ.get("XDG_SESSION_TYPE", "").lower()
    is_wayland = session_type == "wayland" or bool(environ.get("WAYLAND_DISPLAY"))
    if not is_wayland:
        return "x11"

    desktop = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    has_hyprctl = shutil.which("hyprctl") is not None if hyprctl_available is None else hyprctl_available
    if "hyprland" in desktop and has_hyprctl:
        return "hyprland"
    return "unsupported-wayland"


def normalize_key(key: str) -> str:
    normalized = key.strip().lower()
    aliases = {"escape": "esc", "return": "enter"}
    normalized = aliases.get(normalized, normalized)
    if len(normalized) == 1 and normalized.isalnum():
        return normalized
    allowed = {
        *_HYPRLAND_KEYS,
        "space", "enter", "tab", "backspace", "delete", "esc",
        "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r",
        "shift", "shift_l", "shift_r", "caps_lock",
        "home", "end", "page_up", "page_down", "up", "down", "left", "right",
    }
    if normalized not in allowed:
        raise HotkeyError(f"Unsupported push-to-talk key: {key!r}.")
    return normalized


def parse_hotkey(value: str) -> tuple[tuple[str, ...], str]:
    """Return canonical modifiers and key for a persisted hotkey string."""
    parts = [part.strip().lower() for part in value.split("+")]
    if not parts or any(not part for part in parts):
        raise HotkeyError(f"Invalid push-to-talk hotkey: {value!r}.")
    aliases = {"control": "ctrl", "win": "super", "meta": "super"}
    parts = [aliases.get(part, part) for part in parts]
    try:
        key = normalize_key(parts[-1])
    except HotkeyError:
        # Windows and X11 historically accepted backend-specific, unmodified
        # key names. Keep those persisted values loadable; Hyprland validates
        # its key separately below.
        if len(parts) != 1:
            raise
        key = parts[-1]
    modifiers = parts[:-1]
    if key in _MODIFIER_ORDER:
        raise HotkeyError("A push-to-talk hotkey must include a non-modifier key.")
    if any(modifier not in _MODIFIER_ORDER for modifier in modifiers):
        raise HotkeyError(f"Unsupported modifier in push-to-talk hotkey: {value!r}.")
    if len(set(modifiers)) != len(modifiers):
        raise HotkeyError(f"Duplicate modifier in push-to-talk hotkey: {value!r}.")
    ordered = tuple(modifier for modifier in _MODIFIER_ORDER if modifier in modifiers)
    return ordered, key


def normalize_hotkey(value: str) -> str:
    modifiers, key = parse_hotkey(value)
    return "+".join((*modifiers, key))


def _hyprland_modifiers(modifiers: tuple[str, ...]) -> str:
    return " ".join(_HYPRLAND_MODIFIERS[modifier] for modifier in modifiers)


def _hyprland_modmask(modifiers: tuple[str, ...]) -> str:
    return str(sum(_HYPRLAND_MODMASKS[modifier] for modifier in modifiers))


def _hyprland_key(key: str) -> str:
    names = {
        "space": "SPACE", "enter": "RETURN", "esc": "ESCAPE",
        "page_up": "PAGE_UP", "page_down": "PAGE_DOWN",
    }
    return names.get(normalize_key(key), normalize_key(key).upper())


def _lua_bind_key(modifiers: tuple[str, ...], hypr_key_token: str) -> str:
    """Build the '<MOD> + <MOD> + <KEY>' string Hyprland's Lua hl.bind/hl.unbind expect."""
    parts = [_HYPRLAND_MODIFIERS[modifier] for modifier in modifiers]
    parts.append(hypr_key_token)
    return " + ".join(parts)


def _lua_quote(value: str) -> str:
    """Escape a string for embedding as a Lua double-quoted string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


# Hyprland's Lua binds no longer echo the exec command in `hyprctl binds`' arg
# field (it's an opaque Lua callback reference instead), so Murmur identifies
# its own bindings by parsing this pid/token pair back out of the description
# it set, rather than out of the exec argv.
_DESCRIPTION_IDENTITY_RE = re.compile(
    re.escape(_MURMUR_DESCRIPTION) + r" (?:press|release|watcher) \[(\d+):([0-9a-f]+)\]$"
)


def _parse_hyprland_binds(output: str) -> list[dict[str, str]]:
    records = []
    for block in output.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or not lines[0].startswith("bind"):
            continue
        record = {"type": lines[0]}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                record[key.strip()] = value.strip()
        records.append(record)
    return records


def _run_hyprctl(args: list[str]) -> str:
    executable = shutil.which("hyprctl")
    if not executable:
        raise HotkeyError("hyprctl is required for Hyprland global hotkeys.")
    result = subprocess.run(
        [executable, *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    unexpected_output = (
        args[0] in ("keyword", "eval") and result.stdout.strip() not in ("", "ok")
    )
    if result.returncode != 0 or unexpected_output:
        detail = result.stderr.strip() or result.stdout.strip() or "no error details"
        raise HotkeyError(f"hyprctl {' '.join(args[:2])} failed: {detail}")
    return result.stdout


def _bindings_for_hotkey(hotkey: str) -> list[dict[str, str]]:
    modifiers, key = parse_hotkey(hotkey)
    hypr_key = _hyprland_key(key)
    modmask = _hyprland_modmask(modifiers)
    return [
        record for record in _parse_hyprland_binds(_run_hyprctl(["binds"]))
        if record.get("key", "").upper() == hypr_key and record.get("modmask") == modmask
    ]


def hotkey_options() -> list[dict[str, object]]:
    if detect_backend() != "hyprland":
        return []
    records = _parse_hyprland_binds(_run_hyprctl(["binds"]))
    options = []
    for key in _SELECTABLE_KEYS:
        hypr_key = _hyprland_key(key)
        conflicts = [
            record for record in records
            if record.get("key", "").upper() == hypr_key
            and record.get("modmask") == "0"
            if not record.get("description", "").startswith(_MURMUR_DESCRIPTION)
        ]
        descriptions = [record.get("description") or record.get("arg", "unknown binding") for record in conflicts]
        options.append({"key": key, "available": not conflicts, "conflicts": descriptions})
    return options


class WindowsHotkeyBackend:
    name = "windows"

    def __init__(self, key: str, on_press: Callable, on_release: Callable):
        # Preserve the keyboard package's existing free-form unmodified names.
        self.key = normalize_hotkey(key)
        self.on_press = on_press
        self.on_release = on_release

    def start(self):
        import keyboard

        held = False

        def on_key_event(event):
            nonlocal held
            if event.event_type == keyboard.KEY_DOWN and not held:
                held = True
                threading.Thread(target=self.on_press, daemon=True).start()
            elif event.event_type == keyboard.KEY_UP and held:
                held = False
                threading.Thread(target=self.on_release, daemon=True).start()

        def listen():
            modifiers, key = parse_hotkey(self.key)

            def matches():
                return all(keyboard.is_pressed(modifier) for modifier in modifiers)

            def filtered_event(event):
                if matches() or held:
                    on_key_event(event)

            keyboard.hook_key(key, filtered_event, suppress=True)
            keyboard.wait()

        threading.Thread(target=listen, daemon=True).start()

    def stop(self):
        import keyboard
        keyboard.unhook_all()


def _pynput_key(key_str: str):
    from pynput import keyboard
    normalized = key_str.lower()
    special = {
        **{f"f{i}": getattr(keyboard.Key, f"f{i}") for i in range(1, 13)},
        "space": keyboard.Key.space, "enter": keyboard.Key.enter, "tab": keyboard.Key.tab,
        "backspace": keyboard.Key.backspace, "delete": keyboard.Key.delete,
        "esc": keyboard.Key.esc, "escape": keyboard.Key.esc,
        "ctrl": keyboard.Key.ctrl, "ctrl_l": keyboard.Key.ctrl_l, "ctrl_r": keyboard.Key.ctrl_r,
        "alt": keyboard.Key.alt, "alt_l": keyboard.Key.alt_l, "alt_r": keyboard.Key.alt_r,
        "shift": keyboard.Key.shift, "shift_l": keyboard.Key.shift_l, "shift_r": keyboard.Key.shift_r,
        "caps_lock": keyboard.Key.caps_lock,
        "up": keyboard.Key.up, "down": keyboard.Key.down,
        "left": keyboard.Key.left, "right": keyboard.Key.right,
        "home": keyboard.Key.home, "end": keyboard.Key.end,
        "page_up": keyboard.Key.page_up, "page_down": keyboard.Key.page_down,
    }
    # Preserve the previous X11 behavior for arbitrary character keys. Key
    # validation is intentionally stricter only in the Hyprland backend.
    return special.get(normalized, normalized)


class X11HotkeyBackend:
    name = "x11"

    def __init__(self, key: str, on_press: Callable, on_release: Callable):
        self.key = normalize_hotkey(key)
        self.on_press = on_press
        self.on_release = on_release
        self.listener = None

    def start(self):
        from pynput import keyboard
        modifiers, key_name = parse_hotkey(self.key)
        target = _pynput_key(key_name)
        modifier_keys = {
            "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
            "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r},
            "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
            "super": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
        }
        pressed = set()
        held = False

        def matches(key):
            if isinstance(target, keyboard.Key):
                return key == target
            return getattr(key, "char", None) == target

        def on_press(key):
            nonlocal held
            pressed.add(key)
            modifiers_down = all(pressed & modifier_keys[modifier] for modifier in modifiers)
            if matches(key) and modifiers_down and not held:
                held = True
                threading.Thread(target=self.on_press, daemon=True).start()

        def on_release(key):
            nonlocal held
            if matches(key) and held:
                held = False
                threading.Thread(target=self.on_release, daemon=True).start()
            pressed.discard(key)

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def stop(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


class HyprlandHotkeyBackend:
    name = "hyprland"

    def __init__(self, key: str, on_press: Callable, on_release: Callable):
        self.hotkey = normalize_hotkey(key)
        self.modifiers, self.key = parse_hotkey(self.hotkey)
        self.key = normalize_key(self.key)
        self.hypr_modifiers = _hyprland_modifiers(self.modifiers)
        self.hypr_key = _hyprland_key(self.key)
        self.on_press = on_press
        self.on_release = on_release
        self.token = uuid.uuid4().hex[:8]
        self.pid = os.getpid()
        runtime_dir = app_paths.runtime_directory()
        self.runtime_dir = runtime_dir
        self.socket_path = runtime_dir / f"hotkey-{self.pid}-{self.token}.sock"
        self._socket = None
        self._thread = None
        self._stop_event = threading.Event()
        self._registered = False
        self._watchers_active = False
        self._held = False
        self._seen_press = False
        self._reload_thread = None
        self.trace_path = os.environ.get(_HOTKEY_TRACE_ENV)

    def _check_conflicts(self):
        conflicts = _bindings_for_hotkey(self.hotkey)
        if conflicts:
            details = "; ".join(r.get("description") or r.get("arg", "unknown binding") for r in conflicts)
            raise HotkeyError(f"{self.hotkey.upper()} is already bound in Hyprland: {details}")

    def _socket_from_record(self, record: dict[str, str]) -> tuple[Path, int] | None:
        match = _DESCRIPTION_IDENTITY_RE.fullmatch(record.get("description", ""))
        if not match:
            return None
        pid, token = match.group(1), match.group(2)
        return self.runtime_dir / f"hotkey-{pid}-{token}.sock", int(pid)

    def _cleanup_dead_sockets(self):
        for path in self.runtime_dir.glob("hotkey-*-*.sock"):
            match = _HOTKEY_SOCKET_RE.fullmatch(path.name)
            if match and not _pid_is_alive(int(match.group(1))):
                try:
                    path.unlink()
                    _trace_hotkey(self.trace_path, "startup", "stale_socket", f"removed:{path.name}")
                except FileNotFoundError:
                    pass

    def _cleanup_stale_binding(self):
        records = _bindings_for_hotkey(self.hotkey)
        if not records:
            return
        stale = []
        for record in records:
            socket_owner = self._socket_from_record(record)
            if socket_owner is None or _pid_is_alive(socket_owner[1]):
                return
            stale.append(socket_owner[0])

        # Hyprland unbinds by key combination rather than description. Only
        # remove it once every matching record belongs to a dead Murmur instance.
        _run_hyprctl(["eval", f'hl.unbind("{_lua_quote(_lua_bind_key(self.modifiers, self.hypr_key))}")'])
        for path in stale:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        _trace_hotkey(self.trace_path, "startup", "stale_binding", "removed")

    def _binding_target(self) -> str:
        return f"{self.hypr_modifiers}, {self.hypr_key}"

    def _release_watcher_keys(self) -> tuple[str, ...]:
        keys = [self.hypr_key]
        for modifier in self.modifiers:
            keys.extend(_HYPRLAND_MODIFIER_KEYS[modifier])
        return tuple(keys)

    def _release_watcher_targets(self) -> tuple[str, ...]:
        return tuple(f"{self.hypr_modifiers}, {key}" for key in self._release_watcher_keys())

    def _watcher_records(self) -> dict[str, list[dict[str, str]]]:
        records = _parse_hyprland_binds(_run_hyprctl(["binds"]))
        modmask = _hyprland_modmask(self.modifiers)
        return {
            target: [
                record for record in records
                if record.get("modmask") == modmask
                and record.get("key", "").upper() == target.split(",", 1)[1].strip().upper()
            ]
            for target in self._release_watcher_targets()
        }

    def _activate_release_watchers(self) -> bool:
        try:
            records = self._watcher_records()
        except HotkeyError as exc:
            _trace_hotkey(self.trace_path, "watchers", "activate", f"failed:{exc}")
            return False
        base_description = f"{_MURMUR_DESCRIPTION} press [{self.pid}:{self.token}]"
        conflicts = [
            record for target, matches in records.items() for record in matches
            if target != self._binding_target() or record.get("description") != base_description
        ]
        if conflicts:
            details = "; ".join(
                record.get("description") or record.get("arg", "unknown binding")
                for record in conflicts
            )
            _trace_hotkey(self.trace_path, "watchers", "activate", f"conflict:{details}")
            return False

        description = f"{_MURMUR_DESCRIPTION} watcher [{self.pid}:{self.token}]"
        statements = []
        for key in self._release_watcher_keys():
            lua_target = _lua_bind_key(self.modifiers, key)
            statements.append(
                'hl.bind("{}", hl.dsp.exec_cmd("{}"), {{ description = "{}", release = true, non_consuming = true }})'.format(
                    _lua_quote(lua_target),
                    _lua_quote(self._command("release", lua_target)),
                    _lua_quote(description),
                )
            )
        try:
            _run_hyprctl(["eval", "; ".join(statements)])
        except HotkeyError as exc:
            _trace_hotkey(self.trace_path, "watchers", "activate", f"failed:{exc}")
            return False
        self._watchers_active = True
        _trace_hotkey(self.trace_path, "watchers", "activate", "registered")
        return True

    def _deactivate_release_watchers(self, preserve_base: bool = True):
        if not self._watchers_active:
            return
        own_description = f"{_MURMUR_DESCRIPTION} watcher [{self.pid}:{self.token}]"
        base_description = f"{_MURMUR_DESCRIPTION} press [{self.pid}:{self.token}]"
        target_keys = dict(zip(self._release_watcher_targets(), self._release_watcher_keys()))
        try:
            records = self._watcher_records()
            unexpected = [
                record for target, matches in records.items() for record in matches
                if record.get("description") != own_description
                and not (
                    target == self._binding_target()
                    and record.get("description") == base_description
                )
            ]
            if unexpected:
                _trace_hotkey(self.trace_path, "watchers", "deactivate", "conflict;left_registered")
                return
            targets = [target for target, matches in records.items() if matches]
            if targets:
                statements = [
                    f'hl.unbind("{_lua_quote(_lua_bind_key(self.modifiers, target_keys[target]))}")'
                    for target in targets
                ]
                if preserve_base and self._binding_target() in targets:
                    statements.append(self._base_press_binding())
                _run_hyprctl(["eval", "; ".join(statements)])
            self._watchers_active = False
            _trace_hotkey(self.trace_path, "watchers", "deactivate", "removed")
        except HotkeyError as exc:
            _trace_hotkey(self.trace_path, "watchers", "deactivate", f"failed:{exc}")

    def _serve(self):
        while not self._stop_event.is_set():
            try:
                event = self._socket.recv(16).decode("ascii")
            except (OSError, UnicodeError):
                break
            callback = None
            if event == "press" and not self._held:
                if self.modifiers and not self._activate_release_watchers():
                    _trace_hotkey(self.trace_path, "socket", event, "press_rejected_no_watchers")
                    continue
                self._held = True
                self._seen_press = True
                callback = self.on_press
                decision = "press"
            elif event == "press":
                decision = "duplicate_press"
            elif event == "release" and self._held:
                self._held = False
                callback = self.on_release
                decision = "release"
            elif event == "release":
                decision = "duplicate_release" if self._seen_press else "ignored_stale_release"
            else:
                decision = "ignored_unknown"
            _trace_hotkey(self.trace_path, "socket", event, decision)
            if callback:
                threading.Thread(target=callback, daemon=True).start()
            if decision == "release" and self.modifiers:
                self._deactivate_release_watchers()

    def _command(self, event: str, binding_target: str | None = None) -> str:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "emit",
            str(self.socket_path),
            event,
            binding_target or _lua_bind_key(self.modifiers, self.hypr_key),
        ]
        if self.trace_path:
            command.append(self.trace_path)
        return shlex.join(command)

    def _base_press_binding(self) -> str:
        description = f"{_MURMUR_DESCRIPTION} press [{self.pid}:{self.token}]"
        return (
            f'hl.bind("{_lua_quote(_lua_bind_key(self.modifiers, self.hypr_key))}", '
            f'hl.dsp.exec_cmd("{_lua_quote(self._command("press"))}"), '
            f'{{ description = "{_lua_quote(description)}" }})'
        )

    def _register_bindings(self):
        """(Re-)register the press binding, and the unmodified-key release
        binding when there are no modifiers. Shared by start() and reload
        recovery so both stay in sync."""
        _run_hyprctl(["eval", self._base_press_binding()])
        self._registered = True
        if not self.modifiers:
            description = f"{_MURMUR_DESCRIPTION} release [{self.pid}:{self.token}]"
            statement = (
                f'hl.bind("{_lua_quote(_lua_bind_key(self.modifiers, self.hypr_key))}", '
                f'hl.dsp.exec_cmd("{_lua_quote(self._command("release"))}"), '
                f'{{ description = "{_lua_quote(description)}", release = true }})'
            )
            _run_hyprctl(["eval", statement])

    def _recover_from_reload(self):
        """`hyprctl reload` (run by Omarchy after every theme switch, or by
        hand) re-executes Hyprland's config from disk, which silently drops
        any hl.bind() registered at runtime via `hyprctl eval` -- including
        ours. Re-register immediately so push-to-talk doesn't stay dead until
        Murmur is restarted."""
        _trace_hotkey(self.trace_path, "reload", "configreloaded", "detected")
        if self._held:
            # The release watcher that would have ended this press is gone
            # too. End the recording ourselves rather than leaving it stuck
            # "held" forever with no way to release it.
            self._held = False
            threading.Thread(target=self.on_release, daemon=True).start()
        self._watchers_active = False
        self._registered = False
        try:
            self._register_bindings()
            _trace_hotkey(self.trace_path, "reload", "configreloaded", "rebound")
        except HotkeyError as exc:
            _trace_hotkey(self.trace_path, "reload", "configreloaded", f"failed:{exc}")

    def _watch_config_reloads(self):
        path = _hyprland_event_socket_path()
        if path is None:
            return
        while not self._stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(str(path))
            except OSError:
                if self._stop_event.wait(2):
                    return
                continue
            buffer = ""
            try:
                while not self._stop_event.is_set():
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.startswith("configreloaded"):
                            self._recover_from_reload()
            finally:
                sock.close()
            if self._stop_event.wait(1):
                return

    def start(self):
        try:
            self._cleanup_dead_sockets()
            self._cleanup_stale_binding()
            self._check_conflicts()
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._socket.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()
            self._register_bindings()
            self._reload_thread = threading.Thread(target=self._watch_config_reloads, daemon=True)
            self._reload_thread.start()
        except Exception as exc:
            self.stop()
            if isinstance(exc, HotkeyError):
                raise
            raise HotkeyError(f"Could not initialize Hyprland hotkey backend: {exc}") from exc

    def stop(self):
        self._deactivate_release_watchers(preserve_base=False)
        if self._registered:
            try:
                _run_hyprctl(["eval", f'hl.unbind("{_lua_quote(_lua_bind_key(self.modifiers, self.hypr_key))}")'])
            except HotkeyError:
                pass
        self._registered = False
        self._stop_event.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass


class UnsupportedWaylandBackend:
    name = "unsupported-wayland"

    def start(self):
        raise HotkeyError(
            "This Wayland compositor has no supported Murmur hotkey backend."
        )

    def stop(self):
        pass


def create_backend(key: str, on_press: Callable, on_release: Callable):
    backend = detect_backend()
    if backend == "windows":
        return WindowsHotkeyBackend(key, on_press, on_release)
    if backend == "x11":
        return X11HotkeyBackend(key, on_press, on_release)
    if backend == "hyprland":
        return HyprlandHotkeyBackend(key, on_press, on_release)
    return UnsupportedWaylandBackend()


def capture_mode() -> str:
    return "select" if detect_backend() in ("hyprland", "unsupported-wayland") else "capture"


def _emit(socket_path: str, event: str, binding_target: str, trace_path: str | None = None) -> int:
    _trace_hotkey(trace_path, "helper", event, "launched")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(event.encode("ascii"), socket_path)
        _trace_hotkey(trace_path, "helper", event, "sent")
        return 0
    except OSError:
        _trace_hotkey(trace_path, "helper", event, "send_failed")
        # A crashed Murmur can leave a runtime binding until the key is next
        # pressed. Only remove it when a binding's own embedded pid/token
        # identifies it as the one pointing at this exact dead socket.
        try:
            target_path = Path(socket_path)
            records = _parse_hyprland_binds(_run_hyprctl(["binds"]))
            for record in records:
                match = _DESCRIPTION_IDENTITY_RE.fullmatch(record.get("description", ""))
                if match and target_path.parent / f"hotkey-{match.group(1)}-{match.group(2)}.sock" == target_path:
                    _run_hyprctl(["eval", f'hl.unbind("{_lua_quote(binding_target)}")'])
                    break
        except HotkeyError:
            pass
        return 1
    finally:
        client.close()


if __name__ == "__main__" and len(sys.argv) in (5, 6) and sys.argv[1] == "emit":
    trace_path = sys.argv[5] if len(sys.argv) == 6 else None
    raise SystemExit(_emit(sys.argv[2], sys.argv[3], sys.argv[4], trace_path))
