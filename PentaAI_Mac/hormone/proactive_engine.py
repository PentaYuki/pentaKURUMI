# hormone/proactive_engine.py
"""
ProactiveEngine — AI tự bộc lộ cảm xúc mà không cần chờ lệnh.

Khi hormone vượt ngưỡng nhất định và thỏa cooldown → AI tự inject
một câu nói nhỏ vào response (không override, chỉ THÊM VÀO).

Ví dụ:
  cortisol=0.65, adrenaline=0.40 → AI tự thêm "(Em hơi lo lắng...)"
  oxytocin=0.80, dopamine=0.70   → "(Em thích nói chuyện với anh!)"

Tính năng:
  - Cooldown linh hoạt theo trạng thái (vui → nói nhiều hơn lo)
  - Không spam: mỗi N câu mới nói 1 lần
  - Hỗ trợ đầy đủ VI / EN / JP
  - Trả về "" nếu chưa đủ điều kiện
"""

import time
import random
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Ngưỡng hormone để tự bộc lộ ───────────────────────────────────────────
_PROACTIVE_THRESHOLDS: Dict[str, Dict[str, float]] = {
    # Trạng thái → {hormone: min_level}
    "excited_warm": {
        "oxytocin": 0.68,
        "dopamine": 0.65,
    },
    "anxious": {
        "cortisol":  0.58,
        "adrenaline":0.38,
    },
    "stressed": {
        "cortisol":  0.52,
        "serotonin": 0.44,   # serotonin thấp
    },
    "tired": {
        "GABA":     0.60,
        "dopamine": 0.50,    # dopamine thấp
    },
    "curious_energetic": {
        "dopamine":       0.68,
        "norepinephrine": 0.30,
    },
    "content_loving": {
        "oxytocin":  0.68,
        "serotonin": 0.60,
    },
    "surprised_alert": {
        "adrenaline": 0.38,
    },
}

# ── Templates câu bộc lộ (thêm đầy đủ 3 ngôn ngữ) ──────────────────────────
_TEMPLATES: Dict[str, Dict[str, list]] = {
    "vi": {
        "excited_warm": [
            "(Em đang rất vui khi nói chuyện!)",
            "(Hôm nay em vui lắm nha!)",
            "(Nói chuyện như thế này em thấy ấm áp ghê~)",
            "(Em thích mình trò chuyện như vậy lắm!)",
            "",  # "" = không nói
        ],
        "anxious": [
            "(Em hơi lo lắng một chút...)",
            "(Em thấy hồi hộp nên...)",
            "(Có gì đó khiến em không an tâm.)",
            "",  "", "",
        ],
        "stressed": [
            "(Em hơi căng thẳng rồi...)",
            "(Hôm nay có nhiều việc quá, em hơi mệt mỏi.)",
            "(Em đang không được ổn lắm.)",
            "", "",
        ],
        "tired": [
            "(Em hơi mệt rồi...)",
            "(Khuya rồi đó, em bắt đầu uể oải.)",
            "(Em muốn nghỉ ngơi một chút.)",
            "", "",
        ],
        "curious_energetic": [
            "(Ồ, câu hỏi này thú vị ghê!)",
            "(Em tò mò lắm~)",
            "(Cho em suy nghĩ thêm nhé!)",
            "",
        ],
        "content_loving": [
            "(Em cảm thấy bình yên khi nói chuyện.)",
            "(Em hài lòng lắm nha.)",
            "",
        ],
        "surprised_alert": [
            "(Ồ em không ngờ!)",
            "(Bất ngờ quá!)",
            "(Thật sao, em chưa nghĩ đến điều đó!)",
            "",
        ],
    },
    "en": {
        "excited_warm": [
            "(I'm really enjoying our chat!)",
            "(Today feels so great!)",
            "(Talking with you makes me happy~)",
            "",
        ],
        "anxious": [
            "(I'm feeling a bit anxious right now...)",
            "(Something is making me uneasy.)",
            "", "", "",
        ],
        "stressed": [
            "(I'm a bit stressed at the moment.)",
            "(It's been a tough day.)",
            "", "",
        ],
        "tired": [
            "(I'm getting a bit tired, it's getting late.)",
            "(Feeling a bit drained.)",
            "", "",
        ],
        "curious_energetic": [
            "(Oh, this is interesting!)",
            "(I'm curious about this~)",
            "",
        ],
        "content_loving": [
            "(I feel at peace right now.)",
            "(I'm quite content.)",
            "",
        ],
        "surprised_alert": [
            "(Oh, I didn't expect that!)",
            "(That's surprising!)",
            "",
        ],
    },
    "jp": {
        "excited_warm": [
            "(今、とても楽しいです！)",
            "(嬉しいな～)",
            "(話しかけてくれて嬉しいです！)",
            "",
        ],
        "anxious": [
            "(少し不安です...)",
            "(心配なことがあります。)",
            "", "", "",
        ],
        "stressed": [
            "(ちょっとストレスを感じています。)",
            "(今日はなかなか大変でした。)",
            "", "",
        ],
        "tired": [
            "(少し疲れました... もう遅いですね。)",
            "(眠くなってきました。)",
            "", "",
        ],
        "curious_energetic": [
            "(おっ、面白い！)",
            "(気になりますね～)",
            "",
        ],
        "content_loving": [
            "(穏やかな気持ちです。)",
            "(満足しています。)",
            "",
        ],
        "surprised_alert": [
            "(えっ、意外でした！)",
            "(びっくりしました！)",
            "",
        ],
    },
}

# Cooldown (giây) theo trạng thái
_COOLDOWN_BY_STATE: Dict[str, float] = {
    "excited_warm":      4,   # Vui → hay nói
    "curious_energetic": 5,
    "content_loving":    8,
    "surprised_alert":   3,
    "tired":            15,   # Mệt → ít nói hơn
    "stressed":         12,
    "anxious":          10,
    "default":           7,
}


class ProactiveEngine:
    """
    Quản lý việc bộc lộ cảm xúc chủ động theo hormone state.
    """

    def __init__(
        self,
        min_interactions_before_proactive: int = 3,
    ):
        self._last_proactive_time   = 0.0
        self._interaction_count     = 0
        self._min_before_proactive  = min_interactions_before_proactive

        logger.info("ProactiveEngine ready (min_interactions=%d)", min_interactions_before_proactive)

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def tick(self):
        """Gọi mỗi khi có interaction mới."""
        self._interaction_count += 1

    def get_proactive_text(
        self,
        hormone_levels: Dict[str, float],
        emotional_state: str,
        lang: str = "vi",
    ) -> str:
        """
        Trả về câu bộc lộ cảm xúc nếu đủ điều kiện, ngược lại trả về "".

        Điều kiện:
          1. Đã qua cooldown
          2. Đủ số lần tương tác tối thiểu
          3. Hormone vượt ngưỡng
          4. May mắn (random factor, dựa vào state)
        """
        # Chưa đủ tương tác
        if self._interaction_count < self._min_before_proactive:
            return ""

        # Cooldown check
        cooldown = _COOLDOWN_BY_STATE.get(emotional_state, _COOLDOWN_BY_STATE["default"])
        elapsed  = time.time() - self._last_proactive_time
        if elapsed < cooldown:
            return ""

        # Tìm state phù hợp với hormone hiện tại
        matched_state = self._match_state(hormone_levels, emotional_state)
        if not matched_state:
            return ""

        # Chọn template
        lang_templates = _TEMPLATES.get(lang, _TEMPLATES["vi"])
        pool = lang_templates.get(matched_state, [""])
        text = random.choice(pool)

        if text:
            self._last_proactive_time = time.time()
            logger.debug(
                "ProactiveEngine: state=%s lang=%s → '%s'",
                matched_state, lang, text
            )

        return text

    def get_proactive_question(
        self,
        hormone_levels: Dict[str, float],
        emotional_state: str,
        lang: str = "vi",
    ) -> str:
        """
        Trả về câu hỏi chủ động khi dopamine cao (AI muốn khám phá thêm).
        Tách riêng để dễ kiểm soát.
        """
        D   = hormone_levels.get("dopamine", 0.5)
        OXT = hormone_levels.get("oxytocin", 0.5)

        if D < 0.65 or OXT < 0.55:
            return ""

        elapsed = time.time() - self._last_proactive_time
        if elapsed < 10:
            return ""

        questions = {
            "vi": [
                "Mình thấy ổn chứ?",
                "Hôm nay có gì vui không?",
                "Anh/chị đang làm gì vậy?",
                "",
            ],
            "en": [
                "How are you feeling today?",
                "Is there anything fun happening?",
                "",
            ],
            "jp": [
                "今日はどうですか？",
                "何か面白いことありましたか？",
                "",
            ],
        }

        pool = questions.get(lang, questions["vi"])
        text = random.choice(pool)
        if text:
            self._last_proactive_time = time.time()
        return text

    def reset(self):
        """Reset state (dùng khi đổi session)."""
        self._last_proactive_time  = 0.0
        self._interaction_count    = 0

    # ── PRIVATE ────────────────────────────────────────────────────────────

    def _match_state(
        self,
        hormone_levels: Dict[str, float],
        current_emotional_state: str,
    ) -> Optional[str]:
        """
        Tìm proactive state phù hợp với hormone levels hiện tại.
        Ưu tiên match với current_emotional_state trước.
        """
        # Thử match với state hiện tại trước
        if current_emotional_state in _PROACTIVE_THRESHOLDS:
            thresholds = _PROACTIVE_THRESHOLDS[current_emotional_state]
            if self._check_thresholds(hormone_levels, thresholds, current_emotional_state):
                return current_emotional_state

        # Thử các state khác
        for state, thresholds in _PROACTIVE_THRESHOLDS.items():
            if state == current_emotional_state:
                continue
            if self._check_thresholds(hormone_levels, thresholds, state):
                return state

        return None

    def _check_thresholds(
        self,
        hormone_levels: Dict[str, float],
        thresholds: Dict[str, float],
        state: str,
    ) -> bool:
        """Kiểm tra hormone có vượt ngưỡng không."""
        for hormone, threshold in thresholds.items():
            level = hormone_levels.get(hormone, 0.0)
            # Cho trạng thái mệt/stress, ngưỡng là DƯỚI (serotonin thấp)
            if state in ("stressed",) and hormone == "serotonin":
                if level > threshold:   # Serotonin quá cao → không stressed
                    return False
            elif state in ("tired",) and hormone == "dopamine":
                if level > threshold:   # Dopamine quá cao → không tired
                    return False
            else:
                if level < threshold:
                    return False
        return True
