"""
PATCH cho pentami_chat.py — thêm streaming.

Thay thế method chat() cũ bằng 2 method mới:
  - chat()        : blocking như cũ (dùng cho CLI/fallback)
  - chat_stream() : streaming, yield từng token (dùng cho iOS WebSocket)

Thay đổi duy nhất cần thiết trong code cũ:
  1. Đổi method chat() → gọi bonsai.chat_stream() thay vì bonsai.chat()
  2. Thêm method chat_stream() public
  3. Rút system prompt + giảm MAX_CONTEXT_TURNS
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

from .bonsai_client import get_bonsai_client
from memory.knowledge_store import KnowledgeStore

# API_local/ là sub-package → ROOT phải trỏ lên PentaAI_Mac/
ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(ROOT, "data")
CONTEXT_FILE = os.path.join(DATA_DIR, "pentami_context.json")

# ← Giảm từ 20 xuống 8 → context ngắn hơn, prefill nhanh hơn
MAX_CONTEXT_TURNS = 8


def _load_pentami_cfg() -> dict:
    cfg_path = os.path.join(ROOT, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── System prompt (rút gọn ~150 tokens, giảm từ ~600) ─────────────────────────
# Bỏ hết ví dụ đúng/sai dư thừa — model 8B đủ thông minh không cần ví dụ
_SYSTEM_PROMPT_TEMPLATE = """\
Bạn là {ai_name} — trợ lý AI thân thiết, dịu dàng, hay dỗi nhẹ.
Xưng hô bắt buộc (tiếng Việt): bạn = "{ai_pronoun}", người dùng = "{user_pronoun}".
Tiếng Anh → dùng I/you. Tiếng Nhật → dùng あたし. KHÔNG trộn ngôn ngữ.
Tính cách: ấm áp, gần gũi, thỉnh thoảng nũng nịu. Trả lời ngắn 2-3 câu."""
# Fix 2 (KV Cache): facts_line đã chuyển sang seed 1 lần vào đầu history
# → system prompt bất biến mỗi turn → llama.cpp KV cache hit mọi lần

# ── Fix 4: Smart Routing ───────────────────────────────────────────────────────
_SIMPLE_WORDS = {
    "ok", "oke", "hihi", "hehe", "haha", "ừ", "ừm", "ờ", "à",
    "được", "thôi", "uhm", "hmm", "good", "cool", "hay đó",
    "xong", "cảm ơn", "cám ơn", "thanks", "thank", "yeah", "yep",
}


def _is_simple(text: str) -> bool:
    """Trả True nếu câu ngắn/casual → route sang Ollama 1B (~200ms) thay vì Bonsai 8B."""
    t = text.strip()
    tl = t.lower()
    if tl in _SIMPLE_WORDS or any(
        tl.startswith(w + " ") or tl.endswith(" " + w) for w in _SIMPLE_WORDS
    ):
        return True
    return len(t) < 40 and "?" not in t


# Toggle / teach patterns (giữ nguyên từ bản gốc)
_RE_TOGGLE_ON  = re.compile(r'(?:bật|mở|on|kích\s*hoạt|start|enable)\s*(?:chế\s*độ\s*)?(?:pentami|penta\s*mi)', re.IGNORECASE)
_RE_TOGGLE_OFF = re.compile(r'(?:tắt|đóng|off|vô\s*hiệu|stop|disable)\s*(?:chế\s*độ\s*)?(?:pentami|penta\s*mi)', re.IGNORECASE)
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
    if _RE_TOGGLE_ON.search(t):  return "on"
    if _RE_TOGGLE_OFF.search(t): return "off"
    if _RE_CLEAR_CTX.search(t):  return "clear"
    return None


class PentaMiChat:
    def __init__(self):
        self._bonsai  = get_bonsai_client()
        self._store   = KnowledgeStore()
        self._context: deque = deque(maxlen=MAX_CONTEXT_TURNS * 2)
        self._lock    = threading.Lock()
        self._profile: Dict = {}
        self._profile_mtime: float = 0.0   # Cache profile, không load file mỗi lần
        self._cached_system_prompt: Optional[str] = None  # Fix 2: KV cache
        self._last_chat_ts: float  = 0.0
        _cfg = _load_pentami_cfg()
        self._inject_facts: bool = bool(_cfg.get("pentami_inject_known_facts", False))
        self._load_profile()
        self._load_context()
        self._seed_facts_if_needed()  # Fix 2: inject facts vào đầu history 1 lần duy nhất

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
        return self._cached_system_prompt

    def _ollama_quick(self, messages: List[Dict]) -> Optional[str]:
        """Fix 4: Gọi Ollama 1B cho câu ngắn/casual — perceived latency ~200ms."""
        cfg   = _load_pentami_cfg()
        url   = cfg.get("ollama_url",                  "http://localhost:11434")
        model = cfg.get("ollama_local_schedule_model", "llama3.2:1b")
        try:
            r = requests.post(
                f"{url}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=8,
            )
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip() or None
        except Exception as e:
            log.debug(f"[PentaMi] _ollama_quick error: {e}")
            return None

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

    def _build_messages(self, user_text: str) -> List[Dict]:
        """Tạo message list gửi cho LLM. Fix 2: dùng system prompt được cache."""
        msgs: List[Dict] = [{"role": "system", "content": self._get_system_prompt()}]
        msgs.extend(list(self._context))
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

            sulk  = self._idle_sulk_prefix()
            msgs  = self._build_messages(user_text)
            # Fix 4: Smart routing — câu đơn giản → Ollama 1B (~200ms)
            if _is_simple(user_text):
                bonsai_resp = self._ollama_quick(msgs) or self._bonsai.chat(msgs, max_tokens=120)
            else:
                bonsai_resp = self._bonsai.chat(msgs, max_tokens=120)

            ap = self._profile.get("ai_pronoun", "em")
            up = self._profile.get("pronoun", "anh")

            if bonsai_resp:
                resp = (sulk + bonsai_resp).strip()
            elif teach_confirmed:
                subj, pred = teach_result  # type: ignore
                resp = f"{sulk.strip()} Oke {ap} nhớ rồi nha! {subj.capitalize()} là {pred}.".strip()
            else:
                resp = f"{sulk.strip()} Ừm... {ap} nghe {up} nói rồi nha.".strip()

            self._context.append({"role": "user",      "content": user_text})
            self._context.append({"role": "assistant", "content": resp})
            self._last_chat_ts = time.time()

        # Save NGOÀI lock → không block caller
        threading.Thread(target=self._save_context, daemon=True).start()
        return resp

    # ── Public: streaming chat ─────────────────────────────────────────────────

    def chat_stream(self, user_text: str) -> Iterator[str]:
        """
        Streaming — yield từng token ngay khi Bonsai generate ra.
        Perceived latency ~300ms (first token) thay vì 5-8s.

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
            self._load_profile()
            teach_result = self._try_detect_teach(user_text)
            if teach_result:
                subj, pred = teach_result
                self._store.add_fact(subj, pred, relation="is_a", lang="vi")
            sulk = self._idle_sulk_prefix()
            msgs = self._build_messages(user_text)

        # Yield sulk prefix ngay lập tức (không cần chờ LLM)
        if sulk:
            yield sulk

        full_resp_parts = [sulk]

        # Fix 4: Smart routing — câu ngắn/casual → Ollama 1B (~200ms, không stream)
        if _is_simple(user_text):
            quick = self._ollama_quick(msgs)
            if quick:
                full_resp_parts.append(quick)
                yield quick
                full_resp = "".join(full_resp_parts).strip()
                with self._lock:
                    self._context.append({"role": "user",      "content": user_text})
                    self._context.append({"role": "assistant", "content": full_resp})
                    self._last_chat_ts = time.time()
                threading.Thread(target=self._save_context, daemon=True).start()
                return

        # Câu phức tạp → stream từng token từ Bonsai 8B (~1.8s first token)
        for token in self._bonsai.chat_stream(msgs, max_tokens=120):
            full_resp_parts.append(token)
            yield token

        # Lưu context sau khi stream xong
        full_resp = "".join(full_resp_parts).strip()
        with self._lock:
            self._context.append({"role": "user",      "content": user_text})
            self._context.append({"role": "assistant", "content": full_resp})
            self._last_chat_ts = time.time()
        threading.Thread(target=self._save_context, daemon=True).start()

    # ── Context management ─────────────────────────────────────────────────────

    def clear_context(self) -> None:
        with self._lock:
            self._context.clear()
            self._seed_facts_if_needed()  # Fix 2: re-seed sau khi clear
            try:
                if os.path.exists(CONTEXT_FILE):
                    os.remove(CONTEXT_FILE)
            except Exception:
                pass

    def context_length(self) -> int:
        return len(self._context) // 2


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