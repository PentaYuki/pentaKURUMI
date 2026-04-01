# core/intent_detector.py
"""
IntentDetector — Tầng 2.
Chỉ làm 1 việc: nhận ParsedInput → trả Intent.
KHÔNG xử lý logic response gì cả.

Các intent:
  GREET          → câu chào/tạm biệt/cảm ơn
  TEACH_PHRASE   → dạy cặp (trigger → response)
  TEACH_FACT     → dạy sự kiện: "chó là động vật"
  TEACH_SYNONYM  → dạy đồng nghĩa
  ASK_DEFINITION → hỏi định nghĩa: "X là gì?"
  CONVERSE       → câu hội thoại thường
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from core.input_parser import ParsedInput


@dataclass
class Intent:
    type:       str
    confidence: float
    slots:      Dict[str, Any] = field(default_factory=dict)


class IntentDetector:
    """Phân loại ý định. Stateless, không có side effect."""

    # ════════════════════════════════════════════════════════════
    # TEACH_PHRASE PATTERNS
    # Tất cả các cách tự nhiên để dạy cặp (trigger → response)
    # ════════════════════════════════════════════════════════════

    # Mỗi pattern là (regex, group_trigger, group_response)
    # group_trigger/response: index của group chứa trigger và response
    _TEACH_PATTERNS: List[tuple] = [

        # ── Nhóm 1: "khi [chủ_ngữ] [động_từ] X [thì] [chủ_ngữ] [trả_lời] Y" ──
        # "khi nghe X thì nói Y"
        (re.compile(
            r'khi\s+(?:nghe|thấy|nhận được?)\s+["\']?(.+?)["\']?'
            r'\s+(?:thì|hãy|thì hãy)\s+(?:nói|trả lời|reply|bảo|đáp)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # "khi tôi/bạn/anh/em nói X thì [bạn/em/mình] [trả lời/nói/bảo] Y"
        (re.compile(
            r'khi\s+(?:tôi|bạn|anh|chị|em|mình|ta|người dùng|user)\s+'
            r'(?:nói|hỏi|nhắn|viết|gửi|bảo)\s+["\']?(.+?)["\']?'
            r'\s+(?:thì\s+)?(?:bạn|em|mình|anh|chị|ai)?\s*'
            r'(?:trả lời|nói|bảo|reply|đáp|phản hồi)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 2: "khi tôi nói X bạn [hãy] trả lời Y" (KHÔNG có "thì") ──
        # "hãy" là optional — tránh bug "bạn hãy trả lời" bị capture vào trigger
        (re.compile(
            r'khi\s+(?:tôi|bạn|anh|chị|em|mình|ta)\s+'
            r'(?:nói|hỏi|nhắn|viết|gửi|bảo)\s+["\']?(.+?)["\']?'
            r'\s+(?:bạn|em|mình|anh|chị)\s+'
            r'(?:hãy\s+)?(?:trả lời|nói|bảo|reply|đáp|phản hồi|sẽ nói|sẽ trả lời)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 3: "nếu X thì [nói/trả lời] Y" ──
        (re.compile(
            r'nếu\s+(?:(?:tôi|bạn|anh|chị|em|mình)\s+(?:nói|hỏi)\s+)?'
            r'["\']?(.+?)["\']?'
            r'\s+thì\s+(?:(?:bạn|em|mình|anh|chị)\s+)?'
            r'(?:nói|trả lời|bảo|reply|đáp)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 4: "nghe X nói Y" / "nghe X trả lời Y" ──
        (re.compile(
            r'nghe\s+["\']?(.+?)["\']?\s+'
            r'(?:thì\s+)?(?:nói|trả lời|bảo|reply|đáp)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 5: "X thì nói/trả lời Y" (ngắn gọn nhất) ──
        (re.compile(
            r'^["\']?(.+?)["\']?\s+thì\s+'
            r'(?:(?:bạn|em|mình)\s+)?'
            r'(?:nói|trả lời|bảo|reply|đáp)\s+["\']?(.+)["\']?$',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 6: Tiếng Anh ──
        # "when you hear X say/reply Y"
        (re.compile(
            r'when\s+(?:(?:i|you)\s+(?:say|ask|type|send)\s+)?'
            r'["\']?(.+?)["\']?\s+'
            r'(?:then\s+)?(?:say|reply|respond with|answer with)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # "if I say X you say/reply Y"
        (re.compile(
            r'if\s+(?:i|you)\s+say\s+["\']?(.+?)["\']?'
            r'(?:\s+then)?\s+(?:you\s+)?(?:say|reply|respond)\s+["\']?(.+)["\']?',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 7: Dấu mũi tên (ngôn ngữ không quan trọng) ──
        # "X → Y" / "X -> Y" / "X => Y"
        (re.compile(r'^(.+?)\s*(?:→|->|=>)\s*(.+)$'), 1, 2),

        # ── Nhóm 8: Dấu ngoặc kép rõ ràng ──
        # 'nói "X" trả lời "Y"' / '"X" → "Y"'
        (re.compile(
            r'["\'](.+?)["\']\s*'
            r'(?:thì\s+)?(?:trả lời|reply|→|->)\s*'
            r'["\'](.+)["\']',
            re.IGNORECASE), 1, 2),

        # ── Nhóm 9: Tiếng Nhật ──
        # "Xと言ったらYと答えて"
        (re.compile(
            r'(.+?)(?:と言ったら|と聞いたら|の時は?)\s*(.+?)(?:と答えて|と言って|にして)?$'
        ), 1, 2),
    ]

    # ════════════════════════════════════════════════════════════
    # FACT PATTERNS
    # ════════════════════════════════════════════════════════════
    _FACT_VI = re.compile(r'^(.+?)\s+là\s+(.+)$',             re.IGNORECASE)
    _FACT_EN = re.compile(r'^(.+?)\s+(?:is|are)\s+(.+)$',     re.IGNORECASE)
    _FACT_JP = re.compile(
        r'^(.+?)\s*は\s*(?!何(?:ですか|です|\?|$)|なに)(.+?)(?:です|だ)?$'
    )

    # ════════════════════════════════════════════════════════════
    # SYNONYM PATTERNS
    # ════════════════════════════════════════════════════════════
    _SYNONYM_VI = re.compile(
        r'(.+?)\s+(?:đồng nghĩa với|cũng có nghĩa là|tương đương với|'
        r'giống với|còn gọi là|cũng gọi là|hay còn gọi)\s+(.+)',
        re.IGNORECASE)
    _SYNONYM_EN = re.compile(
        r'(.+?)\s+(?:is synonymous with|means the same as|'
        r'is the same as|is another word for|equals)\s+(.+)',
        re.IGNORECASE)

    # ════════════════════════════════════════════════════════════
    # ASK PATTERNS
    # ════════════════════════════════════════════════════════════
    _ASK_VI = re.compile(r'^(.+?)\s+là gì\s*\??$',                  re.IGNORECASE)
    _ASK_EN = re.compile(r'^(?:what is|what are|define)\s+(.+?)\s*\??$', re.IGNORECASE)
    _ASK_JP = re.compile(
        r'^(.+?)(?:は何ですか|とは何ですか|って何ですか|は何\?|とは何|って何|は何)\s*\??$'
    )

    # ════════════════════════════════════════════════════════════
    # GREETING TOKENS
    # ════════════════════════════════════════════════════════════
    _GREET_TOKENS = {
        "vi": {
            "xin chào", "chào", "chào bạn", "chào anh", "chào chị", "chào em",
            "tạm biệt", "bye", "hẹn gặp lại", "chào tạm biệt",
            "cảm ơn", "cám ơn", "cảm ơn bạn", "cảm ơn nhiều",
            "xin lỗi", "không có gì", "ok", "ổn", "được rồi",
            "hi", "hello",
        },
        "en": {
            "hello", "hi", "hey", "goodbye", "bye", "see you",
            "thank you", "thanks", "sorry", "no problem",
            "good morning", "good afternoon", "good evening", "good night",
            "how are you", "are you okay", "how is it going",
            "whats up", "what is up", "nice to meet you",
        },
        "jp": {
            "こんにちは", "こんばんは", "おはよう", "おはようございます",
            "さようなら", "またね", "ありがとう", "ありがとうございます",
            "すみません", "どういたしまして", "よろしく",
        },
    }

    # Từ bắt đầu câu DẠY (dùng để phân biệt với CONVERSE)
    _TEACH_STARTERS_VI = {
        "khi", "nếu", "nghe", "hễ", "lúc", "mỗi khi", "khi nào",
    }

    # ════════════════════════════════════════════════════════════
    # PUBLIC
    # ════════════════════════════════════════════════════════════

    def detect(self, parsed: ParsedInput) -> Intent:
        clean = parsed.clean.strip()
        lang  = parsed.language

        # Thứ tự quan trọng: GREET → TEACH → SYNONYM → ASK → FACT → CONVERSE

        if self._is_greeting(clean, lang):
            return Intent("GREET", 0.95, {"text": clean, "lang": lang})

        teach = self._match_teach_phrase(clean)
        if teach:
            return Intent("TEACH_PHRASE", 0.95, teach)

        syn = self._match_synonym(clean, lang)
        if syn:
            return Intent("TEACH_SYNONYM", 0.90, syn)

        ask = self._match_ask(clean, lang)
        if ask:
            return Intent("ASK_DEFINITION", 0.90, ask)

        # TEACH_FACT: chỉ nhận nếu câu đơn giản "A là B"
        # Không nhận các câu dài/phức tạp (tránh nhầm hội thoại)
        fact = self._match_fact(clean, lang)
        if fact:
            return Intent("TEACH_FACT", 0.80, fact)

        return Intent("CONVERSE", 0.50, {"text": clean, "lang": lang})

    # ════════════════════════════════════════════════════════════
    # PRIVATE
    # ════════════════════════════════════════════════════════════

    def _is_greeting(self, clean: str, lang: str) -> bool:
        all_greets: set = set()
        for tokens in self._GREET_TOKENS.values():
            all_greets |= tokens

        if clean in all_greets:
            return True

        # "chào bạn ơi" vẫn là greeting nếu bắt đầu bằng greeting + max 10 ký tự thêm
        for g in all_greets:
            if clean.startswith(g) and len(clean) <= len(g) + 10:
                return True

        return False

    def _match_teach_phrase(self, clean: str) -> Optional[Dict]:
        """
        Thử từng pattern trong _TEACH_PATTERNS theo thứ tự.
        Trả về {"trigger": ..., "response": ...} hoặc None.
        """
        for pattern, g_trig, g_resp in self._TEACH_PATTERNS:
            m = pattern.match(clean)
            if m:
                trigger  = m.group(g_trig).strip().strip('"\'')
                response = m.group(g_resp).strip().strip('"\'')
                # Validate: cả 2 phải có nội dung thật
                if trigger and response and len(trigger) >= 2 and len(response) >= 2:
                    return {"trigger": trigger, "response": response}
        return None

    def _match_synonym(self, clean: str, lang: str) -> Optional[Dict]:
        for pattern in (self._SYNONYM_VI, self._SYNONYM_EN):
            m = pattern.match(clean)
            if m:
                w1 = m.group(1).strip()
                w2 = m.group(2).strip()
                if w1 and w2:
                    return {"word1": w1, "word2": w2}
        return None

    def _match_ask(self, clean: str, lang: str) -> Optional[Dict]:
        # Ưu tiên pattern của ngôn ngữ hiện tại trước
        lang_first = {
            "vi": [self._ASK_VI, self._ASK_EN, self._ASK_JP],
            "en": [self._ASK_EN, self._ASK_VI, self._ASK_JP],
            "jp": [self._ASK_JP, self._ASK_VI, self._ASK_EN],
        }.get(lang, [self._ASK_VI, self._ASK_EN, self._ASK_JP])

        for pattern in lang_first:
            m = pattern.match(clean)
            if m:
                target = m.group(1).strip()
                if target:
                    return {"target": target, "lang": lang}
        return None

    # ── Từ bắt đầu câu KHÔNG phải fact (câu hội thoại, phản hồi) ──────
    _NON_FACT_STARTERS = {
        # Phản hồi / đồng ý / xác nhận
        "được", "ừ", "ừm", "vâng", "dạ", "ok", "okay", "oke",
        "đúng", "đúng rồi", "thôi", "thôi được", "rồi",
        # Cảm thán
        "ôi", "ồ", "à", "ơi", "trời", "wow", "ừa",
        # Phủ định
        "không", "chưa", "chẳng",
        # Đại từ nhân xưng đứng đầu (câu hội thoại)
        "tôi", "mình", "em", "anh", "chị",
        # Tiếng Anh
        "yes", "no", "yeah", "yep", "nope", "sure", "okay",
        "oh", "wow", "well", "so",
    }

    # Subject KHÔNG bao giờ là fact (đại từ nhân xưng)
    _PRONOUN_SUBJECTS = {
        "tôi", "mình", "tớ", "ta", "em", "anh", "chị",
        "bạn", "cậu", "mày", "nó", "hắn", "họ",
        "i", "you", "he", "she", "we", "they", "it",
    }

    def _match_fact(self, clean: str, lang: str) -> Optional[Dict]:
        """
        Chỉ nhận câu fact đơn giản kiểu A là B.

        Từ chối khi:
          - Câu bắt đầu bằng từ dạy (khi/nếu) hoặc từ hội thoại (được/ừ...)
          - Câu quá dài (> 8 tokens)
          - Subject là đại từ nhân xưng (tôi, bạn, mình...)
          - Predicate dài > 4 tokens (hội thoại thường dài hơn)
          - Subject dài > 3 tokens
        """
        tokens = clean.split()
        if not tokens:
            return None

        first = tokens[0]

        # Từ chối: bắt đầu bằng teach starters
        if first in self._TEACH_STARTERS_VI:
            return None

        # Từ chối: bắt đầu bằng từ hội thoại / phản hồi
        if first in self._NON_FACT_STARTERS:
            return None

        # Từ chối: câu dài (fact thường ngắn)
        if len(tokens) > 8:
            return None

        patterns = {
            "vi": self._FACT_VI,
            "en": self._FACT_EN,
            "jp": self._FACT_JP,
        }
        pattern = patterns.get(lang, self._FACT_VI)
        m = pattern.match(clean)
        if not m:
            return None

        subj = m.group(1).strip()
        pred = m.group(2).strip()

        if not subj or not pred:
            return None

        # Từ chối: subject là đại từ nhân xưng
        if subj.lower() in self._PRONOUN_SUBJECTS:
            return None

        # Từ chối: subject hoặc predicate quá dài
        if len(subj.split()) > 3 or len(pred.split()) > 4:
            return None

        # Từ chối: predicate chứa dấu hiệu hội thoại
        pred_first = pred.split()[0] if pred.split() else ""
        if pred_first in self._NON_FACT_STARTERS:
            return None

        # Từ chối: predicate là question pattern
        # "là gì không" / "là gì vậy" / "là what" → câu hỏi, không phải fact
        _Q_PREDICATES = {
            "gì không", "gì vậy", "gì thế", "gì hả", "gì á",
            "gì đó không", "gì ạ", "what", "which", "who",
        }
        pred_lower = pred.lower().strip()
        for qp in _Q_PREDICATES:
            if pred_lower == qp or pred_lower.startswith(qp):
                return None

        # Từ chối: subject chứa động từ nhận thức
        # "en biết car" → "biết" là cognitive verb → không phải fact
        _COGNITIVE = {"biết", "hiểu", "thấy", "nghe", "nghĩ",
                      "know", "think", "see", "hear", "understand"}
        if set(subj.lower().split()) & _COGNITIVE:
            return None

        return {"subject": subj, "predicate": pred, "lang": lang}