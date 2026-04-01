# engine/slot_resolver.py
"""
SlotResolver — Điền giá trị vào slot khi trả lời.

Vai trò trong hệ thống:
  PatternExtractor tìm được: pattern="bạn {state} không", slot={state: "buồn"}
  SlotResolver quyết định:   response slot {state} → điền gì vào?

Đây là nơi KnowledgeStore + SynonymManager phối hợp để
tạo ra câu trả lời có ngữ nghĩa thật, không phải lookup cứng.

─────────────────────────────────────────────────────────
Chức năng từng method:

  resolve(slot_name, slot_value, response_template, store, syn)
    → Nhận: tên slot, giá trị slot từ query, template response, store, syn
    → Trả về: response string đã điền slot
    → Đây là method chính, gọi các method khác bên trong

  find_response_value(slot_value, slot_category, store, syn)
    → Tìm giá trị phù hợp để điền vào response
    → Chiến lược:
        1. Tìm trong response examples đã dạy (từ pairs)
        2. Tìm qua KnowledgeStore (facts về slot_value)
        3. Tìm qua SynonymManager (đồng nghĩa)
        4. Fallback: dùng chính slot_value

  build_response_from_pattern(response_template, slot_map, syn)
    → Điền tất cả slots vào response template
    → Thay đồng nghĩa ngẫu nhiên để đa dạng
    → Trả về string cuối

  infer_emotional_response(state_word, lang)
    → Với slot category "adj_state":
       tự suy ra cách AI phản hồi cảm xúc tương ứng
    → VD: state="buồn" → AI có thể nói "mình cũng hơi buồn" hoặc
                                        "ôi sao vậy bạn?"
    → Đây là nơi gần triết lý Deacon nhất:
       nghĩa của "buồn" trong response phụ thuộc vào
       MẠNG LƯỚI quan hệ của từ đó trong graph

  _pick_degree(lang)
    → Chọn ngẫu nhiên từ chỉ mức độ (rất/hơi/khá...)
    → Tạo sự đa dạng tự nhiên
─────────────────────────────────────────────────────────
"""

import random
from typing import Dict, List, Optional, Tuple, Any


class SlotResolver:

    # ── Mapping cảm xúc → cách AI phản hồi ──────────────────────
    # Đây là "constraint network" nhỏ: biết "buồn" → biết cách phản hồi
    # Gần với Indexical của Deacon: A → B vì chúng liên quan, không phải
    # vì giống nhau (Iconic) hay vì người dạy gán thẳng (Stimulus-Response)

    _EMOTIONAL_RESPONSES = {
        "vi": {
            # (state_word) → (AI_state, degree_options, follow_up_options)
            "khỏe":     ("ổn",        ["",    "cũng",  "khá"],
                                       ["Bạn thế nào?", ""]),
            "mệt":      ("hơi mệt",   ["hơi", "cũng",  ""],
                                       ["Bạn nghỉ ngơi đi nhé.", "Mình hiểu cảm giác đó."]),
            "vui":      ("vui",       ["rất", "cũng",  "khá"],
                                       ["Vui quá nhỉ!", ""]),
            "buồn":     ("buồn",      ["hơi", "cũng",  ""],
                                       ["Có chuyện gì vậy bạn?", "Mình ở đây nè."]),
            "ốm":       ("không khỏe",["cũng", "hơi",  ""],
                                       ["Uống thuốc đi bạn nhé.", "Mau khỏi nhé!"]),
            "bận":      ("khá bận",   ["cũng", "hơi",  "rất"],
                                       ["Cố lên nhé!", ""]),
            "rảnh":     ("rảnh",      ["cũng", "khá",  ""],
                                       ["Vậy mình nói chuyện nha!", ""]),
            "lo":       ("lo",        ["cũng", "hơi",  ""],
                                       ["Lo chuyện gì vậy?", "Đừng lo quá nhé."]),
            "tức":      ("bực",       ["hơi",  "cũng", ""],
                                       ["Chuyện gì xảy ra vậy?", ""]),
            "đói":      ("đói",       ["cũng", "hơi",  "rất"],
                                       ["Đi ăn gì đi!", ""]),
            "chán":     ("chán",      ["cũng", "hơi",  "khá"],
                                       ["Làm gì cho vui đi?", ""]),
        },
        "en": {
            "good":     ("good",      ["also", "pretty", ""],
                                       ["How about you?", ""]),
            "tired":    ("tired",     ["a bit", "also",  ""],
                                       ["Get some rest!", "I feel you."]),
            "happy":    ("happy",     ["really", "also", "pretty"],
                                       ["That's great!", ""]),
            "sad":      ("sad",       ["a bit", "also",  ""],
                                       ["What happened?", "I'm here for you."]),
            "sick":     ("not well",  ["also", "a bit",  ""],
                                       ["Get well soon!", "Take care."]),
            "busy":     ("busy",      ["also", "quite",  "really"],
                                       ["Keep going!", ""]),
            "bored":    ("bored",     ["also", "a bit",  ""],
                                       ["Let's talk then!", ""]),
            "hungry":   ("hungry",    ["also", "really", ""],
                                       ["Go eat something!", ""]),
        },
        "jp": {
            "元気":     ("元気",       ["",    "まあまあ", "とても"],
                                       ["あなたは？", ""]),
            "疲れ":     ("疲れ気味",   ["少し", "も",     ""],
                                       ["休んでね。", ""]),
            "嬉しい":   ("嬉しい",     ["も",   "とても",  ""],
                                       ["よかった！", ""]),
            "悲しい":   ("悲しい",     ["少し", "も",     ""],
                                       ["どうしたの？", ""]),
        },
    }

    # ── Degree words cho từng ngôn ngữ ───────────────────────────
    _DEGREES = {
        "vi": ["", "hơi ", "khá ", "rất ", "cũng "],
        "en": ["", "a bit ", "quite ", "pretty ", "also "],
        "jp": ["", "少し", "かなり", "とても"],
    }

    # ── PUBLIC ────────────────────────────────────────────────────

    def resolve(
        self,
        slot_map:          Dict[str, str],      # {slot_name: slot_value}
        response_template: str,                  # "mình {degree}{state} cảm ơn"
        slot_categories:   Dict[str, str],       # {slot_name: category}
        lang:              str,
        store=None,
        syn=None,
    ) -> str:
        """
        Method chính. Nhận slot_map + template → trả về string hoàn chỉnh.

        Ví dụ:
          slot_map         = {"state": "buồn"}
          response_template = "mình {state} lắm"
          → output: "mình buồn lắm"
               hoặc "mình cũng buồn" (sau khi vary)
        """
        filled_slots: Dict[str, str] = {}

        for slot_name, slot_value in slot_map.items():
            category = slot_categories.get(slot_name, "unknown")

            # Tìm giá trị phù hợp để điền
            resolved = self.find_response_value(
                slot_value=slot_value,
                slot_category=category,
                lang=lang,
                store=store,
                syn=syn,
            )
            filled_slots[slot_name] = resolved

        # Xây dựng response
        return self.build_response_from_pattern(
            response_template, filled_slots, lang, syn
        )

    def find_response_value(
        self,
        slot_value: str,
        slot_category: str,
        lang: str,
        store=None,
        syn=None,
    ) -> str:
        """
        Tìm giá trị phù hợp để đặt vào response.

        Thứ tự ưu tiên:
          1. Emotional mapping (adj_state → AI cảm nhận gì?)
          2. KnowledgeStore: có fact nào về slot_value không?
          3. SynonymManager: có đồng nghĩa nào phù hợp hơn không?
          4. Fallback: dùng chính slot_value
        """
        # Ưu tiên 1: Emotional mapping
        if slot_category == "adj_state":
            emotional = self._get_emotional_value(slot_value, lang)
            if emotional:
                return emotional

        # Ưu tiên 2: KnowledgeStore facts
        if store:
            facts = store.get_facts(slot_value)
            # Lấy fact phù hợp nhất (ưu tiên has_property hoặc has_state)
            for fact in facts:
                if fact["relation"] in ("has_property", "is_a"):
                    return fact["predicate"]

        # Ưu tiên 3: Synonym
        if syn:
            synonyms = syn.get_synonyms(slot_value)
            if synonyms:
                return random.choice(synonyms)

        # Fallback
        return slot_value

    def build_response_from_pattern(
        self,
        template: str,
        filled_slots: Dict[str, str],
        lang: str,
        syn=None,
    ) -> str:
        """
        Điền slots vào template và tạo câu trả lời cuối.

        Ví dụ:
          template     = "mình {degree}{state} cảm ơn"
          filled_slots = {"state": "ổn"}
          → "mình khá ổn cảm ơn"

        Sau đó SynonymManager thay một số từ để tự nhiên hơn.
        """
        result = template

        for slot_name, value in filled_slots.items():
            placeholder = f"{{{slot_name}}}"
            result = result.replace(placeholder, value)

        # Xử lý slot đặc biệt {degree} nếu còn trong template
        if "{degree}" in result:
            degree = self._pick_degree(lang)
            result = result.replace("{degree}", degree)

        # Xử lý slot {followup} nếu có
        if "{followup}" in result:
            result = result.replace("{followup}", "")

        # Thay đồng nghĩa nhẹ (20%) — không thay slot values vừa điền
        if syn:
            result = self._vary_non_slot_words(result, filled_slots, syn)

        return result.strip()

    def infer_emotional_response(
        self,
        state_word: str,
        lang: str,
        include_followup: bool = True,
    ) -> str:
        """
        Suy ra câu phản hồi cảm xúc hoàn chỉnh từ 1 state word.

        Đây là điểm gần Deacon nhất:
        - Biết "buồn" → AI không chỉ lookup "buồn → ..." mà
          hiểu "buồn" nằm trong cluster cảm xúc tiêu cực
          → phản hồi phù hợp với ngữ cảnh đó

        VD:
          state_word = "buồn", lang = "vi"
          → "Mình cũng hơi buồn. Có chuyện gì vậy bạn?"
        """
        lang_map = self._EMOTIONAL_RESPONSES.get(lang, {})
        entry    = lang_map.get(state_word)

        if entry is None:
            # Không có mapping cụ thể → trả lời chung chung
            return self._generic_empathy(state_word, lang)

        ai_state, degree_opts, followup_opts = entry

        degree  = random.choice(degree_opts)
        followup = random.choice(followup_opts) if include_followup else ""

        # Cấu trúc câu theo ngôn ngữ
        if lang == "vi":
            base = f"Mình {degree}{ai_state}".strip()
            if followup:
                return f"{base}. {followup}"
            return base + "."

        elif lang == "en":
            base = f"I'm {degree}{ai_state}".strip()
            if followup:
                return f"{base}. {followup}"
            return base + "."

        elif lang == "jp":
            base = f"私も{degree}{ai_state}です"
            if followup:
                return f"{base}。{followup}"
            return base + "。"

        return f"{ai_state}."

    def get_slot_follow_up(
        self, state_word: str, lang: str
    ) -> Optional[str]:
        """
        Lấy câu hỏi tiếp theo phù hợp với trạng thái.
        VD: "buồn" → "Có chuyện gì vậy bạn?"
        """
        lang_map = self._EMOTIONAL_RESPONSES.get(lang, {})
        entry    = lang_map.get(state_word)
        if entry:
            _, _, followup_opts = entry
            non_empty = [f for f in followup_opts if f]
            return random.choice(non_empty) if non_empty else None
        return None

    # ── PRIVATE ───────────────────────────────────────────────────

    def _get_emotional_value(self, state_word: str, lang: str) -> Optional[str]:
        """Lấy giá trị AI state tương ứng với state_word của người dùng."""
        lang_map = self._EMOTIONAL_RESPONSES.get(lang, {})
        entry    = lang_map.get(state_word)
        if entry:
            ai_state, degree_opts, _ = entry
            degree = random.choice(degree_opts)
            return f"{degree}{ai_state}".strip()
        return None

    def _pick_degree(self, lang: str) -> str:
        """Chọn ngẫu nhiên từ mức độ cho ngôn ngữ tương ứng."""
        degrees = self._DEGREES.get(lang, self._DEGREES["vi"])
        return random.choice(degrees)

    def _generic_empathy(self, state_word: str, lang: str) -> str:
        """Phản hồi chung khi không có mapping cụ thể."""
        templates = {
            "vi": [
                f"Mình cũng {state_word} vậy.",
                f"Ừ, {state_word} nhỉ.",
                f"Mình hiểu cảm giác {state_word}.",
            ],
            "en": [
                f"I'm {state_word} too.",
                f"Yeah, {state_word}.",
                f"I understand feeling {state_word}.",
            ],
            "jp": [
                f"私も{state_word}です。",
                f"{state_word}ですね。",
            ],
        }
        pool = templates.get(lang, templates["vi"])
        return random.choice(pool)

    def _vary_non_slot_words(
        self,
        text: str,
        filled_slots: Dict[str, str],
        syn,
    ) -> str:
        """
        Thay đồng nghĩa cho các từ KHÔNG phải slot value.
        Tránh thay từ vừa điền vào (sẽ làm mất nghĩa).
        """
        slot_values = set(v.lower() for v in filled_slots.values())
        words       = text.split()
        result      = []

        for word in words:
            clean = word.lower().rstrip(".,!?")
            if clean in slot_values:
                result.append(word)  # Không thay slot values
                continue

            import random as _r
            if _r.random() < 0.20:
                syns = syn.get_synonyms(clean)
                if syns:
                    close = [s for s in syns if abs(len(s) - len(clean)) <= 4]
                    chosen = _r.choice(close if close else syns)
                    # Giữ dấu câu cuối
                    if word and word[-1] in ".,!?":
                        result.append(chosen + word[-1])
                    else:
                        result.append(chosen)
                    continue

            result.append(word)

        return " ".join(result)