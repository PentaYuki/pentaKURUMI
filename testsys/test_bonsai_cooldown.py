import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENTA_AI_MAC = os.path.join(ROOT, "PentaAI_Mac")
if PENTA_AI_MAC not in sys.path:
    sys.path.insert(0, PENTA_AI_MAC)

from API_local.bonsai_client import BonsaiClient


class TestBonsaiCooldown(unittest.TestCase):
    def setUp(self):
        self.client = BonsaiClient(auto_start=False)
        self.client.wake_retry_cooldown = 10.0

    def tearDown(self):
        self.client.shutdown()

    def test_can_wake_now_respects_cooldown(self):
        self.client._last_wake_fail_ts = time.monotonic()
        with patch.object(self.client, "_check_port", return_value=False):
            self.assertFalse(self.client.can_wake_now())

    def test_can_wake_now_true_after_cooldown(self):
        self.client._last_wake_fail_ts = time.monotonic() - 20.0
        with patch.object(self.client, "_check_port", return_value=False):
            self.assertTrue(self.client.can_wake_now())

    def test_ensure_awake_skips_start_during_cooldown(self):
        self.client._last_wake_fail_ts = time.monotonic()
        with patch.object(self.client, "_check_port_ready", return_value=False), \
             patch.object(self.client, "_start_server", return_value=True) as start_mock:
            ok = self.client._ensure_awake()

        self.assertFalse(ok)
        start_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
