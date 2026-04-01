# engine/embedder.py
"""
Embedder — Load sentence-transformer theo config, cache vector.

Đọc EMBEDDING_MODE từ config.py để chọn model:
  "auto"         → tự chọn tốt nhất có thể
  "tfidf"        → luôn dùng TF-IDF (nhanh, không cần cài thêm)
  "small"        → 17MB, EN tốt
  "multilingual" → 118MB, VI/EN/JP tốt  ← khuyến nghị
  "best"         → 280MB, chất lượng cao nhất
"""

import os
import math
import re
from typing import List, Dict, Optional

from config import (
    EMBEDDING_MODE, EMBEDDING_MODELS, MODEL_CACHE_DIR
)


def _try_load_model(model_name: str):
    """Thử load một sentence-transformer model. Trả về model hoặc None."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        model = SentenceTransformer(model_name, cache_folder=MODEL_CACHE_DIR)
        return model
    except ImportError:
        return None
    except Exception:
        return None


class Embedder:
    """
    Unified embedding interface.
    Backend được chọn theo EMBEDDING_MODE trong config.py.
    """

    def __init__(self):
        self._model   = None
        self._backend = "tfidf"
        self._model_name = ""

        # Chọn backend theo config
        mode = EMBEDDING_MODE.lower().strip()

        if mode == "tfidf":
            # Luôn dùng TF-IDF
            print("[Embedder] Backend: TF-IDF (theo config)")

        elif mode == "auto":
            # Thử multilingual trước, fallback TF-IDF
            model_name = EMBEDDING_MODELS["multilingual"]
            model = _try_load_model(model_name)
            if model:
                self._model      = model
                self._backend    = "sbert"
                self._model_name = model_name
                print(f"[Embedder] Backend: {model_name} (auto-selected)")
            else:
                print("[Embedder] Backend: TF-IDF fallback")
                print("           → Cài sentence-transformers để dùng embedding thật:")
                print("             pip install sentence-transformers")
                print("           → Đổi EMBEDDING_MODE='multilingual' trong config.py")

        elif mode in EMBEDDING_MODELS:
            model_name = EMBEDDING_MODELS[mode]
            model = _try_load_model(model_name)
            if model:
                self._model      = model
                self._backend    = "sbert"
                self._model_name = model_name
                print(f"[Embedder] Backend: {model_name}")
            else:
                print(f"[Embedder] Không load được {model_name}, fallback TF-IDF")
                print("           → Kiểm tra: pip install sentence-transformers")

        else:
            print(f"[Embedder] Mode không hợp lệ: {mode!r}, dùng TF-IDF")

        # TF-IDF state
        self._vocab:   Dict[str, int]   = {}
        self._idf:     Dict[str, float] = {}
        self._corpus:  List[str]        = []
        self._vectors: List[List[float]] = []

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def model_name(self) -> str:
        return self._model_name

    # ── PUBLIC API ────────────────────────────────────────────────

    def encode(self, text: str) -> List[float]:
        """Chuyển text → vector (unit-normalized)."""
        if self._backend == "sbert":
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        return self._tfidf_encode(text)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode nhiều text cùng lúc."""
        if self._backend == "sbert":
            vecs = self._model.encode(
                texts, normalize_embeddings=True,
                batch_size=32, show_progress_bar=False
            )
            return [v.tolist() for v in vecs]
        return [self._tfidf_encode(t) for t in texts]

    def similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Cosine similarity (đã normalize → dot product)."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        return sum(a * b for a, b in zip(vec_a, vec_b))

    def update_tfidf_corpus(self, texts: List[str]):
        """Rebuild TF-IDF index (chỉ dùng khi backend = tfidf)."""
        if self._backend == "sbert":
            return

        self._corpus = [t.lower() for t in texts]
        self._vocab  = {}
        self._idf    = {}

        for text in self._corpus:
            for token in self._tokenize(text):
                if token not in self._vocab:
                    self._vocab[token] = len(self._vocab)

        N = max(len(self._corpus), 1)
        df: Dict[str, int] = {}
        for text in self._corpus:
            for t in set(self._tokenize(text)):
                df[t] = df.get(t, 0) + 1

        for token, count in df.items():
            self._idf[token] = math.log((N + 1) / (count + 1)) + 1.0

        self._vectors = [self._tfidf_encode(t) for t in self._corpus]

    # ── TFIDF ─────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        return [t for t in re.split(r'\s+|(?<=[^\w])|(?=[^\w])', text.lower())
                if t.strip()]

    def _tfidf_encode(self, text: str) -> List[float]:
        if not self._vocab:
            return self._char_ngram_encode(text)

        tokens = self._tokenize(text.lower())
        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        total = max(len(tokens), 1)

        vec = [0.0] * len(self._vocab)
        for token, count in tf.items():
            if token in self._vocab:
                idx      = self._vocab[token]
                idf      = self._idf.get(token, 1.0)
                vec[idx] = (count / total) * idf

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _char_ngram_encode(self, text: str, n: int = 3) -> List[float]:
        text   = text.lower().strip()
        ngrams: Dict[str, int] = {}
        for i in range(len(text) - n + 1):
            gram = text[i:i+n]
            ngrams[gram] = ngrams.get(gram, 0) + 1

        vec = [0.0] * 256
        for gram, count in ngrams.items():
            idx = hash(gram) % 256
            vec[idx] += count

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec