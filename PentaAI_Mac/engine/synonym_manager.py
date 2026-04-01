# engine/synonym_manager.py
"""
SynonymManager — Quản lý từ đồng nghĩa. [PATCHED]

Thay đổi so với bản gốc:
  1. BUG FIX: _same_script() chuyển vào TRONG class (hàm module-level gây lỗi import)
  2. vary() an toàn hơn:
     - Chỉ swap từ đơn (1 token), không swap cụm từ → tránh vỡ ngữ pháp
     - Thêm _is_safe_to_swap() kiểm tra trước khi swap
     - Không swap từ trong ngoặc kép, tên riêng (hoa đầu)
     - SYNONYM_SWAP_PROB mặc định giảm: dùng prob=0.12 thay 0.20
  3. get_synonyms() thêm filter: chỉ trả synonym cùng loại từ (cùng script)
  4. Thêm are_near_synonyms() — match gần đúng (prefix/suffix)
  5. SEED bổ sung thêm từ tiếng Việt thông dụng
"""

import re
import random
from typing import List, Optional


# ── Config ────────────────────────────────────────────────────────
# FIX: giảm xác suất swap mặc định (gốc là 0.20, gây vỡ câu)
DEFAULT_SWAP_PROB = 0.12

try:
    from config import SYNONYM_SWAP_PROB
except ImportError:
    SYNONYM_SWAP_PROB = DEFAULT_SWAP_PROB


class SynonymManager:
    """Quản lý từ đồng nghĩa với seed dictionary tích hợp sẵn."""

    # ── SEED SYNONYMS ─────────────────────────────────────────────
    SEED: dict = {
        # Đại từ nhân xưng
        "tôi":      ["mình", "tớ", "ta", "em", "con"],
        "bạn":      ["cậu", "anh", "chị", "bạn ơi", "bạn nhé"],
        "chúng tôi":["bọn tôi", "chúng mình", "tụi mình"],

        # Chào hỏi
        "xin chào": ["chào bạn", "chào", "hello", "hi"],
        "tạm biệt": ["bye", "hẹn gặp lại", "chào nhé", "bye bye"],
        "cảm ơn":   ["cám ơn", "cảm ơn bạn", "thanks", "thank you", "cảm ơn nhiều"],
        "xin lỗi":  ["sorry", "thông cảm", "xin thứ lỗi"],
        "không có gì": ["không sao", "không vấn đề gì", "no problem", "đừng lo"],

        # Trạng thái / cảm xúc
        "khỏe":     ["ổn", "tốt", "bình thường", "fine", "okay"],
        "mệt":      ["mệt mỏi", "uể oải", "kiệt sức", "tired"],
        "vui":      ["vui vẻ", "hạnh phúc", "phấn khởi", "happy"],
        "buồn":     ["buồn bã", "u sầu", "sad", "không vui"],
        "lo":       ["lo lắng", "lo âu", "băn khoăn", "worried"],
        "sợ":       ["sợ hãi", "e ngại", "scared", "afraid"],

        # Tính từ
        "tốt":      ["hay", "tốt lành", "giỏi", "good", "great"],
        "đẹp":      ["xinh", "xinh đẹp", "duyên dáng", "tuyệt vời", "beautiful"],
        "nhanh":    ["mau", "lẹ", "nhanh chóng", "fast", "quick"],
        "chậm":     ["chậm chạp", "ì ạch", "slow"],
        "lớn":      ["to", "to lớn", "rộng lớn", "big", "large"],
        "nhỏ":      ["bé", "nhỏ bé", "tí hon", "small", "tiny"],
        "ngon":     ["ngon lành", "ngon miệng", "delicious", "tasty", "yummy"],
        "hay":      ["thú vị", "hấp dẫn", "tốt", "interesting", "nice"],
        "khó":      ["khó khăn", "phức tạp", "hard", "difficult"],
        "dễ":       ["đơn giản", "dễ dàng", "easy", "simple"],

        # Động từ
        "nói":      ["phát biểu", "chia sẻ", "kể", "nói chuyện"],
        "hiểu":     ["nắm được", "lĩnh hội", "biết", "understand"],
        "biết":     ["hiểu", "nắm được", "know"],
        "học":      ["học hỏi", "tiếp thu", "trau dồi", "learn", "study"],
        "nhớ":      ["ghi nhớ", "lưu lại", "không quên", "remember"],
        "thích":    ["yêu thích", "ưa", "ưa thích", "like", "love"],
        "muốn":     ["mong muốn", "mong", "mong đợi", "want", "wish"],
        "ăn":       ["dùng", "thưởng thức", "ăn uống", "eat"],
        "đi":       ["di chuyển", "tới", "đến", "go", "travel"],
        "làm":      ["thực hiện", "thực hiện", "do", "work on"],

        # Phản hồi đồng ý / không đồng ý
        "đúng rồi": ["đúng vậy", "chính xác", "ừ đúng", "correct", "exactly"],
        "không":    ["không phải", "không đúng", "no", "nope"],
        "có":       ["đúng", "ừ", "yes", "yeah"],

        # Hỏi thăm
        "bạn có khỏe không": ["bạn khỏe không", "bạn ổn không", "how are you"],
        "bạn thế nào":       ["bạn ra sao", "bạn có ổn không", "how's it going"],

        # Biểu đạt cảm xúc mạnh
        "tuyệt vời": ["xuất sắc", "tuyệt", "quá tốt", "wonderful", "amazing", "awesome"],
        "thật sự":   ["thực sự", "quả thật", "really", "truly"],

        # Tiếng Anh
        "hello":    ["hi", "hey", "greetings"],
        "goodbye":  ["bye", "see you", "farewell", "take care"],
        "good":     ["great", "nice", "wonderful", "excellent"],
        "bad":      ["poor", "terrible", "awful"],
        "happy":    ["joyful", "glad", "pleased", "delighted"],
        "sad":      ["unhappy", "down", "gloomy"],
        "fast":     ["quick", "rapid", "swift"],
        "beautiful":["pretty", "gorgeous", "lovely"],
        "understand":["get it", "know", "grasp"],
        "very":     ["really", "quite", "so", "extremely"],
        "maybe":    ["perhaps", "probably", "possibly"],

        # Tiếng Nhật
        "こんにちは": ["やあ", "どうも"],
        "ありがとう": ["ありがとうございます", "どうもありがとう", "サンキュー"],
        "さようなら": ["またね", "じゃあね", "バイバイ"],
        "わかった":   ["なるほど", "了解", "OK"],
        "元気":      ["大丈夫", "よい", "絶好調"],
    }

    def __init__(self, store=None):
        self._store = store
        self._reverse: dict = {}
        for canonical, syns in self.SEED.items():
            self._reverse[canonical] = canonical
            for s in syns:
                self._reverse[s] = canonical

    # ── PUBLIC ────────────────────────────────────────────────────

    def get_synonyms(self, word: str, same_script_only: bool = True) -> List[str]:
        """
        Trả về tất cả đồng nghĩa (seed + learned).
        FIX: same_script_only=True → chỉ trả synonym cùng hệ chữ.
        """
        w = word.lower().strip()
        result = set()

        canonical = self._reverse.get(w, w)
        if canonical in self.SEED:
            result.update(self.SEED[canonical])
            result.add(canonical)
        if w in self.SEED:
            result.update(self.SEED[w])

        if self._store:
            learned = self._store.get_synonyms(w)
            result.update(learned)

        result.discard(w)
        result.discard(word)

        # FIX: lọc cùng script để tránh mix VI↔EN trong câu
        if same_script_only:
            result = {s for s in result if self._same_script(word, s)}

        return list(result)

    def random_synonym(self, word: str) -> str:
        syns = self.get_synonyms(word)
        return random.choice(syns) if syns else word

    def vary(self, text: str, prob: float = SYNONYM_SWAP_PROB) -> str:
        """
        Thay một số từ trong text bằng đồng nghĩa ngẫu nhiên.

        FIX so với bản gốc:
          - Không swap từ có hoa đầu (tên riêng)
          - Không swap từ trong ngoặc kép hoặc nháy đơn
          - Không swap cụm nhiều từ (chỉ xử lý từng token)
          - prob mặc định giảm từ 0.20 → 0.12
        """
        # Phát hiện vùng ngoặc kép (không swap)
        protected = set()
        for m in re.finditer(r'["\'](.+?)["\']', text):
            for i in range(m.start(), m.end()):
                protected.add(i)

        words  = text.split()
        result = []
        char_pos = 0

        for word in words:
            punct = ""
            clean = word
            if word and word[-1] in ".,!?:;":
                punct  = word[-1]
                clean  = word[:-1]

            # FIX: không swap nếu từ trong vùng protected (ngoặc kép)
            in_protected = any(char_pos + i in protected for i in range(len(word)))
            char_pos += len(word) + 1

            if (not in_protected
                    and random.random() < prob
                    and self._is_safe_to_swap(clean)):
                syns = self.get_synonyms(clean, same_script_only=True)
                if syns:
                    close = [s for s in syns if abs(len(s) - len(clean)) <= 4]
                    chosen = random.choice(close if close else syns)
                    result.append(chosen + punct)
                    continue

            result.append(word)
        return " ".join(result)

    def are_synonyms(self, w1: str, w2: str) -> bool:
        return w2.lower() in {s.lower() for s in self.get_synonyms(w1)}

    def are_near_synonyms(self, w1: str, w2: str) -> bool:
        """
        FIX: Match gần đúng — check cả trường hợp một từ là prefix của synonym.
        VD: "thích" ↔ "yêu thích" → True
        """
        w1l, w2l = w1.lower(), w2.lower()
        syns = self.get_synonyms(w1, same_script_only=False)
        for s in syns:
            if w2l == s or w2l in s or s in w2l:
                return True
        return self.are_synonyms(w1, w2)

    # ── PRIVATE ───────────────────────────────────────────────────

    @staticmethod
    def _same_script(a: str, b: str) -> bool:
        """
        FIX: Chuyển từ module-level function vào trong class.
        Gốc: định nghĩa ngoài class → lỗi NameError khi import module riêng lẻ.
        """
        has_latin_a = bool(re.search(r"[a-zA-Z]", a))
        has_latin_b = bool(re.search(r"[a-zA-Z]", b))
        has_viet_a  = bool(re.search(
            r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", a))
        has_viet_b  = bool(re.search(
            r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", b))
        # Nếu một bên có dấu VI và bên kia không → khác script
        if has_viet_a != has_viet_b:
            return False
        # Latin thuần (không dấu VI) vs Vietnamese → khác script
        if has_latin_a and not has_viet_a and has_viet_b:
            return False
        return True

    @staticmethod
    def _is_safe_to_swap(word: str) -> bool:
        """
        FIX: Kiểm tra từ có an toàn để swap không.
        Không swap:
          - Từ rỗng hoặc 1 ký tự
          - Từ hoa đầu (tên riêng, viết tắt)
          - Từ là số hoặc có ký tự đặc biệt
          - Từ rất ngắn (< 2 ký tự)
        """
        if not word or len(word) < 2:
            return False
        # Tên riêng (hoa đầu, không phải đầu câu) → bỏ qua
        if word[0].isupper() and not word.isupper():
            return False
        # Số
        if word.replace(",", "").replace(".", "").isdigit():
            return False
        # Ký tự đặc biệt
        if re.search(r"[{}()\[\]<>@#$%^&*]", word):
            return False
        return True
