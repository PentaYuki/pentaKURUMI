import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENTA_AI_MAC = os.path.join(ROOT, "PentaAI_Mac")
if PENTA_AI_MAC not in sys.path:
    sys.path.insert(0, PENTA_AI_MAC)

from API_local.penta_memory import PentaMemory


class _FakeFaissIndex:
    def __init__(self):
        self.ntotal = 2

    def search(self, vec, k):
        # distance nhỏ hơn threshold thì giữ, lớn hơn thì bỏ
        return np.array([[0.6, 2.4]], dtype=np.float32), np.array([[0, 1]], dtype=np.int64)


class TestPentaMemoryHybrid(unittest.TestCase):
    def setUp(self):
        with patch.object(PentaMemory, "_check_ollama", return_value=False), \
             patch.object(PentaMemory, "_init_cute_phrases", return_value=None):
            self.pm = PentaMemory()

    def test_save_vault_persists_json(self):
        with tempfile.TemporaryDirectory() as td:
            self.pm.vault_file = os.path.join(td, "penta_vault.json")
            self.pm.vault = {0: "memory a", 1: "memory b"}
            self.pm._save_vault()

            self.assertTrue(os.path.exists(self.pm.vault_file))
            with open(self.pm.vault_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_retrieve_long_term_memories_filters_distance(self):
        self.pm.faiss_index = _FakeFaissIndex()
        self.pm.vault = {0: "near memory", 1: "far memory"}
        self.pm.memory_distance_threshold = 1.2

        with patch.object(self.pm, "get_embedding", return_value=np.zeros((1, 768), dtype=np.float32)):
            recalls = self.pm._retrieve_long_term_memories("test query", top_k=2)

        self.assertEqual(recalls, ["near memory"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
