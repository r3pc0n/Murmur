import unittest
from unittest.mock import Mock, patch

import requests

import cleaner
import config


class IsConfiguredTests(unittest.TestCase):
    def test_openrouter_requires_a_key(self):
        with patch.object(config, "CLEANUP_PROVIDER", "openrouter"):
            with patch.object(config, "OPENROUTER_API_KEY", ""):
                self.assertFalse(cleaner.is_configured())
            with patch.object(config, "OPENROUTER_API_KEY", "sk-or-x"):
                self.assertTrue(cleaner.is_configured())

    def test_local_needs_no_key(self):
        with patch.object(config, "CLEANUP_PROVIDER", "local"):
            self.assertTrue(cleaner.is_configured())

    def test_unknown_provider_is_not_configured(self):
        with patch.object(config, "CLEANUP_PROVIDER", "carrier-pigeon"):
            self.assertFalse(cleaner.is_configured())


class OpenRouterCleanupTests(unittest.TestCase):
    def test_request_shape_and_response(self):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": " Cleaned. "}}]}

        with (
            patch.object(config, "CLEANUP_PROVIDER", "openrouter"),
            patch.object(config, "OPENROUTER_API_KEY", "sk-or-x"),
            patch.object(config, "OPENROUTER_MODEL", "anthropic/claude-haiku-4.5"),
            patch("cleaner.requests.post", return_value=response) as post,
        ):
            result = cleaner.Cleaner().clean("um so yeah")

        self.assertEqual(post.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-or-x")
        self.assertEqual(headers["HTTP-Referer"], "https://murmurlabs.dev")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "anthropic/claude-haiku-4.5")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(
            payload["messages"][-1]["content"], "<transcription>um so yeah</transcription>"
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, "Cleaned.")

    def test_missing_key_raises_without_a_network_call(self):
        with (
            patch.object(config, "CLEANUP_PROVIDER", "openrouter"),
            patch.object(config, "OPENROUTER_API_KEY", ""),
            patch("cleaner.requests.post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenRouter"):
                cleaner.Cleaner().clean("um so yeah")
        post.assert_not_called()


class LocalCleanupTests(unittest.TestCase):
    def test_request_shape_uses_configured_base_url_and_no_auth_header(self):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": " Cleaned. "}}]}

        with (
            patch.object(config, "CLEANUP_PROVIDER", "local"),
            patch.object(config, "LOCAL_CLEANUP_MODEL", "llama3.1"),
            patch.object(config, "LOCAL_CLEANUP_BASE_URL", "http://localhost:11434/v1"),
            patch("cleaner.requests.post", return_value=response) as post,
        ):
            result = cleaner.Cleaner().clean("um so yeah")

        self.assertEqual(post.call_args.args[0], "http://localhost:11434/v1/chat/completions")
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])
        self.assertEqual(post.call_args.kwargs["json"]["model"], "llama3.1")
        self.assertEqual(result, "Cleaned.")

    def test_connection_error_is_wrapped_with_a_clear_message(self):
        with (
            patch.object(config, "CLEANUP_PROVIDER", "local"),
            patch.object(config, "LOCAL_CLEANUP_BASE_URL", "http://localhost:11434/v1"),
            patch("cleaner.requests.post", side_effect=requests.ConnectionError("refused")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not reach the local cleanup model"):
                cleaner.Cleaner().clean("um so yeah")


class EmptyInputTests(unittest.TestCase):
    def test_blank_text_short_circuits_without_a_provider_call(self):
        with (
            patch.object(config, "CLEANUP_PROVIDER", "openrouter"),
            patch("cleaner.requests.post") as post,
        ):
            self.assertEqual(cleaner.Cleaner().clean("   "), "   ")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
