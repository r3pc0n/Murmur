import sys
import types
import unittest
from unittest.mock import Mock, call, patch


# Importing pystray connects to the desktop display on Linux.  _process does not
# use it, so provide only the attributes main.py needs while it is imported.
pystray_stub = types.ModuleType("pystray")
pystray_stub.Icon = type("Icon", (), {})
pystray_stub.Menu = type("Menu", (), {"SEPARATOR": object()})
pystray_stub.MenuItem = type("MenuItem", (), {})
sys.modules["pystray"] = pystray_stub

import main


class ProcessingPipelineTests(unittest.TestCase):
    def test_cleaned_text_is_logged_and_passed_to_insertion_for_all_modes(self):
        for mode in ("local", "remote", "cloud"):
            with self.subTest(mode=mode):
                transcriber = Mock()
                transcriber.transcribe.return_value = ("RAW_TEXT", "nl")
                cleaner = Mock()
                cleaner.clean.return_value = "CLEANED_TEXT_12345"

                with (
                    patch.object(main, "transcriber", transcriber),
                    patch.object(main, "cleaner", cleaner),
                    patch.object(main.config, "TRANSCRIPTION_MODE", mode),
                    patch.object(main.config, "AI_CLEANUP_ENABLED", True),
                    patch.object(
                        main, "_apply_corrections", return_value="CORRECTED_TEXT"
                    ) as apply_corrections,
                    patch.object(main.logger, "log") as log,
                    patch.object(main, "paste_text") as paste_text,
                    patch.object(main, "_beep"),
                    patch.object(main, "_update_icon"),
                ):
                    main._process(object())

                transcriber.transcribe.assert_called_once()
                apply_corrections.assert_called_once_with("RAW_TEXT")
                cleaner.clean.assert_called_once_with("CORRECTED_TEXT", "nl")
                self.assertIn(call("Transcribed (nl): RAW_TEXT"), log.call_args_list)
                self.assertIn(
                    call("Cleaned: CLEANED_TEXT_12345", level="RESULT"),
                    log.call_args_list,
                )
                paste_text.assert_called_once_with("CLEANED_TEXT_12345")


if __name__ == "__main__":
    unittest.main()
