# engine/response_builder.py
"""
ResponseBuilder — Tầng 4 (output). [PATCHED]

Thay đổi so với bản gốc:
  1. Pool lớn hơn: 12-16 template thay vì 4-7
  2. Template dùng {topic} và {entity} từ SessionContext
  3. build_unknown() gợi ý cụ thể hơn (hỏi user dạy gì)
  4. build_phrase_response() check uncertain → hỏi lại thay vì trả bừa
  5. build_contextual_unknown() — thay thế cho build_unknown khi có context
  6. Thêm build_clarify() — AI hỏi lại khi match uncertain
  7. apply_hormone_tone() mở rộng: xử lý cả EN, thêm exclamation logic
"""

import re
import random
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from engine.synonym_manager import SynonymManager
from engine.phrase_engine import MatchResult

if TYPE_CHECKING:
    from engine.session_context import SessionContext


class ResponseBuilder:
    def __init__(self, synonym_manager: SynonymManager):
        self.syn = synonym_manager

        # ── GREETING POOLS (mở rộng) ──────────────────────────────
        self._greet_pools: Dict[str, Dict[str, List[str]]] = {
            "vi": {
                "xin chào":   ["Chào bạn! Có gì muốn dạy mình không?",
                                "Xin chào! Mình đang lắng nghe đây.",
                                "Chào! Bạn có khỏe không?",
                                "Ừ chào bạn! Hôm nay bạn thế nào?",
                                "Chào bạn nhé! Bạn cần mình giúp gì không?",
                                "Xin chào! Mình vui được nói chuyện với bạn."],
                "chào":       ["Chào bạn nhé!",
                                "Ừ chào!",
                                "Hi bạn!",
                                "Chào, có gì không?",
                                "Ê chào bạn!",
                                "Chào chào!"],
                "tạm biệt":  ["Tạm biệt! Hẹn gặp lại bạn nhé.",
                                "Tạm biệt! Cảm ơn vì đã trò chuyện.",
                                "Chào bạn nhé! Lần sau ghé chơi.",
                                "Tạm biệt! Chúc bạn ngày vui.",
                                "Bye bạn! Nhớ ghé lại nhé.",
                                "Hẹn gặp lại! Mình sẽ nhớ những gì bạn dạy."],
                "bye":        ["Bye bye!", "Hẹn gặp lại!", "Tạm biệt nhé!",
                                "Bye bạn hiền!"],
                "cảm ơn":    ["Không có gì! Mình học từ bạn mà.",
                                "Ồ không cần cảm ơn đâu!",
                                "Cảm ơn bạn mới đúng! Bạn dạy mình nhiều thứ.",
                                "Vui lòng thôi bạn ơi!",
                                "Hehe, bạn khách khí quá đi!",
                                "Không có gì, mình thấy vui khi giúp được bạn."],
                "xin lỗi":   ["Không sao đâu bạn!",
                                "Ôi, không cần xin lỗi đâu.",
                                "Không sao cả, mình không bận tâm đâu.",
                                "Thôi nào, không có gì đâu bạn!"],
                "không có gì": ["Ừ thì cũng không có gì!",
                                 "Haha, vậy thì thôi nhỉ.",
                                 "Không sao, no problem!",
                                 "Bình thường mà bạn ơi!"],
                "_default":   ["Mình hiểu rồi!",
                                "Ừ bạn ơi!",
                                "Ừ nhỉ!",
                                "OK bạn!",
                                "Ừ, mình nghe bạn.",
                                "Aha!"],
            },
            "en": {
                "hello":     ["Hello! What would you like to teach me?",
                               "Hi there! Ready to learn something new.",
                               "Hey! How can I help?",
                               "Hello! I'm listening.",
                               "Hi! Great to chat with you.",
                               "Hey there! What's on your mind?"],
                "hi":        ["Hi!", "Hey there!", "Hello!", "Hey!", "Hiya!"],
                "how are you":    ["I'm doing well, thanks! How about you?",
                               "Pretty good! What's up?",
                               "I'm fine, thanks for asking!",
                               "All good! How about yourself?",
                               "Doing great! And you?"],
                "are you okay":   ["Yes, I'm fine! Thanks for asking.",
                               "I'm good! What about you?",
                               "Yep, all good! Thanks!"],
                "goodbye":   ["Goodbye! Thanks for chatting.",
                               "See you next time!",
                               "Bye! Have a great day.",
                               "Take care!",
                               "Bye! Come back soon.",
                               "Goodbye! I'll remember what you taught me."],
                "bye":       ["Bye!", "See ya!", "Goodbye!", "Later!"],
                "thank you": ["You're welcome!",
                               "No problem at all!",
                               "Happy to help!",
                               "Anytime!",
                               "Of course!",
                               "Don't mention it!"],
                "thanks":    ["No worries!", "You're welcome!", "Anytime!", "Sure thing!"],
                "sorry":     ["No worries!", "It's fine!", "Don't worry about it.",
                               "All good!"],
                "_default":  ["Got it!", "I see!", "Understood!", "OK!", "Noted!", "Alright!"],
            },
            "jp": {
                "こんにちは":     ["こんにちは！今日は何を教えてくれますか？",
                                   "こんにちは！よろしくお願いします。",
                                   "どうも！何でも聞いてください。",
                                   "こんにちは！お元気ですか？"],
                "さようなら":     ["さようなら！またね。",
                                   "またね！楽しかったです。",
                                   "じゃあね！良い一日を。",
                                   "さようなら！また話しましょう！"],
                "ありがとう":     ["どういたしまして！",
                                   "いえいえ、こちらこそ。",
                                   "お役に立てて嬉しいです！",
                                   "いつでもどうぞ！"],
                "_default":       ["わかりました！", "なるほど！", "OK！", "そうですね！"],
            },
        }

        # ── TEACH RESPONSE POOLS (mở rộng + dùng topic) ──────────
        self._teach_pools: Dict[str, List[str]] = {
            "vi": [
                "Ồ hay! Mình ghi nhớ rồi: {summary}",
                "Tuyệt! Mình đã học được: {summary}",
                "Cảm ơn bạn! {summary} — mình nhớ rồi.",
                "Hiểu rồi! {summary}. Cảm ơn bạn nhé!",
                "Wow, mình biết thêm rồi: {summary}!",
                "OK! Mình lưu lại: {summary}.",
                "Hay quá! '{summary}' — câu này mình thích.",
                "Mình note lại ngay: {summary}. Bạn dạy hay thế!",
                "À ra vậy! {summary}. Mình chưa biết điều này.",
                "Tuyệt vời! {summary} — mình sẽ không quên đâu.",
                "Ồ, {summary}! Lần sau gặp câu này mình biết trả lời rồi.",
                "Haha hay! {summary} — cảm ơn bạn đã dạy mình.",
            ],
            "en": [
                "Got it! I've learned: {summary}",
                "Thanks! I'll remember: {summary}",
                "Awesome, noted: {summary}",
                "Cool! {summary} — saved!",
                "Nice one! '{summary}' — I'll keep that in mind.",
                "Learned! {summary}. Thanks for teaching me.",
                "Oh interesting! {summary}. I didn't know that before.",
                "Perfect, storing that: {summary}.",
            ],
            "jp": [
                "わかりました！{summary}を覚えました。",
                "ありがとう！{summary}ですね、メモしました！",
                "なるほど！{summary}。覚えます！",
                "素晴らしい！{summary}、忘れません！",
            ],
        }

        # ── UNKNOWN RESPONSE POOLS (cải thiện + context-aware) ────
        self._unknown_pools: Dict[str, List[str]] = {
            "vi": [
                "Ui, câu này em chưa học kỹ. Anh nói rõ thêm chút cho em với nha?",
                "Huhu em chưa hiểu trọn ý này, anh diễn đạt lại giúp em một xíu được không?",
                "Câu này mới với em quá, anh dạy em cách trả lời cho chuẩn nha.",
                "Em hơi ngơ đoạn này rồi, anh nói chậm hơn một chút cho em được không?",
                "Em muốn trả lời cho đúng ý anh, anh gợi ý thêm giúp em nha.",
                "Câu này em chưa chắc lắm, mình thử nói lại theo cách khác nè?",
                "Cho em xin thêm tí ngữ cảnh nha, em sẽ trả lời mượt hơn liền.",
            ],
            "en": [
                "Hmm, I haven't learned this yet. Could you teach me?",
                "I'm not sure how to respond to that. Could you show me?",
                "I don't know this one yet. Can you teach me?",
                "I haven't learned this phrase. What should I say?",
                "Oh interesting question! I'm not sure — can you teach me?",
                "I want to answer but I'm not sure how. Could you guide me?",
            ],
            "jp": [
                "まだこれを学んでいません。教えていただけますか？",
                "わかりません。教えてくれますか？",
                "この返事をまだ知りません。どう言えばいいですか？",
                "ちょっと難しいです。教えてもらえますか？",
            ],
        }

        # ── FIX: CLARIFY POOLS (khi match uncertain) ─────────────
        self._clarify_pools: Dict[str, List[str]] = {
            "vi": [
                "Bạn đang hỏi về '{topic}' hay điều gì khác?",
                "Em chưa chắc em hiểu đúng ý, anh nói rõ thêm cho em nhé?",
                "Ý bạn là '{topic}' hay gì khác vậy?",
                "Mình hơi mơ hồ về câu này. Bạn giải thích thêm được không?",
                "Mình chưa chắc câu trả lời đúng. Bạn dạy mình nhé?",
            ],
            "en": [
                "Are you asking about '{topic}' or something else?",
                "Hmm, I'm not 100% sure I understand. Could you clarify?",
                "Did you mean '{topic}'?",
                "I'm a bit uncertain here. Could you rephrase?",
                "Not totally sure about this one — can you elaborate?",
            ],
            "jp": [
                "'{topic}'のことですか？",
                "少し分かりにくいです。もう少し説明してください。",
                "確認しますが、'{topic}'についてですか？",
            ],
        }

        # Lịch sử dùng gần đây (tránh lặp)
        self._recent: Dict[str, List[str]] = {}
        self._max_recent = 4   # FIX: tăng từ 3 → 4

    # ── PUBLIC API ────────────────────────────────────────────────

    def build_greeting(self, text: str, lang: str) -> str:
        pool_lang = lang if lang in self._greet_pools else "vi"
        pool      = self._greet_pools[pool_lang]

        matched_key = "_default"
        for key in pool:
            if key != "_default" and key in text.lower():
                matched_key = key
                break

        responses = pool.get(matched_key, pool["_default"])
        return self._pick_unique(f"greet_{lang}_{matched_key}", responses)

    def build_phrase_response(
        self,
        match:   MatchResult,
        slots:   Dict[str, str],
        lang:    str,
        context: "SessionContext" = None,
    ) -> str:
        """
        FIX: Nếu match.uncertain → gọi build_clarify() thay vì trả bừa.
        """
        if match.uncertain and context:
            return self.build_clarify(match.trigger, lang, context)

        responses = match.responses
        chosen    = self._pick_unique(f"phrase_{match.trigger}", responses)

        # Điền slots nếu có
        if slots:
            for slot_name, slot_value in slots.items():
                chosen = chosen.replace(f"{{{slot_name}}}", slot_value)

        # FIX: Điền {topic} và {entity} từ context nếu có placeholder
        if context and "{topic}" in chosen:
            topic = context.get_topic() or ""
            chosen = chosen.replace("{topic}", topic)
        if context and "{entity}" in chosen:
            entities = context.get_recent_entities(1)
            entity   = entities[0] if entities else ""
            chosen   = chosen.replace("{entity}", entity)

        return self.syn.vary(chosen)

    def build_teach_ack(self, summary: str, lang: str) -> str:
        pool   = self._teach_pools.get(lang, self._teach_pools["vi"])
        chosen = self._pick_unique(f"teach_{lang}", pool)
        if "{summary}" in chosen:
            prefix_part = chosen.split("{summary}")[0]
            suffix_part = chosen.split("{summary}", 1)[1]
            prefix_varied = self.syn.vary(prefix_part, prob=0.15).rstrip()
            result = prefix_varied + " " + summary + suffix_part
        else:
            result = chosen.format(summary=summary)
        return result

    def build_fact_answer(
        self,
        target: str,
        facts:  List[Dict],
        lang:   str,
    ) -> str:
        if not facts:
            return self.build_unknown(lang)

        is_a_list  = [f["predicate"] for f in facts if f["relation"] == "is_a"]
        prop_list  = [f["predicate"] for f in facts if f["relation"] == "has_property"]
        state_list = [f["predicate"] for f in facts if f["relation"] == "has_state"]
        other_list = [f["predicate"] for f in facts
                      if f["relation"] not in ("is_a", "has_property", "has_state")]

        parts = []
        if is_a_list:
            parts.append(self._format_is_a(target, is_a_list, lang))
        if prop_list:
            parts.append(self._format_property(target, prop_list, lang))
        if state_list:
            parts.append(self._format_state(target, state_list, lang))
        if other_list:
            parts.append(", ".join(other_list))

        return " ".join(parts)

    def build_unknown(self, lang: str, context: "SessionContext" = None) -> str:
        """
        FIX: Nếu có context, build câu hỏi gợi ý topic đang nói.
        """
        if context:
            return self.build_contextual_unknown(lang, context)
        pool   = self._unknown_pools.get(lang, self._unknown_pools["vi"])
        chosen = self._pick_unique(f"unknown_{lang}", pool)
        return chosen

    def build_contextual_unknown(
        self, lang: str, context: "SessionContext"
    ) -> str:
        """
        FIX: Thay thế build_unknown khi có ngữ cảnh.
        Dùng topic/entity để gợi ý cụ thể hơn.
        """
        topic   = context.get_topic()
        entity  = (context.get_recent_entities(1) or [None])[0]
        subject = topic or entity

        templates_with_topic = {
            "vi": [
                f"Hmm, câu này mình chưa học. Bạn muốn nói thêm về '{subject}' không?",
                f"Mình chưa có câu trả lời cho câu này. Bạn dạy mình về '{subject}' nhé?",
                f"Ồ, về '{subject}' mình chưa rõ lắm. Bạn giải thích giúp mình được không?",
            ],
            "en": [
                f"I haven't learned this yet. Do you want to tell me more about '{subject}'?",
                f"Not sure about this one. Can you teach me about '{subject}'?",
                f"I'm a bit lost on '{subject}'. Could you help me understand?",
            ],
        }
        templates_no_topic = self._unknown_pools

        if subject:
            pool = templates_with_topic.get(lang, templates_with_topic["vi"])
        else:
            pool = templates_no_topic.get(lang, templates_no_topic["vi"])

        return self._pick_unique(f"unknown_ctx_{lang}", pool)

    def build_clarify(
        self,
        matched_trigger: str,
        lang:            str,
        context:         "SessionContext",
    ) -> str:
        """
        FIX: Khi match uncertain → hỏi lại thay vì trả lời sai.
        """
        topic = context.get_topic() or matched_trigger
        pool  = self._clarify_pools.get(lang, self._clarify_pools["vi"])
        tmpl  = self._pick_unique(f"clarify_{lang}", pool)
        return tmpl.format(topic=topic)

    def build_synonym_ack(self, w1: str, w2: str, lang: str) -> str:
        templates = {
            "vi": [
                f"Ồ! '{w1}' và '{w2}' đồng nghĩa nhau à? Mình ghi nhớ rồi!",
                f"Hay! '{w1}' ≈ '{w2}', mình biết thêm rồi.",
                f"Tuyệt! Mình biết '{w1}' cũng có thể gọi là '{w2}'.",
                f"À vậy à! '{w1}' với '{w2}' nghĩa giống nhau. Hay đó!",
                f"Ghi nhớ luôn: '{w1}' = '{w2}'. Cảm ơn bạn!",
            ],
            "en": [
                f"Oh! '{w1}' and '{w2}' are synonyms? Got it!",
                f"Interesting! '{w1}' ≈ '{w2}', I'll remember that.",
                f"Nice! So '{w1}' means the same as '{w2}'. Noted!",
                f"Got it — '{w1}' and '{w2}' are interchangeable. Thanks!",
            ],
            "jp": [
                f"「{w1}」と「{w2}」は同じ意味ですね！覚えました。",
                f"なるほど！「{w1}」≈「{w2}」、メモしました！",
            ],
        }
        pool   = templates.get(lang, templates["vi"])
        return self._pick_unique(f"syn_{lang}", pool)

    # ── HORMONE INTEGRATION (mở rộng) ────────────────────────────

    def apply_hormone_tone(self, text: str, h_modifiers: dict) -> str:
        if not h_modifiers or not text:
            return text

        warmth     = h_modifiers.get("warmth",     0.5)
        verbosity  = h_modifiers.get("verbosity",  0.5)
        positivity = h_modifiers.get("positivity", 0.5)
        lang       = h_modifiers.get("lang", "vi")
        result     = text

        # Tiếng Việt
        if lang == "vi":
            if warmth > 0.72:
                result = result.replace("Ừ,", "Ừ bạn ơi,")
                result = result.replace("Không.", "Không nhé.")
                if not result.endswith("!") and len(result) < 60:
                    result = result.rstrip(".") + " 😊"

            if positivity < 0.30:
                result = result.replace(" Còn bạn thì sao?", "")
                result = result.replace(" Bạn chọn gì?", "")
                result = result.replace(" Sao hỏi vậy?", "")

        # FIX: Tiếng Anh
        elif lang == "en":
            if warmth > 0.72:
                result = result.replace("Okay.", "Okay!")
                if not result.endswith("!") and len(result) < 60:
                    result = result.rstrip(".") + " 😊"
            if positivity < 0.30:
                result = result.replace(" What about you?", "")
                result = result.replace(" How about you?", "")

        if verbosity < 0.25:
            sentences = result.split(". ")
            if len(sentences) > 1:
                result = sentences[0] + "."

        # NOTE: spontaneous_text được gắn vào response bởi main.py sau khi _route() trả về.
        # Không gắn ở đây để tránh bị lặp đôi.

        return result.strip()

    # ── PRIVATE ───────────────────────────────────────────────────

    def _pick_unique(self, key: str, pool: List[str]) -> str:
        """Chọn ngẫu nhiên, tránh dùng lại _max_recent câu gần nhất."""
        recent  = self._recent.get(key, [])
        unused  = [r for r in pool if r not in recent]
        chosen  = random.choice(unused if unused else pool)

        if key not in self._recent:
            self._recent[key] = []
        self._recent[key].append(chosen)
        if len(self._recent[key]) > self._max_recent:
            self._recent[key].pop(0)

        return chosen

    def _format_is_a(self, target: str, values: List[str], lang: str) -> str:
        joined = ", ".join(values)
        templates = {
            "vi": [f"'{target}' là {joined}.",
                   f"'{target}' thuộc loại {joined}.",
                   f"Ừ, '{target}' là một loại {joined}."],
            "en": [f"'{target}' is {joined}.",
                   f"'{target}' is a type of {joined}."],
            "jp": [f"「{target}」は{joined}です。"],
        }
        return random.choice(templates.get(lang, templates["vi"]))

    def _format_property(self, target: str, values: List[str], lang: str) -> str:
        joined = ", ".join(values)
        templates = {
            "vi": [f"'{target}' có đặc tính: {joined}.",
                   f"'{target}' mang tính chất {joined}."],
            "en": [f"'{target}' has the property of being {joined}."],
            "jp": [f"「{target}」は{joined}という特性があります。"],
        }
        return random.choice(templates.get(lang, templates["vi"]))

    def _format_state(self, target: str, values: List[str], lang: str) -> str:
        joined = ", ".join(values)
        templates = {
            "vi": [f"'{target}' đang ở trạng thái {joined}."],
            "en": [f"'{target}' is currently {joined}."],
            "jp": [f"「{target}」は今{joined}の状態です。"],
        }
        return random.choice(templates.get(lang, templates["vi"]))
