import threading

import numpy as np
import sounddevice as sd

import config


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) pairs for all available input devices, deduplicated."""
    seen = set()
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            name = dev["name"]
            if name not in seen:
                seen.add(name)
                devices.append((i, name))
    return devices


def get_device_names() -> list[str]:
    """Return display names for the settings dropdown (includes a default option)."""
    return ["Default"] + [name for _, name in list_input_devices()]


def resolve_device(name: str | None) -> int | None:
    """Resolve a device name to its index, or None for system default."""
    if not name or name == "Default":
        return None
    for idx, dev_name in list_input_devices():
        if dev_name == name:
            return idx
    return None


def device_available(name: str | None) -> bool:
    """Return True if the configured device exists (or Default is used)."""
    if not name or name == "Default":
        return len(list_input_devices()) > 0
    return any(n == name for _, n in list_input_devices())


class Recorder:
    def __init__(self):
        self._frames = []
        self._recording = False
        self._stream = None
        self._lock = threading.Lock()
        # Guards the whole start()/stop() lifecycle -- a press and a release
        # each run on their own thread (see hotkeys.py), so without this a
        # release arriving mid-start could tear down self._stream while
        # PortAudio's native callback thread for it is still starting up,
        # a real use-after-free (segfault, not a catchable exception).
        self._state_lock = threading.Lock()

    def start(self):
        with self._state_lock:
            self._frames = []
            self._recording = True
            device = resolve_device(config.AUDIO_DEVICE)
            self._stream = sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1024,
                device=device,
                callback=self._callback,
            )
            self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def stop(self) -> np.ndarray | None:
        with self._state_lock:
            self._recording = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            with self._lock:
                if self._frames:
                    return np.concatenate(self._frames, axis=0).flatten()
                return None
