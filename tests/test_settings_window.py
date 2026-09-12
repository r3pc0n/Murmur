import unittest
from unittest.mock import Mock, patch

import requests

from settings_window import SettingsAPI


class GetLocalModelsTests(unittest.TestCase):
    def test_returns_sorted_model_ids_on_success(self):
        response = Mock()
        response.json.return_value = {
            "data": [{"id": "qwen2.5:3b"}, {"id": "llama3.2:3b"}]
        }
        with patch("settings_window.requests.get", return_value=response) as get:
            result = SettingsAPI().get_local_models("http://localhost:11434/v1")

        get.assert_called_once_with("http://localhost:11434/v1/models", timeout=3)
        self.assertEqual(result, {"models": ["llama3.2:3b", "qwen2.5:3b"], "error": None})

    def test_strips_trailing_slash_before_building_the_url(self):
        response = Mock()
        response.json.return_value = {"data": []}
        with patch("settings_window.requests.get", return_value=response) as get:
            SettingsAPI().get_local_models("http://localhost:11434/v1/")
        get.assert_called_once_with("http://localhost:11434/v1/models", timeout=3)

    def test_blank_base_url_returns_a_clear_error_without_a_network_call(self):
        with patch("settings_window.requests.get") as get:
            result = SettingsAPI().get_local_models("")
        get.assert_not_called()
        self.assertEqual(result["models"], [])
        self.assertIn("No server URL", result["error"])

    def test_connection_failure_is_reported_not_raised(self):
        with patch(
            "settings_window.requests.get",
            side_effect=requests.ConnectionError("refused"),
        ):
            result = SettingsAPI().get_local_models("http://localhost:11434/v1")
        self.assertEqual(result["models"], [])
        self.assertIn("refused", result["error"])


if __name__ == "__main__":
    unittest.main()
