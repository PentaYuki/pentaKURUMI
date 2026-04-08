import os
import sys
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENTA_AI_MAC = os.path.join(ROOT, "PentaAI_Mac")
if PENTA_AI_MAC not in sys.path:
    sys.path.insert(0, PENTA_AI_MAC)

from API_local.pentami_chat import PentaMiChat


class TestPentamiTRouting(unittest.TestCase):
    def setUp(self):
        self.pm = PentaMiChat()
        self.pm.clear_context()

    def test_default_thinking_mode_off(self):
        self.pm.set_bonsai_thinking_mode(False)
        self.assertFalse(self.pm.is_bonsai_thinking_mode())

    def test_stream_uses_ollama_when_thinking_off(self):
        self.pm.set_bonsai_thinking_mode(False)

        with patch.object(self.pm, "_ollama_stream", return_value=iter(["Xin ", "chao"])), \
             patch.object(self.pm._bonsai, "chat_stream", return_value=iter([])) as bonsai_stream:
            out = "".join(list(self.pm.chat_stream("phân tích giúp anh")))

        self.assertIn("Xin", out)
        self.assertEqual(self.pm.get_last_route(), "ollama_fast")
        bonsai_stream.assert_not_called()

    def test_stream_can_use_bonsai_when_thinking_on(self):
        self.pm.set_bonsai_thinking_mode(True)

        fake_tokens = iter([("Token1 ", 0.2), ("Token2", 0.0)])
        with patch.object(self.pm._bonsai, "chat_stream", return_value=fake_tokens) as bonsai_stream:
            out = "".join(list(self.pm.chat_stream("phân tích chi tiết kiến trúc hệ thống này giúp anh")))

        self.assertIn("Token1", out)
        self.assertIn("Token2", out)
        self.assertEqual(self.pm.get_last_route(), "bonsai")
        bonsai_stream.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
