# hormone/semantic_trigger_learner.py
"""
SemanticTriggerLearner — Tự học từ mới có nghĩa tương tự (v2.0).

Cải tiến v2.0:
  - Chạy trên TOÀN BỘ câu (không chỉ từng token lạ)
  - Cross-language mapping: "mệt" ↔ "tired" ↔ "疲れ" chia sẻ effect
  - Phrase-level matching: "kiệt sức" nhận diện như một cụm
  - Cache auto-update realtime
  - Ngưỡng similarity thấp hơn một chút để bắt nhiều hơn

Ý tưởng:
  text_triggers.py biết: "mệt" → cortisol +0.08
  User nói: "em kiệt sức quá" — từ lạ

  SemanticTriggerLearner:
    1. Tokenize → ["em", "kiệt sức", "quá", "kiệt", "sức"]
    2. encode("kiệt sức") → vector
    3. Tìm closest keyword: "mệt" (score 0.81)
    4. Kế thừa: cortisol +0.08 × 0.81 × 0.8 = +0.052
    5. Cache lại → lần sau instantaneous
"""

import os
import json
import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SBERT_THRESHOLD  = 0.52   # Giảm từ 0.55 để bắt nhiều hơn
_NGRAM_THRESHOLD  = 0.32   # Giảm từ 0.35
_CACHE_FILE_DEFAULT = "data/semantic_cache.json"

# Cross-language seed mapping: các cụm từ được coi là tương đương
# Khi tìm closest keyword, ưu tiên tìm trong nhóm ngôn ngữ phù hợp
_CROSS_LANG_SEED: Dict[str, str] = {
    # Tiếng Việt → tiếng Anh (để kế thừa effect)
    "kiệt sức":       "exhausted",
    "chán nản":       "depressed",
    "phấn khởi":      "excited",
    "xúc động":       "emotional",
    "bực bội":        "frustrated",
    "hồi hộp":        "nervous",
    "thất vọng":      "disappointed",
    "ngạc nhiên":     "surprised",
    "cô đơn":         "lonely",
    "tuyệt vọng":     "hopeless",
    "ấm lòng":        "heartwarming",
    "cảm kích":       "grateful",
    "kiên nhẫn":      "patient",
    "nhớ nhà":        "homesick",
    # Tiếng Nhật → tiếng Anh
    "疲れました":      "tired",
    "うれしい":        "happy",
    "かなしい":        "sad",
    "こわい":          "scared",
    "びっくり":        "surprised",
    "かわいい":        "cute",
    "つまらない":      "boring",
    "たのしい":        "fun",
    "さみしい":        "lonely",
    "むかつく":        "annoyed",
}


class SemanticTriggerLearner:
    """
    Học tự động: từ lạ → hormone effect dựa trên embedding similarity (v2.0).
    """

    def __init__(
        self,
        embedder,
        text_triggers,
        synonym_manager=None,
        cache_path: str = _CACHE_FILE_DEFAULT,
        sbert_threshold: float = _SBERT_THRESHOLD,
        ngram_threshold: float = _NGRAM_THRESHOLD,
    ):
        self.embedder         = embedder
        self.text_triggers    = text_triggers
        self.synonym_manager  = synonym_manager
        self.sbert_threshold  = sbert_threshold
        self.ngram_threshold  = ngram_threshold
        self.cache_path       = cache_path

        # keyword → vector (lazy build)
        self._keyword_vectors: Dict[str, List[float]] = {}
        self._keywords_built  = False

        # Cache: word / phrase → { hormone: delta }
        self._learned: Dict[str, Dict[str, float]] = {}
        self._load_cache()

        # Pre-load cross-lang seeds vào cache (không cần encode)
        self._bootstrap_cross_lang()

        self._discoveries = 0

        logger.info(
            "SemanticTriggerLearner v2.0 ready (backend=%s, cache=%d entries)",
            self.embedder.backend, len(self._learned)
        )

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def enrich_hormone_changes(
        self,
        text: str,
        base_changes: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Mở rộng hormone changes bằng cách tìm từ/cụm từ gần nghĩa.

        v2.0: chạy trên TOÀN BỘ câu + phrase-level tokens.
        """
        if not text:
            return base_changes

        enriched = dict(base_changes)

        # Tạo danh sách tokens: đơn + bigram + trigram + cả câu
        tokens = self._tokenize_multilevel(text)

        for token in tokens:
            if len(token.strip()) < 2:
                continue

            # Kiểm tra cache trước
            if token in self._learned:
                for hormone, delta in self._learned[token].items():
                    enriched[hormone] = enriched.get(hormone, 0) + delta
                continue

            # Tìm keyword gần nghĩa nhất
            best_keyword, best_score = self._find_closest_keyword(token)

            if best_keyword and best_score > 0:
                keyword_effects = self.text_triggers.from_text(best_keyword)
                if keyword_effects:
                    # Không scale lại nếu base_changes đã có effect tương tự
                    already_covered = self._is_effect_covered(keyword_effects, base_changes)
                    scale_factor = 0.4 if already_covered else 0.8

                    scaled = {
                        h: d * best_score * scale_factor
                        for h, d in keyword_effects.items()
                    }

                    for hormone, delta in scaled.items():
                        enriched[hormone] = enriched.get(hormone, 0) + delta

                    # Lưu cache
                    self._learned[token] = scaled
                    self._discoveries += 1
                    self._save_cache_if_needed()

                    # Notify SynonymManager
                    if self.synonym_manager and best_score > 0.60:
                        try:
                            self.synonym_manager.add_synonym_pair(token, best_keyword)
                        except Exception:
                            pass

                    logger.info(
                        "🔍 Learned: %r ≈ %r (score=%.2f) → %s",
                        token, best_keyword, best_score,
                        {k: round(v, 3) for k, v in scaled.items()}
                    )

        return enriched

    def get_learned_count(self) -> int:
        return len(self._learned)

    def get_discoveries(self) -> int:
        return self._discoveries

    def get_learned_words(self) -> List[str]:
        return list(self._learned.keys())

    def reset_cache(self):
        self._learned = {}
        self._save_cache()
        logger.info("SemanticTriggerLearner cache reset.")

    # ── PRIVATE: SIMILARITY ───────────────────────────────────────────────

    def _find_closest_keyword(
        self, word: str
    ) -> Tuple[Optional[str], float]:
        if not self._keywords_built:
            self._build_keyword_vectors()

        if self.embedder.backend == "sbert":
            return self._find_closest_sbert(word)
        else:
            return self._find_closest_ngram(word)

    def _find_closest_sbert(self, word: str) -> Tuple[Optional[str], float]:
        try:
            word_vec = self.embedder.encode(word)
        except Exception:
            return None, 0.0

        best_kw    = None
        best_score = self.sbert_threshold

        for keyword, kw_vec in self._keyword_vectors.items():
            if not kw_vec:
                continue
            score = self.embedder.similarity(word_vec, kw_vec)
            if score > best_score:
                best_score = score
                best_kw    = keyword

        return best_kw, best_score

    def _find_closest_ngram(self, word: str) -> Tuple[Optional[str], float]:
        best_kw    = None
        best_score = self.ngram_threshold

        word_ngrams = self._char_ngrams(word, n=2)

        for keyword in self._keyword_vectors.keys():
            # Prefix match
            if word.startswith(keyword) or keyword.startswith(word):
                score = len(min(word, keyword, key=len)) / len(max(word, keyword, key=len))
                score *= 0.9
                if score > best_score:
                    best_score = score
                    best_kw    = keyword
                continue

            # N-gram similarity
            kw_ngrams = self._char_ngrams(keyword, n=2)
            if not word_ngrams or not kw_ngrams:
                continue

            intersection = len(word_ngrams & kw_ngrams)
            union        = len(word_ngrams | kw_ngrams)
            if union == 0:
                continue

            score = intersection / union
            if score > best_score:
                best_score = score
                best_kw    = keyword

        return best_kw, best_score

    # ── PRIVATE: BUILD VECTORS ────────────────────────────────────────────

    def _build_keyword_vectors(self):
        """Build embedding vectors cho tất cả keywords (v2.0: thêm phrases)."""
        all_keywords: List[str] = []

        for pattern, _ in self.text_triggers._compiled:
            raw   = pattern.pattern
            words = re.findall(r'[a-zA-ZÀ-ỹ\u3040-\u9FFF]{2,}', raw)
            all_keywords.extend(words)

        # Seed từ điển mở rộng (bao gồm phrases)
        extra_keywords = [
            # Tiếng Việt
            "mệt", "buồn", "vui", "tức", "sợ", "yêu", "thích",
            "giận", "khóc", "cười", "lo", "hạnh phúc", "đau",
            "chán", "bực", "nhớ", "thương", "cảm ơn", "xin lỗi",
            "ngốc", "giỏi", "tệ", "hay",
            "kiệt sức", "chán nản", "phấn khởi", "xúc động", "bực bội",
            "hồi hộp", "thất vọng", "ngạc nhiên", "cô đơn", "tuyệt vọng",
            "ấm lòng", "cảm kích", "nhớ nhà", "mệt mỏi",
            # English
            "tired", "sad", "happy", "angry", "scared", "love",
            "hate", "cry", "laugh", "worried", "pain", "thank",
            "sorry", "stupid", "smart", "bad", "good",
            "exhausted", "depressed", "excited", "anxious", "frustrated",
            "nostalgic", "grateful", "lonely", "hopeless", "surprised",
            # Japanese
            "疲れ", "悲しい", "嬉しい", "怒り", "怖い", "愛",
            "泣く", "笑う", "心配", "痛い", "ありがとう", "ごめん",
            "バカ", "すごい", "ダメ", "楽しい", "さみしい", "うれしい",
        ]
        all_keywords.extend(extra_keywords)

        unique = list({k.lower() for k in all_keywords if len(k) >= 2})

        if self.embedder.backend == "sbert" and unique:
            try:
                vectors = self.embedder.encode_batch(unique)
                self._keyword_vectors = dict(zip(unique, vectors))
                logger.info(
                    "Built %d keyword vectors (sbert v2.0)", len(self._keyword_vectors)
                )
            except Exception as e:
                logger.warning("Failed to build sbert vectors: %s", e)
                self._keyword_vectors = {k: [] for k in unique}
        else:
            self._keyword_vectors = {k: [] for k in unique}
            logger.info(
                "Built %d keyword list (ngram fallback v2.0)", len(self._keyword_vectors)
            )

        self._keywords_built = True

    # ── PRIVATE: HELPERS ──────────────────────────────────────────────────

    def _tokenize_multilevel(self, text: str) -> List[str]:
        """
        Tách text thành tokens ở nhiều cấp độ:
        - Từ đơn
        - Bigram (2 từ liên tiếp)
        - Trigram (3 từ liên tiếp)
        - CJK chars
        """
        tokens = set()
        text_lower = text.lower()

        # Latin + Vietnamese
        latin_parts = re.findall(r'[a-zA-ZÀ-ỹ]{2,}(?:\s+[a-zA-ZÀ-ỹ]{2,})*', text_lower)
        for part in latin_parts:
            words = part.split()
            # Unigrams
            tokens.update(words)
            # Bigrams
            for i in range(len(words) - 1):
                tokens.add(words[i] + " " + words[i+1])
            # Trigrams
            for i in range(len(words) - 2):
                tokens.add(words[i] + " " + words[i+1] + " " + words[i+2])

        # CJK
        cjk_chars = re.findall(r'[\u3040-\u9FFF\uAC00-\uD7AF]+', text)
        tokens.update(cjk_chars)

        return list(tokens)

    def _is_effect_covered(
        self,
        keyword_effects: Dict[str, float],
        base_changes: Dict[str, float],
    ) -> bool:
        """Kiểm tra xem effect đã được cover trong base_changes chưa."""
        if not base_changes:
            return False
        overlap = set(keyword_effects.keys()) & set(base_changes.keys())
        return len(overlap) >= len(keyword_effects) * 0.5

    def _char_ngrams(self, text: str, n: int = 2) -> set:
        text = text.lower().replace(" ", "")
        return {text[i:i+n] for i in range(len(text) - n + 1)}

    def _bootstrap_cross_lang(self):
        """
        Pre-load cross-language mappings vào cache.
        Lần sau không cần encode lại.
        """
        loaded = 0
        for word, equiv in _CROSS_LANG_SEED.items():
            if word not in self._learned:
                effects = self.text_triggers.from_text(equiv)
                if effects:
                    # Scale xuống 0.7 (chắc chắn không chính xác 100%)
                    self._learned[word] = {
                        h: d * 0.7 for h, d in effects.items()
                    }
                    loaded += 1
        if loaded > 0:
            logger.info("Cross-lang bootstrap: %d mappings pre-loaded", loaded)
            self._save_cache()

    # ── CACHE ─────────────────────────────────────────────────────────────

    def _load_cache(self):
        if self.cache_path and os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._learned = json.load(f)
            except Exception:
                self._learned = {}

    def _save_cache(self):
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._learned, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("SemanticLearner cache save error: %s", e)

    def _save_cache_if_needed(self):
        """Lưu cache mỗi 5 discoveries (giảm từ 10 để realtime hơn)."""
        if self._discoveries % 5 == 0:
            self._save_cache()