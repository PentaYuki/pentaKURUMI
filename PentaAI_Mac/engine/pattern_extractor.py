# engine/pattern_extractor.py
"""
PatternExtractor — Phát hiện pattern và slot trong câu.

Ý tưởng gốc từ Deacon:
  Ý nghĩa không nằm trong từng cặp câu riêng lẻ
  mà nằm trong PATTERN chung giữa nhiều câu.

  "bạn khỏe không" → "mình ổn"
  "bạn mệt không"  → "mình hơi mệt"
  "bạn vui không"  → "mình vui lắm"

  PatternExtractor nhận 3 cặp trên và rút ra:
    trigger pattern:  "bạn {state} không"
    response pattern: "mình {degree} {state}"

  Sau đó khi nghe "bạn buồn không" → điền slot → trả lời được
  mà không cần người dùng dạy cặp đó.

─────────────────────────────────────────────────────────
Chức năng từng method:

  extract_slots_from_single(text)
    → Nhận 1 câu, trả về pattern với slot đã phát hiện
    → VD: "bạn khỏe không" → "bạn {adj_0} không"
    → Dùng khi người dùng dạy cặp mới, slot hóa ngay

  generalize_from_pairs(pairs)
    → Nhận nhiều cặp (trigger, response)
    → So sánh chéo để tìm slot chung
    → VD: 3 cặp trên → rút ra template chung
    → Dùng sau khi có đủ 3+ cặp tương tự

  find_matching_pattern(query, patterns)
    → Nhận câu query + danh sách patterns đã học
    → Trả về (pattern_matched, slot_values)
    → VD: "bạn buồn không" → pattern "bạn {adj} không", slot={adj: buồn}

  slots_are_compatible(slot1, slot2)
    → Kiểm tra 2 slot có thể ghép nhóm không
    → Dùng khi quyết định có nên tạo pattern chung không
─────────────────────────────────────────────────────────
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class SlotInfo:
    name:     str        # tên slot: "adj", "state", "name", ...
    position: int        # vị trí token trong câu
    examples: List[str]  # các giá trị đã gặp: ["khỏe", "mệt", "vui"]
    category: str        # "adj_state" | "noun" | "name" | "unknown"


@dataclass
class Pattern:
    template:       str          # "bạn {state} không"
    slots:          List[SlotInfo]
    source_pairs:   int          # số cặp đóng góp vào pattern này
    lang:           str
    confidence:     float        # càng nhiều cặp → confidence cao hơn
    trigger_fixed:  List[str]    # các token cố định (không phải slot)


class PatternExtractor:

    # ── Từ điển phân loại slot theo ngữ nghĩa ────────────────────
    # Dùng để đặt tên slot có nghĩa thay vì slot_0, slot_1
    _SLOT_CATEGORIES = {
        "adj_state": {
            "vi": {"khỏe", "mệt", "vui", "buồn", "ốm", "tốt", "xấu",
                   "đói", "khát", "no", "nóng", "lạnh", "bận", "rảnh",
                   "lo", "sợ", "hạnh phúc", "tức", "giận", "chán"},
            "en": {"good", "bad", "tired", "happy", "sad", "sick",
                   "hungry", "cold", "hot", "busy", "free", "fine",
                   "angry", "scared", "bored", "stressed"},
            "jp": {"元気", "疲れ", "嬉しい", "悲しい", "忙しい", "暇"},
        },
        "degree": {
            "vi": {"rất", "hơi", "khá", "cực kỳ", "lắm", "quá",
                   "chút", "một chút", "tí", "siêu"},
            "en": {"very", "quite", "pretty", "really", "so", "too",
                   "a bit", "a little", "extremely"},
            "jp": {"とても", "少し", "かなり", "すごく"},
        },
        "name": {
            "vi": set(),  # tên riêng → detect bằng heuristic khác
            "en": set(),
            "jp": set(),
        },
        "topic": {
            "vi": {"học", "làm", "ăn", "ngủ", "chơi", "đọc", "xem",
                   "nghe", "đi", "về", "mua", "bán"},
            "en": {"study", "work", "eat", "sleep", "play", "read",
                   "watch", "listen", "go", "come", "buy", "sell"},
        },
    }

    # Các token KHÔNG bao giờ là slot (từ cấu trúc câu)
    _FIXED_TOKENS_VI = {
        "bạn", "anh", "chị", "em", "tôi", "mình",
        "có", "không", "thế", "nào", "à", "ư", "nhỉ",
        "là", "và", "hay", "hoặc", "nhưng", "mà",
    }
    _FIXED_TOKENS_EN = {
        "you", "i", "we", "they", "he", "she", "it",
        "are", "is", "do", "does", "can", "will",
        "the", "a", "an", "and", "or", "but",
    }
    _FIXED_TOKENS_JP = {
        "は", "が", "を", "に", "で", "と", "も",
        "か", "ね", "よ", "な", "の",
    }

    # ── PUBLIC ────────────────────────────────────────────────────

    def extract_slots_from_single(
        self, text: str, lang: str = "vi"
    ) -> Tuple[str, List[SlotInfo]]:
        """
        Nhận 1 câu → trả về (template_string, slot_list).

        Cách hoạt động:
          1. Tokenize câu
          2. Với mỗi token: kiểm tra có thuộc từ điển slot không
          3. Nếu có → thay bằng {slot_name}, ghi lại SlotInfo
          4. Trả về template + danh sách slots

        VD:
          input:  "bạn khỏe không"
          output: ("bạn {state} không", [SlotInfo(name="state", pos=1, ...)])
        """
        tokens = text.lower().strip().split()
        fixed  = self._get_fixed_tokens(lang)

        template_tokens = []
        slots           = []
        slot_counter    = {}

        for i, token in enumerate(tokens):
            if token in fixed:
                template_tokens.append(token)
                continue

            category = self._classify_token(token, lang)
            if category != "unknown":
                # Đây là slot
                slot_name = self._make_slot_name(category, slot_counter)
                slot_counter[category] = slot_counter.get(category, 0) + 1

                template_tokens.append(f"{{{slot_name}}}")
                slots.append(SlotInfo(
                    name=slot_name,
                    position=i,
                    examples=[token],
                    category=category,
                ))
            else:
                template_tokens.append(token)

        template = " ".join(template_tokens)
        return template, slots

    def generalize_from_pairs(
        self,
        pairs: List[Tuple[str, str]],  # [(trigger, response), ...]
        lang: str = "vi",
    ) -> Optional[Pattern]:
        """
        Nhận nhiều cặp (trigger, response) tương tự nhau
        → Rút ra Pattern chung.

        Cách hoạt động:
          1. Tokenize tất cả triggers
          2. Tìm các vị trí token THAY ĐỔI giữa các triggers
          3. Vị trí thay đổi → slot, vị trí cố định → giữ nguyên
          4. Đặt tên slot dựa vào giá trị gặp được

        VD pairs:
          ("bạn khỏe không", "mình ổn"),
          ("bạn mệt không",  "mình hơi mệt"),
          ("bạn vui không",  "mình vui lắm")

        Output Pattern:
          template = "bạn {state} không"
          slots    = [SlotInfo(name="state", examples=["khỏe","mệt","vui"])]
        """
        if len(pairs) < 2:
            return None

        tokenized = [t.lower().strip().split() for t, _ in pairs]

        # Tìm độ dài phổ biến nhất
        lengths  = [len(t) for t in tokenized]
        # Chỉ xét các trigger có cùng độ dài (pattern rõ ràng hơn)
        mode_len = max(set(lengths), key=lengths.count)
        same_len = [t for t in tokenized if len(t) == mode_len]

        if len(same_len) < 2:
            return None

        # Tìm vị trí token thay đổi
        template_tokens = []
        slots           = []
        fixed_tokens    = []

        for pos in range(mode_len):
            values_at_pos = [tokens[pos] for tokens in same_len]
            unique_values = set(values_at_pos)

            if len(unique_values) == 1:
                # Token cố định
                template_tokens.append(values_at_pos[0])
                fixed_tokens.append(values_at_pos[0])
            else:
                # Token thay đổi → đây là slot
                category  = self._classify_token_group(unique_values, lang)
                slot_name = category if category != "unknown" else f"slot_{pos}"
                template_tokens.append(f"{{{slot_name}}}")
                slots.append(SlotInfo(
                    name=slot_name,
                    position=pos,
                    examples=list(unique_values),
                    category=category,
                ))

        if not slots:
            return None  # Không có gì thay đổi → không phải pattern

        template   = " ".join(template_tokens)
        confidence = min(0.95, 0.5 + len(pairs) * 0.1)

        return Pattern(
            template=template,
            slots=slots,
            source_pairs=len(pairs),
            lang=lang,
            confidence=confidence,
            trigger_fixed=fixed_tokens,
        )

    def find_matching_pattern(
        self,
        query: str,
        patterns: List[Pattern],
    ) -> Optional[Tuple[Pattern, Dict[str, str]]]:
        """
        Nhận câu query + danh sách patterns đã học
        → Trả về (pattern_khớp_nhất, {slot_name: giá_trị}).

        Cách hoạt động:
          1. Với mỗi pattern: thử match query vào template
          2. Dùng regex: template → regex (thay {slot} bằng (.+))
          3. Nếu match → trích xuất giá trị slot
          4. Trả về pattern có confidence cao nhất

        VD:
          query:   "bạn buồn không"
          pattern: "bạn {state} không"
          output:  (pattern, {"state": "buồn"})
        """
        query_clean = query.lower().strip()
        best_match  = None
        best_conf   = 0.0

        for pattern in patterns:
            result = self._try_match(query_clean, pattern)
            if result is not None:
                slots_dict, score = result
                combined = score * pattern.confidence
                if combined > best_conf:
                    best_conf  = combined
                    best_match = (pattern, slots_dict)

        return best_match

    def slots_are_compatible(
        self,
        slot1: SlotInfo,
        slot2: SlotInfo,
    ) -> bool:
        """
        Kiểm tra 2 SlotInfo có thể ghép thành 1 group không.
        Dùng khi quyết định merge patterns.

        Hai slot compatible khi:
          - Cùng category (đều là adj_state, hoặc đều là degree)
          - Hoặc examples có giao nhau (cùng tập từ vựng)
        """
        if slot1.category == slot2.category and slot1.category != "unknown":
            return True

        # Kiểm tra overlap examples
        ex1 = set(slot1.examples)
        ex2 = set(slot2.examples)
        overlap = len(ex1 & ex2)
        return overlap >= 1

    def add_example_to_pattern(
        self,
        pattern: Pattern,
        slot_name: str,
        new_value: str,
    ):
        """
        Thêm ví dụ mới vào slot của pattern.
        Gọi khi người dùng dạy cặp mới khớp với pattern cũ.
        Pattern ngày càng phong phú hơn.
        """
        for slot in pattern.slots:
            if slot.name == slot_name:
                if new_value not in slot.examples:
                    slot.examples.append(new_value)
                break
        pattern.source_pairs += 1
        pattern.confidence = min(0.97, pattern.confidence + 0.02)

    # ── PRIVATE ───────────────────────────────────────────────────

    def _get_fixed_tokens(self, lang: str) -> set:
        if lang == "en":
            return self._FIXED_TOKENS_EN
        if lang == "jp":
            return self._FIXED_TOKENS_JP
        return self._FIXED_TOKENS_VI

    def _classify_token(self, token: str, lang: str) -> str:
        """Phân loại 1 token vào category."""
        for category, lang_sets in self._SLOT_CATEGORIES.items():
            word_set = lang_sets.get(lang, set())
            if token in word_set:
                return category
        # Heuristic: token dài 1-2 âm tiết, không phải số → có thể là adj
        if len(token) <= 8 and not token.isdigit():
            return "unknown"
        return "unknown"

    def _classify_token_group(self, values: set, lang: str) -> str:
        """Phân loại nhóm token (slot) dựa vào majority vote."""
        category_votes: Dict[str, int] = {}
        for val in values:
            cat = self._classify_token(val, lang)
            if cat != "unknown":
                category_votes[cat] = category_votes.get(cat, 0) + 1

        if not category_votes:
            return "unknown"
        return max(category_votes, key=category_votes.get)

    def _make_slot_name(self, category: str, counter: Dict[str, int]) -> str:
        """Tạo tên slot không trùng."""
        base  = category
        count = counter.get(category, 0)
        return base if count == 0 else f"{base}_{count}"

    def _try_match(
        self,
        query: str,
        pattern: Pattern,
    ) -> Optional[Tuple[Dict[str, str], float]]:
        """
        Thử khớp query với pattern template.
        Trả về (slot_values, score) hoặc None.

        Cách hoạt động:
          template = "bạn {state} không"
          → regex  = r"bạn (.+?) không"
          → match  = re.match(regex, query)
          → extract slot values từ groups
        """
        template = pattern.template

        # Tách template thành phần cố định và slot
        slot_names = re.findall(r'\{(\w+)\}', template)

        # Tạo regex từ template
        # Mỗi {slot} → (.+?) để match non-greedy
        regex_str = re.escape(template)
        # unescape các slot placeholder (đã bị escape)
        for slot_name in slot_names:
            escaped_slot = re.escape(f"{{{slot_name}}}")
            regex_str    = regex_str.replace(escaped_slot, r"(.+?)")

        regex_str = f"^{regex_str}$"

        try:
            m = re.match(regex_str, query)
        except re.error:
            return None

        if not m:
            # Thử partial match (query ngắn hơn template)
            return self._partial_match(query, pattern)

        # Trích xuất slot values
        groups     = m.groups()
        slot_dict  = {}
        for slot_name, value in zip(slot_names, groups):
            slot_dict[slot_name] = value.strip()

        # Score = 1.0 nếu exact structural match
        return slot_dict, 1.0

    def _partial_match(
        self,
        query: str,
        pattern: Pattern,
    ) -> Optional[Tuple[Dict[str, str], float]]:
        """
        Match mềm hơn khi query không khớp exact với template.
        Kiểm tra xem các fixed tokens của pattern có trong query không.
        """
        query_tokens   = set(query.split())
        fixed_in_query = sum(
            1 for t in pattern.trigger_fixed if t in query_tokens
        )
        total_fixed    = max(len(pattern.trigger_fixed), 1)
        coverage       = fixed_in_query / total_fixed

        if coverage < 0.6:
            return None

        # Tìm phần "lạ" trong query (không phải fixed token) → đó là slot value
        slot_dict = {}
        new_tokens = [t for t in query.split() if t not in pattern.trigger_fixed]

        for i, slot in enumerate(pattern.slots):
            if i < len(new_tokens):
                slot_dict[slot.name] = new_tokens[i]

        return slot_dict, coverage * 0.8