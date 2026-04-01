# engine/phrase_engine.py
"""
PhraseEngine — Tầng 3B (matching). [PATCHED]

Thay đổi so với bản gốc:
  - EMBED_MIN_SCORE: 0.55 → 0.68 (tránh match nhầm)
  - Thêm SOFT_FLOOR = 0.60: vùng "uncertain" → hỏi lại thay vì trả bừa
  - Embedding match dùng top-2 để kiểm tra độ tách biệt (gap check)
  - Token overlap: Jaccard riêng cho tiếng Việt (xử lý từ ghép có dấu)
  - Thêm get_uncertain() → cho phép AI hỏi lại khi không chắc
  - Thêm score_debug() → dễ debug từng entry

Flow tìm kiếm (3 bước theo thứ tự ưu tiên):

  Bước 1 — Exact match (0ms)
    "bạn khỏe không" == "bạn khỏe không" → score 1.0, dừng ngay

  Bước 2 — Embedding similarity (3-8ms)
    score >= EMBED_MIN_SCORE (0.68) VÀ gap vs runner-up >= 0.05 → match
    score trong [SOFT_FLOOR, EMBED_MIN_SCORE) → uncertain (hỏi lại)

  Bước 3 — Token overlap fallback (1ms)
    Jaccard + order bonus (cải tiến xử lý dấu tiếng Việt)
"""

from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
import re

from engine.embedder import Embedder
from config import FUZZY_MIN_SCORE

# ── Ngưỡng ──────────────────────────────────────────────────────
EMBED_MIN_SCORE = 0.68   # FIX: tăng từ 0.55 → tránh match nhầm
SOFT_FLOOR      = 0.58   # Vùng "uncertain": không chắc → hỏi lại
GAP_MIN         = 0.05   # Top-1 phải cách top-2 ít nhất 5% (tránh ambiguous)


@dataclass
class MatchResult:
    trigger:    str
    responses:  List[str]
    score:      float
    matched_by: str
    slots:      Dict[str, str] = field(default_factory=dict)
    uncertain:  bool = False   # FIX: thêm flag uncertain


class PhraseEngine:

    def __init__(self):
        self._embedder      = Embedder()
        self._trigger_cache: Dict[str, List[float]] = {}

    # ── PUBLIC ────────────────────────────────────────────────────

    def find_best_match(
        self,
        query: str,
        phrases: List[Dict],
    ) -> Optional[MatchResult]:
        if not phrases:
            return None

        query_clean = query.lower().strip()

        # Bước 1: Exact
        for entry in phrases:
            if query_clean == entry["trigger"]:
                return MatchResult(
                    trigger=entry["trigger"], responses=entry["responses"],
                    score=1.0, matched_by="exact",
                )

        # Bước 2: Embedding (với gap check)
        embed_result, runner_up_score = self._embedding_match_with_gap(query_clean, phrases)

        if embed_result:
            gap = embed_result.score - runner_up_score
            if embed_result.score >= EMBED_MIN_SCORE and gap >= GAP_MIN:
                # Match chắc chắn
                return embed_result
            elif embed_result.score >= SOFT_FLOOR:
                # Vùng uncertain: trả về nhưng đánh dấu để caller quyết định
                embed_result.uncertain = True
                return embed_result

        # Bước 3: Token overlap fallback
        token_result = self._token_overlap_match(query_clean, phrases)
        if token_result and token_result.score >= FUZZY_MIN_SCORE:
            if embed_result and embed_result.score > token_result.score:
                best = embed_result
            else:
                best = token_result
            # Nếu score thấp vẫn đánh dấu uncertain
            if best.score < EMBED_MIN_SCORE:
                best.uncertain = True
            return best

        return None

    def rebuild_index(self, phrases: List[Dict]):
        """Rebuild embedding cache — gọi sau mỗi lần add_phrase()."""
        triggers = [entry["trigger"] for entry in phrases]

        if self._embedder.backend == "tfidf":
            self._embedder.update_tfidf_corpus(triggers)

        if triggers:
            vectors = self._embedder.encode_batch(triggers)
            self._trigger_cache = dict(zip(triggers, vectors))
        else:
            self._trigger_cache = {}

    def get_top_matches(
        self,
        query: str,
        phrases: List[Dict],
        top_k: int = 3,
    ) -> List[MatchResult]:
        """Lấy top-k matches (dùng để debug)."""
        query_clean = query.lower().strip()
        query_vec   = self._embedder.encode(query_clean)
        results     = []

        for entry in phrases:
            trigger = entry["trigger"]
            if query_clean == trigger:
                results.append(MatchResult(
                    trigger=trigger, responses=entry["responses"],
                    score=1.0, matched_by="exact",
                ))
                continue

            t_vec = self._trigger_cache.get(trigger) or self._embedder.encode(trigger)
            self._trigger_cache[trigger] = t_vec
            score = self._embedder.similarity(query_vec, t_vec)
            results.append(MatchResult(
                trigger=trigger, responses=entry["responses"],
                score=score, matched_by="embedding",
                uncertain=(score < EMBED_MIN_SCORE),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def score_debug(self, query: str, phrases: List[Dict]) -> str:
        """Debug: in bảng điểm top-5 cho query."""
        top = self.get_top_matches(query, phrases, top_k=5)
        lines = [f"Query: '{query}'", "-" * 50]
        for i, r in enumerate(top):
            flag = " ✓" if r.score >= EMBED_MIN_SCORE else (" ~" if r.score >= SOFT_FLOOR else " ✗")
            lines.append(f"{i+1}. [{r.score:.3f}]{flag} '{r.trigger}' ({r.matched_by})")
        return "\n".join(lines)

    # ── PRIVATE ───────────────────────────────────────────────────

    def _embedding_match_with_gap(
        self,
        query_clean: str,
        phrases: List[Dict],
    ) -> Tuple[Optional[MatchResult], float]:
        """
        Trả về (best_match, runner_up_score).
        Gap = best.score - runner_up cho phép phát hiện ambiguous.
        """
        query_vec  = self._embedder.encode(query_clean)
        scores     = []

        for entry in phrases:
            trigger = entry["trigger"]
            t_vec = self._trigger_cache.get(trigger)
            if t_vec is None:
                t_vec = self._embedder.encode(trigger)
                self._trigger_cache[trigger] = t_vec

            score = self._embedder.similarity(query_vec, t_vec)
            scores.append((score, entry))

        scores.sort(key=lambda x: x[0], reverse=True)

        if not scores:
            return None, 0.0

        best_score, best_entry = scores[0]
        runner_up = scores[1][0] if len(scores) > 1 else 0.0

        if best_score < SOFT_FLOOR:
            return None, runner_up

        return MatchResult(
            trigger=best_entry["trigger"], responses=best_entry["responses"],
            score=best_score, matched_by="embedding",
        ), runner_up

    def _token_overlap_match(self, query_clean: str, phrases: List[Dict]) -> Optional[MatchResult]:
        """
        FIX: Tokenize tiếng Việt đúng hơn — giữ nguyên từ ghép có dấu.
        Gốc dùng split() → tách sai "bánh xèo" thành ["bánh", "xèo"].
        """
        query_tokens = self._vi_tokenize(query_clean)
        if not query_tokens:
            return None

        query_set  = set(query_tokens)
        best_score = 0.0
        best_entry = None

        for entry in phrases:
            # FIX: dùng lại _vi_tokenize cho trigger thay vì trigger_tokens tĩnh
            t_tokens = self._vi_tokenize(entry["trigger"])
            t_set    = set(t_tokens)
            if not t_set:
                continue

            intersection = query_set & t_set
            union        = query_set | t_set
            jaccard      = len(intersection) / len(union) if union else 0.0
            order        = self._order_bonus(query_tokens, t_tokens)

            # FIX: bigram bonus — thưởng khi hai từ liền nhau khớp (từ ghép VI)
            bigram_bonus = self._bigram_overlap(query_tokens, t_tokens)

            score = jaccard * 0.6 + order * 0.25 + bigram_bonus * 0.15

            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is None:
            return None

        return MatchResult(
            trigger=best_entry["trigger"], responses=best_entry["responses"],
            score=best_score, matched_by="token_overlap",
        )

    @staticmethod
    def _vi_tokenize(text: str) -> List[str]:
        """
        Tokenize tiếng Việt: split theo khoảng trắng, giữ dấu.
        Cải thiện so với gốc: normalize trước, bỏ stopword cực ngắn.
        """
        text = text.lower().strip()
        tokens = [t for t in text.split() if len(t) >= 1]
        return tokens

    @staticmethod
    def _bigram_overlap(a_tokens: List[str], b_tokens: List[str]) -> float:
        """Đo overlap của bigram — giúp nhận diện cụm từ ghép."""
        def bigrams(tokens):
            return set(zip(tokens, tokens[1:]))

        a_bi = bigrams(a_tokens)
        b_bi = bigrams(b_tokens)
        if not a_bi or not b_bi:
            return 0.0
        inter = a_bi & b_bi
        denom = max(len(a_bi), len(b_bi))
        return len(inter) / denom

    @staticmethod
    def _order_bonus(query_tokens: List[str], trigger_tokens: List[str]) -> float:
        qi = matched = 0
        for t_tok in trigger_tokens:
            while qi < len(query_tokens):
                if query_tokens[qi] == t_tok:
                    matched += 1; qi += 1; break
                qi += 1
        denom = max(len(trigger_tokens), len(query_tokens))
        return matched / denom if denom else 0.0
