import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import config
import theme_utils

_SAMPLE_DARK = {
    "mode": "dark",
    "accent": "#7daea3",
    "selection": "#504945",
    "background": "#282828",
    "dark_background": "#1e1e1e",
    "darker_background": "#161616",
    "lighter_background": "#3c3836",
    "foreground": "#d4be98",
    "dark_foreground": "#7c6f64",
    "light_foreground": "#bdae93",
    "bright_foreground": "#d4be98",
    "red": "#ea6962",
    "yellow": "#d8a657",
    "green": "#a9b665",
}


class PaletteMappingTests(unittest.TestCase):
    def test_maps_omarchy_keys_to_murmur_css_vars(self):
        css = theme_utils._map_palette_to_css_vars(_SAMPLE_DARK)
        self.assertEqual(css["--bg-base"], "#161616")
        self.assertEqual(css["--bg-surface"], "#282828")
        self.assertEqual(css["--bg-raised"], "#3c3836")
        self.assertEqual(css["--bg-hover"], "#504945")
        self.assertEqual(css["--bg-input"], "#1e1e1e")
        self.assertEqual(css["--accent"], "#7daea3")
        self.assertEqual(css["--text-pri"], "#d4be98")
        self.assertEqual(css["--text-sec"], "#bdae93")
        self.assertEqual(css["--text-muted"], "#7c6f64")
        self.assertEqual(css["--green"], "#a9b665")
        self.assertEqual(css["--red"], "#ea6962")
        self.assertEqual(css["--amber"], "#d8a657")

    def test_accent_dim_and_glow_are_derived_rgba(self):
        css = theme_utils._map_palette_to_css_vars(_SAMPLE_DARK)
        # accent #7daea3 -> (125, 174, 163)
        self.assertEqual(css["--accent-dim"], "rgba(125,174,163,0.18)")
        self.assertEqual(css["--accent-glow"], "rgba(125,174,163,0.09)")


class ResolveThemeTests(unittest.TestCase):
    def test_system_mode_has_no_overrides(self):
        with patch.object(config, "THEME", "system"):
            self.assertEqual(theme_utils.resolve_theme(), ("system", None))

    def test_named_bundled_theme_resolves_to_its_palette(self):
        with (
            patch.object(config, "THEME", "gruvbox"),
            patch.object(theme_utils, "_bundled_palettes", return_value={"gruvbox": _SAMPLE_DARK}),
        ):
            mode, overrides = theme_utils.resolve_theme()
        self.assertEqual(mode, "dark")
        self.assertEqual(overrides["--accent"], "#7daea3")

    def test_unknown_named_theme_falls_back_to_system(self):
        with (
            patch.object(config, "THEME", "not-a-real-theme"),
            patch.object(theme_utils, "_bundled_palettes", return_value={}),
        ):
            self.assertEqual(theme_utils.resolve_theme(), ("system", None))

    def test_omarchy_mode_reads_live_colors(self):
        with (
            patch.object(config, "THEME", "omarchy"),
            patch.object(theme_utils, "_read_omarchy_live_colors", return_value=_SAMPLE_DARK),
        ):
            mode, overrides = theme_utils.resolve_theme()
        self.assertEqual(mode, "dark")
        self.assertEqual(overrides["--accent"], "#7daea3")

    def test_omarchy_mode_falls_back_to_system_when_colors_missing(self):
        with (
            patch.object(config, "THEME", "omarchy"),
            patch.object(theme_utils, "_read_omarchy_live_colors", return_value=None),
        ):
            self.assertEqual(theme_utils.resolve_theme(), ("system", None))


class ThemeOptionsTests(unittest.TestCase):
    def test_omarchy_option_only_offered_when_on_omarchy(self):
        with (
            patch.object(theme_utils, "is_omarchy", return_value=True),
            patch.object(theme_utils, "_bundled_palettes", return_value={"gruvbox": _SAMPLE_DARK}),
        ):
            values = [o["value"] for o in theme_utils.available_theme_options()]
        self.assertIn("omarchy", values)
        self.assertIn("system", values)
        self.assertIn("gruvbox", values)

        with (
            patch.object(theme_utils, "is_omarchy", return_value=False),
            patch.object(theme_utils, "_bundled_palettes", return_value={"gruvbox": _SAMPLE_DARK}),
        ):
            values = [o["value"] for o in theme_utils.available_theme_options()]
        self.assertNotIn("omarchy", values)
        self.assertIn("system", values)


class ApplyThemeToWindowTests(unittest.TestCase):
    def test_evaluates_js_with_theme_payload(self):
        window = Mock()
        with patch.object(config, "THEME", "system"):
            theme_utils.apply_theme_to_window(window)
        window.evaluate_js.assert_called_once()
        js = window.evaluate_js.call_args.args[0]
        self.assertIn("applyThemeOverrides", js)
        self.assertIn('"mode": "system"', js)

    def test_swallows_errors_from_a_closed_window(self):
        window = Mock()
        window.evaluate_js.side_effect = RuntimeError("window is closed")
        theme_utils.apply_theme_to_window(window)  # must not raise


class BundledPalettesAssetTests(unittest.TestCase):
    def test_bundled_json_parses_and_has_required_keys(self):
        path = Path(theme_utils.__file__).parent / "themes" / "omarchy_palettes.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 22)
        required = {
            "mode", "accent", "selection", "background", "dark_background",
            "darker_background", "lighter_background", "foreground",
            "dark_foreground", "light_foreground", "bright_foreground",
            "red", "yellow", "green",
        }
        for name, colors in data.items():
            missing = required - colors.keys()
            self.assertFalse(missing, f"{name} missing keys: {missing}")


if __name__ == "__main__":
    unittest.main()
