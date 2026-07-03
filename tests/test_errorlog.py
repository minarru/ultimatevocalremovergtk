import unittest

from data.error_handling import error_dialouge, error_text
from uvr_gtk.errorlog import (
    _friendly_error_message,
    get_error_log,
    log_error,
    set_error_log,
)


class ErrorLogTests(unittest.TestCase):
    def setUp(self) -> None:
        set_error_log("")

    def test_log_error_stores_formatted_text(self) -> None:
        exc = KeyError("'All Stems'")
        formatted = log_error("MDX-Net", exc)
        self.assertIn("MDX-Net", formatted)
        self.assertIn("All Stems", formatted)
        self.assertEqual(get_error_log(), formatted)

    def test_error_dialouge_includes_exception_name(self) -> None:
        body = error_dialouge(ValueError("bad segment size"))
        self.assertIn("ValueError", body)

    def test_error_text_includes_traceback_block(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            formatted = error_text("VR", exc)
        self.assertIn("Traceback Error", formatted)
        self.assertIn("RuntimeError", formatted)

    def test_friendly_error_message_omits_generic_contact_only_text(self) -> None:
        self.assertIsNone(_friendly_error_message(RuntimeError("boom")))

    def test_friendly_error_message_keeps_mapped_guidance(self) -> None:
        message = _friendly_error_message(MemoryError("CUDA out of memory"))
        self.assertIsNotNone(message)
        self.assertIn("GPU memory", message or "")


if __name__ == "__main__":
    unittest.main()
