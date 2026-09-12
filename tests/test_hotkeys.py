import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import hotkeys


class BackendSelectionTests(unittest.TestCase):
    def test_windows_backend(self):
        self.assertEqual(hotkeys.detect_backend("win32", {}), "windows")

    def test_x11_backend(self):
        self.assertEqual(
            hotkeys.detect_backend("linux", {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}),
            "x11",
        )

    def test_hyprland_wins_when_xwayland_display_exists(self):
        environment = {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-1",
            "DISPLAY": ":0",
            "XDG_CURRENT_DESKTOP": "Hyprland",
        }
        self.assertEqual(
            hotkeys.detect_backend("linux", environment, hyprctl_available=True),
            "hyprland",
        )

    def test_other_wayland_is_explicitly_unsupported(self):
        environment = {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-1",
            "XDG_CURRENT_DESKTOP": "sway",
        }
        self.assertEqual(
            hotkeys.detect_backend("linux", environment, hyprctl_available=True),
            "unsupported-wayland",
        )

    def test_wayland_settings_use_selection_instead_of_raw_capture(self):
        with patch("hotkeys.detect_backend", return_value="hyprland"):
            self.assertEqual(hotkeys.capture_mode(), "select")


class KeyTests(unittest.TestCase):
    def test_key_normalization(self):
        self.assertEqual(hotkeys.normalize_key(" F8 "), "f8")
        self.assertEqual(hotkeys.normalize_key("Escape"), "esc")
        self.assertEqual(hotkeys._hyprland_key("f8"), "F8")

    def test_unsupported_key_is_rejected(self):
        with self.assertRaises(hotkeys.HotkeyError):
            hotkeys.normalize_key("not-a-key")

    def test_hotkey_normalization_orders_modifiers(self):
        self.assertEqual(hotkeys.normalize_hotkey(" Alt + CTRL + Z "), "ctrl+alt+z")
        self.assertEqual(hotkeys.normalize_hotkey("f8"), "f8")
        self.assertEqual(hotkeys.parse_hotkey("super+shift+x"), (("shift", "super"), "x"))

    def test_hotkey_requires_one_normal_key(self):
        with self.assertRaises(hotkeys.HotkeyError):
            hotkeys.normalize_hotkey("ctrl+alt")
        with self.assertRaises(hotkeys.HotkeyError):
            hotkeys.normalize_hotkey("ctrl+ctrl+z")

    def test_normalized_combination_persists_and_reloads(self):
        fake_dotenv = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
        with patch.dict(sys.modules, {"dotenv": fake_dotenv}):
            import config
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            legacy = Path(directory) / "legacy.json"
            with (
                patch.object(config, "_SETTINGS_FILE", settings),
                patch.object(config, "_LEGACY_SETTINGS_FILE", legacy),
                patch.object(config.sys, "platform", "win32"),
            ):
                value = hotkeys.normalize_hotkey("ALT+ctrl+Z")
                config.save({"PUSH_TO_TALK_KEY": value})
                self.assertEqual(json.loads(settings.read_text())["PUSH_TO_TALK_KEY"], "ctrl+alt+z")
                self.assertEqual(config._load()["PUSH_TO_TALK_KEY"], "ctrl+alt+z")

    def test_x11_preserves_arbitrary_character_keys(self):
        fake_keyboard = types.SimpleNamespace(Key=types.SimpleNamespace(
            **{f"f{i}": object() for i in range(1, 13)},
            **{name: object() for name in (
                "space", "enter", "tab", "backspace", "delete", "esc",
                "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r",
                "shift", "shift_l", "shift_r", "caps_lock", "up", "down",
                "left", "right", "home", "end", "page_up", "page_down",
            )},
        ))
        fake_pynput = types.SimpleNamespace(keyboard=fake_keyboard)
        with patch.dict(sys.modules, {"pynput": fake_pynput}):
            self.assertEqual(hotkeys._pynput_key(";"), ";")

    def test_plain_bind_output_is_parsed(self):
        output = """bindd
\tmodmask: 0
\tkey: F9
\tdescription: Start dictation
\tdispatcher: exec
\targ: voxtype record start

bindrd
\tmodmask: 0
\tkey: F9
\tdescription: Stop dictation
\tdispatcher: exec
\targ: voxtype record stop
"""
        records = hotkeys._parse_hyprland_binds(output)
        self.assertEqual([record["type"] for record in records], ["bindd", "bindrd"])
        self.assertEqual(records[0]["key"], "F9")
        self.assertEqual(records[1]["description"], "Stop dictation")


class HyprlandBackendTests(unittest.TestCase):
    def make_backend(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            return hotkeys.HyprlandHotkeyBackend("f8", Mock(), Mock())

    def test_existing_binding_is_reported_without_unbinding_it(self):
        backend = self.make_backend()
        conflict = {
            "key": "F8", "modmask": "0", "description": "Existing action",
            "arg": "existing-command",
        }
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[conflict]),
            patch("hotkeys._run_hyprctl") as run,
        ):
            with self.assertRaisesRegex(hotkeys.HotkeyError, "Existing action"):
                backend._check_conflicts()
        run.assert_not_called()

    def test_startup_leaves_one_current_pid_socket_and_idle_press_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("hotkeys.app_paths.runtime_directory", return_value=Path(directory)):
                backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
            fake_socket = Mock()
            fake_socket.bind.side_effect = lambda path: Path(path).touch()
            with (
                patch("hotkeys._bindings_for_hotkey", return_value=[]),
                patch("hotkeys._run_hyprctl") as run,
                patch("hotkeys.socket.socket", return_value=fake_socket),
                patch("hotkeys.threading.Thread", return_value=Mock()),
            ):
                backend.start()
                sockets = list(Path(directory).glob("hotkey-*-*.sock"))
                self.assertEqual(sockets, [backend.socket_path])
                self.assertIn(f"hotkey-{hotkeys.os.getpid()}-", backend.socket_path.name)
                calls = [call.args[0] for call in run.call_args_list]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], "eval")
                self.assertTrue(calls[0][1].startswith('hl.bind("CTRL + ALT + Z",'))
                backend.stop()
            self.assertFalse(backend.socket_path.exists())

    def test_dead_pid_socket_is_removed_before_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            stale_path = Path(directory) / "hotkey-424242-deadbeef.sock"
            stale_path.touch()
            with patch("hotkeys.app_paths.runtime_directory", return_value=Path(directory)):
                backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
            with patch("hotkeys._pid_is_alive", return_value=False):
                backend._cleanup_dead_sockets()
            self.assertFalse(stale_path.exists())

    def test_stale_dead_instance_binding_is_removed_but_user_binding_is_not(self):
        backend = self.make_backend()
        stale = {
            "key": "F8", "modmask": "0",
            "description": "Murmur push-to-talk press [424242:deadbeef]",
        }
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[stale]),
            patch("hotkeys._pid_is_alive", return_value=False),
            patch("hotkeys._run_hyprctl") as run,
        ):
            backend._cleanup_stale_binding()
        run.assert_called_once_with(["eval", 'hl.unbind("F8")'])

        user = {"key": "F8", "modmask": "0", "description": "User binding"}
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[stale, user]),
            patch("hotkeys._pid_is_alive", return_value=False),
            patch("hotkeys._run_hyprctl") as run,
        ):
            backend._cleanup_stale_binding()
        run.assert_not_called()

    def test_preexisting_murmur_binding_is_not_overwritten(self):
        backend = self.make_backend()
        stale = {
            "key": "F8", "modmask": "0",
            "description": "Murmur push-to-talk press [old]",
        }
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[stale]),
            patch("hotkeys._run_hyprctl") as run,
        ):
            with self.assertRaises(hotkeys.HotkeyError):
                backend._check_conflicts()
        run.assert_not_called()

    def test_press_release_commands_and_cleanup(self):
        backend = self.make_backend()
        fake_socket = Mock()
        fake_thread = Mock()
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[]),
            patch("hotkeys._run_hyprctl") as run,
            patch("hotkeys.socket.socket", return_value=fake_socket),
            patch("hotkeys.threading.Thread", return_value=fake_thread),
            patch("hotkeys.os.chmod"),
            patch.object(hotkeys.Path, "unlink"),
        ):
            backend.start()
            backend.stop()

        eval_calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(eval_calls[0][0], "eval")
        self.assertEqual(eval_calls[1][0], "eval")
        self.assertIn(" emit ", eval_calls[0][1])
        self.assertIn(" press ", eval_calls[0][1])
        self.assertIn(" release ", eval_calls[1][1])
        self.assertIn("release = true", eval_calls[1][1])
        self.assertEqual(eval_calls[2], ["eval", 'hl.unbind("F8")'])

    def test_release_registration_failure_removes_press_binding(self):
        backend = self.make_backend()
        fake_socket = Mock()
        calls = []

        def run(args):
            calls.append(args)
            if args[0] == "eval" and "push-to-talk release" in args[1]:
                raise hotkeys.HotkeyError("release failed")
            return ""

        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[]),
            patch("hotkeys._run_hyprctl", side_effect=run),
            patch("hotkeys.socket.socket", return_value=fake_socket),
            patch("hotkeys.threading.Thread", return_value=Mock()),
            patch("hotkeys.os.chmod"),
            patch.object(hotkeys.Path, "unlink"),
        ):
            with self.assertRaisesRegex(hotkeys.HotkeyError, "release failed"):
                backend.start()

        self.assertIn(["eval", 'hl.unbind("F8")'], calls)

    def test_modifier_commands_and_exact_cleanup(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            backend = hotkeys.HyprlandHotkeyBackend("Alt+Ctrl+Z", Mock(), Mock())
        fake_socket = Mock()
        with (
            patch("hotkeys._bindings_for_hotkey", return_value=[]),
            patch("hotkeys._run_hyprctl") as run,
            patch("hotkeys.socket.socket", return_value=fake_socket),
            patch("hotkeys.threading.Thread", return_value=Mock()),
            patch("hotkeys.os.chmod"),
            patch.object(hotkeys.Path, "unlink"),
        ):
            backend.start()
            backend.stop()
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls[0][0], "eval")
        self.assertTrue(calls[0][1].startswith('hl.bind("CTRL + ALT + Z",'))
        self.assertEqual(calls[1], ["eval", 'hl.unbind("CTRL + ALT + Z")'])

    def test_socket_events_preserve_hold_semantics_and_ignore_duplicates(self):
        backend = self.make_backend()
        backend._socket = Mock()
        backend._socket.recv.side_effect = [b"release", b"press", b"press", b"release", b"release", OSError()]

        with patch("hotkeys.threading.Thread") as thread:
            backend._serve()

        callbacks = [call.kwargs["target"] for call in thread.call_args_list]
        self.assertEqual(callbacks, [backend.on_press, backend.on_release])

    def test_opt_in_trace_records_helper_and_socket_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "hotkey.trace"
            backend = self.make_backend()
            backend.trace_path = str(trace)
            backend._socket = Mock()
            backend._socket.recv.side_effect = [b"release", b"press", b"press", b"release", b"release", OSError()]

            with patch("hotkeys.threading.Thread"):
                backend._serve()
            with patch("hotkeys.socket.socket") as socket_class:
                hotkeys._emit("/tmp/murmur.sock", "release", ", F8", str(trace))
                socket_class.return_value.sendto.assert_called_once_with(b"release", "/tmp/murmur.sock")

            contents = trace.read_text()
            self.assertIn("stage=socket event=release detail=ignored_stale_release", contents)
            self.assertIn("stage=socket event=press detail=press", contents)
            self.assertIn("stage=socket event=press detail=duplicate_press", contents)
            self.assertIn("stage=socket event=release detail=release", contents)
            self.assertIn("stage=socket event=release detail=duplicate_release", contents)
            self.assertIn("stage=helper event=release detail=launched", contents)
            self.assertIn("stage=helper event=release detail=sent", contents)

    def test_modifier_release_watchers_are_temporary_and_non_consuming(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
        fake_socket = Mock()
        own = f"Murmur push-to-talk watcher [{backend.pid}:{backend.token}]"
        watcher_records = {
            target: [{"key": target.split(",", 1)[1].strip(), "modmask": "0", "description": own}]
            for target in backend._release_watcher_targets()
        }
        with (
            patch.object(backend, "_watcher_records", side_effect=[
                {target: [] for target in backend._release_watcher_targets()},
                watcher_records,
            ]),
            patch("hotkeys._run_hyprctl") as run,
        ):
            self.assertTrue(backend._activate_release_watchers())
            backend._deactivate_release_watchers()

        register = run.call_args_list[0].args[0]
        cleanup = run.call_args_list[1].args[0]
        self.assertEqual(register[0], "eval")
        self.assertIn('hl.bind("CTRL + ALT + Z", ', register[1])
        self.assertIn('hl.bind("CTRL + ALT + Control_L", ', register[1])
        self.assertIn('hl.bind("CTRL + ALT + Control_R", ', register[1])
        self.assertIn('hl.bind("CTRL + ALT + Alt_L", ', register[1])
        self.assertIn('hl.bind("CTRL + ALT + Alt_R", ', register[1])
        self.assertIn("release = true, non_consuming = true", register[1])
        self.assertEqual(cleanup[0], "eval")
        self.assertIn('hl.unbind("CTRL + ALT + Z")', cleanup[1])
        self.assertIn('hl.unbind("CTRL + ALT + Control_L")', cleanup[1])
        self.assertIn('hl.bind("CTRL + ALT + Z", ', cleanup[1])

    def test_ctrl_alt_z_watcher_targets_use_active_modifier_mask(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())

        self.assertEqual(hotkeys._hyprland_modmask(backend.modifiers), "12")
        self.assertEqual(backend._release_watcher_targets(), (
            "CTRL ALT, Z",
            "CTRL ALT, Control_L",
            "CTRL ALT, Control_R",
            "CTRL ALT, Alt_L",
            "CTRL ALT, Alt_R",
        ))

    def test_modifier_watcher_conflict_prevents_registration(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
        records = {target: [] for target in backend._release_watcher_targets()}
        records["CTRL ALT, Control_L"] = [{
            "key": "Control_L", "modmask": "12", "description": "User control release",
        }]
        with (
            patch.object(backend, "_watcher_records", return_value=records),
            patch("hotkeys._run_hyprctl") as run,
        ):
            self.assertFalse(backend._activate_release_watchers())
        run.assert_not_called()

    def test_temporary_watcher_failure_keeps_idle_backend_active(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("hotkeys.app_paths.runtime_directory", return_value=Path(directory)):
                backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
            fake_socket = Mock()
            fake_socket.bind.side_effect = lambda path: Path(path).touch()
            with (
                patch("hotkeys._bindings_for_hotkey", return_value=[]),
                patch("hotkeys._run_hyprctl"),
                patch("hotkeys.socket.socket", return_value=fake_socket),
                patch("hotkeys.threading.Thread", return_value=Mock()),
            ):
                backend.start()
                with patch.object(backend, "_watcher_records", side_effect=hotkeys.HotkeyError("watchers failed")):
                    self.assertFalse(backend._activate_release_watchers())
                self.assertTrue(backend._registered)
                self.assertIsNotNone(backend._socket)
                self.assertTrue(backend.socket_path.exists())
                backend.stop()

    def test_first_constituent_release_stops_once_and_removes_watchers(self):
        with patch(
            "hotkeys.app_paths.runtime_directory",
            return_value=hotkeys.Path("/tmp/murmur-test-runtime"),
        ):
            backend = hotkeys.HyprlandHotkeyBackend("ctrl+alt+z", Mock(), Mock())
        backend._socket = Mock()
        backend._socket.recv.side_effect = [b"press", b"press", b"release", b"release", OSError()]

        with (
            patch.object(backend, "_activate_release_watchers", return_value=True) as activate,
            patch.object(backend, "_deactivate_release_watchers") as deactivate,
            patch("hotkeys.threading.Thread") as thread,
        ):
            backend._serve()

        callbacks = [call.kwargs["target"] for call in thread.call_args_list]
        self.assertEqual(callbacks, [backend.on_press, backend.on_release])
        activate.assert_called_once_with()
        deactivate.assert_called_once_with()

    def test_conflicts_match_complete_modifier_mask(self):
        records = [
            {"key": "Z", "modmask": "68", "description": "Super Ctrl Z"},
            {"key": "Z", "modmask": "76", "description": "Other Z"},
            {"key": "Z", "modmask": "12", "description": "Ctrl Alt Z"},
        ]
        with (
            patch("hotkeys._run_hyprctl", return_value="bind output"),
            patch("hotkeys._parse_hyprland_binds", return_value=records),
        ):
            matches = hotkeys._bindings_for_hotkey("ctrl+alt+z")
        self.assertEqual([record["description"] for record in matches], ["Ctrl Alt Z"])

    def test_hotkey_options_report_conflicts(self):
        records = [
            {"key": "F8", "modmask": "0", "description": "Existing F8 action"},
            {"key": "F9", "modmask": "0", "description": "Murmur push-to-talk press [self]"},
        ]
        with (
            patch("hotkeys.detect_backend", return_value="hyprland"),
            patch("hotkeys._run_hyprctl", return_value="bind output"),
            patch("hotkeys._parse_hyprland_binds", return_value=records),
        ):
            options = {item["key"]: item for item in hotkeys.hotkey_options()}

        self.assertFalse(options["f8"]["available"])
        self.assertEqual(options["f8"]["conflicts"], ["Existing F8 action"])
        self.assertTrue(options["f9"]["available"])


class HyprctlCommandTests(unittest.TestCase):
    @patch("hotkeys.shutil.which", return_value="/usr/bin/hyprctl")
    @patch("hotkeys.subprocess.run")
    def test_hyprctl_uses_argument_array(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")
        hotkeys._run_hyprctl(["keyword", "unbind", ", F8"])
        run.assert_called_once_with(
            ["/usr/bin/hyprctl", "keyword", "unbind", ", F8"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )


if __name__ == "__main__":
    unittest.main()
