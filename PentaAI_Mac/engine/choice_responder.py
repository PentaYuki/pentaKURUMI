# engine/choice_responder.py
"""
ChoiceResponder — Xử lý câu hỏi lựa chọn "A hay B?"

Ví dụ:
  "ngày mai em làm gì mua sắm hay làm chuyện bí mật"
  → AI chọn 1 trong 2, trả lời tự nhiên có ngữ cảnh

  "em ăn phở hay bún bò"
  → AI chọn ngẫu nhiên, bias theo sentiment/context

─────────────────────────────────────────────────────────
Chức năng:

  is_choice_question(text, lang) → bool
    → Phát hiện câu có cấu trúc "A hay B" / "A or B"
    → Phân biệt với câu hỏi thường ("bạn có thích không")

  extract_choices(text, lang) → List[str]
    → Trích xuất các lựa chọn từ câu
    → "mua sắm hay làm chuyện bí mật" → ["mua sắm", "làm chuyện bí mật"]
    → Hỗ trợ 2+ lựa chọn: "A, B hay C"

  generate_response(text, lang, context) → str | None
    → Chọn 1 option, tạo câu trả lời tự nhiên
    → Dùng context để bias (sentiment, topic)
    → None nếu không phải choice question

  _pick_choice(choices, text, lang, context) → str
    → Quyết định chọn option nào
    → Bias: option tích cực hơn được chọn nhiều hơn

  _build_choice_response(chosen, all_choices, lang, context) → str
    → Tạo câu trả lời tự nhiên với option đã chọn
    → Đôi khi hỏi ngược lại người dùng
─────────────────────────────────────────────────────────
"""

import re
import random
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.session_context import SessionContext


class ChoiceResponder:

    # ── Pattern phát hiện câu hỏi lựa chọn ──────────────────────
    _VI_CHOICE_PATTERNS = [
        # "A hay B" / "A hay là B"
        re.compile(r'.+\s+hay(?:\s+là)?\s+.+', re.IGNORECASE),
        # "A hoặc B"
        re.compile(r'.+\s+hoặc\s+.+', re.IGNORECASE),
        # "chọn A hay B" / "thích A hay B"
        re.compile(
            r'(?:chọn|thích|muốn|nên|sẽ)\s+.+\s+hay(?:\s+là)?\s+.+',
            re.IGNORECASE
        ),
    ]
    _EN_CHOICE_PATTERNS = [
        re.compile(r'.+\s+or\s+.+', re.IGNORECASE),
        re.compile(r'(?:choose|prefer|like)\s+.+\s+or\s+.+', re.IGNORECASE),
    ]
    _JP_CHOICE_PATTERNS = [
        re.compile(r'.+(?:か|それとも).+', re.IGNORECASE),
    ]

    # ── Từ split lựa chọn ────────────────────────────────────────
    _SPLIT_WORDS = {
        "vi": [" hay là ", " hay ", " hoặc là ", " hoặc "],
        "en": [" or "],
        "jp": ["それとも", "か"],
    }

    # ── Từ prefix cần bỏ trước khi lấy lựa chọn ─────────────────
    _STRIP_PREFIXES_VI = [
        r'^(?:ngày mai|hôm nay|hôm qua|tuần này|tháng này)\s+',
        r'^(?:em|anh|bạn|mình|tôi|chị)\s+(?:sẽ\s+)?(?:làm gì|ăn gì|đi đâu|thích gì|muốn gì)\s+',
        r'^(?:em|anh|bạn|mình|tôi|chị)\s+',
        r'^(?:muốn|thích|nên|sẽ|định)\s+',
    ]
    _STRIP_PREFIXES_EN = [
        r'^(?:do|does|would|will|should|can)\s+(?:you|i|we|they)\s+',
        r'^(?:you|i|we)\s+(?:prefer|like|want|choose)\s+',
        r'^(?:prefer|like|want|choose)\s+',
        r'^(?:between)\s+',
    ]

    # ── Response pools ────────────────────────────────────────────
    _PICK_RESPONSES = {
        "vi": [
            "{chosen} nghe hay đó! {followup}",
            "Mình chọn {chosen}! {followup}",
            "{chosen} chứ! {followup}",
            "Tất nhiên là {chosen} rồi. {followup}",
            "Mình thích {chosen} hơn. {followup}",
            "Hmm, {chosen} đi! {followup}",
            "{chosen}! Bạn thấy sao? {followup}",
        ],
        "en": [
            "{chosen}, definitely! {followup}",
            "I'd go with {chosen}! {followup}",
            "{chosen} for sure! {followup}",
            "Definitely {chosen}. {followup}",
        ],
        "jp": [
            "{chosen}がいいです！{followup}",
            "{chosen}を選びます！{followup}",
            "もちろん{chosen}！{followup}",
        ],
    }

    _FOLLOWUPS = {
        "vi": [
            "Còn bạn thì sao?",
            "Bạn chọn gì?",
            "Bạn thích cái nào?",
            "Sao bạn hỏi vậy?",
            "",
            "",
            "",  # trống nhiều hơn → không luôn luôn hỏi lại
        ],
        "en": [
            "What about you?",
            "Which do you prefer?",
            "How about you?",
            "",
            "",
        ],
        "jp": [
            "あなたは？",
            "どちらが好き？",
            "",
        ],
    }

    # ── Keyword tích cực / tiêu cực để bias chọn lựa ─────────────
    _POSITIVE_KEYWORDS = {
        "vi": {"vui", "ăn", "chơi", "mua", "đi", "thích", "hay", "ngon",
               "tốt", "đẹp", "thú vị", "bí mật", "lãng mạn", "đặc biệt"},
        "en": {"fun", "eat", "play", "buy", "go", "like", "nice", "good",
               "special", "romantic", "interesting", "enjoy"},
    }

    # ── PUBLIC ────────────────────────────────────────────────────

    def is_choice_question(self, text: str, lang: str = "vi") -> bool:
        """
        Phát hiện câu hỏi lựa chọn.
        Phân biệt với yes/no: "bạn thích không?" ≠ "bạn thích A hay B?"
        """
        text_lower = text.lower().strip()

        patterns = {
            "vi": self._VI_CHOICE_PATTERNS,
            "en": self._EN_CHOICE_PATTERNS,
            "jp": self._JP_CHOICE_PATTERNS,
        }.get(lang, self._VI_CHOICE_PATTERNS)

        for pattern in patterns:
            if pattern.search(text_lower):
                choices = self.extract_choices(text_lower, lang)
                # Phải có ít nhất 2 lựa chọn thực sự
                if len(choices) >= 2 and all(len(c.strip()) >= 2 for c in choices):
                    return True

        return False

    def extract_choices(self, text: str, lang: str = "vi") -> List[str]:
        """
        Trích xuất các lựa chọn từ câu.

        Ví dụ:
          "mua sắm hay làm chuyện bí mật" → ["mua sắm", "làm chuyện bí mật"]
          "phở, bún bò hay cơm tấm"       → ["phở", "bún bò", "cơm tấm"]
          "A or B or C"                   → ["A", "B", "C"]
        """
        # Bỏ phần prefix câu hỏi
        clean = self._strip_question_prefix(text, lang)

        # Tách theo từ split
        split_words = self._SPLIT_WORDS.get(lang, self._SPLIT_WORDS["vi"])
        parts = [clean]
        for splitter in split_words:
            new_parts = []
            for part in parts:
                split = re.split(re.escape(splitter), part, flags=re.IGNORECASE)
                new_parts.extend(split)
            parts = new_parts

        # Tách thêm bằng dấu phẩy
        final_parts = []
        for part in parts:
            comma_split = [p.strip() for p in part.split(',')]
            final_parts.extend(comma_split)

        # Lọc: bỏ rỗng, bỏ quá ngắn
        choices = [p.strip().rstrip('?!.,') for p in final_parts
                   if p.strip() and len(p.strip()) >= 2]

        return choices

    def generate_response(
        self,
        text:        str,
        lang:        str,
        context:     "SessionContext",
        h_modifiers: dict = None,
    ) -> Optional[str]:
        """
        Tạo câu trả lời lựa chọn tự nhiên.
        Trả về None nếu không phải choice question.
        """
        if not self.is_choice_question(text, lang):
            return None

        choices = self.extract_choices(text.lower(), lang)
        if len(choices) < 2:
            return None

        # Chọn 1 option
        chosen = self._pick_choice(choices, text, lang, context, h_modifiers)

        # Build response
        return self._build_choice_response(chosen, choices, lang, context)

    # ── PRIVATE ───────────────────────────────────────────────────

    def _strip_question_prefix(self, text: str, lang: str) -> str:
        """Bỏ phần tiền tố câu hỏi để lấy phần lựa chọn."""
        result = text.lower().strip().rstrip('?!.')

        if lang == "vi":
            for prefix_pattern in self._STRIP_PREFIXES_VI:
                result = re.sub(prefix_pattern, '', result, flags=re.IGNORECASE)
                result = result.strip()
        elif lang == "en":
            for prefix_pattern in self._STRIP_PREFIXES_EN:
                result = re.sub(prefix_pattern, '', result, flags=re.IGNORECASE)
                result = result.strip()

        return result

    def _pick_choice(
        self,
        choices:     List[str],
        text:        str,
        lang:        str,
        context:     "SessionContext",
        h_modifiers: dict = None,
    ) -> str:
        """
        Chọn 1 option dựa vào ngữ cảnh.

        Điểm số mỗi option:
          base: 0
          +2: chứa keyword tích cực
          +1: sentiment phiên tích cực
          +1: option ngắn hơn (dễ xử lý hơn)
          ±1: random noise
        """
        scores = [0.0] * len(choices)
        pos_kw = self._POSITIVE_KEYWORDS.get(lang, set())
        sentiment = context.get_sentiment_trend()

        for i, choice in enumerate(choices):
            words = set(choice.lower().split())

            # Keyword tích cực
            if words & pos_kw:
                scores[i] += 2

            # Sentiment bias
            if sentiment == "positive":
                scores[i] += 0.5

            # Ưu tiên option đầu tiên nhẹ (thường là option chính)
            if i == 0:
                scores[i] += 0.3

            # Hormone choice_bias: avoidant → ưu tiên option cuối (né tránh)
            if h_modifiers:
                cb = h_modifiers.get("choice_bias", "neutral")
                if cb == "avoidant" and i == len(choices) - 1:
                    scores[i] += 1.0  # None/không chọn gì option cuối
                elif cb == "positive" and i == 0:
                    scores[i] += 0.5  # Thiên về option đầu

            # Random noise
            scores[i] += random.uniform(-1, 1)

        # Chọn option có điểm cao nhất
        best_idx = scores.index(max(scores))
        return choices[best_idx]

    def _build_choice_response(
        self,
        chosen:      str,
        all_choices: List[str],
        lang:        str,
        context:     "SessionContext",
    ) -> str:
        """Tạo câu trả lời tự nhiên với option đã chọn."""
        pool      = self._PICK_RESPONSES.get(lang, self._PICK_RESPONSES["vi"])
        template  = random.choice(pool)

        followup_pool = self._FOLLOWUPS.get(lang, self._FOLLOWUPS["vi"])
        followup      = random.choice(followup_pool)

        # Capitalize chosen
        chosen_display = chosen.strip()
        if chosen_display:
            chosen_display = chosen_display[0].upper() + chosen_display[1:]

        result = template.format(
            chosen=chosen_display,
            followup=followup,
        ).strip()

        # Dọn khoảng trắng
        result = re.sub(r'\s+', ' ', result).strip()
        return result