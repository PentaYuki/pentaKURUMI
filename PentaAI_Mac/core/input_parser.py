# core/input_parser.py
"""
InputParser — Tầng 1.
Chỉ làm 1 việc: nhận raw string → trả ParsedInput.
KHÔNG quyết định logic gì cả.
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ParsedInput:
    raw: str                        # Nguyên văn
    clean: str                      # Đã lowercase + strip
    tokens: List[str]               # Danh sách từ
    language: str                   # "vi" | "en" | "jp" | "unknown"
    has_question_mark: bool
    has_japanese: bool
    has_vietnamese_accent: bool


# ── TYPO MAP: ký tự hay gõ sai trong tiếng Việt ─────────────────
# Mapping từ gõ thiếu dấu → có dấu phổ biến
# Chỉ áp dụng cho TỪNG TỪ riêng lẻ, không phải toàn câu
_COMMON_TYPOS = {
    # Thiếu dấu hỏi/ngã/sắc/huyền/nặng trên từ phổ biến
    "ban":   "bạn",
    "minh":  "mình",
    "khoe":  "khỏe",
    "on":    "ổn",  
    "met":   "mệt",
    "vui":   "vui",   # đúng rồi
    "buon":  "buồn",
    "chao":  "chào",
    "cam":   "cảm",
    "ten":   "tên",
    "gi":    "gì",
    "gi":    "gì",
    "noi":   "nói",
    "nghe":  "nghe",   # đúng rồi
    "biet":  "biết",
    "hieu":  "hiểu",
    "duoc":  "được",
    "khong": "không",
    "co":    "có",
    "la":    "là",
    "tot":   "tốt",
    "xau":   "xấu",
    "dep":   "đẹp",
    "lon":   "lớn",
    "nho":   "nhỏ",
    "nhanh": "nhanh",
    "cham":  "chậm",
}


class InputParser:
    """Tokenize và detect ngôn ngữ. Không có state."""

    # Ký tự có dấu tiếng Việt
    _VI_ACCENT = re.compile(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ'
                             r'òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'
                             r'ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨ'
                             r'ÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]')

    # Kana / Kanji
    _JP_CHARS = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')

    # Từ khóa tiếng Việt không dấu phổ biến
    _VI_KEYWORDS = {
        'la', 'co', 'khong', 'ban', 'toi', 'minh', 'cua', 'va',
        'trong', 'nay', 'do', 'gi', 'nhu', 'hay', 'cung', 'vay',
        'roi', 'nhe', 'nha', 'di', 'xin', 'chao', 'cam', 'on',
    }

    # Từ khóa tiếng Anh rõ ràng
    _EN_KEYWORDS = {
        'the', 'is', 'are', 'was', 'were', 'have', 'has', 'do',
        'does', 'what', 'how', 'where', 'when', 'why', 'who',
        'hello', 'hi', 'bye', 'yes', 'no', 'please', 'thank',
        'thanks', 'good', 'morning', 'evening', 'night',
        # Thêm: đại từ, động từ thường, tính từ EN phổ biến
        'you', 'i', 'we', 'they', 'he', 'she', 'it', 'my', 'your',
        'will', 'would', 'can', 'could', 'should', 'may', 'might',
        'like', 'love', 'want', 'need', 'know', 'think', 'feel',
        'eat', 'drink', 'go', 'come', 'make', 'get', 'say', 'see',
        'okay', 'sure', 'great', 'nice', 'fine', 'bad', 'happy', 'sad',
        'and', 'or', 'but', 'not', 'very', 'just', 'also', 'too',
    }

    def parse(self, text: str) -> ParsedInput:
        raw   = text
        clean = text.lower().strip()

        has_vi_accent = bool(self._VI_ACCENT.search(text))
        has_jp        = bool(self._JP_CHARS.search(text))

        # Normalize typos ở token level
        clean = self._normalize_typos(clean)

        tokens = self._tokenize(clean)

        language = self._detect_language(
            clean, tokens, has_vi_accent, has_jp
        )

        return ParsedInput(
            raw=raw,
            clean=clean,
            tokens=tokens,
            language=language,
            has_question_mark=clean.endswith('?') or 'là gì' in clean
                              or 'what is' in clean or 'は何' in clean,
            has_japanese=has_jp,
            has_vietnamese_accent=has_vi_accent,
        )

    # ── private ──────────────────────────────────────────────────

    def _normalize_typos(self, text: str) -> str:
        """
        Sửa lỗi gõ thiếu dấu ở cấp độ TỪNG TOKEN riêng lẻ.
        Mỗi token được kiểm tra độc lập:
          - Nếu token đã có dấu → giữ nguyên
          - Nếu token không có dấu và có trong _COMMON_TYPOS → sửa
        VD: "ban tên là gì" → "bạn tên là gì"
            ("ban" không dấu → sửa, "tên/là/gì" có dấu → giữ)
        """
        import re as _re
        _VI_ACCENT_RE = _re.compile(
            r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ"
            r"òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
            r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄ]"
        )
        words  = text.split()
        result = []
        for word in words:
            # Tách dấu câu cuối từ
            punct      = ""
            clean_word = word
            while clean_word and clean_word[-1] in ".,!?:;":
                punct      = clean_word[-1] + punct
                clean_word = clean_word[:-1]

            lower = clean_word.lower()

            # Chỉ sửa nếu token này KHÔNG có dấu tiếng Việt
            if not _VI_ACCENT_RE.search(clean_word) and lower in _COMMON_TYPOS:
                result.append(_COMMON_TYPOS[lower] + punct)
            else:
                result.append(word)

        return " ".join(result)

    def _tokenize(self, clean: str) -> List[str]:
        """Tách từ, giữ từ ghép phổ biến."""
        # Xóa dấu câu cuối
        text = re.sub(r'[?!.,;:]+$', '', clean).strip()
        # Tách theo khoảng trắng, lọc rỗng
        return [t for t in text.split() if t]

    def _detect_language(
        self,
        clean: str,
        tokens: List[str],
        has_vi_accent: bool,
        has_jp: bool,
    ) -> str:
        if has_jp:
            return "jp"
        if has_vi_accent:
            return "vi"

        token_set = set(tokens)

        vi_hits = len(token_set & self._VI_KEYWORDS)
        en_hits = len(token_set & self._EN_KEYWORDS)

        if vi_hits > en_hits:
            return "vi"
        if en_hits > vi_hits:
            return "en"
        if vi_hits == 0 and en_hits == 0:
            # Heuristic: tiếng Việt hay dùng từ 1-2 âm tiết ngắn
            avg_len = sum(len(t) for t in tokens) / max(len(tokens), 1)
            return "vi" if avg_len < 5 else "en"

        return "vi"  # default