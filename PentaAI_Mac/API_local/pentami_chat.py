"""
pentami_chat.py — PentaMi Chat Module

Hai mode:
  - chat()        : blocking (dùng cho CLI/fallback)
  - chat_stream() : streaming token-by-token (dùng cho iOS WebSocket)

Kiến trúc llm backend (06/2025):
  Tier 1: Ollama 1B (nhanh, câu đơn giản)
  Tier 2: MLX-vLLM Qwen2.5-7B-Instruct-4bit (embedded, streaming real-time)
  Tier 3: Cloud (fallback cuối)
"""

import json
import logging
import os
import re
import time
import threading
from collections import deque
from typing import Iterator, List, Dict, Optional, Tuple

import requests

log = logging.getLogger("PentaMiChat")

# Dùng mlx_client trực tiếp — bonsai_client.py là shim trỏ về đây
from .mlx_client import get_mlx_client as get_bonsai_client
from memory.knowledge_store import KnowledgeStore
from .penta_memory import PentaMemory
from engine.phrase_engine import PhraseEngine
from engine.response_builder import ResponseBuilder
from engine.synonym_manager import SynonymManager

# API_local/ là sub-package → ROOT phải trỏ lên PentaAI_Mac/
ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(ROOT, "data")
CONTEXT_FILE = os.path.join(DATA_DIR, "pentami_context.json")

# Giữ 5 lượt (10 tin nhắn) — cân bằng giữa trí nhớ và tốc độ prefill.
MAX_CONTEXT_TURNS = 5


def _load_pentami_cfg() -> dict:
    cfg_path = os.path.join(ROOT, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── System prompt (rút gọn ~60 tokens, giảm từ ~150) ─────────────────────────
# Bỏ hết dư thừa — model 8B đủ thông minh, cần prefill nhanh cho first-token
_SYSTEM_PROMPT_TEMPLATE = """\
Bạn là trợ lý AI {ai_name}. Xưng hô CỐ ĐỊNH: '{ai_pronoun}' gọi người dùng là '{user_pronoun}'.
Quy tắc: Thân thiện, ấm áp. Trả lời cực kỳ ngắn gọn, súc tích (tối đa 2-3 câu)."""
# Fix 2 (KV Cache): facts_line đã chuyển sang seed 1 lần vào đầu history
# → system prompt bất biến mỗi turn → llama.cpp KV cache hit mọi lần

# ── Fix 4: Smart Routing ───────────────────────────────────────────────────────
_SIMPLE_WORDS = {
    "ok", "oke", "hihi", "hehe", "haha", "ừ", "ừm", "ờ", "à",
    "được", "thôi", "uhm", "hmm", "good", "cool", "hay đó",
    "xong", "cảm ơn", "cám ơn", "thanks", "thank", "yeah", "yep",
}

# ── Enhanced simple word detection for Ollama routing ─────────────────────────
_SIMPLE_WORDS_EXTENDED = _SIMPLE_WORDS | {
    "vâng", "vâng ạ", "dạ", "dạ ạ", "ơi", "em", "anh", "chị", "em nha",
    "lol", "😂", "😆", "😸", "nice", "great", "awesome", "thôi mà", "được rồi",
    "biết rồi", "hiểu rồi", "ok rồi", "yup", "nope", "nah", "yeah yeah",
}

_FAST_QUERY_PREFIXES = (
    "làm sao", "cách", "như nào", "như thế nào", "bao lâu", "bao nhiêu",
    "là gì", "vì sao", "tại sao", "how to", "what is", "why",
)

_EMOTIONAL_HINTS = {
    "tâm sự", "cô đơn", "buồn", "mệt", "stress", "áp lực", "nhớ", "yêu",
    "giận", "sợ", "lo", "hurt", "sad", "lonely", "anxious",
}

_COMPLEX_HINTS = {
    "phân tích", "so sánh", "chi tiết", "kế hoạch", "lộ trình", "đề xuất",
    "tư duy", "lập luận", "nguyên nhân", "hệ thống", "kiến trúc", "optimize",
    "debug", "thiết kế", "chiến lược", "triết học", "nhân sinh", "tình cảm",
}

_WIBU_SUFFIXES = [" nha, senpai.", " nè~", " đó nha."]

_LEADING_FILLERS_RE = re.compile(r"^(?:\s)*(?:ủa|ua|à|ờ|ơ|ơ kìa|nè|nha|hả|ê|êm|này)(?:[\s,!.?]+)", re.IGNORECASE)
_LEADING_MODEL_NOISE_RE = re.compile(
    r"^(?:\s)*(?:assistant|bot|ai|penta\s*mi|pentami|senpai|nè|nha|ê)(?:\s*[:,-]+\s*|\s+)",
    re.IGNORECASE,
)

_VI_INPUT_TYPOS = {
    "ban": "bạn",
    "minh": "mình",
    "khoe": "khỏe",
    "on": "ổn",
    "met": "mệt",
    "buon": "buồn",
    "chao": "chào",
    "cam": "cảm",
    "ten": "tên",
    "gi": "gì",
    "noi": "nói",
    "biet": "biết",
    "hieu": "hiểu",
    "duoc": "được",
    "khong": "không",
    "co": "có",
    "la": "là",
    "tot": "tốt",
    "xau": "xấu",
    "dep": "đẹp",
    "lon": "lớn",
    "nho": "nhỏ",
    "cham": "chậm",
}

_VI_OUTPUT_FIXES = {
    "tôts": "tốt",
    "tôt": "tốt",
    "hoctap": "học tập",
}

_VI_ACCENT_RE = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ"
    r"òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄ]"
)


def _normalize_input_text(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return ""
    return _LEADING_FILLERS_RE.sub("", t, count=1).strip() or t


def _normalize_vi_typos(text: str) -> str:
    words = str(text or "").split()
    out: List[str] = []
    for word in words:
        punct = ""
        base = word
        while base and base[-1] in ".,!?:;":
            punct = base[-1] + punct
            base = base[:-1]

        lower = base.lower()
        if base and (not _VI_ACCENT_RE.search(base)) and lower in _VI_INPUT_TYPOS:
            out.append(_VI_INPUT_TYPOS[lower] + punct)
        else:
            out.append(word)
    return " ".join(out)


def _sanitize_model_output_text(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return ""
    t = _LEADING_MODEL_NOISE_RE.sub("", t, count=1).strip()
    for wrong, fixed in _VI_OUTPUT_FIXES.items():
        t = re.sub(rf"\b{re.escape(wrong)}\b", fixed, t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def _is_simple(text: str) -> bool:
    """Trả True nếu câu rất ngắn/casual/vô thưởng vô phạt → route sang Ollama 1B.
    Câu có dấu hỏi hoặc dài hơn 40 ký tự sẽ được xử lý bởi MLX Qwen2.5-7B."""
    t = text.strip()
    if len(t) > 40 or "?" in t:
        return False
    
    tl = t.lower()
    # Exact match các từ casual
    if tl in _SIMPLE_WORDS_EXTENDED:
        return True
    
    # Chỉ match prefix/suffix cho các từ cực ngắn, không áp dụng cho mọi câu
    if len(t) < 15:
        if any(tl.startswith(w + " ") or tl.endswith(" " + w) for w in _SIMPLE_WORDS_EXTENDED):
            return True

    return False


def _is_fast_factual_query(text: str) -> bool:
    """Route câu hỏi kiến thức ngắn sang Ollama để giảm latency.
    Tránh route các câu thiên cảm xúc/tâm sự vì cần chất lượng cao hơn từ Bonsai.
    """
    t = _normalize_input_text(text)
    if not t:
        return False
    if len(t) > 90:
        return False

    tl = t.lower()
    if any(h in tl for h in _EMOTIONAL_HINTS):
        return False

    if any(tl.startswith(p) for p in _FAST_QUERY_PREFIXES):
        return True
    if any(k in tl for k in (" làm sao ", " cách ", " là gì", " bao lâu", " bao nhiêu", " tại sao", " vì sao")):
        return True
    return False


def _should_use_bonsai_for_text(text: str) -> bool:
    """MLX Qwen2.5-7B chỉ dành cho câu phức tạp; câu thường ưu tiên Ollama để nhanh.
    Tên hàm giữ nguyên để backward compat với ai_server.py."""
    # NOTE: tên 'bonsai' giữ nguyên cho backward compat nhưng thực tế gọi MLX engine
    t = _normalize_input_text(text)
    if not t:
        return False
    tl = t.lower()
    if len(t) >= 120:
        return True
    if any(h in tl for h in _COMPLEX_HINTS):
        return True
    # Câu giàu cảm xúc + hỏi dài thường cần Bonsai hơn.
    if any(h in tl for h in _EMOTIONAL_HINTS) and ("?" in tl or len(t) > 60):
        return True
    return False


# Toggle / teach patterns (giữ nguyên từ bản gốc)
_RE_TOGGLE_ON  = re.compile(r'(?:bật|mở|on|kích\s*hoạt|start|enable)\s*(?:chế\s*độ\s*)?(?:pentami|penta\s*mi)', re.IGNORECASE)
_RE_TOGGLE_OFF = re.compile(r'(?:tắt|đóng|off|vô\s*hiệu|stop|disable)\s*(?:chế\s*độ\s*)?(?:pentami|penta\s*mi)', re.IGNORECASE)
_RE_TOGGLE_ON_THINK  = re.compile(r'(?:bật|mở|on|kích\s*hoạt|start|enable)\s*(?:chế\s*độ\s*)?(?:pentami\s*t|penta\s*mi\s*t|pentamit)', re.IGNORECASE)
_RE_TOGGLE_OFF_THINK = re.compile(r'(?:tắt|đóng|off|vô\s*hiệu|stop|disable)\s*(?:chế\s*độ\s*)?(?:pentami\s*t|penta\s*mi\s*t|pentamit)', re.IGNORECASE)
_RE_CLEAR_CTX  = re.compile(r'(?:xoá|xóa|clear|reset|quên)\s*(?:ngữ\s*cảnh|context|hội\s*thoại)', re.IGNORECASE)
_RE_TEACH_PATTERNS = [
    re.compile(r'(?:nhớ nhé|biết không|ghi nhớ|nhớ lấy)[,: ]+(.+?)\s+là\s+(.+)', re.IGNORECASE),
    re.compile(r'(?:dạy|học|cho\s+biết)[: ]+(.+?)\s+là\s+(.+)',                   re.IGNORECASE),
    re.compile(r'(?:remember|note|know\s+that|fyi)[,: ]+(.+?)\s+is\s+(.+)',       re.IGNORECASE),
    re.compile(r'(?:覚えて|メモ|覚えておいて)[,: ]*(.+?)[はが](.+)',              re.IGNORECASE),
]
_SKIP_SUBJECTS = {"hôm nay","bây giờ","lúc này","anh","em","tôi","mình","bạn","chúng ta","nó","họ"}


def check_toggle(text: str) -> Optional[str]:
    t = text.strip()
    if _RE_TOGGLE_ON_THINK.search(t):  return "on_thinking"
    if _RE_TOGGLE_OFF_THINK.search(t): return "off_thinking"
    if _RE_TOGGLE_ON.search(t):  return "on"
    if _RE_TOGGLE_OFF.search(t): return "off"
    if _RE_CLEAR_CTX.search(t):  return "clear"
    return None


def _is_simple_query(text: str) -> bool:
    """
    Heuristic để quyết định dùng mô hình Nhanh (1B) hay mô hình Não (7B).
    """
    t = text.strip()
    tl = t.lower()
    
    # 1. Câu hỏi cực ngắn (<35 ký tự) có dấu ? -> Xem là đơn giản
    if "?" in t and len(t) < 35:
        return True
    
    # 2. Câu quá dài (>90 ký tự) -> Phức tạp
    if len(t) > 90:
        return False
        
    # 3. Chứa keyword chuyên sâu
    complex_kws = [
        "phân tích", "giải thích", "so sánh", "code", "lập trình",
        "kế hoạch", "lịch sử", "tâm lý", "chính trị", "tóm tắt", "hướng dẫn"
    ]
    if any(kw in tl for kw in complex_kws) and len(t) > 30:
        return False
        
    # 4. Câu dài vừa phải (>40) mà không phải câu hỏi cực ngắn -> Phức tạp
    if len(t) > 40:
        return False
        
    return True


class PentaMiChat:
    def __init__(self):
        # _bonsai attribute trỏ tới MLXClient (Qwen2.5-7B) qua alias shim
        self._bonsai  = get_bonsai_client()
        self._store   = KnowledgeStore()
        self._context: deque = deque(maxlen=MAX_CONTEXT_TURNS * 2)
        self._lock    = threading.Lock()
        self._profile: Dict = {}
        self._profile_mtime: float = 0.0   # Cache profile, không load file mỗi lần
        self._cached_system_prompt: Optional[str] = None  # Fix 2: KV cache
        self._bonsai = get_bonsai_client()
        self.store = KnowledgeStore()
        self._phrase_engine = PhraseEngine()
        self._syn = SynonymManager(self.store)
        self._builder = ResponseBuilder(self._syn)
        
        # --- Memory Integration (Redis + FAISS) ---
        cfg = _load_pentami_cfg()
        oll_url = cfg.get("ollama_url", "http://127.0.0.1:11434")
        oll_model = cfg.get("ollama_local_schedule_model", "llama3.2:1b")
        self._llm_memory = PentaMemory(ollama_url=oll_url, model=oll_model)
        
        # Rebuild index từ store
        existing = self.store.get_all_phrases()
        if existing:
            self._phrase_engine.rebuild_index(existing)
        
        # Session ID mặc định cho môi trường Mac
        self._session_id = "default_user"
        
        # Load context từ Redis (ưu tiên) hoặc JSON
        self._context = deque(maxlen=MAX_CONTEXT_TURNS * 2)
        self._load_context_from_redis_or_json()
        
        self._lock = threading.Lock()
        self._last_chat_ts = 0.0
        self._inject_facts = True
        self._wibu_style_enabled = True
        self._bonsai_thinking_mode = True
        self._last_route = "none"
        self._cached_system_prompt = None

        log.info(f"✅ PentaMiChat init: Multi-Tier Memory (Redis/FAISS/Phrases) integrated.")

    def _load_context_from_redis_or_json(self):
        """Restore history từ Redis nếu có, nếu không thì dùng JSON."""
        # 1. Thử Redis
        if self._llm_memory.redis:
            try:
                raw_hist = self._llm_memory.redis.lrange(self._session_id, 0, (MAX_CONTEXT_TURNS * 2) - 1)
                if raw_hist:
                    # Redis lrange trả về theo thứ tự lpush (mới nhất index 0)
                    # Deque cần nạp theo thứ tự cũ -> mới
                    for m_json in reversed(raw_hist):
                        self._context.append(json.loads(m_json))
                    log.debug(f"[Memory] Restored {len(self._context)} messages from Redis")
                    return
            except Exception as e:
                log.warning(f"[Memory] Redis restore failed: {e}")

        # 2. Fallback sang JSON
        self._load_context_json()

    def _load_context_json(self):
        try:
            if os.path.exists(CONTEXT_FILE):
                with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for msg in data.get("messages", []):
                        self._context.append(msg)
                log.debug(f"[Memory] Restored context from JSON fallback")
        except Exception:
            pass

    def _save_context(self, user_text: str, ai_resp: str) -> None:
        """Lưu đồng thời vào Redis (nhanh) và JSON (bền)."""
        # 1. Ghi Redis
        if self._llm_memory.redis:
            try:
                self._llm_memory.redis.lpush(self._session_id, json.dumps({"role": "assistant", "content": ai_resp}))
                self._llm_memory.redis.lpush(self._session_id, json.dumps({"role": "user", "content": user_text}))
                self._llm_memory.redis.ltrim(self._session_id, 0, (MAX_CONTEXT_TURNS * 2) - 1)
            except Exception as e:
                log.warning(f"[Memory] Redis save failed: {e}")

        # 2. Ghi FAISS (Vault) — chỉ lưu cặp Q&A chất lượng
        if len(user_text) > 10 and len(ai_resp) > 20:
            threading.Thread(target=self._llm_memory._add_phrase_to_memory, 
                             args=(f"Anh: {user_text}\nEm: {ai_resp}",), 
                             daemon=True).start()

        # 3. Ghi JSON (background)
        threading.Thread(target=self._save_context_json, daemon=True).start()

    def _save_context_json(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            messages = list(self._context)
            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                json.dump({"messages": messages, "saved_at": time.time()},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── Profile (cached) ───────────────────────────────────────────────────────

    def _load_profile(self) -> None:
        path = os.path.join(DATA_DIR, "user_profile.json")
        try:
            mtime = os.path.getmtime(path)
            if mtime == self._profile_mtime:
                return  # File không đổi → không load lại
            self._profile_mtime = mtime
            with open(path, "r", encoding="utf-8") as f:
                self._profile = json.load(f)
            self._cached_system_prompt = None  # Fix 2: invalidate cache khi profile đổi
        except Exception:
            if not self._profile:
                self._profile = {"name": None, "ai_name": "PentaMi",
                                 "pronoun": "anh", "ai_pronoun": "em"}

    # ── Context persistence ────────────────────────────────────────────────────

    def _load_context(self) -> None:
        try:
            if os.path.exists(CONTEXT_FILE):
                with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for msg in data.get("messages", []):
                    self._context.append(msg)
        except Exception:
            pass

    def _save_context(self) -> None:
        """Ghi file — gọi trong background thread, không block chat()."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            messages = list(self._context)
            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                json.dump({"messages": messages, "saved_at": time.time()},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_facts_line(self) -> str:
        if not self._inject_facts:
            return ""
        try:
            path = os.path.join(DATA_DIR, "knowledge.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            facts = data.get("facts", {})
            lines = [f"{s} là {e['predicate']}"
                     for s, entries in list(facts.items())[:5]
                     for e in entries[:1]]
            return "\nBạn biết: " + "; ".join(lines) if lines else ""
        except Exception:
            return ""

    def _seed_facts_if_needed(self) -> None:
        """Fix 2 (KV Cache): Inject facts vào đầu history 1 lần → system prompt bất biến mỗi turn."""
        if not self._inject_facts:
            return
        if self._context:  # Chỉ seed khi history trống
            return
        facts_line = self._get_facts_line()
        if not facts_line:
            return
        ap = self._profile.get("ai_pronoun", "em")
        self._context.append({"role": "user",      "content": f"[Thông tin bối cảnh]{facts_line}"})
        self._context.append({"role": "assistant", "content": f"Vâng {ap} nhớ rồi ạ, {ap} sẽ ghi nhớ những thông tin đó!"})

    def _get_system_prompt(self) -> str:
        """Fix 2: Trả về system prompt được cache — không rebuild mỗi lần gọi."""
        if self._cached_system_prompt is None:
            p = self._profile
            self._cached_system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
                ai_name      = p.get("ai_name",   "PentaMi"),
                user_pronoun = p.get("pronoun",    "anh"),
                ai_pronoun   = p.get("ai_pronoun", "em"),
            )
            log.debug(f"[PentaMi] System Prompt: {self._cached_system_prompt}")
        return self._cached_system_prompt

    def _ollama_stream(self, messages: List[Dict]) -> Iterator[str]:
        """Fix 4: Gọi Ollama 1B streaming cho câu ngắn/casual — hiện chữ tức thì."""
        cfg   = _load_pentami_cfg()
        url   = cfg.get("ollama_url",                  "http://localhost:11434")
        model = cfg.get("ollama_local_schedule_model", "llama3.2:1b")
        try:
            r = requests.post(
                f"{url}/api/chat",
                json={
                    "model": model, 
                    "messages": messages, 
                    "stream": True,
                    "options": {
                        "num_ctx": 1024,
                        "num_predict": 128,
                        "temperature": 0.7,
                        "num_thread": 4
                    }
                },
                timeout=15,
                stream=True,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    data = json.loads(line.decode("utf-8"))
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
        except Exception as e:
            log.debug(f"[PentaMi] _ollama_stream error: {e}")
            yield ""

    def _ollama_quick(self, messages: List[Dict]) -> Tuple[Optional[str], float]:
        """Blocking call tới Ollama cho nhánh fast-route."""
        cfg   = _load_pentami_cfg()
        url   = cfg.get("ollama_url", "http://localhost:11434")
        model = cfg.get("ollama_local_schedule_model", "llama3.2:1b")
        t0 = time.monotonic()
        t0 = time.monotonic()
        try:
            r = requests.post(
                f"{url}/api/chat",
                json={
                    "model": model, 
                    "messages": messages, 
                    "stream": False,
                    "options": {
                        "num_ctx": 1024,
                        "num_predict": 128,
                        "temperature": 0.7,
                        "num_thread": 4
                    }
                },
                timeout=15,
            )
            r.raise_for_status()
            text = str(r.json().get("message", {}).get("content", "")).strip()
            return text or None, (time.monotonic() - t0)
        except Exception as e:
            log.debug(f"[PentaMi] _ollama_quick error: {e}")
            return None, 0.0

    def _enforce_pronouns(self, text: str) -> str:
        """Fix: Hậu kiểm xưng hô để đảm bảo chuẩn 'anh/em' kể cả khi model nhầm."""
        if not text: return ""
        up = self._profile.get("pronoun", "anh")
        ap = self._profile.get("ai_pronoun", "em")
        
        # Nếu AI xưng 'tôi' hoặc 'mình' -> đổi thành 'em'
        res = re.sub(r'\b(tôi|mình|tớ)\b', ap, text, flags=re.IGNORECASE)
        # Nếu AI gọi user là 'bạn' -> đổi thành 'anh'
        res = re.sub(r'\b(bạn|cậu)\b', up, res, flags=re.IGNORECASE)
        
        return res

    def _apply_wibu_flavor(self, text: str) -> str:
        """Thêm chút màu wibu nhẹ, tránh lố và không phá nội dung chính."""
        t = str(text or "").strip()
        if not t:
            return t
        if not self._wibu_style_enabled:
            return t
        low = t.lower()
        if "senpai" in low or "-chan" in low or low.endswith("~"):
            return t
        if len(t) < 18:
            return t + _WIBU_SUFFIXES[1]
        return t + _WIBU_SUFFIXES[0]

    def _idle_sulk_prefix(self) -> str:
        if self._last_chat_ts == 0.0:
            return ""
        idle_h = (time.time() - self._last_chat_ts) / 3600
        ap = self._profile.get("ai_pronoun", "em")
        up = self._profile.get("pronoun", "anh")
        if idle_h > 24: return f"Cả ngày mới nhắn nha {up}... {ap} cứ nghĩ {up} quên {ap} rồi. "
        if idle_h > 8:  return f"Lâu quá mới nhắn nè, {ap} nhớ {up} ghê... "
        if idle_h > 4:  return f"Ơ {up} đâu mất tiêu vậy, {ap} chờ mãi. "
        return ""

    def _try_detect_teach(self, text: str) -> Optional[Tuple[str, str]]:
        if "?" in text:
            return None
        tl = text.strip().lower()
        if any(tl.startswith(k) for k in ("cái gì","là gì","thế nào","ai là")):
            return None
        for pat in _RE_TEACH_PATTERNS:
            m = pat.search(text.strip())
            if m:
                subj, pred = m.group(1).strip().lower(), m.group(2).strip()
                if len(subj) >= 2 and len(pred) >= 2 and subj not in _SKIP_SUBJECTS:
                    return subj, pred
        return None

    def _build_messages(self, user_text: str, memories: List[str] = None) -> List[Dict]:
        """Tạo message list gửi cho LLM. Fix 2: dùng system prompt được cache."""
        sys_content = self._get_system_prompt()
        if memories:
            mem_text = "\n[KÝ ỨC CŨ GỢI NHỚ]:\n- " + "\n- ".join(memories)
            sys_content += mem_text
            
        msgs: List[Dict] = [{"role": "system", "content": sys_content}]
        msgs.extend(list(self._context))
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def _build_fast_messages(self, user_text: str, memories: List[str] = None) -> List[Dict]:
        """Nhánh tốc độ cao: chỉ giữ ngữ cảnh gần nhất để giảm prefill."""
        sys_content = self._get_system_prompt()
        if memories:
             mem_text = "\n[KÝ ỨC CŨ]: " + "; ".join(memories[:2])
             sys_content += mem_text

        msgs: List[Dict] = [{"role": "system", "content": sys_content}]
        recent = list(self._context)[-2:]  # tối đa 1 turn gần nhất
        msgs.extend(recent)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    # ── Public: blocking chat (giữ tương thích cũ) ────────────────────────────

    def chat(self, user_text: str) -> str:
        """
        Blocking — trả về full string.
        Dùng khi caller không support streaming (CLI, fallback text).
        """
        with self._lock:
            self._load_profile()
            teach_result = self._try_detect_teach(user_text)
            teach_confirmed = False
            if teach_result:
                subj, pred = teach_result
                teach_confirmed = self._store.add_fact(subj, pred, relation="is_a", lang="vi")

            user_text = _normalize_input_text(user_text)
            user_text = _normalize_vi_typos(user_text)
            sulk  = self._idle_sulk_prefix()
            
            # --- Tier 0: Semantic Phrase Match (Redis backed) ---
            phrases = self.store.get_all_phrases()
            match = self._phrase_engine.find_best_match(user_text, phrases)
            if match and match.score >= 0.88:
                self.store.increment_use(match.trigger)
                resp = self._builder.build_phrase_response(match, match.slots, "vi")
                resp = (sulk + resp).strip()
                resp = self._postprocess_internal(resp)
                
                self._last_route = "phrase_match"
                self._context.append({"role": "user", "content": user_text})
                self._context.append({"role": "assistant", "content": resp})
                self._last_chat_ts = time.time()
                self._save_context(user_text, resp)
                return resp
            
            use_fast_ollama = _is_simple_query(user_text)
            
            # --- FAISS Retrieval ---
            memories = self._llm_memory._retrieve_long_term_memories(user_text)
            
            if use_fast_ollama:
                msgs = self._build_fast_messages(user_text, memories)
            else:
                msgs = self._build_messages(user_text, memories)
            
            # Retry loop: Chờ MLX ready tối đa 1s (phòng trường hợp pre-warm sắp xong)
            if not use_fast_ollama and not self._bonsai.is_available():
                for _ in range(10):
                    time.sleep(0.1)
                    if self._bonsai.is_available():
                        break
            # Fix 4: Smart routing — câu đơn giản → Ollama 1B (~200ms)
            bonsai_resp = None
            if use_fast_ollama:
                self._last_route = "ollama_fast"
                bonsai_resp, _ = self._ollama_quick(msgs)
                if not bonsai_resp:
                    self._last_route = "mlx_fallback"
                    bonsai_resp, _ = self._bonsai.chat(msgs, max_tokens=200)
            else:
                self._last_route = "mlx"
                bonsai_resp, total_time = self._bonsai.chat(msgs, max_tokens=200)
                log.debug(f"[PentaMi] chat() MLX/Qwen {total_time:.3f}s")

            ap = self._profile.get("ai_pronoun", "em")
            up = self._profile.get("pronoun", "anh")

            if bonsai_resp:
                resp = (sulk + bonsai_resp).strip()
            elif teach_confirmed:
                subj, pred = teach_result  # type: ignore
                resp = f"{sulk.strip()} Oke {ap} nhớ rồi nha! {subj.capitalize()} là {pred}.".strip()
            else:
                resp = f"{sulk.strip()} Ừm... {ap} nghe {up} nói rồi nha.".strip()

            resp = _sanitize_model_output_text(resp)
            resp = self._apply_wibu_flavor(self._enforce_pronouns(resp))

            self._context.append({"role": "user",      "content": user_text})
            self._context.append({"role": "assistant", "content": resp})
            self._last_chat_ts = time.time()

        # Save NGOÀI lock → không block caller
        threading.Thread(target=self._save_context, daemon=True).start()
        return resp

    # ── Public: streaming chat ─────────────────────────────────────────────────

    def chat_stream(self, user_text: str) -> Iterator[str]:
        """
        Streaming — yield từng token ngay khi MLX Qwen2.5-7B generate ra.
        Perceived latency ~150-300ms TTFT (first token) thay vì 5-8s wait toàn bộ.

        Dùng trong ai_server.py / WebSocket handler:

            @app.websocket("/ws/chat")
            async def ws_chat(ws):
                text = await ws.recv()
                for token in pentami.chat_stream(text):
                    await ws.send(json.dumps({"type": "token", "text": token}))
                await ws.send(json.dumps({"type": "done"}))
        """
        # Chuẩn bị context TRƯỚC khi stream (cần lock ngắn)
        with self._lock:
            user_text = _normalize_input_text(user_text)
            user_text = _normalize_vi_typos(user_text)
            self._load_profile()
            sulk = self._idle_sulk_prefix()
            
            # --- Tier 0: Semantic Phrase Match ---
            phrases = self.store.get_all_phrases()
            match = self._phrase_engine.find_best_match(user_text, phrases)
            if match and match.score >= 0.88:
                self.store.increment_use(match.trigger)
                resp = self._builder.build_phrase_response(match, match.slots, "vi")
                resp = (sulk + resp).strip()
                resp = self._postprocess_internal(resp)
                
                if sulk: yield sulk
                yield resp.replace(sulk, "").strip()
                
                self._last_route = "phrase_match"
                self._context.append({"role": "user", "content": user_text})
                self._context.append({"role": "assistant", "content": resp})
                self._last_chat_ts = time.time()
                self._save_context(user_text, resp)
                return

            use_fast_ollama = _is_simple_query(user_text)
            
            # --- FAISS Retrieval ---
            memories = self._llm_memory._retrieve_long_term_memories(user_text)
            
            if use_fast_ollama:
                msgs = self._build_fast_messages(user_text, memories)
            else:
                msgs = self._build_messages(user_text, memories)
        
        # Hiệu ứng trì hoãn sulk
        if sulk:
            yield sulk

        full_resp_parts = [sulk]
        
        # Kiểm tra MLX availability tức thì (có retry nhẹ 1s)
        if not use_fast_ollama and not self._bonsai.is_available():
            # Chờ 1s
            for _ in range(10):
                if self._bonsai.is_available(): break
                # Lưu ý: chat_stream là sync generator nhưng gọi từ async worker
                # Ta dùng time.sleep ở đây vì chat_stream chạy trong executor
                time.sleep(0.1) 
            
        if not self._bonsai.is_available() and not use_fast_ollama:
            log.info("[PentaMi] MLX not ready, using Ollama 1B immediately")
            for token in self._ollama_stream(msgs):
                if token:
                    clean_token = token
                    if clean_token.lower() in ["tôi", "mình", "tớ", "bạn", "cậu"]:
                        clean_token = self._enforce_pronouns(clean_token)
                    full_resp_parts.append(token)
                    yield clean_token
            
            full_resp = "".join(full_resp_parts).strip()
            full_resp = _sanitize_model_output_text(full_resp)
            full_resp = self._apply_wibu_flavor(self._enforce_pronouns(full_resp))
            if full_resp:
                with self._lock:
                    self._context.append({"role": "user",      "content": user_text})
                    self._context.append({"role": "assistant", "content": full_resp})
                    self._last_chat_ts = time.time()
                threading.Thread(target=self._save_context, daemon=True).start()
            return

        # Fix 4: Smart routing — câu ngắn/casual → Ollama 1B (~200ms, streaming)
        if use_fast_ollama:
            with self._lock:
                self._last_route = "ollama_fast"
            log.debug(f"[PentaMi] Routing to Ollama (simple text) with streaming")
            for token in self._ollama_stream(msgs):
                if token:
                    # Enforce pronouns on tokens if they are complete words (rough attempt)
                    # For safer results, we enforce on full_resp later, but here we try best effort
                    clean_token = token
                    if clean_token.lower() in ["tôi", "mình", "tớ", "bạn", "cậu"]:
                        clean_token = self._enforce_pronouns(clean_token)
                    
                    full_resp_parts.append(token)
                    yield clean_token
            
            full_resp = "".join(full_resp_parts).strip()
            full_resp = _sanitize_model_output_text(full_resp)
            full_resp = self._apply_wibu_flavor(self._enforce_pronouns(full_resp))
            if full_resp:
                with self._lock:
                    self._context.append({"role": "user",      "content": user_text})
                    self._context.append({"role": "assistant", "content": full_resp})
                    self._last_chat_ts = time.time()
                threading.Thread(target=self._save_context, daemon=True).start()
                return

        # Câu phức tạp → stream từng token từ MLX Qwen2.5-7B (target TTFT: ~150-300ms)
        def log_first_token(ttft):
            log.info(f"[PentaMi] First token in {ttft:.3f}s (MLX/Qwen2.5-7B)")

        has_bonsai_token = False
        with self._lock:
            self._last_route = "mlx"
        for token, ttft in self._bonsai.chat_stream(msgs, max_tokens=200, on_first_token=log_first_token):
            # Enforce pronouns token-by-token (best effort)
            clean_token = token
            if not isinstance(clean_token, str):
                clean_token = getattr(clean_token, "text", str(clean_token))
            
            if clean_token.lower().strip() in ["tôi", "mình", "tớ", "bạn", "cậu"]:
                clean_token = self._enforce_pronouns(clean_token)

            has_bonsai_token = True
            full_resp_parts.append(token)
            yield clean_token

        # Nếu MLX không trả token nào (engine chưa load/crash), fallback sang Ollama stream.
        if not has_bonsai_token:
            with self._lock:
                self._last_route = "ollama_fallback"
            log.warning("[PentaMi] MLX stream rỗng, fallback sang Ollama stream")
            for token in self._ollama_stream(msgs):
                if not token:
                    continue
                clean_token = token
                if not isinstance(clean_token, str):
                    clean_token = getattr(clean_token, "text", str(clean_token))
                
                if clean_token.lower().strip() in ["tôi", "mình", "tớ", "bạn", "cậu"]:
                    clean_token = self._enforce_pronouns(clean_token)
                full_resp_parts.append(token)
                yield clean_token

        # Lưu context sau khi stream xong
        full_resp = "".join(full_resp_parts).strip()
        full_resp = _sanitize_model_output_text(full_resp)
        full_resp = self._apply_wibu_flavor(self._enforce_pronouns(full_resp))
        with self._lock:
            self._context.append({"role": "user",      "content": user_text})
            self._context.append({"role": "assistant", "content": full_resp})
            self._last_chat_ts = time.time()
        self._save_context(user_text, full_resp)

    # ── Context management ─────────────────────────────────────────────────────

    def _postprocess_internal(self, text: str) -> str:
        """Helper cho phrase responses."""
        res = _sanitize_model_output_text(text)
        res = self._apply_wibu_flavor(self._enforce_pronouns(res))
        return res

    def clear_context(self) -> None:
        with self._lock:
            self._context.clear()
            if self._llm_memory.redis:
                try:
                    self._llm_memory.redis.delete(self._session_id)
                except Exception:
                    pass
            try:
                if os.path.exists(CONTEXT_FILE):
                    os.remove(CONTEXT_FILE)
            except Exception:
                pass

    def context_length(self) -> int:
        return len(self._context) // 2

    def get_last_route(self) -> str:
        with self._lock:
            return self._last_route

    def set_bonsai_thinking_mode(self, active: bool) -> None:
        with self._lock:
            self._bonsai_thinking_mode = bool(active)

    def is_bonsai_thinking_mode(self) -> bool:
        with self._lock:
            return bool(self._bonsai_thinking_mode)

    def postprocess_output(self, text: str) -> str:
        """Chuẩn hóa xưng hô + wibu flavor cho output đã hợp nhất."""
        clean = _sanitize_model_output_text(str(text or "").strip())
        return self._apply_wibu_flavor(self._enforce_pronouns(clean))


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[PentaMiChat] = None
_instance_lock = threading.Lock()


def get_pentami_chat() -> PentaMiChat:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PentaMiChat()
    return _instance