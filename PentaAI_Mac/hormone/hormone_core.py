# hormone/hormone_core.py
"""
HormoneCore — Động lực hormone thuần túy cho chat AI (v2.0).

Cải tiến v2.0:
  - Tích hợp Temperament: scale delta theo tính khí
  - Jitter ngẫu nhiên 5%: giống con người ngẫu nhiên
  - Decay nhanh/chậm phụ thuộc gaba_inhibition của Temperament
  - Auto-save với atexit hook (không mất state khi tắt)
  - Auto-save mỗi 10 interactions (giảm từ 20)

5 hormone chính:
  dopamine    — tò mò, hứng thú, muốn học hỏi
  serotonin   — bình ổn, hài lòng, tự tin
  oxytocin    — gắn bó, tin tưởng, ấm áp
  cortisol    — căng thẳng, cảnh giác, phòng thủ
  adrenaline  — phản ứng nhanh, bất ngờ, kích thích đột ngột

2 hormone điều tiết:
  GABA        — ức chế, làm dịu
  norepinephrine — tập trung, cảnh giác
"""

import time
import json
import os
import atexit
import random
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── BASELINE THEO TÍNH CÁCH ────────────────────────────────────────────
PERSONALITY_BASELINES: Dict[str, Dict[str, float]] = {
    "curious": {
        "dopamine":       0.55,
        "serotonin":      0.60,
        "oxytocin":       0.50,
        "cortisol":       0.20,
        "adrenaline":     0.15,
        "GABA":           0.55,
        "norepinephrine": 0.25,
    },
    "attached": {
        "dopamine":       0.45,
        "serotonin":      0.65,
        "oxytocin":       0.75,
        "cortisol":       0.20,
        "adrenaline":     0.10,
        "GABA":           0.60,
        "norepinephrine": 0.20,
    },
    "sensitive": {
        "dopamine":       0.40,
        "serotonin":      0.35,
        "oxytocin":       0.50,
        "cortisol":       0.35,
        "adrenaline":     0.25,
        "GABA":           0.45,
        "norepinephrine": 0.35,
    },
    "resilient": {
        "dopamine":       0.60,
        "serotonin":      0.70,
        "oxytocin":       0.55,
        "cortisol":       0.20,
        "adrenaline":     0.10,
        "GABA":           0.65,
        "norepinephrine": 0.20,
    },
    "introvert": {
        "dopamine":       0.40,
        "serotonin":      0.60,
        "oxytocin":       0.40,
        "cortisol":       0.25,
        "adrenaline":     0.10,
        "GABA":           0.65,
        "norepinephrine": 0.20,
    },
}

# Decay half-life (giây)
_HALF_LIVES: Dict[str, float] = {
    "dopamine":       120,
    "serotonin":      300,
    "oxytocin":       180,
    "cortisol":       240,
    "adrenaline":      45,
    "GABA":           180,
    "norepinephrine":  90,
}

# Cơ chế đối kháng: (A ↑) → (B ↓)
_ANTAGONISMS: Dict[tuple, float] = {
    ("oxytocin",  "cortisol"):        0.25,
    ("serotonin", "cortisol"):        0.20,
    ("GABA",      "cortisol"):        0.20,
    ("GABA",      "adrenaline"):      0.30,
    ("GABA",      "norepinephrine"):  0.15,
    ("cortisol",  "oxytocin"):        0.20,
    ("cortisol",  "dopamine"):        0.15,
}

_MIN_LEVEL = 0.0
_MAX_LEVEL = 1.5

# Jitter: khi jitter kích hoạt, delta bị scale ngẫu nhiên
_JITTER_SCALE_RANGE = (0.3, 1.8)   # 30%–180% của delta gốc


class HormoneCore:
    """
    Engine hormone tối giản cho text chat (v2.0).
    Tích hợp Temperament để scale phản ứng theo tính khí.
    """

    def __init__(
        self,
        personality: str = "curious",
        save_path: Optional[str] = None,
        temperament=None,           # hormone.temperament.Temperament (optional)
    ):
        self.personality  = personality
        self.save_path    = save_path
        self.temperament  = temperament  # None → không dùng

        # Khởi tạo từ baseline
        baseline = PERSONALITY_BASELINES.get(personality, PERSONALITY_BASELINES["curious"])
        self.levels: Dict[str, float] = baseline.copy()

        # Điều chỉnh baseline theo Temperament nếu có
        if self.temperament:
            self.levels = self.temperament.apply_baseline(self.levels)
            logger.info(
                "HormoneCore: Temperament applied → %s", self.temperament.describe()
            )

        self._last_tick      = time.time()
        self._apply_count    = 0      # Đếm số lần apply (dùng để auto-save)

        # Load state đã lưu nếu có
        if save_path and os.path.exists(save_path):
            self._load(save_path)
            logger.info("HormoneCore loaded from %s (state=%s)",
                        save_path, self.get_emotional_state())
        else:
            logger.info("HormoneCore fresh start (personality=%s)", personality)

        # Đăng ký atexit để save khi Python tắt
        if save_path:
            atexit.register(self._atexit_save)

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def apply(self, changes: Dict[str, float]):
        """
        Áp dụng thay đổi hormone.
        - Scale theo Temperament tính khí
        - Thêm jitter ngẫu nhiên (5% xác suất)
        - Auto-save mỗi 10 lần
        """
        self._decay()

        # Jitter: nếu kích hoạt, random scale tất cả delta
        jitter_active = self.temperament and self.temperament.should_jitter()
        if jitter_active:
            jitter_scale = random.uniform(*_JITTER_SCALE_RANGE)
            logger.debug("HormoneCore: jitter active (scale=%.2f)", jitter_scale)
        else:
            jitter_scale = 1.0

        for hormone, delta in changes.items():
            if hormone not in self.levels:
                continue

            # Scale theo Temperament
            effective_delta = (
                self.temperament.scale_delta(hormone, delta)
                if self.temperament else delta
            )

            # Áp dụng jitter
            effective_delta *= jitter_scale

            # Diminishing returns
            if effective_delta > 0:
                headroom = _MAX_LEVEL - self.levels[hormone]
                effective_delta = effective_delta * (headroom / _MAX_LEVEL)

            old = self.levels[hormone]
            self.levels[hormone] = max(
                _MIN_LEVEL,
                min(_MAX_LEVEL, self.levels[hormone] + effective_delta)
            )
            logger.debug(
                "Hormone %s: %.3f → %.3f (Δ%.3f, jitter=%s)",
                hormone, old, self.levels[hormone], effective_delta, jitter_active
            )

        self._apply_antagonisms()
        self._regulate_gaba()

        # Auto-save mỗi 10 lần apply
        self._apply_count += 1
        if self._apply_count % 10 == 0:
            self.save()

    def tick(self):
        """Gọi định kỳ để decay hormone về baseline."""
        self._decay()

    def get(self) -> Dict[str, float]:
        """Snapshot hormone hiện tại."""
        self._decay()
        return self.levels.copy()

    def get_emotional_state(self) -> str:
        """Chuyển hormone levels → tên trạng thái cảm xúc."""
        lvl  = self.levels
        D    = lvl["dopamine"]
        S    = lvl["serotonin"]
        OXT  = lvl["oxytocin"]
        CORT = lvl["cortisol"]
        ADR  = lvl["adrenaline"]
        GABA = lvl["GABA"]

        # ── CỰC ĐOAN ─────────────────────────────────────
        if CORT > 0.55 and ADR > 0.35:
            return "anxious"
        if CORT > 0.50 and S < 0.45:
            return "stressed"

        # ── TÍCH CỰC ─────────────────────────────────────
        if OXT > 0.65 and D > 0.55:
            return "excited_warm"
        if OXT > 0.65 and S > 0.55:
            return "content_loving"
        if D > 0.65 and CORT < 0.28:
            return "curious_energetic"
        if S > 0.65 and CORT < 0.28:
            return "calm_confident"

        # ── NHẸ TIÊU CỰC ─────────────────────────────────
        if CORT > 0.30 and GABA > 0.55:
            return "tired_uneasy"
        if CORT > 0.28 and S < 0.60:
            return "mildly_stressed"
        if GABA > 0.58 and D < 0.55:
            return "sleepy_calm"
        if D < 0.35 and S < 0.42:
            return "low_energy"

        # ── TRUNG TÍNH ────────────────────────────────────
        if CORT > 0.30 and OXT < 0.45:
            return "guarded"
        if ADR > 0.30:
            return "surprised_alert"
        return "neutral"

    def get_response_modifiers(self) -> Dict:
        """Chuyển hormone → tham số ảnh hưởng câu trả lời."""
        lvl = self.levels
        D    = lvl["dopamine"]
        S    = lvl["serotonin"]
        OXT  = lvl["oxytocin"]
        CORT = lvl["cortisol"]
        ADR  = lvl["adrenaline"]

        warmth = max(0.0, min(1.0, OXT * 0.6 + S * 0.3 - CORT * 0.2))
        verbosity = max(0.1, min(1.0, D * 0.4 + OXT * 0.3 + S * 0.2 - CORT * 0.3))
        positivity = max(0.0, min(1.0, S * 0.4 + D * 0.3 + OXT * 0.2 - CORT * 0.4))
        proactivity = max(0.0, min(1.0, D * 0.5 + OXT * 0.2 - CORT * 0.2))

        if positivity > 0.6:
            choice_bias = "positive"
        elif positivity < 0.4 or CORT > 0.5:
            choice_bias = "avoidant"
        else:
            choice_bias = "neutral"

        yes_bias = (OXT - 0.5) * 0.6 + (D - 0.5) * 0.3 - (CORT - 0.3) * 0.4
        willingness = max(0.1, min(1.0, S * 0.3 + D * 0.3 + OXT * 0.3 - CORT * 0.3))

        # Spontaneous emotion
        spontaneous = None
        state = self.get_emotional_state()
        if state in ("anxious", "stressed"):
            spontaneous = "stressed"
        elif state == "tired_uneasy":
            spontaneous = "tired"
        elif state == "mildly_stressed":
            spontaneous = "stressed"
        elif state == "sleepy_calm":
            spontaneous = "tired"
        elif state in ("excited_warm", "content_loving", "curious_energetic"):
            spontaneous = "happy"
        elif ADR > 0.35:
            spontaneous = "surprised"

        return {
            "warmth":              round(warmth, 3),
            "verbosity":           round(verbosity, 3),
            "positivity":          round(positivity, 3),
            "proactivity":         round(proactivity, 3),
            "choice_bias":         choice_bias,
            "yes_bias":            round(yes_bias, 3),
            "willingness":         round(willingness, 3),
            "spontaneous_emotion": spontaneous,
            "emotional_state":     self.get_emotional_state(),
            # Thêm raw levels cho ProactiveEngine
            "hormone_levels":      self.levels.copy(),
        }

    def save(self):
        """Lưu state xuống file."""
        if not self.save_path:
            return
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump({
                    "levels":      self.levels,
                    "personality": self.personality,
                    "last_tick":   self._last_tick,
                    "apply_count": self._apply_count,
                    "version":     "2.0",
                }, f, indent=2)
        except Exception as e:
            logger.warning("HormoneCore save error: %s", e)

    # ── PRIVATE ───────────────────────────────────────────────────────────

    def _decay(self):
        """Decay hormone về baseline theo thời gian thực."""
        now     = time.time()
        elapsed = now - self._last_tick
        if elapsed < 0.5:
            return
        self._last_tick = now

        baseline = PERSONALITY_BASELINES.get(
            self.personality, PERSONALITY_BASELINES["curious"]
        )

        # Hệ số decay phụ thuộc gaba_inhibition của Temperament
        decay_modifier = (
            self.temperament.get_decay_modifier()
            if self.temperament else 1.0
        )

        for hormone in self.levels:
            half_life    = _HALF_LIVES.get(hormone, 120) / decay_modifier
            decay_factor = 0.5 ** (elapsed / half_life)
            target       = baseline.get(hormone, 0.5)
            diff         = self.levels[hormone] - target
            self.levels[hormone] = target + diff * decay_factor

    def _apply_antagonisms(self):
        """A tăng → B giảm nhẹ."""
        for (h_up, h_down), factor in _ANTAGONISMS.items():
            if h_up in self.levels and h_down in self.levels:
                excess    = max(0, self.levels[h_up] - 0.5)
                reduction = excess * factor * 0.3
                self.levels[h_down] = max(
                    _MIN_LEVEL,
                    self.levels[h_down] - reduction
                )

    def _regulate_gaba(self):
        """GABA tự điều chỉnh khi hệ thống quá kích thích."""
        excitatory = (
            self.levels["dopamine"]       * 0.4 +
            self.levels["adrenaline"]     * 0.4 +
            self.levels["norepinephrine"] * 0.3 +
            self.levels["cortisol"]       * 0.2
        )
        inhibitory = self.levels["GABA"] * 0.8

        if excitatory > inhibitory + 0.2:
            self.levels["GABA"] = min(1.0, self.levels["GABA"] + 0.05)
        elif inhibitory > excitatory + 0.3:
            self.levels["GABA"] = max(0.2, self.levels["GABA"] - 0.03)

    def _load(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.levels       = state.get("levels", self.levels)
            self.personality  = state.get("personality", self.personality)
            self._last_tick   = state.get("last_tick", time.time())
            self._apply_count = state.get("apply_count", 0)
        except Exception as e:
            logger.warning("HormoneCore load error: %s", e)

    def _atexit_save(self):
        """Lưu khi Python tắt (atexit hook)."""
        try:
            self.save()
            logger.info("HormoneCore: atexit save OK (%s)", self.save_path)
        except Exception as e:
            logger.warning("HormoneCore: atexit save failed: %s", e)