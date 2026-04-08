import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENTA_AI_MAC = os.path.join(ROOT, "PentaAI_Mac")
if PENTA_AI_MAC not in sys.path:
    sys.path.insert(0, PENTA_AI_MAC)

from API_local.pentami_chat import check_toggle


class TestToggleIntents(unittest.TestCase):
    def test_toggle_pentami_basic(self):
        self.assertEqual(check_toggle("bật pentami"), "on")
        self.assertEqual(check_toggle("tắt penta mi"), "off")

    def test_toggle_pentamit_thinking(self):
        self.assertEqual(check_toggle("bật pentami t"), "on_thinking")
        self.assertEqual(check_toggle("enable pentamit"), "on_thinking")
        self.assertEqual(check_toggle("tắt pentami t"), "off_thinking")

    def test_toggle_clear(self):
        self.assertEqual(check_toggle("xóa context"), "clear")


if __name__ == "__main__":
    unittest.main(verbosity=2)
