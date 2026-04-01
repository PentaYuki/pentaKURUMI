from typing import Optional, List, Dict, Any, Union
import os

"""
PentaAI — Controller trung tâm.
Tích hợp đầy đủ 4 tầng + PatternExtractor + SlotResolver + LLM Fallback (Redis/Faiss).
"""

from core.input_parser       import InputParser
from core.user_profile       import UserProfile
from core.time_awareness     import TimeAwareness
from hormone.emotion_bridge  import EmotionBridge
from core.intent_detector    import IntentDetector
from memory.knowledge_store  import KnowledgeStore
from engine.phrase_engine    import PhraseEngine
from engine.synonym_manager  import SynonymManager
from engine.response_builder import ResponseBuilder
from engine.pattern_extractor  import PatternExtractor, Pattern
from engine.slot_resolver      import SlotResolver
from engine.session_context    import SessionContext
from engine.yes_no_responder   import YesNoResponder
from engine.choice_responder   import ChoiceResponder

# --- TÍCH HỢP BỘ NHỚ LLM (REDIS + FAISS) ---
try:
    from penta_memory import PentaMemory
    llm_memory = PentaMemory()
except ImportError:
    import logging
    logging.warning("⚠️ Không tìm thấy penta_memory.py, AI sẽ không có trí nhớ LLM.")
    llm_memory = None
# -------------------------------------------

class PentaAI:
    def __init__(self):
        self.parser    = InputParser()
        self.detector  = IntentDetector()
        self.store     = KnowledgeStore()
        self.phrase_engine = PhraseEngine()
        self.syn       = SynonymManager(store=self.store)
        self.builder   = ResponseBuilder(self.syn)
        self.extractor = PatternExtractor()
        self.resolver  = SlotResolver()

        # Rebuild index từ data đã lưu
        existing = self.store.get_all_phrases()
        if existing:
            self.phrase_engine.rebuild_index(existing)

        # Load patterns đã lưu → chuyển lại thành Pattern objects
        self._patterns: List[Pattern] = self._load_patterns()

        # Time awareness + reminders
        self.time = TimeAwareness(
            save_path=os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'data', 'reminders.json'
            )
        )

        # User profile
        self.profile  = UserProfile(
            save_path=os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'data', 'user_profile.json'
            )
        )

        # Session context + yes/no responder
        self.context  = SessionContext()
        self.yesno    = YesNoResponder()
        self.choice   = ChoiceResponder()

        # Hormone system v2.0 (graceful: nếu lỗi thì bỏ qua)
        try:
            self.emotion = EmotionBridge(
                personality='curious',
                data_dir=os.path.join(os.path.dirname(__file__), 'data'),
                temperament_preset='curious',   # Tính khí mặc định
            )
        except Exception as e:
            import logging
            logging.warning('EmotionBridge init failed: %s', e)
            self.emotion = None

        # Gắn embedder SAU khi emotion đã được tạo
        if self.emotion:
            try:
                self.emotion.attach_embedder(
                    embedder=self.phrase_engine._embedder,
                    synonym_manager=self.syn,
                )
            except Exception:
                pass

    # ── PUBLIC ────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        if not user_input or not user_input.strip():
            return ""
        parsed = self.parser.parse(user_input)
        intent = self.detector.detect(parsed)
        self.context.push("user", parsed.clean, parsed.language)

        # Kiểm tra nhắc nhở đến hạn
        due = self.time.check_due_reminders()
        if due:
            if self.emotion:
                for r in due:
                    try:
                        self.emotion.apply_reminder_fired(r, minutes_late=0)
                    except Exception:
                        pass
            reminder_msgs = [self.time.format_reminder_message(r, parsed.language)
                             for r in due]
            return " | ".join(reminder_msgs)

        # Kiểm tra câu hỏi / lệnh thời gian
        time_resp = self._handle_time(parsed.clean, parsed.language)
        if time_resp:
            return time_resp

        # Đọc hormone state TRƯỚC khi tạo response
        h_modifiers: Dict[str, Any] = {}
        if self.emotion:
            try:
                h_modifiers = self.emotion.before_response(
                    parsed.clean, intent.type, parsed.language
                )
            except Exception:
                pass

        response = self._route(intent, parsed, h_modifiers)

        # Cập nhật hormone SAU khi tạo response (non-blocking)
        if self.emotion:
            try:
                self.emotion.after_response(
                    parsed.clean,
                    intent.type,
                    response_matched=(response != self.builder.build_unknown(parsed.language))
                )
            except Exception:
                pass
            # Feedback loop: tự điều chỉnh lại hormone sau mỗi response
            try:
                self.emotion.apply_feedback_loop()
            except Exception:
                pass

        # Personalize response nếu có tên người dùng
        response = self.profile.personalize(response)
        self.context.push("ai", response, parsed.language)
        return response

    def get_stats(self) -> dict:
        return self.store.stats()

    def get_hormone_status(self) -> dict:
        """Trả về trạng thái hormone hiện tại để API endpoint sử dụng."""
        if self.emotion:
            try:
                return self.emotion.get_status()
            except Exception:
                pass
        return {"hormone_state": "unavailable"}

    # ── ROUTING ───────────────────────────────────────────────────

    def _route(self, intent, parsed, h_modifiers: Optional[Dict] = None) -> str:
        if h_modifiers is None:
            h_modifiers = {}
        lang = parsed.language

        if intent.type == "GREET":
            phrases = self.store.get_all_phrases()
            for entry in phrases:
                if parsed.clean == entry["trigger"]:
                    self.store.increment_use(entry["trigger"])
                    from engine.phrase_engine import MatchResult
                    exact = MatchResult(
                        trigger=entry["trigger"],
                        responses=entry["responses"],
                        score=1.0, matched_by="exact",
                    )
                    return self.builder.build_phrase_response(exact, {}, lang)
            return self.builder.build_greeting(parsed.clean, lang)

        if intent.type == "TEACH_PHRASE":
            return self._handle_teach_phrase(intent, lang)

        if intent.type == "TEACH_SYNONYM":
            w1 = intent.slots["word1"]
            w2 = intent.slots["word2"]
            self.store.add_synonym(w1, w2)
            self.store.flush()
            return self.builder.build_synonym_ack(w1, w2, lang)

        if intent.type == "TEACH_FACT":
            if self._is_known_trigger(parsed.clean):
                return self._handle_converse(parsed.clean, lang, h_modifiers)
            return self._handle_teach_fact(intent, lang)

        if intent.type == "ASK_DEFINITION":
            if self._is_known_trigger(parsed.clean):
                return self._handle_converse(parsed.clean, lang, h_modifiers)
            return self._handle_ask(intent, lang)

        if intent.type == "CONVERSE":
            return self._handle_converse(parsed.clean, lang, h_modifiers)

        return self.builder.build_unknown(lang)

    # ── HANDLERS ─────────────────────────────────────────────────

    def _handle_time(self, text: str, lang: str) -> Optional[str]:
        user_name = self.profile.name or self.profile.pronoun
        t_lower = text.lower()
        _remind_kw = ['nhắc ', 'nhắc anh', 'nhắc em', 'nhắc mình', 'nhắc tôi',
                      'remind me', 'remind us', 'reminder', 'リマインド',
                      'every monday', 'every tuesday', 'every wednesday',
                      'every thursday', 'every friday', 'every saturday', 'every sunday',
                      'mỗi thứ', 'mỗi ngày']
        if any(kw in t_lower for kw in _remind_kw):
            reminder = self.time.parse_remind_command(text, lang)
            if not reminder and lang != 'en':
                reminder = self.time.parse_remind_command(text, 'en')
            if reminder:
                self.time.add_reminder(reminder)
                time_str = reminder.get('time', '')
                msg      = reminder.get('message', '')
                repeat   = reminder.get('repeat', False)
                if lang == 'vi':
                    ack = (f"Được rồi! {'Mỗi tuần mình' if repeat else 'Mình'} "
                           f"sẽ nhắc {user_name} '{msg}'"
                           f"{' lúc ' + time_str if time_str else ''} nhé.")
                elif lang == 'en':
                    ack = (f"Got it! {'Every week I' if repeat else 'I'}'ll "
                           f"remind you to '{msg}'"
                           f"{' at ' + time_str if time_str else ''}.")
                else:
                    ack = f"わかりました！'{msg}'をリマインドします。"
                return ack

        if self.time.is_time_query(text, lang):
            return self.time.format_time_response(text, lang, user_name)

        return None

    def _handle_teach_phrase(self, intent, lang: str) -> str:
        trigger  = intent.slots["trigger"]
        response = intent.slots["response"]

        is_new = self.store.add_phrase(trigger, response)
        self.store.flush()
        self.phrase_engine.rebuild_index(self.store.get_all_phrases())

        self._try_generalize(trigger, response, lang)

        if lang == "jp":
            summary     = f"「{trigger}」→「{response}」"
            summary_dup = f"「{trigger}」に別の返答を追加：「{response}」"
        elif lang == "en":
            summary     = f"hear '{trigger}' → say '{response}'"
            summary_dup = f"added another reply for '{trigger}': '{response}'"
        else:
            summary     = f"nghe '{trigger}' → nói '{response}'"
            summary_dup = f"thêm cách trả lời cho '{trigger}': '{response}'"

        return self.builder.build_teach_ack(summary_dup if not is_new else summary, lang)

    def _handle_teach_fact(self, intent, lang: str) -> str:
        subject   = intent.slots["subject"]
        predicate = intent.slots["predicate"]
        relation  = self._infer_relation(subject, predicate)
        self.store.add_fact(subject, predicate, relation, lang)
        self.store.flush()

        rel_label = self._relation_label(relation, lang)
        summary_fmt = {
            "vi": f"'{subject}' {rel_label} {predicate}",
            "en": f"'{subject}' {rel_label} {predicate}",
            "jp": f"「{subject}」{rel_label}「{predicate}」",
        }
        summary = summary_fmt.get(lang, summary_fmt["vi"])
        return self.builder.build_teach_ack(summary, lang)

    def _handle_ask(self, intent, lang: str) -> str:
        target = intent.slots["target"]
        facts  = self.store.get_facts(target)
        if facts:
            return self.builder.build_fact_answer(target, facts, lang)

        for syn in self.syn.get_synonyms(target):
            facts = self.store.get_facts(syn)
            if facts:
                return self.builder.build_fact_answer(syn, facts, lang)

        return self.builder.build_unknown(lang)

    def _handle_converse(self, text: str, lang: str, h_modifiers: Optional[Dict] = None) -> str:
        if h_modifiers is None:
            h_modifiers = {}
            
        phrases = self.store.get_all_phrases()
        backend = getattr(self.phrase_engine._embedder, 'backend', 'tfidf')
        THRESHOLD_HIGH = 0.78 if backend == 'sbert' else 0.90
        THRESHOLD_LOW  = 0.62 if backend == 'sbert' else 999

        # Bước 0: Choice question (A hay B?)
        choice_resp = self.choice.generate_response(text, lang, self.context, h_modifiers)
        if choice_resp:
            return self.builder.apply_hormone_tone(choice_resp, h_modifiers)

        # Bước 1: Exact phrase match
        for entry in phrases:
            if text.lower().strip() == entry["trigger"]:
                self.store.increment_use(entry["trigger"])
                from engine.phrase_engine import MatchResult
                exact = MatchResult(
                    trigger=entry["trigger"],
                    responses=entry["responses"],
                    score=1.0,
                    matched_by="exact",
                )
                resp = self.builder.build_phrase_response(exact, {}, lang)
                return self.builder.apply_hormone_tone(resp, h_modifiers)

        # Bước 2: Yes/No handler
        yesno = self.yesno.generate_response(text, lang, self.context, h_modifiers)
        if yesno:
            return self.builder.apply_hormone_tone(yesno, h_modifiers)

        # Bước 3: Phrase match rõ ràng (ngưỡng cao)
        match = self.phrase_engine.find_best_match(text, phrases)
        if match and (match.matched_by == "exact" or match.score >= THRESHOLD_HIGH):
            if match.score < 0.95 and self._state_word_differs(text, match.trigger, lang):
                emotional = self._try_emotional_inference(text, lang)
                if emotional:
                    return emotional
            self.store.increment_use(match.trigger)
            resp = self.builder.build_phrase_response(match, match.slots, lang)
            return self.builder.apply_hormone_tone(resp, h_modifiers)

        # Bước 4: Pattern match
        pattern_result = self._match_pattern(text, lang)
        if pattern_result:
            return pattern_result

        # Bước 5: Emotional inference
        emotional = self._try_emotional_inference(text, lang)
        if emotional:
            return emotional

        # Bước 6: Phrase match mờ — CHỈ KHI SBERT (tfidf = tắt)
        if match and match.score >= THRESHOLD_LOW:
            self.store.increment_use(match.trigger)
            resp = self.builder.build_phrase_response(match, match.slots, lang)
            return self.builder.apply_hormone_tone(resp, h_modifiers)

        # =========================================================
        # Bước 8: Thà nói không biết còn hơn bịa
        return self.builder.build_unknown(lang)

    # ── PATTERN LOGIC ─────────────────────────────────────────────

    def _try_generalize(self, trigger: str, response: str, lang: str):
        all_phrases = self.store.get_all_phrases()
        lang_phrases = [p for p in all_phrases if p.get("lang") == lang]

        if len(lang_phrases) < 2:
            return

        groups = self._group_similar_phrases(lang_phrases)

        for group in groups:
            if len(group) < 2:
                continue

            pairs = [(p["trigger"], p["responses"][0]) for p in group
                     if p.get("responses")]

            pattern = self.extractor.generalize_from_pairs(pairs, lang)
            if pattern and pattern.confidence >= 0.5:
                pattern_dict = self._pattern_to_dict(pattern)
                is_new = self.store.save_pattern(pattern_dict)
                if is_new:
                    self._patterns.append(pattern)
                    self.store.flush()

    def _group_similar_phrases(self, phrases: list) -> list:
        groups = []
        used   = set()

        for i, p1 in enumerate(phrases):
            if i in used:
                continue
            group = [p1]
            t1    = set(p1["trigger_tokens"])

            for j, p2 in enumerate(phrases):
                if j <= i or j in used:
                    continue
                t2      = set(p2["trigger_tokens"])
                overlap = len(t1 & t2) / max(len(t1 | t2), 1)
                if overlap >= 0.4:
                    group.append(p2)
                    used.add(j)

            if len(group) >= 2:
                used.add(i)
                groups.append(group)

        return groups

    def _match_pattern(self, text: str, lang: str) -> Optional[str]:
        lang_patterns = [p for p in self._patterns if p.lang == lang]
        if not lang_patterns:
            return None

        result = self.extractor.find_matching_pattern(text, lang_patterns)
        if result is None:
            return None

        pattern, slot_map = result

        response_template = self._get_response_template_for_pattern(pattern)
        if not response_template:
            for slot_name, slot_value in slot_map.items():
                if slot_name in ("state", "adj_state"):
                    return self.resolver.infer_emotional_response(slot_value, lang)
            return None

        slot_categories = {s.name: s.category for s in pattern.slots}
        response = self.resolver.resolve(
            slot_map=slot_map,
            response_template=response_template,
            slot_categories=slot_categories,
            lang=lang,
            store=self.store,
            syn=self.syn,
        )

        for slot_name, slot_value in slot_map.items():
            if slot_name in ("state", "adj_state"):
                followup = self.resolver.get_slot_follow_up(slot_value, lang)
                if followup and __import__('random').random() < 0.4:
                    response = f"{response} {followup}"
                break

        return response

    def _get_response_template_for_pattern(self, pattern: Pattern) -> Optional[str]:
        all_phrases = self.store.get_all_phrases()

        for phrase in all_phrases:
            trigger = phrase["trigger"]
            result  = self.extractor.find_matching_pattern(
                trigger, [pattern]
            )
            if result and phrase.get("responses"):
                raw_response = phrase["responses"][0]
                r_template, _ = self.extractor.extract_slots_from_single(
                    raw_response, pattern.lang
                )
                return r_template

        return None

    def _is_known_trigger(self, text: str) -> bool:
        phrases = self.store.get_all_phrases()
        if not phrases:
            return False

        text_clean = text.lower().strip()

        for entry in phrases:
            if text_clean == entry["trigger"]:
                return True

        match = self.phrase_engine.find_best_match(text_clean, phrases)
        if match and match.score >= 0.78:
            return True

        return False

    def _state_word_differs(self, query: str, trigger: str, lang: str) -> bool:
        state_words = self.extractor._SLOT_CATEGORIES.get("adj_state", {}).get(lang, set())
        q_states = set(query.lower().split()) & state_words
        t_states = set(trigger.lower().split()) & state_words
        return bool(q_states) and q_states != t_states

    def _try_emotional_inference(self, text: str, lang: str) -> Optional[str]:
        tokens = text.lower().split()
        state_map = self.extractor._SLOT_CATEGORIES.get("adj_state", {})
        state_words = state_map.get(lang, set())

        for token in tokens:
            if token in state_words:
                return self.resolver.infer_emotional_response(token, lang)

        return None

    # ── HELPERS ───────────────────────────────────────────────────

    def _infer_relation(self, subject: str, predicate: str) -> str:
        pred  = predicate.lower()
        words = set(pred.split())

        state_words = {
            'mệt','buồn','vui','ốm','đói','khát','no','nóng','lạnh',
            'tired','sad','happy','sick','hungry','cold','hot',
        }
        prop_words = {
            'to','nhỏ','lớn','bé','cao','thấp','đẹp','xấu',
            'big','small','tall','short','beautiful','ugly',
        }

        if words & state_words: return "has_state"
        if words & prop_words:  return "has_property"
        if 'của' in pred:       return "belongs_to"
        if any(m in pred for m in ['ở ','tại ','trong ']):
            return "located_at"
        if any(m in pred for m in ['bằng ','làm từ ']):
            return "made_of"
        if any(m in pred for m in ['để ','dùng để ']):
            return "used_for"
        return "is_a"

    def _relation_label(self, relation: str, lang: str) -> str:
        labels = {
            "vi": {
                "is_a":       "là loại",
                "has_property":"có đặc tính",
                "has_state":  "đang ở trạng thái",
                "belongs_to": "thuộc về",
                "located_at": "nằm ở",
                "made_of":    "làm từ",
                "used_for":   "dùng để",
            },
            "en": {
                "is_a":       "is a type of",
                "has_property":"has property",
                "has_state":  "is currently",
                "belongs_to": "belongs to",
                "located_at": "is located at",
                "made_of":    "is made of",
                "used_for":   "is used for",
            },
            "jp": {
                "is_a":       "は一種の",
                "has_property":"は〜という特性があります",
                "has_state":  "は〜の状態です",
                "belongs_to": "は〜に属します",
                "located_at": "は〜にあります",
                "made_of":    "は〜でできています",
                "used_for":   "は〜に使われます",
            },
        }
        return labels.get(lang, labels["vi"]).get(relation, "は")

    def _pattern_to_dict(self, pattern: Pattern) -> dict:
        return {
            "template":      pattern.template,
            "slots":         [
                {"name": s.name, "position": s.position,
                 "examples": s.examples, "category": s.category}
                for s in pattern.slots
            ],
            "source_pairs":  pattern.source_pairs,
            "lang":          pattern.lang,
            "confidence":    pattern.confidence,
            "trigger_fixed": pattern.trigger_fixed,
        }

    def _load_patterns(self) -> list:
        from engine.pattern_extractor import SlotInfo
        result   = []
        raw_list = self.store.get_all_patterns()
        for d in raw_list:
            slots = [
                SlotInfo(
                    name=s["name"], position=s["position"],
                    examples=s["examples"], category=s["category"]
                )
                for s in d.get("slots", [])
            ]
            result.append(Pattern(
                template=d["template"],
                slots=slots,
                source_pairs=d.get("source_pairs", 1),
                lang=d.get("lang", "vi"),
                confidence=d.get("confidence", 0.5),
                trigger_fixed=d.get("trigger_fixed", []),
            ))
        return result
