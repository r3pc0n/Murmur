import unittest
from unittest.mock import Mock, patch

import config
import transcriber


class RuntimeResolutionTests(unittest.TestCase):
    def runtime(self, model="large-v3", device="cuda", compute_type="float16"):
        return patch.multiple(
            config,
            WHISPER_MODEL=model,
            WHISPER_DEVICE=device,
            WHISPER_COMPUTE_TYPE=compute_type,
        )

    def test_cuda_available_preserves_existing_cuda_configuration(self):
        with self.runtime(), patch("transcriber._cuda_available", return_value=True):
            self.assertEqual(
                transcriber._resolve_runtime(),
                ("large-v3", "cuda", "float16"),
            )

    def test_cuda_unavailable_with_defaults_falls_back_to_cpu(self):
        with (
            self.runtime(),
            patch("transcriber._cuda_available", return_value=False),
            patch("transcriber._select_cpu_compute_type", return_value="int8"),
            patch("transcriber.logger.log") as log,
        ):
            self.assertEqual(
                transcriber._resolve_runtime(),
                ("large-v3", "cpu", "int8"),
            )
        self.assertIn("automatic CPU fallback", log.call_args.args[0])

    def test_explicit_cpu_configuration_is_preserved_without_cuda_probe(self):
        with (
            self.runtime(model="medium", device="cpu", compute_type="int8"),
            patch("transcriber._cuda_available") as cuda_available,
        ):
            self.assertEqual(
                transcriber._resolve_runtime(),
                ("medium", "cpu", "int8"),
            )
        cuda_available.assert_not_called()

    def test_non_default_cuda_configuration_is_not_silently_rewritten(self):
        with (
            self.runtime(model="medium"),
            patch("transcriber._cuda_available", return_value=False),
            patch("transcriber._select_cpu_compute_type") as cpu_compute,
            patch("transcriber.logger.log") as log,
        ):
            with self.assertRaisesRegex(RuntimeError, "explicitly configured"):
                transcriber._resolve_runtime()
        cpu_compute.assert_not_called()
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")

    def test_cpu_compute_type_prefers_int8(self):
        fake_ctranslate2 = Mock()
        fake_ctranslate2.get_supported_compute_types.return_value = {
            "float32", "int16", "int8_float32", "int8"
        }
        with patch.dict("sys.modules", {"ctranslate2": fake_ctranslate2}):
            self.assertEqual(transcriber._select_cpu_compute_type(), "int8")

    def test_cpu_compute_type_uses_supported_fallback(self):
        fake_ctranslate2 = Mock()
        fake_ctranslate2.get_supported_compute_types.return_value = {"float32"}
        with patch.dict("sys.modules", {"ctranslate2": fake_ctranslate2}):
            self.assertEqual(transcriber._select_cpu_compute_type(), "float32")

    def test_load_constructs_only_the_resolved_model(self):
        with (
            patch.object(config, "TRANSCRIPTION_MODE", "local"),
            patch(
                "transcriber._resolve_runtime",
                return_value=("large-v3", "cpu", "int8"),
            ),
            patch("transcriber._create_model", return_value=object()) as create_model,
            patch("transcriber.logger.log"),
        ):
            instance = transcriber.Transcriber()
            instance.load()

        create_model.assert_called_once_with("large-v3", "cpu", "int8")

    def test_load_skips_local_model_in_cloud_mode(self):
        with (
            patch.object(config, "TRANSCRIPTION_MODE", "cloud"),
            patch.object(config, "CLOUD_PROVIDER", "voxtral"),
            patch("transcriber._create_model") as create_model,
            patch("transcriber.logger.log"),
        ):
            instance = transcriber.Transcriber()
            instance.load()

        create_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
