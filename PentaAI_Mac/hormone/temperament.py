# hormone/temperament.py
"""
Temperament — Tính khí bẩm sinh, ảnh hưởng đến baseline hormone và mức độ phản ứng.

Dựa trên nghiên cứu về sự khác biệt cá thể trong hệ thần kinh.
Khác với PersonalityCore (học từ trải nghiệm), Temperament là CỐ ĐỊNH từ khi khởi tạo.

Ví dụ thực tế:
  - Temperament "nhạy cảm": cortisol tăng gấp 1.3× khi bị chỉ trích
  - Temperament "mạnh mẽ": cortisol chỉ tăng 0.6× khi stress → bình tĩnh hơn
  - Temperament "hướng ngoại": dopamine tăng 1.4× khi gặp câu vui → hứng thú hơn
"""

import random
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Giới hạn tham số ────────────────────────────────────────────────────────
_PARAM_LIMITS = {
    "dopamine_sensitivity":  (0.3, 1.8),
    "cortisol_reactivity":   (0.2, 1.5),
    "oxytocin_baseline_adj": (0.7, 1.3),
    "gaba_inhibition":       (0.5, 1.5),
}


@dataclass
class Temperament:
    """
    Các tham số cốt lõi ảnh hưởng cách hormone thay đổi.

    dopamine_sensitivity:  (0.3–1.8)  càng cao → phản ứng khen thưởng càng mạnh
    cortisol_reactivity:   (0.2–1.5)  càng cao → stress tác động càng lớn
    oxytocin_baseline_adj: (0.7–1.3)  oxytocin nền cao → gắn bó, ấm áp tự nhiên
    gaba_inhibition:       (0.5–1.5)  càng cao → tự trấn tĩnh nhanh hơn
    """
    dopamine_sensitivity:  float = 1.0
    cortisol_reactivity:   float = 1.0
    oxytocin_baseline_adj: float = 1.0
    gaba_inhibition:       float = 1.0

    # Tên hiển thị
    name: str = "cân bằng"

    # Jitter: xác suất phản ứng ngẫu nhiên (tạo "cá tính")
    jitter_probability: float = 0.05

    def __post_init__(self):
        """Validate và clamp các tham số trong giới hạn."""
        for attr, (lo, hi) in _PARAM_LIMITS.items():
            val = getattr(self, attr)
            clamped = max(lo, min(hi, val))
            if clamped != val:
                logger.warning("Temperament.%s clamped %.2f → %.2f", attr, val, clamped)
                setattr(self, attr, clamped)

    # ── FACTORY METHODS ────────────────────────────────────────────────────

    @classmethod
    def from_preset(cls, preset: str) -> "Temperament":
        """Tạo Temperament từ preset có sẵn."""
        presets = {
            # Trung hòa — phù hợp chatbot thông thường
            "cân bằng": cls(
                dopamine_sensitivity=1.0,
                cortisol_reactivity=1.0,
                oxytocin_baseline_adj=1.0,
                gaba_inhibition=1.0,
                jitter_probability=0.05,
                name="cân bằng",
            ),
            # Phản ứng mạnh với cả tích cực lẫn tiêu cực
            "nhạy cảm": cls(
                dopamine_sensitivity=1.4,
                cortisol_reactivity=1.3,
                oxytocin_baseline_adj=1.2,
                gaba_inhibition=0.8,
                jitter_probability=0.08,
                name="nhạy cảm",
            ),
            # Bình tĩnh, ít bị stress, tự tin
            "mạnh mẽ": cls(
                dopamine_sensitivity=1.3,
                cortisol_reactivity=0.6,
                oxytocin_baseline_adj=0.8,
                gaba_inhibition=1.3,
                jitter_probability=0.03,
                name="mạnh mẽ",
            ),
            # Cần không gian, ít phản ứng xã hội
            "hướng nội": cls(
                dopamine_sensitivity=0.7,
                cortisol_reactivity=1.1,
                oxytocin_baseline_adj=0.9,
                gaba_inhibition=1.2,
                jitter_probability=0.04,
                name="hướng nội",
            ),
            # Hứng thú với kết nối, náo nhiệt, vui vẻ
            "hướng ngoại": cls(
                dopamine_sensitivity=1.4,
                cortisol_reactivity=0.8,
                oxytocin_baseline_adj=1.1,
                gaba_inhibition=0.7,
                jitter_probability=0.07,
                name="hướng ngoại",
            ),
            # Ấm áp, yêu thương, hay quan tâm
            "ấm áp": cls(
                dopamine_sensitivity=1.1,
                cortisol_reactivity=0.9,
                oxytocin_baseline_adj=1.3,
                gaba_inhibition=1.0,
                jitter_probability=0.06,
                name="ấm áp",
            ),
        }
        # Alias tiếng Anh
        _aliases = {
            "balanced":    "cân bằng",
            "sensitive":   "nhạy cảm",
            "resilient":   "mạnh mẽ",
            "introvert":   "hướng nội",
            "extrovert":   "hướng ngoại",
            "warm":        "ấm áp",
            "curious":     "cân bằng",   # curious → balanced by default
        }
        key = _aliases.get(preset, preset)
        result = presets.get(key, presets["cân bằng"])
        logger.info("Temperament preset: %s → %s", preset, result.name)
        return result

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def apply_baseline(self, base_hormones: Dict[str, float]) -> Dict[str, float]:
        """
        Điều chỉnh baseline hormone theo temperament.
        Gọi một lần khi HormoneCore khởi tạo.
        """
        adjusted = base_hormones.copy()

        if "oxytocin" in adjusted:
            adjusted["oxytocin"] = min(1.5, adjusted["oxytocin"] * self.oxytocin_baseline_adj)

        if "GABA" in adjusted:
            adjusted["GABA"] = min(1.5, adjusted["GABA"] * self.gaba_inhibition)

        # Clamp tất cả vào khoảng an toàn
        for k in adjusted:
            adjusted[k] = max(0.0, min(1.5, adjusted[k]))

        return adjusted

    def scale_delta(self, hormone: str, delta: float) -> float:
        """
        Scale delta của hormone theo hệ số sensitivity tương ứng.
        Dùng trong HormoneCore.apply() để khuếch đại/giảm phản ứng.

        Ví dụ:
          cortisol_reactivity=1.3 → cortisol spike × 1.3
          gaba_inhibition=0.8     → GABA phản ứng thấp hơn (dễ bị kích động hơn)
        """
        if hormone in ("dopamine", "serotonin"):
            return delta * self.dopamine_sensitivity
        elif hormone in ("cortisol", "adrenaline", "norepinephrine"):
            return delta * self.cortisol_reactivity
        elif hormone == "oxytocin":
            return delta * self.oxytocin_baseline_adj
        elif hormone == "GABA":
            return delta * self.gaba_inhibition
        else:
            return delta

    def should_jitter(self) -> bool:
        """
        Trả về True nếu lần này AI nên phản ứng khác đi (nhiễu ngẫu nhiên).
        Xác suất = jitter_probability (mặc định 5%).
        """
        return random.random() < self.jitter_probability

    def get_decay_modifier(self) -> float:
        """
        GABA cao → hormone decay về baseline nhanh hơn (tự trấn tĩnh).
        Trả về multiplier cho decay factor (1.0 = bình thường).

        gaba_inhibition=1.5 → decay nhanh hơn 20%
        gaba_inhibition=0.5 → decay chậm hơn 15% (cảm xúc kéo dài hơn)
        """
        return 0.85 + (self.gaba_inhibition - 0.5) * 0.2  # range 0.85–1.05

    def describe(self) -> str:
        """Mô tả tính khí bằng tiếng Việt."""
        parts = []
        if self.dopamine_sensitivity > 1.2:
            parts.append("phản ứng mạnh với niềm vui")
        elif self.dopamine_sensitivity < 0.8:
            parts.append("ít hứng thú hơn bình thường")

        if self.cortisol_reactivity > 1.2:
            parts.append("nhạy cảm với stress")
        elif self.cortisol_reactivity < 0.8:
            parts.append("bình tĩnh trước áp lực")

        if self.oxytocin_baseline_adj > 1.1:
            parts.append("gắn bó, ấm áp tự nhiên")

        if self.gaba_inhibition > 1.2:
            parts.append("tự trấn tĩnh nhanh")
        elif self.gaba_inhibition < 0.8:
            parts.append("cảm xúc kéo dài lâu")

        return f"[{self.name}] " + (", ".join(parts) if parts else "cân bằng")

    def to_dict(self) -> Dict:
        return {
            "name":                  self.name,
            "dopamine_sensitivity":  self.dopamine_sensitivity,
            "cortisol_reactivity":   self.cortisol_reactivity,
            "oxytocin_baseline_adj": self.oxytocin_baseline_adj,
            "gaba_inhibition":       self.gaba_inhibition,
            "jitter_probability":    self.jitter_probability,
        }
