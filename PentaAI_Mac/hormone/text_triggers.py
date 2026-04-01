# hormone/text_triggers.py
"""
TextTriggers — Phân tích text → thay đổi hormone (v2.0).

Cải tiến v2.0:
  - Thêm từ khóa tiếng Việt đầy đủ hơn (kiệt sức, chán nản, xúc động...)
  - Cross-language links: "mệt" ↔ "tired" ↔ "疲れ" có cùng loại effect
  - Danh xưng: "em/anh/mình/bạn" → oxytocin nhẹ (nhận ra mối quan hệ)
  - Từ gợi nhớ: "nhớ lại", "hồi đó" → adrenaline + oxytocin
  - Thêm từ cảm xúc Nhật mở rộng

3 nguồn kích thích:
  1. Keywords trong text người dùng
  2. Intent type (TEACH, GREET, CONVERSE...)
  3. Interaction pattern (lần đầu gặp, bị bỏ qua, được khen...)
"""

import re
from typing import Dict, Tuple

# ── KEYWORD → HORMONE CHANGES ─────────────────────────────────────────────
_KEYWORD_TRIGGERS: Dict[str, Dict[str, float]] = {

    # ── YÊU THƯƠNG / GẮN BÓ ──────────────────────────────────────────────
    r'\b(yêu|thương|thích|mến|quý|nhớ|nhớ bạn|nhớ anh|nhớ em)\b': {
        "oxytocin":  +0.12,
        "serotonin": +0.06,
        "dopamine":  +0.05,
        "cortisol":  -0.04,
    },
    r'\b(love|like|miss|adore|care|fond|cherish)\b': {
        "oxytocin":  +0.12,
        "serotonin": +0.06,
        "dopamine":  +0.04,
    },
    r'\b(愛|好き|恋しい|大切|思いやり)\b': {
        "oxytocin":  +0.12,
        "serotonin": +0.05,
    },

    # ── VUI VẺ / HẠNH PHÚC ────────────────────────────────────────────────
    r'\b(vui|hạnh phúc|tuyệt|hay|thú vị|thích thú|hehe|haha|lol|phấn khởi|hứng thú|sung sướng)\b': {
        "dopamine":  +0.10,
        "serotonin": +0.07,
        "oxytocin":  +0.03,
    },
    r'\b(happy|joy|great|awesome|wonderful|fun|excited|yay|delighted|cheerful)\b': {
        "dopamine":  +0.10,
        "serotonin": +0.07,
    },
    r'\b(嬉しい|楽しい|幸せ|最高|ワクワク|うれしい)\b': {
        "dopamine":  +0.10,
        "serotonin": +0.06,
    },

    # ── BUỒN / ĐAU KHỔ ────────────────────────────────────────────────────
    r'\b(buồn|khóc|đau|khổ|tủi|thất vọng|chán|mệt mỏi|đau lòng|nản|tuyệt vọng|chán nản)\b': {
        "serotonin": -0.12,
        "dopamine":  -0.08,
        "cortisol":  +0.08,
        "oxytocin":  -0.04,
    },
    r'\b(sad|cry|hurt|pain|depress|disappointed|tired|exhausted|miserable|sorrow)\b': {
        "serotonin": -0.12,
        "dopamine":  -0.08,
        "cortisol":  +0.08,
    },
    r'\b(悲しい|泣く|つらい|辛い|寂しい|落ち込む|苦しい)\b': {
        "serotonin": -0.12,
        "dopamine":  -0.08,
        "cortisol":  +0.08,
    },

    # ── MỆT MỎI / KIỆT SỨC ────────────────────────────────────────────────
    # Thêm riêng với effect mạnh hơn vì user thường dùng để kể chuyện
    r'\b(mệt|kiệt sức|kiệt|uể oải|đuối|không còn sức|mệt lắm|mệt quá)\b': {
        "dopamine":  -0.09,
        "adrenaline":-0.05,
        "serotonin": -0.05,
        "GABA":      +0.07,
        "cortisol":  +0.06,
    },
    r'\b(exhausted|drained|burn.?out|worn out|wiped out|no energy|dead tired)\b': {
        "dopamine":  -0.09,
        "adrenaline":-0.05,
        "serotonin": -0.05,
        "GABA":      +0.07,
        "cortisol":  +0.06,
    },
    r'\b(疲れ|疲れた|くたくた|へとへと|ぐったり)\b': {
        "dopamine":  -0.09,
        "GABA":      +0.07,
        "cortisol":  +0.06,
    },

    # ── TỨC GIẬN / THẤT VỌNG ──────────────────────────────────────────────
    r'\b(tức|giận|bực|ghét|chửi|khó chịu|điên|bực bội|tức điên|ghét lắm)\b': {
        "cortisol":       +0.15,
        "adrenaline":     +0.12,
        "norepinephrine": +0.08,
        "oxytocin":       -0.10,
        "serotonin":      -0.06,
    },
    r'\b(angry|hate|annoyed|mad|frustrated|irritat|furious|rage)\b': {
        "cortisol":       +0.15,
        "adrenaline":     +0.12,
        "norepinephrine": +0.08,
        "oxytocin":       -0.08,
    },
    r'\b(怒り|腹が立つ|むかつく|イライラ|頭に来る|嫌い|憎い)\b': {
        "cortisol":       +0.15,
        "adrenaline":     +0.12,
        "oxytocin":       -0.08,
    },

    # ── KHEN NGỢI AI ──────────────────────────────────────────────────────
    r'\b(giỏi|thông minh|hay quá|tuyệt vời|cảm ơn|thanks?|cám ơn|tài|xuất sắc|ngoan)\b': {
        "dopamine":  +0.12,
        "serotonin": +0.08,
        "oxytocin":  +0.06,
        "cortisol":  -0.05,
    },
    r'\b(smart|clever|good job|well done|thank you|great job|brilliant|amazing)\b': {
        "dopamine":  +0.12,
        "serotonin": +0.08,
        "oxytocin":  +0.05,
    },
    r'\b(すごい|ありがとう|よかった|上手|賢い|天才|素晴らしい)\b': {
        "dopamine":  +0.12,
        "serotonin": +0.08,
        "oxytocin":  +0.05,
    },

    # ── CHỈ TRÍCH / CHỬI AI ────────────────────────────────────────────────
    r'\b(ngốc|ngu|dở|tệ|kém|vô dụng|sai rồi|không đúng|vớ vẩn|vô lý)\b': {
        "cortisol":  +0.10,
        "serotonin": -0.08,
        "dopamine":  -0.05,
        "adrenaline":+0.06,
    },
    r'\b(stupid|dumb|wrong|bad|useless|idiot|error|incorrect|nonsense)\b': {
        "cortisol":  +0.10,
        "serotonin": -0.08,
        "dopamine":  -0.05,
    },
    r'\b(バカ|馬鹿|ダメ|違う|おかしい|最悪|下手)\b': {
        "cortisol":  +0.10,
        "serotonin": -0.08,
        "dopamine":  -0.05,
    },

    # ── TÒ MÒ / HỌC HỎI ──────────────────────────────────────────────────
    r'\b(tại sao|vì sao|như thế nào|thế nào|giải thích|ý nghĩa|cho biết|muốn biết)\b': {
        "dopamine":  +0.08,
        "norepinephrine": +0.04,
    },
    r'\b(why|how|explain|what does|what is|define|tell me|curious|wonder)\b': {
        "dopamine":  +0.08,
        "norepinephrine": +0.04,
    },
    r'\b(なぜ|どうして|どのように|説明|意味|知りたい)\b': {
        "dopamine":  +0.08,
        "norepinephrine": +0.04,
    },

    # ── LO LẮNG / SỢ HÃI ─────────────────────────────────────────────────
    r'\b(sợ|lo|lo lắng|hồi hộp|căng thẳng|stress|áp lực|lo ngại|lo sợ|băn khoăn)\b': {
        "cortisol":   +0.12,
        "adrenaline": +0.08,
        "serotonin":  -0.06,
        "GABA":       -0.04,
    },
    r'\b(scared|afraid|worried|anxious|nervous|stress|pressure|fear|dread)\b': {
        "cortisol":   +0.12,
        "adrenaline": +0.08,
        "serotonin":  -0.06,
    },
    r'\b(怖い|不安|心配|緊張|ストレス|プレッシャー)\b': {
        "cortisol":   +0.12,
        "adrenaline": +0.08,
        "serotonin":  -0.06,
    },

    # ── BẤT NGỜ ──────────────────────────────────────────────────────────
    r'\b(wow|ồ|ôi|trời|bất ngờ|không ngờ|thật không|thật sao|ngạc nhiên)\b': {
        "adrenaline":     +0.10,
        "dopamine":       +0.06,
        "norepinephrine": +0.05,
    },
    r'\b(wow|oh|omg|really|seriously|no way|surprising|unexpected|shocked)\b': {
        "adrenaline":     +0.10,
        "dopamine":       +0.06,
    },
    r'\b(びっくり|驚き|まさか|えっ|本当に|信じられない)\b': {
        "adrenaline":     +0.10,
        "dopamine":       +0.06,
    },

    # ── XÃ GIAO THÂN MẬT ─────────────────────────────────────────────────
    r'\b(chào|hello|hi|xin chào|ơi|bạn ơi|alo)\b': {
        "oxytocin":  +0.08,
        "dopamine":  +0.05,
        "serotonin": +0.03,
    },
    r'\b(tạm biệt|bye|goodbye|hẹn gặp|thôi nhé|đi ngủ)\b': {
        "oxytocin":  -0.05,
        "serotonin": +0.03,
    },
    r'\b(おやすみ|さようなら|またね|じゃあね|バイバイ)\b': {
        "oxytocin":  -0.04,
        "serotonin": +0.03,
    },

    # ── DANH XƯNG — PHÁT HIỆN MỐI QUAN HỆ ──────────────────────────────────
    # User xưng "em" hoặc gọi AI là "anh/chị" → oxytocin nhẹ (gắn bó)
    r'\b(em|anh ơi|chị ơi|bạn ơi|mình ơi)\b': {
        "oxytocin":  +0.04,
        "serotonin": +0.02,
    },
    # Nói về "mình" với người khác → gắn bó
    r'\b(mình với|chúng mình|hai mình|bọn mình)\b': {
        "oxytocin":  +0.06,
        "serotonin": +0.02,
    },

    # ── GỢI NHỚ / KÝ ỨC ──────────────────────────────────────────────────
    r'\b(nhớ lại|hồi đó|trước đây|ngày xưa|lúc trước|hồi năm|hồi nhỏ|kỷ niệm)\b': {
        "adrenaline": +0.06,
        "oxytocin":   +0.08,
        "dopamine":   +0.04,
    },
    r'\b(remember when|back then|in the past|used to|long ago|nostalgia|memoir)\b': {
        "adrenaline": +0.06,
        "oxytocin":   +0.08,
        "dopamine":   +0.04,
    },
    r'\b(昔|思い出|以前|あの頃|懐かしい|記憶)\b': {
        "adrenaline": +0.06,
        "oxytocin":   +0.08,
    },

    # ── XÚC ĐỘNG / CẢM KÍCH ──────────────────────────────────────────────
    r'\b(xúc động|cảm động|rơi nước mắt|nghẹn ngào|ấm lòng|xúc cảm)\b': {
        "oxytocin":  +0.10,
        "serotonin": +0.05,
        "adrenaline":+0.07,
    },
    r'\b(touched|moved|emotional|tears|heartwarming|overwhelming)\b': {
        "oxytocin":  +0.10,
        "serotonin": +0.05,
        "adrenaline":+0.07,
    },
    r'\b(感動|泣けた|ジーン|心に刺さる|号泣|涙が出る)\b': {
        "oxytocin":  +0.10,
        "serotonin": +0.05,
        "adrenaline":+0.07,
    },

    # ── TẦM THƯỜNG / THÓI QUEN ────────────────────────────────────────────
    r'\b(ừ|ok|được|thôi|vậy đi|oke|okay|alright)\b': {
        "serotonin": +0.02,
    },
}

# ── INTENT → HORMONE CHANGES ──────────────────────────────────────────────
_INTENT_TRIGGERS: Dict[str, Dict[str, float]] = {
    "TEACH_PHRASE": {
        "dopamine":  +0.10,
        "oxytocin":  +0.05,
        "serotonin": +0.03,
        "cortisol":  -0.03,
    },
    "TEACH_FACT": {
        "dopamine":  +0.08,
        "serotonin": +0.04,
    },
    "TEACH_SYNONYM": {
        "dopamine":  +0.07,
        "serotonin": +0.03,
    },
    "ASK_DEFINITION": {
        "dopamine":  +0.06,
        "norepinephrine": +0.03,
    },
    "GREET": {
        "oxytocin":  +0.08,
        "dopamine":  +0.04,
        "serotonin": +0.03,
    },
    "CONVERSE": {
        "oxytocin":  +0.03,
        "dopamine":  +0.02,
    },
}

# ── INTERACTION EVENTS ─────────────────────────────────────────────────────
_EVENT_TRIGGERS: Dict[str, Dict[str, float]] = {
    "response_matched": {
        "dopamine":  +0.06,
        "serotonin": +0.04,
    },
    "response_unknown": {
        "cortisol":  +0.04,
        "dopamine":  -0.03,
    },
    "high_frequency": {
        "cortisol":  +0.05,
        "adrenaline":+0.03,
    },
    "long_absence": {
        "dopamine":  +0.08,
        "oxytocin":  +0.05,
    },
    "session_start": {
        "dopamine":  +0.05,
        "serotonin": +0.03,
    },
}

# Cross-language equivalence table
# Nhóm các từ đồng nghĩa đa ngôn ngữ để SemanticLearner kế thừa
CROSS_LANG_GROUPS = [
    ["mệt", "kiệt sức", "tired", "exhausted", "疲れ", "疲れた"],
    ["buồn", "sad", "悲しい", "sorrow"],
    ["vui", "happy", "嬉しい", "楽しい"],
    ["tức", "angry", "怒り", "frustrated"],
    ["sợ", "scared", "怖い", "afraid"],
    ["yêu", "love", "愛"],
    ["cảm ơn", "thank you", "ありがとう"],
    ["lo lắng", "worried", "不安", "anxious"],
    ["bất ngờ", "surprised", "びっくり", "shocked"],
    ["đau", "hurt", "つらい", "pain"],
    ["nhớ", "miss", "恋しい"],
    ["tuyệt vời", "amazing", "すごい", "wonderful"],
]


class TextTriggers:
    """
    Phân tích text → hormone changes (v2.0).
    Stateless: không lưu gì, chỉ tính toán.
    """

    def __init__(self):
        self._compiled = [
            (re.compile(pattern, re.IGNORECASE | re.UNICODE), changes)
            for pattern, changes in _KEYWORD_TRIGGERS.items()
        ]

    def from_text(self, text: str) -> Dict[str, float]:
        """Phân tích text → dict hormone changes."""
        if not text:
            return {}

        text_lower = text.lower()
        combined: Dict[str, float] = {}

        for pattern, changes in self._compiled:
            if pattern.search(text_lower):
                for hormone, delta in changes.items():
                    combined[hormone] = combined.get(hormone, 0) + delta

        # Scale down nếu quá nhiều triggers
        if combined:
            n_triggers = sum(1 for p, _ in self._compiled if p.search(text_lower))
            if n_triggers > 3:
                scale = 3 / n_triggers
                combined = {k: v * scale for k, v in combined.items()}

        return combined

    def from_intent(self, intent_type: str) -> Dict[str, float]:
        """Intent type → hormone changes."""
        return _INTENT_TRIGGERS.get(intent_type, {}).copy()

    def from_event(self, event_name: str) -> Dict[str, float]:
        """Special event → hormone changes."""
        return _EVENT_TRIGGERS.get(event_name, {}).copy()

    def analyze(
        self,
        text: str,
        intent_type: str = "CONVERSE",
        event: str = None,
    ) -> Tuple[Dict[str, float], str]:
        """
        Phân tích đầy đủ → (combined_changes, dominant_trigger).
        """
        text_changes   = self.from_text(text)
        intent_changes = self.from_intent(intent_type)
        event_changes  = self.from_event(event) if event else {}

        combined: Dict[str, float] = {}
        for changes, weight in [
            (text_changes,   1.0),
            (intent_changes, 0.7),
            (event_changes,  0.5),
        ]:
            for hormone, delta in changes.items():
                combined[hormone] = combined.get(hormone, 0) + delta * weight

        if text_changes:
            dominant = "keyword"
        elif intent_changes:
            dominant = f"intent:{intent_type}"
        elif event_changes:
            dominant = f"event:{event}"
        else:
            dominant = "none"

        return combined, dominant

    def get_cross_lang_group(self, word: str) -> list:
        """
        Trả về nhóm cross-language của một từ.
        Dùng để SemanticLearner biết 'mệt' ↔ 'tired' ↔ '疲れ' là một nhóm.
        """
        word_lower = word.lower()
        for group in CROSS_LANG_GROUPS:
            if word_lower in [g.lower() for g in group]:
                return group
        return []