# engine/yes_no_responder.py
"""
YesNoResponder — Xử lý câu hỏi yes/no dựa vào ngữ cảnh phiên.

Ý tưởng:
  Khi AI không có phrase đã học cho câu "em ăn bánh xèo không?" —
  thay vì nói "mình chưa biết", AI phát hiện đây là câu hỏi yes/no
  và trả lời ngẫu nhiên có/không với tone tự nhiên, có follow-up.

  NGẪU NHIÊN ≠ 50/50 — Xác suất phụ thuộc ngữ cảnh:
    - Topic tích cực (ăn, chơi, thích...) → bias có (60%)
    - Topic tiêu cực (mệt, đau, sợ...)    → bias không (60%)
    - Sentiment phiên tích cực             → có nhiều hơn
    - Câu follow-up sau câu phủ định       → không nhiều hơn

─────────────────────────────────────────────────────────
Chức năng:

  is_yes_no_question(text, lang) → bool
    → Phát hiện câu hỏi dạng có/không
    → VD: "bạn có X không", "em X không", "X chưa?"

  generate_response(text, lang, context) → str | None
    → Trả về câu trả lời yes/no tự nhiên dựa vào context
    → None nếu không phải yes/no question

  _decide_yes_or_no(text, lang, context) → bool
    → Quyết định có (True) hay không (False)
    → Dựa vào sentiment, topic, lịch sử phiên

  _build_yes_response(topic, lang, sentiment) → str
  _build_no_response(topic, lang, sentiment) → str
    → Tạo câu trả lời có/không tự nhiên với follow-up
─────────────────────────────────────────────────────────
"""

import re
import random
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.session_context import SessionContext


class YesNoResponder:

    # ── Pattern phát hiện câu hỏi yes/no ─────────────────────────

    # Tiếng Việt: "X không?", "có X không?", "X chưa?", "X nhỉ?"
    _VI_YESNO_PATTERNS = [
        re.compile(r'.+\s+không\s*\??$',           re.IGNORECASE),
        re.compile(r'.+\s+chưa\s*\??$',             re.IGNORECASE),
        re.compile(r'^có\s+.+\s+không\s*\??$',      re.IGNORECASE),
        re.compile(r'^bạn\s+có\s+.+\s+không\s*\??', re.IGNORECASE),
        re.compile(r'^em\s+(?:có\s+)?.+\s+không',   re.IGNORECASE),
        re.compile(r'^anh\s+(?:có\s+)?.+\s+không',  re.IGNORECASE),
        re.compile(r'.+\s+nhỉ\s*\??$',              re.IGNORECASE),
        re.compile(r'.+\s+nhé\s*\??$',              re.IGNORECASE),
        re.compile(r'.+\s+hả\s*\??$',               re.IGNORECASE),
        re.compile(r'.+\s+ha\s*\??$',               re.IGNORECASE),
    ]

    # Tiếng Anh: "do you X?", "are you X?", "will you X?", "X right?"
    _EN_YESNO_PATTERNS = [
        re.compile(r'^(?:do|does|did|are|is|was|will|would|can|could|should)\s+.+\??$',
                   re.IGNORECASE),
        re.compile(r'.+\s+right\s*\??$',            re.IGNORECASE),
        re.compile(r'.+\s+okay\s*\??$',             re.IGNORECASE),
        re.compile(r'.+\s+huh\s*\??$',              re.IGNORECASE),
        re.compile(r'^(?:you|you\'re|you\'ve).+\??$', re.IGNORECASE),
    ]

    # Tiếng Nhật
    _JP_YESNO_PATTERNS = [
        re.compile(r'.+(?:ですか|ますか|でしょうか|だろうか)\s*\??$'),
        re.compile(r'.+(?:かな|かしら|かな？)\s*$'),
    ]

    # ── Từ topic tích cực / tiêu cực (ảnh hưởng bias yes/no) ─────
    _POSITIVE_TOPICS = {
        "vi": {"ăn", "uống", "chơi", "thích", "yêu", "vui", "bánh", "đồ ăn",
               "kem", "phim", "nhạc", "du lịch", "mua", "ngủ", "nghỉ",
               "cà phê", "trà", "ngon", "tuyệt", "hay"},
        "en": {"eat", "drink", "play", "like", "love", "fun", "food",
               "movie", "music", "travel", "buy", "sleep", "rest",
               "coffee", "tea", "nice", "great"},
    }
    _NEGATIVE_TOPICS = {
        "vi": {"mệt", "đau", "sợ", "lo", "buồn", "khó", "tệ", "chán",
               "bận", "muộn", "trễ", "khóc", "thất bại", "thua"},
        "en": {"tired", "pain", "scared", "worried", "sad", "hard", "bad",
               "boring", "busy", "late", "fail", "lose"},
    }

    # ── Response pools theo ngôn ngữ ─────────────────────────────
    _YES_RESPONSES = {
        "vi": {
            "default": [
                "Có chứ! {followup}",
                "Ừ, có! {followup}",
                "Dĩ nhiên rồi! {followup}",
                "Tất nhiên! {followup}",
                "Ừ thì có. {followup}",
                "Có ạ! {followup}",
            ],
            "food": [
                "Ăn chứ! {topic} ngon lắm mà. {followup}",
                "Có, {topic} là khoái khẩu của mình đó! {followup}",
                "Thích ăn {topic} lắm! {followup}",
            ],
            "activity": [
                "Có chứ, mình thích {topic} lắm! {followup}",
                "Ừ, {topic} vui mà! {followup}",
                "Dĩ nhiên, mình hay {topic} đó. {followup}",
            ],
            "feeling": [
                "Ừ, mình {topic} thật. {followup}",
                "Có, hơi {topic} một chút. {followup}",
            ],
        },
        "en": {
            "default": [
                "Yes! {followup}",
                "Of course! {followup}",
                "Sure! {followup}",
                "Yeah, I do! {followup}",
                "Definitely! {followup}",
            ],
        },
        "jp": {
            "default": [
                "はい！{followup}",
                "もちろん！{followup}",
                "ええ！{followup}",
            ],
        },
    }

    _NO_RESPONSES = {
        "vi": {
            "default": [
                "Không hẳn. {followup}",
                "Không đâu. {followup}",
                "Thật ra thì không. {followup}",
                "Ừm, chưa chắc. {followup}",
                "Không nhé! {followup}",
            ],
            "food": [
                "Không, mình không hợp với {topic} lắm. {followup}",
                "{topic} thì mình ít ăn. {followup}",
                "Không thích {topic} mấy. {followup}",
            ],
            "activity": [
                "Không, mình không hay {topic}. {followup}",
                "Thật ra mình không thích {topic} lắm. {followup}",
            ],
        },
        "en": {
            "default": [
                "Not really. {followup}",
                "No, I don't. {followup}",
                "Hmm, not quite. {followup}",
                "I don't think so. {followup}",
            ],
        },
        "jp": {
            "default": [
                "いいえ。{followup}",
                "そうでもないです。{followup}",
                "ちょっと違います。{followup}",
            ],
        },
    }

    # Follow-up sau câu có/không
    _FOLLOWUPS = {
        "vi": {
            "after_yes":  [
                "Còn bạn thì sao?",
                "Bạn thì có không?",
                "Bạn cũng thích vậy không?",
                "Sao hỏi vậy?",
                "",  # đôi khi không follow-up
                "",
            ],
            "after_no": [
                "Còn bạn thì sao?",
                "Bạn có không?",
                "Tại sao bạn hỏi vậy?",
                "",
                "",
            ],
        },
        "en": {
            "after_yes":  ["What about you?", "How about you?", "Do you?", ""],
            "after_no":   ["What about you?", "Why do you ask?", ""],
        },
        "jp": {
            "after_yes":  ["あなたは？", "そっちは？", ""],
            "after_no":   ["あなたは？", "どうして？", ""],
        },
    }

    # ── PUBLIC ────────────────────────────────────────────────────

    def is_yes_no_question(self, text: str, lang: str = "vi") -> bool:
        """
        Phát hiện câu hỏi yes/no.
        Kiểm tra theo ngôn ngữ + fallback chung.
        """
        text_stripped = text.strip().rstrip("?!.,")

        patterns = {
            "vi": self._VI_YESNO_PATTERNS,
            "en": self._EN_YESNO_PATTERNS,
            "jp": self._JP_YESNO_PATTERNS,
        }.get(lang, self._VI_YESNO_PATTERNS)

        for pattern in patterns:
            if pattern.search(text_stripped):
                return True

        # Fallback: câu kết thúc bằng "không" hoặc "?"
        if lang == "vi" and text_stripped.endswith("không"):
            return True

        return False

    def generate_response(
        self,
        text:        str,
        lang:        str,
        context:     "SessionContext",
        h_modifiers: dict = None,
    ) -> Optional[str]:
        """
        Tạo câu trả lời yes/no tự nhiên dựa vào ngữ cảnh.
        Trả về None nếu không phải yes/no question.
        """
        if not self.is_yes_no_question(text, lang):
            return None

        # Quyết định có hay không
        answer_yes = self._decide_yes_or_no(text, lang, context, h_modifiers)

        # Trích xuất topic từ câu hỏi + context
        topic = self._extract_topic_from_question(text, lang, context)

        # Phân loại topic
        topic_type = self._classify_topic(topic, lang)

        # Tạo câu trả lời
        if answer_yes:
            response = self._build_yes_response(topic, topic_type, lang)
        else:
            response = self._build_no_response(topic, topic_type, lang)

        return response

    # ── PRIVATE: DECISION LOGIC ───────────────────────────────────

    def _decide_yes_or_no(
        self,
        text:          str,
        lang:          str,
        context:       "SessionContext",
        h_modifiers:   dict = None,
    ) -> bool:
        """
        Quyết định có (True) hay không (False).

        Điểm số: > 0 → có, < 0 → không
        Base:    +0 (50/50)
        Điều chỉnh:
          +2: topic tích cực (ăn ngon, chơi, thích...)
          -2: topic tiêu cực (mệt, đau, khó...)
          +1: sentiment phiên tích cực
          -1: sentiment phiên tiêu cực
          +1: câu trước AI đã nói "có"
          -1: câu trước AI đã nói "không"
          ±1: random noise để không quá đoán được
        """
        score = 0

        # Kiểm tra topic trong câu hỏi
        topic = self._extract_topic_from_question(text, lang, context)
        pos_topics = self._POSITIVE_TOPICS.get(lang, set())
        neg_topics = self._NEGATIVE_TOPICS.get(lang, set())

        if topic:
            topic_words = set(topic.lower().split())
            if topic_words & pos_topics:
                score += 2
            elif topic_words & (pos_topics | {t for t in pos_topics}):
                score += 1
            if topic_words & neg_topics:
                score -= 2

        # Sentiment của phiên
        sentiment = context.get_sentiment_trend()
        if sentiment == "positive":
            score += 1
        elif sentiment == "negative":
            score -= 1

        # Câu AI trả lời gần nhất
        last_ai = context.last_ai()
        if last_ai:
            last_lower = last_ai.lower()
            if any(w in last_lower for w in ["có", "yes", "ừ", "được", "thích"]):
                score += 1
            elif any(w in last_lower for w in ["không", "no", "chưa", "thôi"]):
                score -= 1

        # Hormone yes_bias nếu có
        if h_modifiers:
            yes_bias = h_modifiers.get("yes_bias", 0)
            score += yes_bias * 2  # scale up để có ảnh hưởng rõ

        # Random noise (±1)
        score += random.choice([-1, 0, 0, 1, 1])

        return score >= 0

    def _extract_topic_from_question(
        self,
        text:    str,
        lang:    str,
        context: "SessionContext",
    ) -> Optional[str]:
        """
        Trích xuất chủ đề DANH TỪ từ câu hỏi (bỏ động từ/tính từ đơn).
        VD: "em ăn bánh xèo không" → "bánh xèo"  (giữ danh từ)
            "bạn thích ăn không"   → None         (chỉ có động từ → dùng default)
            "bạn có vui không"     → "vui"         (tính từ trạng thái)
        """
        stopwords_q = {
            "vi": {"em", "anh", "bạn", "có", "không", "chưa", "nhỉ",
                   "nhé", "hả", "ha", "à", "ạ", "thì", "đi", "nha",
                   "mình", "tôi", "chị", "ơi",
                   # Thời gian — không phải topic
                   "hôm", "hôm nay", "hôm qua", "ngày", "tuần", "tháng",
                   "chủ", "nhật", "thứ", "năm", "sáng", "chiều", "tối",
                   # Đại từ thêm
                   "tớ", "cậu", "mày", "nó", "họ",
                   # Kết nối
                   "rồi", "thôi", "vậy", "nha", "nè", "hén"},
            "en": {"do", "does", "are", "is", "you", "right", "huh",
                   "okay", "will", "can", "would", "i", "we", "they",
                   "today", "tomorrow", "monday", "tuesday", "sunday",
                   "this", "that", "when", "where"},
        }.get(lang, set())

        # Các động từ chung không phải topic
        generic_verbs_vi = {"ăn", "uống", "đi", "làm", "có", "thích",
                             "muốn", "biết", "hiểu", "nói", "nghe",
                             "chơi", "học", "xem", "mua", "về", "ra",
                             "lên", "xuống", "qua", "lại"}

        words = text.lower().strip().rstrip("?!").split()
        content_words = [w for w in words if w not in stopwords_q and len(w) >= 2]

        if not content_words:
            return context.get_topic()

        # Bỏ động từ chung nếu là từ DUY NHẤT còn lại
        non_verb = [w for w in content_words if w not in generic_verbs_vi]
        if non_verb:
            if len(non_verb) >= 2:
                return " ".join(non_verb[-2:])
            return non_verb[-1]

        # Chỉ còn động từ → không có topic cụ thể → dùng context
        return context.get_topic()

    def _classify_topic(self, topic: Optional[str], lang: str) -> str:
        """Phân loại topic: 'food' | 'activity' | 'feeling' | 'default'"""
        if not topic:
            return "default"

        topic_lower = topic.lower()

        food_words = {
            "vi": {"ăn", "uống", "bánh", "cơm", "phở", "bún", "cà phê",
                   "trà", "bia", "rượu", "đồ ăn", "món", "hoa quả"},
            "en": {"eat", "drink", "food", "cake", "rice", "coffee",
                   "tea", "beer", "meal", "fruit"},
        }.get(lang, set())

        activity_words = {
            "vi": {"chơi", "đi", "học", "làm", "xem", "nghe", "đọc",
                   "mua", "bán", "gặp", "thăm", "du lịch"},
            "en": {"play", "go", "study", "work", "watch", "listen",
                   "read", "buy", "sell", "meet", "visit", "travel"},
        }.get(lang, set())

        feeling_words = {
            "vi": {"thích", "yêu", "ghét", "sợ", "vui", "buồn", "mệt",
                   "khỏe", "ổn", "lo", "tức", "bực"},
            "en": {"like", "love", "hate", "scared", "happy", "sad",
                   "tired", "okay", "worried", "angry"},
        }.get(lang, set())

        topic_words = set(topic_lower.split())
        if topic_words & food_words:
            return "food"
        if topic_words & activity_words:
            return "activity"
        if topic_words & feeling_words:
            return "feeling"
        return "default"

    # ── PRIVATE: RESPONSE BUILDERS ────────────────────────────────

    def _build_yes_response(
        self,
        topic:      Optional[str],
        topic_type: str,
        lang:       str,
    ) -> str:
        lang_pool = self._YES_RESPONSES.get(lang, self._YES_RESPONSES["vi"])
        pool      = lang_pool.get(topic_type, lang_pool["default"])
        template  = random.choice(pool)

        followup_pool = self._FOLLOWUPS.get(lang, {}).get("after_yes", [""])
        followup      = random.choice(followup_pool)

        result = template.format(
            topic      = topic or "",
            verb_topic = f"{topic} " if topic else "",
            has_topic  = f"{topic} " if topic else "",
            followup   = followup,
        ).strip()

        # Dọn khoảng trắng thừa
        result = re.sub(r'\s+', ' ', result).strip()
        return result

    def _build_no_response(
        self,
        topic:      Optional[str],
        topic_type: str,
        lang:       str,
    ) -> str:
        lang_pool = self._NO_RESPONSES.get(lang, self._NO_RESPONSES["vi"])
        pool      = lang_pool.get(topic_type, lang_pool["default"])
        template  = random.choice(pool)

        followup_pool = self._FOLLOWUPS.get(lang, {}).get("after_no", [""])
        followup      = random.choice(followup_pool)

        result = template.format(
            topic      = topic or "",
            verb_topic = f"{topic} " if topic else "",
            has_topic  = f"{topic} " if topic else "",
            followup   = followup,
        ).strip()

        result = re.sub(r'\s+', ' ', result).strip()
        return result