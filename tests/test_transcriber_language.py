import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import config
import transcriber


class LanguageConfigurationTests(unittest.TestCase):
    def test_default_language_is_automatic(self):
        self.assertEqual(config._DEFAULTS["WHISPER_LANGUAGE"], "")

    def test_existing_settings_without_language_use_default(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text(json.dumps({"WHISPER_MODEL": "medium"}))
            with patch.object(config, "_SETTINGS_FILE", settings_file):
                loaded = config._load()

        self.assertEqual(loaded["WHISPER_LANGUAGE"], "")
        self.assertEqual(loaded["WHISPER_MODEL"], "medium")

    def test_language_setting_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            with (
                patch.object(config, "_SETTINGS_FILE", settings_file),
                patch.object(config, "_apply"),
            ):
                config.save({"WHISPER_LANGUAGE": "nl"})
            saved = json.loads(settings_file.read_text())

        self.assertEqual(saved["WHISPER_LANGUAGE"], "nl")


class LocalLanguageTests(unittest.TestCase):
    def transcribe_with(self, language):
        model = Mock()
        model.transcribe.return_value = (
            [SimpleNamespace(text=" test ")],
            SimpleNamespace(language=language or "nl"),
        )
        instance = transcriber.Transcriber()
        instance.model = model
        with (
            patch.object(config, "WHISPER_LANGUAGE", language),
            patch.object(config, "WORD_CORRECTIONS", {}),
        ):
            result = instance._transcribe_local(np.zeros(160, dtype=np.float32))
        return model, result

    def test_auto_detect_passes_none(self):
        model, result = self.transcribe_with("")
        self.assertIsNone(model.transcribe.call_args.kwargs["language"])
        self.assertEqual(result, ("test", "nl"))

    def test_explicit_dutch_is_passed_to_faster_whisper(self):
        model, _ = self.transcribe_with("nl")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "nl")

    def test_explicit_english_is_passed_to_faster_whisper(self):
        model, _ = self.transcribe_with("en")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "en")


class RemoteLanguageTests(unittest.TestCase):
    def test_remote_request_includes_auto_and_explicit_language(self):
        for selected in ("", "nl", "en"):
            with self.subTest(selected=selected):
                response = Mock()
                response.json.return_value = {
                    "text": "test", "language": selected or "nl"
                }
                with (
                    patch.object(config, "REMOTE_WHISPER_URL", "http://server"),
                    patch.object(config, "REMOTE_WHISPER_API_KEY", "key"),
                    patch.object(config, "WHISPER_LANGUAGE", selected),
                    patch("transcriber._to_wav_bytes", return_value=b"wav"),
                    patch("transcriber.requests.post", return_value=response) as post,
                ):
                    result = transcriber.Transcriber()._transcribe_remote(
                        np.zeros(1, dtype=np.float32)
                    )

                self.assertEqual(
                    post.call_args.kwargs["data"], {"language": selected}
                )
                self.assertEqual(result, ("test", selected or "nl"))


class CloudVoxtralTests(unittest.TestCase):
    def test_missing_key_raises_before_any_request(self):
        with (
            patch.object(config, "CLOUD_VOXTRAL_API_KEY", ""),
            patch("transcriber.requests.post") as post,
        ):
            with self.assertRaises(RuntimeError):
                transcriber.Transcriber()._transcribe_cloud(np.zeros(1, dtype=np.float32))
        post.assert_not_called()

    def test_unknown_provider_raises_before_any_request(self):
        with (
            patch.object(config, "CLOUD_PROVIDER", "unknownprovider"),
            patch.object(config, "CLOUD_UNKNOWNPROVIDER_API_KEY", "key", create=True),
            patch("transcriber.requests.post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "Unknown cloud transcription provider"):
                transcriber.Transcriber()._transcribe_cloud(np.zeros(1, dtype=np.float32))
        post.assert_not_called()

    def test_voxtral_request_shape_and_response(self):
        response = Mock()
        response.json.return_value = {"text": " test "}
        with (
            patch.object(config, "CLOUD_VOXTRAL_API_KEY", "secret-key"),
            patch.object(config, "CLOUD_PROVIDER", "voxtral"),
            patch.object(config, "CLOUD_VOXTRAL_MODEL", "voxtral-mini-latest"),
            patch("transcriber._to_wav_bytes", return_value=b"wav"),
            patch("transcriber.requests.post", return_value=response) as post,
        ):
            result = transcriber.Transcriber()._transcribe_cloud(
                np.zeros(1, dtype=np.float32)
            )

        self.assertEqual(
            post.call_args.args[0], "https://api.mistral.ai/v1/audio/transcriptions"
        )
        self.assertEqual(
            post.call_args.kwargs["headers"], {"Authorization": "Bearer secret-key"}
        )
        self.assertEqual(
            post.call_args.kwargs["data"], {"model": "voxtral-mini-latest"}
        )
        self.assertEqual(
            post.call_args.kwargs["files"], {"file": ("utterance.wav", b"wav", "audio/wav")}
        )
        self.assertEqual(result, ("test", ""))


class CloudGroqTests(unittest.TestCase):
    def test_request_shape_and_response(self):
        response = Mock()
        response.json.return_value = {"text": " test "}
        with (
            patch.object(config, "CLOUD_GROQ_API_KEY", "secret-key"),
            patch.object(config, "CLOUD_PROVIDER", "groq"),
            patch.object(config, "CLOUD_GROQ_MODEL", "whisper-large-v3-turbo"),
            patch("transcriber._to_wav_bytes", return_value=b"wav"),
            patch("transcriber.requests.post", return_value=response) as post,
        ):
            result = transcriber.Transcriber()._transcribe_cloud(
                np.zeros(1, dtype=np.float32)
            )

        self.assertEqual(
            post.call_args.args[0], "https://api.groq.com/openai/v1/audio/transcriptions"
        )
        self.assertEqual(
            post.call_args.kwargs["headers"], {"Authorization": "Bearer secret-key"}
        )
        self.assertEqual(
            post.call_args.kwargs["data"], {"model": "whisper-large-v3-turbo"}
        )
        self.assertEqual(
            post.call_args.kwargs["files"], {"file": ("utterance.wav", b"wav", "audio/wav")}
        )
        self.assertEqual(result, ("test", ""))


class CloudDeepgramTests(unittest.TestCase):
    def test_request_shape_and_response(self):
        response = Mock()
        response.json.return_value = {
            "results": {"channels": [{"alternatives": [{"transcript": " test "}]}]}
        }
        with (
            patch.object(config, "CLOUD_DEEPGRAM_API_KEY", "secret-key"),
            patch.object(config, "CLOUD_PROVIDER", "deepgram"),
            patch.object(config, "CLOUD_DEEPGRAM_MODEL", "nova-3"),
            patch("transcriber._to_wav_bytes", return_value=b"wav"),
            patch("transcriber.requests.post", return_value=response) as post,
        ):
            result = transcriber.Transcriber()._transcribe_cloud(
                np.zeros(1, dtype=np.float32)
            )

        self.assertEqual(post.call_args.args[0], "https://api.deepgram.com/v1/listen")
        self.assertEqual(
            post.call_args.kwargs["headers"],
            {"Authorization": "Token secret-key", "Content-Type": "audio/wav"},
        )
        self.assertEqual(post.call_args.kwargs["params"], {"model": "nova-3"})
        self.assertEqual(post.call_args.kwargs["data"], b"wav")
        self.assertNotIn("files", post.call_args.kwargs)
        self.assertEqual(result, ("test", ""))


class CloudCartesiaTests(unittest.TestCase):
    def test_request_shape_and_response(self):
        response = Mock()
        response.json.return_value = {"text": " test "}
        with (
            patch.object(config, "CLOUD_CARTESIA_API_KEY", "secret-key"),
            patch.object(config, "CLOUD_PROVIDER", "cartesia"),
            patch.object(config, "CLOUD_CARTESIA_MODEL", "ink-whisper"),
            patch("transcriber._to_wav_bytes", return_value=b"wav"),
            patch("transcriber.requests.post", return_value=response) as post,
        ):
            result = transcriber.Transcriber()._transcribe_cloud(
                np.zeros(1, dtype=np.float32)
            )

        self.assertEqual(post.call_args.args[0], "https://api.cartesia.ai/stt")
        self.assertEqual(
            post.call_args.kwargs["headers"],
            {"Authorization": "Bearer secret-key", "Cartesia-Version": "2026-08-14"},
        )
        self.assertEqual(post.call_args.kwargs["data"], {"model": "ink-whisper"})
        self.assertEqual(
            post.call_args.kwargs["files"], {"file": ("utterance.wav", b"wav", "audio/wav")}
        )
        self.assertEqual(result, ("test", ""))


class CloudApiKeyMigrationTests(unittest.TestCase):
    def test_legacy_shared_key_migrates_to_voxtral_field(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text(json.dumps({"CLOUD_API_KEY": "old-shared-key"}))
            with patch.object(config, "_SETTINGS_FILE", settings_file):
                loaded = config._load()

        self.assertEqual(loaded["CLOUD_VOXTRAL_API_KEY"], "old-shared-key")
        self.assertNotIn("CLOUD_API_KEY", loaded)

    def test_migration_does_not_overwrite_an_already_set_voxtral_key(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text(json.dumps({
                "CLOUD_API_KEY": "old-shared-key",
                "CLOUD_VOXTRAL_API_KEY": "already-set-key",
            }))
            with patch.object(config, "_SETTINGS_FILE", settings_file):
                loaded = config._load()

        self.assertEqual(loaded["CLOUD_VOXTRAL_API_KEY"], "already-set-key")


if __name__ == "__main__":
    unittest.main()
