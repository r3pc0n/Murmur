import io
import wave

import numpy as np
import requests

import config
import logger


_CPU_COMPUTE_PREFERENCE = ("int8", "int8_float32", "int16", "float32")


def _language_argument() -> str | None:
    """Return None to let faster-whisper perform language detection."""
    language = config.WHISPER_LANGUAGE.strip().lower()
    return language or None


def _cuda_available(compute_type: str) -> bool:
    """Ask CTranslate2 whether CUDA supports the requested compute type."""
    try:
        import ctranslate2
        return (
            ctranslate2.get_cuda_device_count() > 0
            and compute_type in ctranslate2.get_supported_compute_types("cuda")
        )
    except Exception:
        return False


def _select_cpu_compute_type() -> str:
    import ctranslate2

    supported = ctranslate2.get_supported_compute_types("cpu")
    for compute_type in _CPU_COMPUTE_PREFERENCE:
        if compute_type in supported:
            return compute_type
    raise RuntimeError(
        "CTranslate2 reports no supported CPU compute type for Murmur."
    )


def _create_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _resolve_runtime() -> tuple[str, str, str]:
    model_name = config.WHISPER_MODEL
    device = config.WHISPER_DEVICE
    compute_type = config.WHISPER_COMPUTE_TYPE

    if device != "cuda" or _cuda_available(compute_type):
        return model_name, device, compute_type

    if not config.uses_default_whisper_runtime():
        message = (
            "CUDA is unavailable, but Murmur is explicitly configured for "
            f"{model_name} on CUDA ({compute_type}). Choose CPU in Settings "
            "or restore the default runtime to allow automatic fallback."
        )
        logger.log(message, level="ERROR")
        raise RuntimeError(message)

    cpu_compute_type = _select_cpu_compute_type()
    logger.log(
        "CUDA is unavailable; using automatic CPU fallback "
        f"({cpu_compute_type}) with the configured model {model_name}.",
        level="INFO",
    )
    return model_name, "cpu", cpu_compute_type


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(config.SAMPLE_RATE)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class Transcriber:
    def __init__(self):
        self.model = None

    def load(self):
        if config.TRANSCRIPTION_MODE == "remote":
            logger.log(f"Transcription mode: remote ({config.REMOTE_WHISPER_URL})")
            return
        if config.TRANSCRIPTION_MODE == "cloud":
            logger.log(f"Transcription mode: cloud ({config.CLOUD_PROVIDER})")
            return
        model_name, device, compute_type = _resolve_runtime()
        logger.log(f"Loading Whisper {model_name} on {device} ({compute_type})...")
        self.model = _create_model(model_name, device, compute_type)
        logger.log("Whisper model ready.", level="OK")

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        if config.TRANSCRIPTION_MODE == "remote":
            return self._transcribe_remote(audio)
        if config.TRANSCRIPTION_MODE == "cloud":
            return self._transcribe_cloud(audio)
        return self._transcribe_local(audio)

    def _transcribe_local(self, audio: np.ndarray) -> tuple[str, str]:
        initial_prompt = None
        if config.WORD_CORRECTIONS:
            # Feed correct spellings as a hint so Whisper biases toward them
            initial_prompt = ", ".join(config.WORD_CORRECTIONS.values())

        segments, info = self.model.transcribe(
            audio,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=initial_prompt,
            language=_language_argument(),
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language

    def _transcribe_remote(self, audio: np.ndarray) -> tuple[str, str]:
        url = config.REMOTE_WHISPER_URL.rstrip("/") + "/transcribe"
        headers = {"X-API-Key": config.REMOTE_WHISPER_API_KEY}
        wav = _to_wav_bytes(audio)
        resp = requests.post(
            url,
            headers=headers,
            files={"audio": ("audio.wav", wav, "audio/wav")},
            data={"language": config.WHISPER_LANGUAGE},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["text"], data["language"]

    def _transcribe_cloud(self, audio: np.ndarray) -> tuple[str, str]:
        if not config.CLOUD_API_KEY:
            raise RuntimeError(
                "Cloud transcription is enabled but no API key is configured."
            )
        provider = config.CLOUD_PROVIDER
        if provider == "voxtral":
            return self._transcribe_voxtral(audio)
        raise RuntimeError(f"Unknown cloud transcription provider: {provider!r}")

    def _transcribe_voxtral(self, audio: np.ndarray) -> tuple[str, str]:
        wav = _to_wav_bytes(audio)
        resp = requests.post(
            "https://api.mistral.ai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.CLOUD_API_KEY}"},
            data={"model": config.CLOUD_VOXTRAL_MODEL},
            files={"file": ("utterance.wav", wav, "audio/wav")},
            timeout=30,
        )
        resp.raise_for_status()
        # Voxtral's response has no language field, unlike local/remote Whisper.
        return str(resp.json().get("text", "")).strip(), ""
