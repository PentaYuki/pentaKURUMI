# hormone/time_hormone_bridge.py
"""
TimeHormoneBridge — Kết nối thời gian thực → hormone.

Ý tưởng cốt lõi:
  Con người không chỉ cảm xúc do lời nói — thời gian trong ngày,
  ngày trong tuần, và các sự kiện lịch đều ảnh hưởng hormone tự nhiên.

  Ví dụ:
    Buổi tối → cortisol tăng (lo lắng chưa xong việc)
    Thứ Hai sáng → stress đầu tuần
    Thứ Sáu tối → nhẹ nhõm, serotonin lên
    Nhắc nhở kích hoạt → adrenaline spike ("ồ quên!")
    Người dùng quay lại sau 3 ngày → oxytocin tăng (vui được gặp lại)

Không chạy liên tục — chỉ được gọi khi:
  1. Bắt đầu session (apply time-of-day effect)
  2. Nhắc nhở kích hoạt (apply reminder spike)
  3. Mỗi N tin nhắn (apply slow drift)

Latency: ~0.1ms — không ảnh hưởng gì.
"""

import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── TIME-OF-DAY → HORMONE EFFECTS ────────────────────────────────────
# Áp dụng 1 lần khi bắt đầu session, và drift chậm trong phiên.

_TIME_OF_DAY_EFFECTS: Dict[str, Dict[str, float]] = {
    "early_morning": {   # 5-7h: tỉnh táo, cortisol buổi sáng cao
        "norepinephrine": +0.08,
        "cortisol":       +0.06,
        "dopamine":       +0.04,
    },
    "morning": {         # 7-12h: năng lượng cao, tốt nhất trong ngày
        "dopamine":       +0.06,
        "norepinephrine": +0.04,
        "serotonin":      +0.03,
        "cortisol":       -0.02,  # cortisol bắt đầu giảm
    },
    "noon": {            # 12-13h: hơi đói, mệt nhẹ
        "dopamine":       -0.04,
        "serotonin":      -0.02,
        "cortisol":       +0.03,  # cần ăn, hơi lo
    },
    "afternoon": {       # 13-18h: ổn định, hơi uể oải sau bữa trưa
        "GABA":           +0.03,  # buồn ngủ nhẹ sau ăn
        "dopamine":       -0.02,
    },
    "evening": {         # 18-22h: lo lắng buổi tối tăng
        "cortisol":       +0.08,  # lo lắng chưa xong việc
        "serotonin":      -0.04,  # giảm khi trời tối
        "GABA":           +0.04,  # cơ thể bắt đầu muốn nghỉ
        "dopamine":       -0.03,
    },
    "night": {           # 22-5h: mệt mỏi, cortisol khuya
        "cortisol":       +0.12,  # lo lắng khuya mạnh nhất
        "serotonin":      -0.08,  # serotonin thấp nhất đêm
        "dopamine":       -0.06,
        "GABA":           +0.08,  # cơ thể muốn ngủ mạnh
        "norepinephrine": -0.04,  # phản xạ chậm hơn
    },
}

# ── WEEKDAY EFFECTS ───────────────────────────────────────────────────
# Ảnh hưởng đặc biệt theo ngày trong tuần.

_WEEKDAY_EFFECTS: Dict[int, Dict[str, float]] = {
    0: {   # Thứ Hai — stress đầu tuần
        "cortisol":       +0.10,
        "norepinephrine": +0.06,
        "dopamine":       -0.04,
        "oxytocin":       -0.03,  # chưa kịp ấm lên sau cuối tuần
    },
    4: {   # Thứ Sáu — nhẹ nhõm cuối tuần gần
        "serotonin":  +0.08,
        "dopamine":   +0.06,
        "cortisol":   -0.05,
        "oxytocin":   +0.04,
    },
    5: {   # Thứ Bảy — cuối tuần thư giãn
        "serotonin":  +0.10,
        "oxytocin":   +0.08,
        "cortisol":   -0.08,
        "GABA":       +0.06,
        "dopamine":   +0.05,
    },
    6: {   # Chủ Nhật — thư giãn nhưng hơi lo ngày mai
        "serotonin":  +0.06,
        "oxytocin":   +0.06,
        "cortisol":   +0.03,   # "monday blues" bắt đầu
        "GABA":       +0.04,
    },
}

# ── EVENT EFFECTS ─────────────────────────────────────────────────────
# Sự kiện đặc biệt → spike hormone tức thì.

_EVENT_EFFECTS: Dict[str, Dict[str, float]] = {

    "reminder_fired": {         # Nhắc nhở kích hoạt → "ồ quên!"
        "cortisol":       +0.12,
        "adrenaline":     +0.10,
        "norepinephrine": +0.08,
        "dopamine":       +0.05,  # "tốt là được nhắc"
    },

    "reminder_urgent": {        # Nhắc nhở trễ (đã qua giờ > 30 phút)
        "cortisol":       +0.18,
        "adrenaline":     +0.15,
        "norepinephrine": +0.10,
        "serotonin":      -0.06,
    },

    "long_absence_return": {    # Người dùng quay lại sau > 6 tiếng
        "oxytocin":       +0.14,
        "dopamine":       +0.10,
        "serotonin":      +0.06,
        "cortisol":       -0.05,  # nhẹ nhõm gặp lại
    },

    "first_chat_of_day": {      # Tin nhắn đầu tiên trong ngày
        "dopamine":       +0.08,
        "oxytocin":       +0.06,
        "norepinephrine": +0.04,
    },

    "session_end_approaching": {  # Người dùng có vẻ sắp rời (bye, tạm biệt)
        "oxytocin":       -0.06,  # nhẹ buồn khi chia tay
        "serotonin":      +0.03,  # nhưng vẫn ổn
    },
}

# ── SLOW DRIFT ────────────────────────────────────────────────────────
# Mỗi N tin nhắn, hormone drift nhẹ theo hướng time-of-day.
# Mô phỏng sự thay đổi từ từ trong phiên dài.

_DRIFT_INTERVAL = 5      # Drift sau mỗi 5 tin nhắn
_DRIFT_SCALE    = 0.3    # 30% của time-of-day effect


class TimeHormoneBridge:
    """
    Quản lý ảnh hưởng thời gian lên hormone.
    Stateless về hormone — chỉ tính toán changes, không lưu state.
    State được quản lý bởi HormoneCore.
    """

    def __init__(self):
        self._last_period:   str   = ""
        self._last_weekday:  int   = -1
        self._message_count: int   = 0
        self._session_start: float = time.time()

        logger.info("TimeHormoneBridge initialized")

    # ── PUBLIC API ────────────────────────────────────────────────────

    def on_session_start(
        self,
        ctx:          Dict,
        absence_hours: float = 0.0,
    ) -> Dict[str, float]:
        """
        Gọi khi bắt đầu session mới.
        Trả về combined hormone changes.

        ctx: output của TimeAwareness.get_time_context()
        absence_hours: số giờ kể từ lần cuối nói chuyện
        """
        changes: Dict[str, float] = {}

        period  = ctx.get("period",      "morning")
        weekday = ctx.get("weekday_idx", 0)

        # 1. Time-of-day effect
        tod_changes = _TIME_OF_DAY_EFFECTS.get(period, {})
        _merge(changes, tod_changes, scale=1.0)

        # 2. Weekday effect
        wd_changes = _WEEKDAY_EFFECTS.get(weekday, {})
        _merge(changes, wd_changes, scale=0.7)  # Nhẹ hơn TOD

        # 3. Long absence effect
        if absence_hours >= 6:
            event = "long_absence_return"
            _merge(changes, _EVENT_EFFECTS[event], scale=1.0)
            logger.info(
                "TimeHormone: long absence %.1fh → %s",
                absence_hours, event
            )
        elif absence_hours >= 1:
            # Vắng ngắn hơn → effect nhẹ hơn
            _merge(changes, _EVENT_EFFECTS["long_absence_return"], scale=0.4)

        # 4. First chat of day
        if absence_hours >= 8:
            _merge(changes, _EVENT_EFFECTS["first_chat_of_day"], scale=1.0)

        self._last_period  = period
        self._last_weekday = weekday
        self._session_start = time.time()

        logger.debug(
            "TimeHormone session_start: period=%s weekday=%d → %s",
            period, weekday,
            {k: round(v, 3) for k, v in changes.items()}
        )
        return changes

    def on_reminder_fired(
        self,
        reminder:     Dict,
        minutes_late: float = 0.0,
    ) -> Dict[str, float]:
        """
        Gọi khi nhắc nhở kích hoạt.
        minutes_late: số phút trễ so với giờ đặt.
        """
        if minutes_late > 30:
            event   = "reminder_urgent"
            scale   = min(1.5, 1.0 + minutes_late / 60)
        else:
            event   = "reminder_fired"
            scale   = 1.0

        changes = dict(_EVENT_EFFECTS[event])
        # Scale
        changes = {k: v * scale for k, v in changes.items()}

        logger.info(
            "TimeHormone reminder_fired: event=%s minutes_late=%.1f → %s",
            event, minutes_late,
            {k: round(v, 3) for k, v in changes.items()}
        )
        return changes

    def on_message(self, ctx: Dict) -> Dict[str, float]:
        """
        Gọi sau mỗi tin nhắn.
        Áp dụng slow drift định kỳ.
        """
        self._message_count += 1

        # Drift mỗi N tin nhắn
        if self._message_count % _DRIFT_INTERVAL != 0:
            return {}

        period  = ctx.get("period", "morning")
        tod     = _TIME_OF_DAY_EFFECTS.get(period, {})
        changes = {k: v * _DRIFT_SCALE for k, v in tod.items()}

        # Chỉ drift theo hướng tăng (không giảm hormone qua drift)
        changes = {k: v for k, v in changes.items() if v > 0}

        if changes:
            logger.debug(
                "TimeHormone drift (msg=%d): %s",
                self._message_count,
                {k: round(v, 3) for k, v in changes.items()}
            )

        return changes

    def on_period_change(
        self, new_period: str, new_ctx: Dict
    ) -> Dict[str, float]:
        """
        Gọi khi buổi trong ngày thay đổi (sáng → chiều → tối).
        Áp dụng transition effect.
        """
        if new_period == self._last_period:
            return {}

        old_effects = _TIME_OF_DAY_EFFECTS.get(self._last_period, {})
        new_effects = _TIME_OF_DAY_EFFECTS.get(new_period, {})

        # Delta: chênh lệch giữa hai buổi
        changes: Dict[str, float] = {}
        all_hormones = set(old_effects) | set(new_effects)

        for h in all_hormones:
            delta = new_effects.get(h, 0) - old_effects.get(h, 0)
            if abs(delta) > 0.01:
                changes[h] = delta * 0.5  # Chuyển tiếp mượt hơn

        self._last_period = new_period
        logger.info(
            "TimeHormone period_change: %s → %s → %s",
            self._last_period, new_period,
            {k: round(v, 3) for k, v in changes.items()}
        )
        return changes

    def describe_state(
        self, ctx: Dict, lang: str = "vi"
    ) -> Optional[str]:
        """
        Mô tả ngắn trạng thái cảm xúc theo thời gian.
        AI có thể tự nhiên đề cập khi hormone threshold vượt ngưỡng.
        """
        period  = ctx.get("period", "morning")
        weekday = ctx.get("weekday_idx", 0)
        is_mon  = weekday == 0

        descriptions = {
            "vi": {
                "night":         "Em hơi mệt rồi, muộn rồi đó.",
                "early_morning": "Dậy sớm thế, em cũng vừa bắt đầu ngày mới!",
                "evening":       "Buổi tối rồi, anh có xong việc chưa?",
            },
            "en": {
                "night":         "It's getting late, I'm a bit tired.",
                "early_morning": "Early bird! I'm just starting my day too.",
                "evening":       "It's evening already. Did you finish everything?",
            },
            "jp": {
                "night":         "夜遅いですね。少し疲れました。",
                "early_morning": "早起きですね！",
                "evening":       "夕方になりましたね。",
            },
        }

        lang_desc = descriptions.get(lang, descriptions["vi"])
        base = lang_desc.get(period)

        if is_mon and lang == "vi" and period in ("morning", "early_morning"):
            return "Thứ Hai rồi, đầu tuần hơi nặng nhỉ."

        return base


# ── HELPERS ───────────────────────────────────────────────────────────

def _merge(
    target: Dict[str, float],
    source: Dict[str, float],
    scale:  float = 1.0,
):
    """Cộng source × scale vào target in-place."""
    for k, v in source.items():
        if k != "melatonin_proxy":  # Bỏ key giả
            target[k] = target.get(k, 0) + v * scale