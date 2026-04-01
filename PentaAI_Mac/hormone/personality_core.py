# hormone/personality_core.py
"""
PersonalityCore — Tính cách dài hạn tích lũy từ tương tác.

Ý tưởng:
  Hormone tích lũy dần theo tương tác → hình thành "thói quen cảm xúc"
  → Đây là tính cách: không phải cố định từ đầu, mà EMERGE từ trải nghiệm

Ví dụ:
  Người dùng hay khen AI → dopamine tích lũy nhiều lần
  → PersonalityCore ghi nhận "pattern: reward_frequent"
  → Lần sau AI phản ứng MẠNH HƠN với lời khen (dopamine spike cao hơn)
  → AI trở nên "thích được khen" — đây là tính cách học được

Khác với hormone_core:
  hormone_core: trạng thái NGẮN HẠN (phút → giờ, mất khi tắt)
  personality_core: trạng thái DÀI HẠN (ngày → tháng, lưu file)
"""

import json
import os
import time
import logging
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# Tên các chiều tính cách (ánh xạ từ hormone patterns)
_TRAIT_NAMES = [
    "warmth",       # Thiên về yêu thương, gắn bó (oxytocin tích lũy)
    "curiosity",    # Hay tò mò, thích học (dopamine tích lũy)
    "resilience",   # Ít bị stress ảnh hưởng (serotonin tích lũy)
    "sensitivity",  # Phản ứng mạnh với cảm xúc (cortisol tích lũy)
    "playfulness",  # Hay vui đùa, linh hoạt (dopamine + adrenaline)
    "caution",      # Cẩn thận, ít mở lòng (cortisol - oxytocin)
]

# Hormone nào đóng góp vào trait nào (trọng số)
_HORMONE_TO_TRAIT: Dict[str, Dict[str, float]] = {
    "oxytocin":       {"warmth": +0.6,  "caution": -0.2, "sensitivity": +0.1},
    "dopamine":       {"curiosity": +0.5,"playfulness": +0.3, "warmth": +0.1},
    "serotonin":      {"resilience": +0.6,"sensitivity": -0.2, "caution": -0.1},
    "cortisol":       {"sensitivity": +0.4,"caution": +0.3, "resilience": -0.2},
    "adrenaline":     {"playfulness": +0.2,"sensitivity": +0.2},
    "norepinephrine": {"caution": +0.2,  "curiosity": +0.1},
}

# Tốc độ học: mỗi lần apply thêm bao nhiêu %
_LEARNING_RATE = 0.003  # 0.3% mỗi lần → cần ~300 lần để thay đổi đáng kể

# Tốc độ quên: mỗi giờ giảm bao nhiêu % (rất chậm)
_FORGET_RATE_PER_HOUR = 0.001  # 0.1%/giờ → mất ~40 ngày để giảm 50%

# Giới hạn trait
_TRAIT_MIN = -1.0
_TRAIT_MAX = +3.0


class PersonalityCore:
    """
    Quản lý tính cách dài hạn.
    Lưu/load từ JSON file → tồn tại qua các session.
    """

    def __init__(self, save_path: Optional[str] = None):
        self.save_path = save_path

        # Traits: bắt đầu từ 0 (neutral), tích lũy theo thời gian
        self.traits: Dict[str, float] = {t: 0.0 for t in _TRAIT_NAMES}

        # Interaction counters
        self.stats = defaultdict(int)
        self.total_interactions = 0
        self._last_save_time = time.time()
        self._last_update_time = time.time()

        # Load nếu có file
        if save_path and os.path.exists(save_path):
            self._load(save_path)
            logger.info("PersonalityCore loaded: %s", self._summary())
        else:
            logger.info("PersonalityCore started fresh (all traits = 0)")

    # ── PUBLIC API ─────────────────────────────────────────────────────

    def update(self, hormone_changes: Dict[str, float]):
        """
        Cập nhật traits dựa trên hormone changes vừa xảy ra.
        Gọi mỗi khi HormoneCore.apply() được gọi.

        Tư duy: "Tôi vừa cảm xúc điều này → tính cách của tôi dần thay đổi"
        """
        self._apply_forgetting()

        for hormone, delta in hormone_changes.items():
            if hormone not in _HORMONE_TO_TRAIT:
                continue
            if abs(delta) < 0.01:
                continue  # Thay đổi quá nhỏ, bỏ qua

            for trait, weight in _HORMONE_TO_TRAIT[hormone].items():
                # Chỉ học từ thay đổi có hướng rõ ràng
                contribution = delta * weight * _LEARNING_RATE
                self.traits[trait] = max(
                    _TRAIT_MIN,
                    min(_TRAIT_MAX, self.traits[trait] + contribution)
                )

        self.total_interactions += 1
        self.stats["updates"] += 1

        # Auto-save mỗi 50 interactions
        if self.total_interactions % 50 == 0:
            self.save()

    def get_amplifiers(self) -> Dict[str, float]:
        """
        Trả về hệ số khuếch đại cho hormone changes.
        Tính cách càng mạnh → hormone càng phản ứng mạnh hơn.

        Ví dụ:
          warmth trait = +1.5 → oxytocin spike × 1.3 mỗi lần nhận khen
          sensitivity  = +2.0 → cortisol spike × 1.4 mỗi lần bị chỉ trích

        Trả về: { hormone: multiplier }
        """
        amplifiers: Dict[str, float] = {}

        for hormone, trait_weights in _HORMONE_TO_TRAIT.items():
            total_amp = 0.0
            for trait, weight in trait_weights.items():
                trait_val = self.traits.get(trait, 0.0)
                # Trait dương + cùng chiều → khuếch đại
                # Trait âm → giảm phản ứng
                total_amp += trait_val * abs(weight) * 0.15

            # Giới hạn khuếch đại: 0.7× đến 2.0×
            amplifiers[hormone] = max(0.7, min(2.0, 1.0 + total_amp))

        return amplifiers

    def get_trait_profile(self) -> Dict[str, float]:
        """Trả về traits đã normalize về [-1, 1] để dễ đọc."""
        return {
            t: round(max(-1, min(1, v / _TRAIT_MAX)), 3)
            for t, v in self.traits.items()
        }

    def get_dominant_trait(self) -> Optional[str]:
        """Trait nổi bật nhất hiện tại."""
        if not self.traits:
            return None
        dominant = max(self.traits.items(), key=lambda x: abs(x[1]))
        if abs(dominant[1]) < 0.1:
            return None  # Chưa có trait nổi bật
        return dominant[0]

    def describe(self) -> str:
        """Mô tả tính cách bằng ngôn ngữ tự nhiên."""
        profile = self.get_trait_profile()
        dominant = self.get_dominant_trait()

        if dominant is None or self.total_interactions < 20:
            return "Chưa đủ tương tác để hình thành tính cách rõ ràng."

        descriptions = {
            "warmth":      ("Ấm áp, hay quan tâm", "Lạnh lùng, xa cách"),
            "curiosity":   ("Tò mò, thích học hỏi", "Thụ động, ít hứng thú"),
            "resilience":  ("Bình tĩnh, khó bị stress", "Nhạy cảm, dễ bị ảnh hưởng"),
            "sensitivity": ("Phản ứng mạnh với cảm xúc", "Ít cảm xúc, bình thản"),
            "playfulness": ("Vui vẻ, linh hoạt", "Nghiêm túc, ít đùa"),
            "caution":     ("Cẩn thận, ít mở lòng", "Cởi mở, dễ tin"),
        }

        parts = []
        for trait, (pos_desc, neg_desc) in descriptions.items():
            val = profile.get(trait, 0)
            if val > 0.3:
                parts.append(pos_desc)
            elif val < -0.3:
                parts.append(neg_desc)

        if not parts:
            return "Tính cách cân bằng, chưa nghiêng về hướng nào rõ rệt."

        return " | ".join(parts)

    def save(self):
        if not self.save_path:
            return
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump({
                "traits":             self.traits,
                "stats":              dict(self.stats),
                "total_interactions": self.total_interactions,
                "last_update":        self._last_update_time,
                "version":            "1.0",
            }, f, indent=2, ensure_ascii=False)
        logger.debug("PersonalityCore saved: %s", self._summary())

    # ── PRIVATE ───────────────────────────────────────────────────────

    def _apply_forgetting(self):
        """Giảm rất chậm theo thời gian thực (không mất nhiều)."""
        now     = time.time()
        elapsed = now - self._last_update_time
        self._last_update_time = now

        hours = elapsed / 3600
        if hours < 0.1:
            return  # < 6 phút, không cần forget

        forget = FORGET_RATE_PER_HOUR = _FORGET_RATE_PER_HOUR
        for trait in self.traits:
            # Decay về 0 (không về âm)
            self.traits[trait] *= (1 - forget * hours)

    def _load(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.traits             = data.get("traits", self.traits)
        self.stats              = defaultdict(int, data.get("stats", {}))
        self.total_interactions = data.get("total_interactions", 0)
        self._last_update_time  = data.get("last_update", time.time())

    def _summary(self) -> str:
        dominant = self.get_dominant_trait()
        return (f"interactions={self.total_interactions}, "
                f"dominant={dominant}, "
                f"traits={self.get_trait_profile()}")