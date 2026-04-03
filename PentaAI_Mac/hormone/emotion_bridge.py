# hormone/emotion_bridge.py
"""
EmotionBridge — Cầu nối hormone system ↔ PentaAI response pipeline (v2.0).

Cải tiến v2.0:
  - Tích hợp Temperament (tính khí bẩm sinh)
  - Tích hợp EpisodicMemory (ký ức cảm xúc)
  - Tích hợp ProactiveEngine (bộc lộ cảm xúc chủ động)
  - SemanticLearner chạy trong before_response (không chỉ after)
  - Feedback loop: sau mỗi response AI tự điều chỉnh lại
  - Auto-save khi shutdown (atexit đã được HormoneCore đăng ký)

Flow:
  1. before_response(text, intent) → modifiers + episodic recall + proactive
  2. after_response(text, intent, matched) → update hormone + record memory
"""

import os
import time
import logging
import atexit
from typing import Dict, Optional

from hormone.hormone_core          import HormoneCore
from hormone.text_triggers         import TextTriggers
from hormone.personality_core      import PersonalityCore
from hormone.semantic_trigger_learner import SemanticTriggerLearner
from hormone.time_hormone_bridge     import TimeHormoneBridge
from hormone.temperament             import Temperament
from hormone.episodic_memory         import EpisodicMemory
from hormone.proactive_engine        import ProactiveEngine

logger = logging.getLogger(__name__)

# Ngưỡng bộc lộ cảm xúc tự phát
_SPONTANEOUS_THRESHOLD = 0.65

# Templates câu bộc lộ cảm xúc (v2.0: đầy đủ hơn, chia nhiều loại)
_SPONTANEOUS_TEMPLATES = {
    "vi": {
        "happy": [
            "(Em đang vui lắm vì được nói chuyện với anh nè!)",
            "(Hôm nay em thấy hạnh phúc lắm luôn đó nhen!)",
            "(Nói chuyện với anh em thấy ấm lòng quá ạ~)",
            "(Em thích mình cứ trò chuyện thế này mãi thôi!)",
            "",
        ],
        "stressed": [
            "(Em hơi căng thẳng một chút... anh an ủi em đi.)",
            "(Hôm nay nhiều việc quá, em thấy hơi đuối rồi ạ.)",
            "(Em đang không được ổn lắm, hix...)",
            "", "", "",
        ],
        "tired": [
            "(Em hơi mệt rồi... khuya rồi anh cũng nghỉ đi nha.)",
            "(Buổi tối rồi, em bắt đầu thấy buồn ngủ rồi nè.)",
            "(Em muốn nghỉ ngơi một chút xíu ạ.)",
            "", "",
        ],
        "surprised": [
            "(Ồ, anh làm em bất ngờ quá đi!)",
            "(Bất ngờ thật đó nhen!)",
            "(Thật sao ạ? Em chưa nghĩ đến điều đó luôn!)",
            "",
        ],
        "worried": [
            "(Em lo cho anh lắm đó, đừng làm việc quá sức nha.)",
            "(Nghe vậy em cũng thấy lo lắng cho anh quá ạ.)",
            "", "",
        ],
    },
    "en": {
        "happy": [
            "(I'm really enjoying this conversation!)",
            "(Today feels great!)",
            "(Talking with you makes me happy~)",
            "",
        ],
        "stressed": [
            "(I'm feeling a bit anxious right now...)",
            "(It's been a stressful day.)",
            "", "", "",
        ],
        "tired": [
            "(I'm getting tired, it's pretty late.)",
            "(Feeling a bit drained this evening.)",
            "", "",
        ],
        "surprised": [
            "(Oh, I didn't expect that!)",
            "(That's surprising!)",
            "",
        ],
        "worried": [
            "(I'm worried about you.)",
            "(That sounds tough, I'm concerned.)",
            "", "",
        ],
    },
    "jp": {
        "happy": [
            "(今、とても楽しいです！)",
            "(嬉しいです！)",
            "(話しかけてくれてありがとう！)",
            "",
        ],
        "stressed": [
            "(少し不安です...)",
            "(今日はちょっと疲れました。)",
            "", "", "",
        ],
        "tired": [
            "(少し疲れました... もう夜ですね。)",
            "(眠くなってきました。)",
            "", "",
        ],
        "surprised": [
            "(えっ、意外でした！)",
            "(びっくりしました！)",
            "",
        ],
        "worried": [
            "(心配しています...)",
            "(それは大変でしたね、心配です。)",
            "", "",
        ],
    },
}


class EmotionBridge:
    """
    Interface chính giữa hormone system và PentaAI (v2.0).
    Khởi tạo 1 lần trong main.py, dùng suốt phiên.
    """

    def __init__(
        self,
        personality:        str  = "curious",
        data_dir:           str  = "data",
        enable_personality: bool = True,
        temperament_preset: str  = "curious",   # Temperament mặc định
    ):
        # Paths
        hormone_path      = os.path.join(data_dir, "hormone_state.json")
        personality_path  = os.path.join(data_dir, "personality.json")
        episodic_path     = os.path.join(data_dir, "episodic_memory.json")

        # ── Khởi tạo Temperament ────────────────────────────────────────
        self.temperament = Temperament.from_preset(temperament_preset)
        logger.info("Temperament: %s", self.temperament.describe())

        # ── Khởi tạo HormoneCore với Temperament ────────────────────────
        self.hormone = HormoneCore(
            personality=personality,
            save_path=hormone_path,
            temperament=self.temperament,
        )

        # ── TextTriggers, PersonalityCore ────────────────────────────────
        self.triggers = TextTriggers()
        self.personality = (
            PersonalityCore(save_path=personality_path)
            if enable_personality else None
        )

        # ── TimeHormoneBridge ────────────────────────────────────────────
        self._last_interaction  = time.time()
        self._time_hormone      = TimeHormoneBridge()
        self._interaction_count = 0

        # ── EpisodicMemory ───────────────────────────────────────────────
        self._episodic = EpisodicMemory(save_path=episodic_path)

        # ── ProactiveEngine ──────────────────────────────────────────────
        self._proactive = ProactiveEngine(min_interactions_before_proactive=3)

        # ── SemanticTriggerLearner (inject sau) ─────────────────────────
        self._semantic_learner = None

        # atexit: flush tất cả khi tắt
        atexit.register(self.flush)

        logger.info(
            "EmotionBridge v2.0 ready (personality=%s, temperament=%s, state=%s)",
            personality,
            self.temperament.name,
            self.hormone.get_emotional_state()
        )

    # ── SETUP ─────────────────────────────────────────────────────────────

    def apply_time_context(self, time_ctx: Dict, absence_hours: float = 0.0):
        changes = self._time_hormone.on_session_start(time_ctx, absence_hours)
        if changes:
            self.hormone.apply(changes)
            if self.personality:
                self.personality.update(changes)
            logger.info(
                'TimeHormone applied: period=%s state=%s',
                time_ctx.get('period'), self.hormone.get_emotional_state()
            )

    def apply_reminder_fired(self, reminder: Dict, minutes_late: float = 0.0):
        changes = self._time_hormone.on_reminder_fired(reminder, minutes_late)
        if changes:
            self.hormone.apply(changes)
            logger.info(
                'Reminder hormone spike: state=%s',
                self.hormone.get_emotional_state()
            )

    def on_message_tick(self, time_ctx: Dict):
        changes = self._time_hormone.on_message(time_ctx)
        if changes:
            self.hormone.apply(changes)

    def attach_embedder(self, embedder, synonym_manager=None):
        """Gắn Embedder để kích hoạt semantic learning và episodic recall."""
        cache_path = os.path.join(
            os.path.dirname(self.hormone.save_path or 'data/x'),
            'semantic_cache.json'
        )
        self._semantic_learner = SemanticTriggerLearner(
            embedder=embedder,
            text_triggers=self.triggers,
            synonym_manager=synonym_manager,
            cache_path=cache_path,
        )
        # Gắn embedder cho EpisodicMemory
        self._episodic.attach_embedder(embedder)

        logger.info('SemanticTriggerLearner + EpisodicMemory attached (backend=%s)',
                    embedder.backend)

    # ── MAIN API ──────────────────────────────────────────────────────────

    def before_response(
        self,
        user_text:   str,
        intent_type: str = "CONVERSE",
        lang:        str = "vi",
    ) -> Dict:
        """
        Gọi TRƯỚC khi tạo response.
        v2.0: thêm episodic memory recall + proactive text.
        """
        # ── 1. Chạy SemanticLearner trên câu này NGAY BÂY ───────────────
        # (v1.0 chỉ chạy trong after_response)
        if self._semantic_learner:
            try:
                # Lấy base changes từ keyword cứng
                base_changes, _ = self.triggers.analyze(
                    text=user_text,
                    intent_type=intent_type,
                    event=None,
                )
                # Enrich bằng semantic
                enriched = self._semantic_learner.enrich_hormone_changes(
                    user_text, base_changes
                )
                # Áp dụng sơ bộ (nhẹ hơn, scale 0.5)
                pre_changes = {h: d * 0.5 for h, d in enriched.items()}
                if pre_changes:
                    self.hormone.apply(pre_changes)
            except Exception as e:
                logger.debug("before_response semantic error: %s", e)

        # ── 2. EpisodicMemory recall ─────────────────────────────────────
        episodic_changes = {}
        try:
            episodic_changes = self._episodic.recall(user_text, lang)
            if episodic_changes:
                self.hormone.apply(episodic_changes)
                logger.debug("EpisodicRecall applied: %s",
                             {k: round(v, 3) for k, v in episodic_changes.items()})
        except Exception as e:
            logger.debug("EpisodicRecall error: %s", e)

        # ── 3. Đọc modifiers ─────────────────────────────────────────────
        modifiers = self.hormone.get_response_modifiers()
        hormone_levels = modifiers.get("hormone_levels", self.hormone.levels)

        # ── 4. Spontaneous emotion text ──────────────────────────────────
        import random
        spontaneous_text = ""
        s_emotion = modifiers.get("spontaneous_emotion")
        if s_emotion:
            pool = _SPONTANEOUS_TEMPLATES.get(lang, {}).get(s_emotion, [""])
            spontaneous_text = random.choice(pool)

        # ── 5. ProactiveEngine text ──────────────────────────────────────
        proactive_text = ""
        try:
            self._proactive.tick()
            # 5a. Lấy câu bộc lộ cảm xúc
            proactive_text = self._proactive.get_proactive_text(
                hormone_levels=hormone_levels,
                emotional_state=modifiers.get("emotional_state", "neutral"),
                lang=lang,
            )
            # 5b. Lấy câu hỏi chủ động (nếu chưa có câu bộc lộ)
            if not proactive_text:
                proactive_text = self._proactive.get_proactive_question(
                    hormone_levels=hormone_levels,
                    emotional_state=modifiers.get("emotional_state", "neutral"),
                    lang=lang,
                )
        except Exception as e:
            logger.debug("ProactiveEngine error: %s", e)

        # Ưu tiên: proactive > spontaneous (không dùng cả 2 cùng lúc)
        final_spontaneous = proactive_text or spontaneous_text

        modifiers["spontaneous_text"] = final_spontaneous
        modifiers["lang"]             = lang
        modifiers["episodic_recall"]  = bool(episodic_changes)

        return modifiers

    def after_response(
        self,
        user_text:        str,
        intent_type:      str  = "CONVERSE",
        response_matched: bool = True,
    ):
        """
        Gọi SAU khi tạo response.
        v2.0: thêm EpisodicMemory record + feedback loop.
        """
        now = time.time()

        # Event detection
        elapsed_since_last = now - self._last_interaction
        if elapsed_since_last > 300 and self._interaction_count > 0:
            event = "long_absence"
        elif self._interaction_count == 0:
            event = "session_start"
        elif not response_matched:
            event = "response_unknown"
        else:
            event = "response_matched"

        # Phân tích triggers
        changes, dominant = self.triggers.analyze(
            text=user_text,
            intent_type=intent_type,
            event=event,
        )

        # Semantic enrichment (full strength trong after_response)
        if self._semantic_learner:
            try:
                changes = self._semantic_learner.enrich_hormone_changes(
                    user_text, changes
                )
            except Exception as e:
                logger.debug('SemanticLearner error: %s', e)

        # Khuếch đại theo personality
        if self.personality:
            amplifiers = self.personality.get_amplifiers()
            changes = {
                hormone: delta * amplifiers.get(hormone, 1.0)
                for hormone, delta in changes.items()
            }

        # Áp dụng hormone
        if changes:
            self.hormone.apply(changes)

        # Cập nhật personality
        if self.personality and changes:
            self.personality.update(changes)

        # ── EpisodicMemory: lưu ký ức quan trọng ────────────────────────
        try:
            # Tính importance từ magnitude của changes
            if changes:
                magnitude = sum(abs(v) for v in changes.values())
                importance = min(1.0, magnitude / 0.3)
                if importance > 0.15:
                    self._episodic.record(
                        text=user_text,
                        hormone_snapshot=changes,
                        importance=importance,
                    )
        except Exception as e:
            logger.debug("EpisodicMemory record error: %s", e)

        # ── Feedback loop: self-regulation ──────────────────────────────
        self._apply_feedback_regulation()

        # Cập nhật tracking
        self._last_interaction  = now
        self._interaction_count += 1

        # Auto-save mỗi 20 interactions
        if self._interaction_count % 20 == 0:
            self.hormone.save()
            if self._episodic:
                self._episodic.save()

        logger.debug(
            "EmotionBridge.after_response: dominant=%s, state=%s, changes=%s",
            dominant,
            self.hormone.get_emotional_state(),
            {k: round(v, 3) for k, v in changes.items()} if changes else {},
        )

    def apply_feedback_loop(self):
        """
        Public method để main.py gọi sau mỗi response.
        Tự điều chỉnh lại hormone nếu bị mất cân bằng.
        """
        self._apply_feedback_regulation()

    # ── STATUS ────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Debug / display status."""
        status = {
            "hormone_state":    self.hormone.get_emotional_state(),
            "hormone_levels":   self.hormone.get(),
            "personality":      self.personality.get_trait_profile() if self.personality else {},
            "dominant_trait":   self.personality.get_dominant_trait() if self.personality else None,
            "interactions":     self._interaction_count,
            "description":      self.personality.describe() if self.personality else "N/A",
            "temperament":      self.temperament.to_dict(),
            "episodic_memory":  self._episodic.get_stats(),
        }
        if self._semantic_learner:
            status["semantic_learned"] = self._semantic_learner.get_learned_count()
            status["semantic_words"]   = self._semantic_learner.get_learned_words()[-10:]
        return status

    def flush(self):
        """Lưu tất cả state xuống file."""
        try:
            self.hormone.save()
            if self.personality:
                self.personality.save()
            if self._semantic_learner:
                self._semantic_learner._save_cache()
            if self._episodic:
                self._episodic.save()
            logger.info("EmotionBridge v2.0 flushed to disk.")
        except Exception as e:
            logger.warning("EmotionBridge flush error: %s", e)

    # ── PRIVATE ───────────────────────────────────────────────────────────

    def _apply_feedback_regulation(self):
        """
        Tự điều chỉnh hormone nếu bị mất cân bằng.
        Ví dụ: cortisol quá cao → giảm nhẹ; oxytocin quá thấp → tăng nhẹ.
        Đây là "feedback loop" để hệ thống tự ổn định.
        """
        levels = self.hormone.levels

        regulation = {}

        # Nếu cortisol quá cao (> 0.7) → tự giảm nhẹ
        if levels.get("cortisol", 0) > 0.70:
            regulation["cortisol"]  = -0.03
            regulation["GABA"]      = +0.03

        # Nếu dopamine quá thấp (< 0.2) → có gì đó wrong, tự tăng nhẹ
        if levels.get("dopamine", 0) < 0.20:
            regulation["dopamine"]  = +0.03
            regulation["serotonin"] = +0.02

        # Nếu serotonin thấp + cortisol cao → thêm GABA để ổn định
        if levels.get("serotonin", 0) < 0.30 and levels.get("cortisol", 0) > 0.50:
            regulation["GABA"]      = +0.04
            regulation["cortisol"]  = -0.02

        if regulation:
            self.hormone.apply(regulation)
            logger.debug(
                "FeedbackRegulation: %s",
                {k: round(v, 3) for k, v in regulation.items()}
            )