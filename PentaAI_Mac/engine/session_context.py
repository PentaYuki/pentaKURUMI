# engine/session_context.py
"""
SessionContext — Bộ nhớ ngắn hạn trong một phiên hội thoại.

Không persist xuống file — chỉ tồn tại trong RAM, mất khi tắt chương trình.
Đây là "working memory" của AI: nhớ những gì vừa nói trong cuộc trò chuyện.

─────────────────────────────────────────────────────────
Chức năng:

  push(role, text)
    → Thêm lượt nói mới vào lịch sử
    → role: "user" hoặc "ai"
    → Tự động trim nếu vượt quá MAX_TURNS

  last_user() → str | None
    → Lượt nói gần nhất của người dùng
    → Dùng để detect ngữ cảnh (câu trước hỏi gì?)

  last_ai() → str | None
    → Câu AI vừa trả lời
    → Dùng để tránh lặp lại y chang

  get_topic() → str | None
    → Chủ đề đang nói (noun/entity phổ biến nhất gần đây)
    → VD: vừa nói về "bánh xèo" → topic = "bánh xèo"

  is_follow_up(text) → bool
    → Câu hiện tại có phải tiếp nối câu trước không?
    → VD: "còn anh?" sau "em thích ăn bánh" → follow-up = True

  get_sentiment_trend() → str
    → Xu hướng cảm xúc gần đây: "positive" | "negative" | "neutral"
    → Dùng để chọn tone phản hồi phù hợp

  get_recent_entities() → List[str]
    → Các danh từ/thực thể xuất hiện gần đây
    → Dùng để điền vào câu trả lời có ngữ cảnh

  summarize() → str
    → Tóm tắt ngắn phiên (debug / hiển thị)
─────────────────────────────────────────────────────────
"""

import re
from typing import List, Optional, Dict
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


MAX_TURNS = 20   # Nhớ tối đa N lượt (mỗi lượt = 1 câu user + 1 câu AI)


@dataclass
class Turn:
    role:      str       # "user" | "ai"
    text:      str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    lang:      str = "vi"


class SessionContext:

    # ── Từ chỉ cảm xúc tích cực / tiêu cực ──────────────────────
    _POSITIVE_WORDS = {
        "vi": {"thích", "yêu", "vui", "hay", "tốt", "đẹp", "ngon", "thú vị",
               "tuyệt", "ổn", "được", "ok", "yes", "có", "muốn", "thích thú"},
        "en": {"like", "love", "good", "great", "yes", "nice", "enjoy",
               "happy", "wonderful", "awesome", "sure", "okay"},
    }
    _NEGATIVE_WORDS = {
        "vi": {"không", "ghét", "chán", "tệ", "xấu", "buồn", "mệt",
               "dở", "khó", "sợ", "lo", "thôi", "bỏ"},
        "en": {"no", "hate", "bad", "terrible", "sad", "tired", "boring",
               "awful", "don't", "won't", "can't"},
    }

    # ── Từ chỉ follow-up ──────────────────────────────────────────
    _FOLLOWUP_STARTERS = {
        "vi": {"còn", "thế còn", "vậy còn", "còn bạn", "còn anh",
               "còn em", "thế thì", "vậy thì", "ừ", "ừ thì", "vậy"},
        "en": {"and you", "what about you", "how about", "so you",
               "and", "but", "then", "so"},
    }

    def __init__(self):
        self._turns:   List[Turn] = []
        self._lang:    str = "vi"
        self._keyword_links: Dict[str, Counter] = {}

    # ── PUBLIC ────────────────────────────────────────────────────

    def push(self, role: str, text: str, lang: str = "vi"):
        """Thêm lượt nói mới."""
        self._lang = lang
        self._turns.append(Turn(role=role, text=text, lang=lang))
        self._update_keyword_links(text)
        # Giữ tối đa MAX_TURNS * 2 entries (user + ai mỗi lượt)
        if len(self._turns) > MAX_TURNS * 2:
            self._turns = self._turns[-(MAX_TURNS * 2):]

    def last_user(self) -> Optional[str]:
        """Câu user gần nhất (không tính câu hiện tại đang xử lý)."""
        for t in reversed(self._turns):
            if t.role == "user":
                return t.text
        return None

    def last_ai(self) -> Optional[str]:
        """Câu AI gần nhất."""
        for t in reversed(self._turns):
            if t.role == "ai":
                return t.text
        return None

    def prev_user(self) -> Optional[str]:
        """Câu user trước câu user gần nhất (2 lượt trước)."""
        found = 0
        for t in reversed(self._turns):
            if t.role == "user":
                found += 1
                if found == 2:
                    return t.text
        return None

    def get_topic(self) -> Optional[str]:
        """
        Chủ đề hiện tại của cuộc hội thoại.
        = noun/entity xuất hiện nhiều nhất trong 6 turns gần nhất.
        """
        recent = self._turns[-12:]  # 6 lượt × 2
        all_text = " ".join(t.text for t in recent)
        nouns = self._extract_nouns(all_text)
        if not nouns:
            return None
        counter = Counter(nouns)
        return counter.most_common(1)[0][0]

    def get_recent_entities(self, n: int = 5) -> List[str]:
        """Các danh từ/thực thể gần đây nhất."""
        recent = self._turns[-8:]
        all_text = " ".join(t.text for t in recent)
        return self._extract_nouns(all_text)[:n]

    def is_follow_up(self, text: str) -> bool:
        """
        Câu hiện tại có phải tiếp nối không?
        Dấu hiệu: bắt đầu bằng "còn", "vậy", "thế", "ừ"...
        """
        text_lower = text.lower().strip()
        lang = self._lang

        starters = self._FOLLOWUP_STARTERS.get(lang, set())
        for starter in starters:
            if text_lower.startswith(starter):
                return True

        # Câu rất ngắn (1-2 từ) thường là follow-up
        if len(text_lower.split()) <= 2 and self._turns:
            return True

        return False

    def get_sentiment_trend(self) -> str:
        """
        Xu hướng cảm xúc trong 4 turns gần nhất.
        Trả về: "positive" | "negative" | "neutral"
        """
        recent = self._turns[-8:]
        pos_count = neg_count = 0

        for turn in recent:
            text_lower = turn.text.lower()
            lang = turn.lang

            pos_words = self._POSITIVE_WORDS.get(lang, set())
            neg_words = self._NEGATIVE_WORDS.get(lang, set())

            pos_count += sum(1 for w in pos_words if w in text_lower)
            neg_count += sum(1 for w in neg_words if w in text_lower)

        if pos_count > neg_count + 1:
            return "positive"
        if neg_count > pos_count + 1:
            return "negative"
        return "neutral"

    def has_talked_about(self, keyword: str) -> bool:
        """Kiểm tra từ/cụm từ có được đề cập trong phiên không."""
        kw_lower = keyword.lower()
        for turn in self._turns:
            if kw_lower in turn.text.lower():
                return True
        return False

    def turn_count(self) -> int:
        """Số lượt (user) đã nói trong phiên."""
        return sum(1 for t in self._turns if t.role == "user")

    def is_first_turn(self) -> bool:
        return self.turn_count() <= 1

    def summarize(self) -> str:
        """Tóm tắt phiên (dùng để debug)."""
        n = len([t for t in self._turns if t.role == "user"])
        topic = self.get_topic() or "chưa rõ"
        sentiment = self.get_sentiment_trend()
        return f"{n} lượt | chủ đề: {topic} | cảm xúc: {sentiment}"

    def extract_keywords(self, text: str) -> List[str]:
        """Public helper: tách keywords từ text theo cùng logic context."""
        return self._extract_nouns(text)

    def get_related_keywords(self, keyword: str, top_k: int = 5) -> List[str]:
        """Lấy các từ khóa hay đi cùng keyword trong phiên hiện tại."""
        key = keyword.lower().strip()
        if not key or key not in self._keyword_links:
            return []
        return [w for w, _ in self._keyword_links[key].most_common(top_k)]

    def recall_recent_by_keyword(self, keyword: str, limit: int = 3) -> List[Turn]:
        """Lấy các lượt nói gần nhất có chứa keyword."""
        key = keyword.lower().strip()
        if not key:
            return []
        hits: List[Turn] = []
        for turn in reversed(self._turns):
            if key in turn.text.lower():
                hits.append(turn)
                if len(hits) >= limit:
                    break
        return list(reversed(hits))

    def recall_recent_summary(self, keyword: str, limit: int = 3) -> str:
        """Tóm tắt ngắn các câu gần đây có chứa keyword."""
        turns = self.recall_recent_by_keyword(keyword, limit=limit)
        if not turns:
            return ""
        lines = []
        for t in turns:
            who = "Anh" if t.role == "user" else "Em"
            lines.append(f"- {who}: {t.text}")
        return "\n".join(lines)

    def clear(self):
        """Reset phiên (khi bắt đầu cuộc trò chuyện mới)."""
        self._turns = []
        self._keyword_links = {}

    # ── PRIVATE ───────────────────────────────────────────────────

    def _extract_nouns(self, text: str) -> List[str]:
        """
        Trích xuất danh từ đơn giản từ text.
        Phương pháp: lấy các từ không phải stop words, có độ dài >= 2.
        """
        stop_vi = {
            "là", "có", "và", "hoặc", "hay", "nhưng", "mà", "để",
            "trong", "ngoài", "trên", "dưới", "với", "của", "cho",
            "từ", "bởi", "vì", "nên", "thì", "mà", "đã", "đang",
            "sẽ", "rất", "lắm", "quá", "cũng", "đều", "không",
            "tôi", "mình", "bạn", "anh", "chị", "em", "nó", "họ",
            "gì", "nào", "đâu", "sao", "thế", "vậy", "ừ", "ừm",
            "à", "ạ", "nhé", "nha", "ơi", "thôi", "rồi", "đi",
        }
        stop_en = {
            "the", "a", "an", "is", "are", "was", "were", "be",
            "to", "of", "and", "in", "that", "it", "for", "on",
            "with", "he", "she", "they", "we", "you", "i", "do",
            "not", "this", "but", "have", "from", "at", "by",
        }
        stop = stop_vi | stop_en

        words = re.findall(r'\b\w+\b', text.lower())
        nouns = [w for w in words
                 if w not in stop
                 and len(w) >= 2
                 and not w.isdigit()]
        return nouns

    def _update_keyword_links(self, text: str):
        """Xây map đồng xuất hiện keyword để truy hồi chủ đề tốt hơn."""
        kws = list(dict.fromkeys(self._extract_nouns(text)))
        if len(kws) < 2:
            return
        for key in kws:
            counter = self._keyword_links.setdefault(key, Counter())
            for other in kws:
                if other != key:
                    counter[other] += 1