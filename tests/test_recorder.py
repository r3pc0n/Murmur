import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

import recorder


class StartStopMutualExclusionTests(unittest.TestCase):
    """Regression test for a real crash: a release arriving mid-start used
    to be able to tear down self._stream while PortAudio's native callback
    thread for it was still being set up -- a native use-after-free
    (SIGSEGV), not a catchable Python exception. start()/stop() each run on
    their own thread (see hotkeys.py's per-event threading), so this is a
    real, reachable race under normal fast press/release/press dictation,
    not just a theoretical one."""

    def test_stop_waits_for_start_to_finish_before_touching_the_stream(self):
        events = []
        stream_started = threading.Event()
        let_start_finish = threading.Event()

        def fake_input_stream(**kwargs):
            stream = Mock()

            def fake_stream_start():
                events.append("start-critical-section-begin")
                stream_started.set()
                # Held open until the test explicitly releases it, so a
                # concurrent stop() has no choice but to wait -- this proves
                # mutual exclusion rather than a lucky race outcome.
                let_start_finish.wait(timeout=2)
                events.append("start-critical-section-end")

            stream.start = fake_stream_start
            return stream

        rec = recorder.Recorder()
        with (
            patch("recorder.resolve_device", return_value=None),
            patch("recorder.sd.InputStream", side_effect=fake_input_stream),
        ):
            start_thread = threading.Thread(target=rec.start)
            start_thread.start()
            self.assertTrue(stream_started.wait(timeout=2), "start() never reached the stream")

            def do_stop():
                events.append("stop-called")
                rec.stop()
                events.append("stop-returned")

            stop_thread = threading.Thread(target=do_stop)
            stop_thread.start()
            # Give stop() every opportunity to (incorrectly) race past the
            # still-running start() before we let start() finish.
            stop_thread.join(timeout=0.2)
            let_start_finish.set()

            start_thread.join(timeout=2)
            stop_thread.join(timeout=2)

        # The meaningful assertion isn't when stop() was *called* (that can
        # happen any time) -- it's that stop()'s body, which tears down
        # self._stream, cannot complete until start()'s critical section has.
        self.assertLess(
            events.index("start-critical-section-end"),
            events.index("stop-returned"),
        )

    def test_normal_start_then_stop_still_returns_recorded_audio(self):
        rec = recorder.Recorder()
        captured_callback = []

        def fake_input_stream(**kwargs):
            captured_callback.append(kwargs["callback"])
            return Mock()

        with (
            patch("recorder.resolve_device", return_value=None),
            patch("recorder.sd.InputStream", side_effect=fake_input_stream),
        ):
            rec.start()
            callback = captured_callback[0]
            callback(np.ones((10, 1), dtype=np.float32), 10, None, None)
            result = rec.stop()

        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (10,))


if __name__ == "__main__":
    unittest.main()
