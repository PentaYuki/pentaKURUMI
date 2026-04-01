# hormone/episodic_memory.py
"""
EpisodicMemory — Bộ nhớ cảm xúc ngữ cảnh.

Lưu các ký ức dưới dạng: { text, hormone_snapshot, timestamp, lang }
Khi user nói câu liên quan → tìm ký ức gần nhất → replay hormone effect.

Ví dụ:
  Ký ức: "anh nói em giỏi" → { dopamine: +0.12, ... }
  User nói mới: "anh khen em" → similarity cao → replay nhẹ lại effect đó
  → AI "nhớ lại" cảm giác được khen → dopamine tăng nhẹ

Tồn tại qua session: lưu vào JSON file.
Fallback: dùng n-gram nếu không có SBERT embedder.
"""

import os
import json
import time
import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Số ký ức tối đa lưu (giữ lại ký ức có > impact)
_MAX_EPISODES    = 200
# Ngưỡng similarity để coi là "nhớ lại"
_RECALL_THRESHOLD_SBERT = 0.60
_RECALL_THRESHOLD_NGRAM = 0.40
# Hệ số fade-out: ký ức cũ hơn → effect yếu hơn
_FADE_HALF_LIFE_HOURS = 48.0   # 48h → effect còn 50%
# Scale replay: không full strength, chỉ 30% để tránh double-count
_REPLAY_SCALE = 0.30


class EpisodicMemory:
    """
    Lưu và recall ký ức cảm xúc theo ngữ cảnh câu chuyện.
    Thread-safe read; write từ 1 thread.
    """

    def __init__(
        self,
        save_path: Optional[str] = None,
        embedder=None,                        # Embedder từ PentaAI (nếu có)
        max_episodes: int = _MAX_EPISODES,
    ):
        self.save_path    = save_path
        self.embedder     = embedder
        self.max_episodes = max_episodes

        # episodes: list of { text, hormones, timestamp, lang, importance }
        self._episodes: List[Dict] = []
        self._load()

        logger.info(
            "EpisodicMemory ready: %d episodes, backend=%s",
            len(self._episodes),
            getattr(embedder, "backend", "none") if embedder else "none"
        )

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def record(
        self,
        text: str,
        hormone_snapshot: Dict[str, float],
        lang: str = "vi",
        importance: float = 1.0,
    ):
        """
        Lưu một ký ức mới.

        text:             câu user vừa nói
        hormone_snapshot: trạng thái hormone lúc đó (delta hoặc absolute)
        importance:       0–1 (ký ức quan trọng → giữ lâu hơn)
        """
        if not text or not text.strip():
            return

        # Tính importance dựa trên magnitude của hormone changes
        if importance == 1.0 and hormone_snapshot:
            auto_imp = min(1.0, sum(abs(v) for v in hormone_snapshot.values()) / 0.5)
            importance = max(0.1, auto_imp)

        # Không lưu ký ức quá nhỏ (không đáng nhớ)
        if importance < 0.1:
            return

        episode = {
            "text":      text.lower().strip(),
            "hormones":  hormone_snapshot.copy(),
            "timestamp": time.time(),
            "lang":      lang,
            "importance": round(importance, 3),
        }
        self._episodes.append(episode)

        # Giữ kích thước hợp lý — loại bỏ ký ức ít quan trọng, cũ nhất
        if len(self._episodes) > self.max_episodes:
            self._prune()

        # Auto-save mỗi 20 ký ức
        if len(self._episodes) % 20 == 0:
            self.save()

    def recall(
        self,
        text: str,
        lang: str = "vi",
    ) -> Dict[str, float]:
        """
        Tìm ký ức gần nhất và trả về hormone effect (đã fade + scale).

        Trả về {} nếu không tìm thấy ký ức liên quan.
        """
        if not self._episodes or not text:
            return {}

        best_episode, best_score = self._find_closest(text)

        threshold = (
            _RECALL_THRESHOLD_SBERT
            if (self.embedder and getattr(self.embedder, "backend", "") == "sbert")
            else _RECALL_THRESHOLD_NGRAM
        )

        if not best_episode or best_score < threshold:
            return {}

        # Tính fade theo thời gian
        age_hours = (time.time() - best_episode["timestamp"]) / 3600.0
        fade = 0.5 ** (age_hours / _FADE_HALF_LIFE_HOURS)

        # Scale effect
        replayed = {
            h: d * best_score * fade * _REPLAY_SCALE * best_episode.get("importance", 1.0)
            for h, d in best_episode["hormones"].items()
        }

        if replayed:
            logger.debug(
                "EpisodicMemory recall: '%s' ≈ '%s' (score=%.2f, fade=%.2f) → %s",
                text[:40], best_episode["text"][:40], best_score, fade,
                {k: round(v, 3) for k, v in replayed.items()},
            )

        return replayed

    def get_stats(self) -> Dict:
        return {
            "total_episodes":  len(self._episodes),
            "oldest_hours":    self._oldest_hours(),
            "avg_importance":  self._avg_importance(),
        }

    def save(self):
        if not self.save_path:
            return
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(self._episodes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("EpisodicMemory save error: %s", e)

    def attach_embedder(self, embedder):
        """Gắn embedder sau khi khởi tạo."""
        self.embedder = embedder
        logger.info("EpisodicMemory: embedder attached (backend=%s)",
                    getattr(embedder, "backend", "?"))

    # ── PRIVATE ───────────────────────────────────────────────────────────

    def _find_closest(self, text: str) -> Tuple[Optional[Dict], float]:
        """Tìm ký ức gần nhất với text đầu vào."""
        if not self._episodes:
            return None, 0.0

        text_lower = text.lower().strip()

        if self.embedder and getattr(self.embedder, "backend", "") == "sbert":
            return self._find_closest_sbert(text_lower)
        else:
            return self._find_closest_ngram(text_lower)

    def _find_closest_sbert(self, text: str) -> Tuple[Optional[Dict], float]:
        """Dùng sentence-transformers."""
        try:
            text_vec = self.embedder.encode(text)
        except Exception:
            return self._find_closest_ngram(text)

        best_ep    = None
        best_score = 0.0

        for ep in self._episodes:
            try:
                ep_vec = self.embedder.encode(ep["text"])
                score  = self.embedder.similarity(text_vec, ep_vec)
                if score > best_score:
                    best_score = score
                    best_ep    = ep
            except Exception:
                continue

        return best_ep, best_score

    def _find_closest_ngram(self, text: str) -> Tuple[Optional[Dict], float]:
        """Fallback: character n-gram similarity."""
        text_ngrams = self._ngrams(text, n=2)
        if not text_ngrams:
            return None, 0.0

        best_ep    = None
        best_score = 0.0

        for ep in self._episodes:
            ep_ngrams  = self._ngrams(ep["text"], n=2)
            if not ep_ngrams:
                continue
            intersection = len(text_ngrams & ep_ngrams)
            union        = len(text_ngrams | ep_ngrams)
            score        = intersection / union if union > 0 else 0.0
            if score > best_score:
                best_score = score
                best_ep    = ep

        return best_ep, best_score

    def _ngrams(self, text: str, n: int = 2) -> set:
        text = text.replace(" ", "")
        return {text[i:i+n] for i in range(len(text) - n + 1)}

    def _prune(self):
        """Loại bỏ ký ức: ưu tiên giữ lại ký ức quan trọng + gần đây."""
        def score(ep):
            age_hours = (time.time() - ep["timestamp"]) / 3600.0
            recency   = 1.0 / (1.0 + age_hours / 24.0)   # normalize by day
            return ep.get("importance", 0.5) * 0.6 + recency * 0.4

        self._episodes.sort(key=score, reverse=True)
        self._episodes = self._episodes[:self.max_episodes]
        logger.debug("EpisodicMemory pruned to %d episodes", len(self._episodes))

    def _load(self):
        if self.save_path and os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as f:
                    self._episodes = json.load(f)
                logger.info("EpisodicMemory loaded %d episodes", len(self._episodes))
            except Exception as e:
                logger.warning("EpisodicMemory load error: %s", e)
                self._episodes = []

    def _oldest_hours(self) -> float:
        if not self._episodes:
            return 0.0
        oldest_ts = min(ep["timestamp"] for ep in self._episodes)
        return round((time.time() - oldest_ts) / 3600.0, 1)

    def _avg_importance(self) -> float:
        if not self._episodes:
            return 0.0
        return round(sum(ep.get("importance", 0.5) for ep in self._episodes) / len(self._episodes), 3)
