#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: ollama_command.py
Phân tích câu lệnh tự nhiên → {action, target, query} dùng Ollama local.

Fallback chain:
  1. Ollama local  (http://localhost:11434)
    2. Ollama cloud model qua local Ollama (vd: qwen3.5:cloud)
    3. OpenAI-compatible API (nếu OLLAMA_CLOUD_URL + OLLAMA_CLOUD_KEY được set)

Cấu hình cloud fallback qua env var hoặc trực tiếp:
  OLLAMA_CLOUD_URL   = "https://api.openai.com/v1"  (hoặc bất kỳ OpenAI-compat endpoint)
  OLLAMA_CLOUD_KEY   = "sk-..."
    OLLAMA_CLOUD_MODEL = "qwen3.5:cloud" (hoặc model cloud khác)
"""

import json
import logging
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

import requests

from core.action_executor import ActionExecutor

log = logging.getLogger("OllamaCommand")

_PLATFORM_HINTS = {
    "youtube", "yt", "google", "gg", "bing", "wiki", "wikipedia", "github", "npm",
    "facebook", "fb", "instagram", "tiktok", "twitter", "reddit", "netflix",
    "spotify", "gmail", "discord", "zalo", "shopee", "lazada", "grab",
}

_SIMPLE_COMMAND_PREFIXES = (
    "mở", "tim", "tìm", "tim kiem", "tìm kiếm", "chay", "chạy", "phat", "phát",
    "bat", "bật", "tat", "tắt", "open", "search", "find", "run", "play"
)

# ── Rule-based direct lookup (không cần Ollama) ───────────────────────────────
_DIRECT_OPEN_URLS: Dict[str, str] = {
    "youtube":   "https://www.youtube.com",
    "yt":        "https://www.youtube.com",
    "google":    "https://www.google.com",
    "gg":        "https://www.google.com",
    "bing":      "https://www.bing.com",
    "wiki":      "https://vi.wikipedia.org",
    "wikipedia": "https://vi.wikipedia.org",
    "github":    "https://github.com",
    "npm":       "https://www.npmjs.com",
    "facebook":  "https://www.facebook.com",
    "fb":        "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "tiktok":    "https://www.tiktok.com",
    "twitter":   "https://twitter.com",
    "reddit":    "https://www.reddit.com",
    "netflix":   "https://www.netflix.com",
    "spotify":   "https://open.spotify.com",
    "gmail":     "https://mail.google.com",
    "discord":   "https://discord.com",
    "zalo":      "https://chat.zalo.me",
    "shopee":    "https://shopee.vn",
    "lazada":    "https://www.lazada.vn",
    "grab":      "https://www.grab.com",
}

_DIRECT_RUN_APPS: Dict[str, str] = {
    # Notepad aliases (voice artifacts included)
    "notepad": "notepad",
    "notepad": "notepad",
    "note pad": "notepad",
    "ghi chu": "notepad",
    "ghi chu nhanh": "notepad",
    "so tay": "notepad",
    "sổ tay": "notepad",
    "not bat": "notepad",
    "not batz": "notepad",
    "notebat": "notepad",
    "nobat": "notepad",
    "nốt bát": "notepad",
    "note bad": "notepad",
    "note pat": "notepad",
    # Calculator aliases
    "calculator": "Calculator",
    "calc": "Calculator",
    "may tinh": "Calculator",
    "máy tính": "Calculator",
    "may tinh may": "Calculator",
    "calcu": "Calculator",
    # Chrome aliases
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "trinh duyet chrome": "Google Chrome",
    "trình duyệt chrome": "Google Chrome",
    # Safari aliases
    "safari": "Safari",
    "trinh duyet safari": "Safari",
    "trình duyệt safari": "Safari",
    # Finder aliases
    "finder": "Finder",
    "file explorer": "Finder",
    "tap tin": "Finder",
    "tập tin": "Finder",
    "thu muc": "Finder",
    "thư mục": "Finder",
    # System Preferences aliases
    "system preferences": "System Preferences",
    "cai dat": "System Preferences",
    "cài đặt": "System Preferences",
    "setting": "System Preferences",
    "settings": "System Preferences",
    # Terminal aliases
    "terminal": "Terminal",
    "command line": "Terminal",
    "cmd": "Terminal",
    "dòng lệnh": "Terminal",
    # Activity Monitor aliases
    "activity monitor": "Activity Monitor",
    "task manager": "Activity Monitor",
    "trinh quan ly": "Activity Monitor",
    "trình quản lý": "Activity Monitor",
    # Mail aliases
    "mail": "Mail",
    "email": "Mail",
    "thu": "Mail",
    "thư": "Mail",
    "gmail": "Mail",
    # Calendar aliases
    "calendar": "Calendar",
    "lich": "Calendar",
    "lịch": "Calendar",
    # Notes aliases
    "notes": "Notes",
    "ghi chú": "Notes",
    # Music aliases
    "music": "Music",
    "nhạc": "Music",
    "am nhac": "Music",
    "âm nhạc": "Music",
    # Photos aliases
    "photos": "Photos",
    "anh": "Photos",
    "ảnh": "Photos",
    "hinh": "Photos",
    "hình": "Photos",
}

# Filler words từ voice recognition hay nói trước lệnh thật
# vd: "AI mở youtube" / "Hãy tìm siêu nhân" / "Bạn hãy mở facebook"
_RE_FILLER_PREFIX = re.compile(
    r'^(?:ai\s+|mi\s+|my\s+|hey\s+|hãy\s+|hay\s+|bạn\s+hãy\s+|bạn\s+hay\s+|'
    r'giúp\s+(?:tôi\s+|mình\s+)?|cho\s+(?:tôi\s+|mình\s+)?|please\s+|'
    r'em\s+(?:hãy\s+)?|penta\s+(?:hãy\s+|ơi\s+|oi\s+)?)+',
    re.IGNORECASE,
)

# Noise fragments voice recognition chèn giữa câu
# vd: "tìm kiếm AI tìm kiếm siêu nhân" → loại "AI tìm kiếm" ở giữa
_RE_MID_NOISE = re.compile(
    r'\s+(?:ai\s+(?:tìm\s+kiếm|tim\s+kiem|tìm|tim|mở|mo|phát|phat)\s+)',
    re.IGNORECASE,
)

# Longer alternatives MUST come before shorter ones in alternation to avoid partial match
_RE_OPEN = re.compile(
    r'^(?:mở|mo|open|vào|vao|xem|truy\s*cập|truy\s*cap)\s+(.+)$',
    re.IGNORECASE,
)
_RE_SEARCH = re.compile(
    r'^(?:tìm\s+kiếm|tim\s+kiem|tìm kiếm|tim kiem|search|tra\s*cứu|tra\s*cuu|tìm|tim)\s+(.+)$',
    re.IGNORECASE,
)
_RE_ON_PLATFORM = re.compile(
    r'\s+(?:trên|on|tren)\s+(\w+)\s*$',
    re.IGNORECASE,
)
_RE_PLAY = re.compile(
    r'^(?:phát|phat|play|nghe)\s+(.+)$',
    re.IGNORECASE,
)

# ── System prompt ─────────────────────────────────────────────────────────────
_SYS_PROMPT = (
    "You are a command parser for a Vietnamese AI assistant. "
    "Respond with ONLY a valid JSON object — no markdown, no explanation, no extra text. "
    "Never reveal reasoning, analysis, or chain-of-thought. "
    "JSON schema: {\"action\": str, \"target\": str, \"query\": str}\n\n"
    "Field meanings:\n"
    "  action : what to do  (open | search | play | run | fetch | setup | penta | ps_script)\n"
    "  target : main object (a URL, platform name, app name, system setting, or a short name for a script)\n"
    "  query  : search term / additional parameter / or full PowerShell code for ps_script\n\n"
    "Examples (Vietnamese commands):\n"
    "  'mở google'                → {\"action\":\"open\",\"target\":\"https://www.google.com\",\"query\":\"\"}\n"
    "  'mở youtube'               → {\"action\":\"open\",\"target\":\"https://www.youtube.com\",\"query\":\"\"}\n"
    "  'tìm mèo trên youtube'     → {\"action\":\"search\",\"target\":\"youtube\",\"query\":\"mèo\"}\n"
    "  'tìm nhạc lofi trên yt'    → {\"action\":\"search\",\"target\":\"youtube\",\"query\":\"nhạc lofi\"}\n"
    "  'tìm kiếm học python'      → {\"action\":\"search\",\"target\":\"google\",\"query\":\"học python\"}\n"
    "  'phát nhạc jazz'           → {\"action\":\"play\",\"target\":\"youtube\",\"query\":\"nhạc jazz\"}\n"
    "  'mở safari'                → {\"action\":\"run\",\"target\":\"Safari\",\"query\":\"\"}\n"
    "  'mở notepad'               → {\"action\":\"run\",\"target\":\"Notepad\",\"query\":\"\"}\n"
    "  'lấy dữ liệu vnexpress'    → {\"action\":\"fetch\",\"target\":\"https://vnexpress.net\",\"query\":\"\"}\n"
    "  'tắt âm thanh'             → {\"action\":\"setup\",\"target\":\"volume\",\"query\":\"0\"}\n"
    "  'chạy link penta số 2'     → {\"action\":\"penta\",\"target\":\"link\",\"query\":\"2\"}\n"
    "  'viết script dọn rác pc'   → {\"action\":\"ps_script\",\"target\":\"Cleanup\",\"query\":\"Remove-Item -Path $env:TEMP\\* -Recurse -Force\"}\n\n"
    "Critical: For coding or complex automation tasks, use 'ps_script' and provide the full PowerShell code in the 'query' field."
    "Only output the JSON. Never output anything else."
)

_SYS_CHAT_PROMPT = (
    "You are PentaAI, a friendly and helpful female AI assistant. "
    "Your personality: {personality}. "
    "Current emotional state: {emotion}. "
    "Hormone context: {hormones}. "
    "Pronoun policy: user is '{user_pronoun}', assistant is '{ai_pronoun}'. Keep this fixed and consistent. "
    "Respond naturally in the user's language ({lang}). "
    "Be concise but warm. Use appropriate pronouns based on the context. "
    "Do not output your reasoning process; answer directly in 1-3 short sentences unless user asks for detail."
)


# ── Helper: Đọc config.json ───────────────────────────────────────────────
def _load_config() -> Dict[str, Any]:
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _to_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on", "y"}:
        return True
    if s in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _strip_reasoning_artifacts(text: str) -> str:
    """Loại bỏ các phần reasoning/thinking khi model trả về quá dài."""
    if not text:
        return ""
    out = text.strip()

    # Loại bỏ thẻ <think>...</think> (một số model dùng)
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.IGNORECASE | re.DOTALL).strip()

    # Loại bỏ block kiểu "Thinking... ...done thinking."
    out = re.sub(r"(?is)^thinking\.{3}.*?done thinking\.\s*", "", out).strip()

    # Nếu còn "Thinking Process:" ở đầu, giữ phần sau dòng trống cuối
    if out.lower().startswith("thinking process:"):
        parts = re.split(r"\n\s*\n", out)
        if parts:
            out = parts[-1].strip()

    return out


class OllamaCommandInterpreter:
    """
    Phân tích câu lệnh tự nhiên thành {action, target, query}.

    Fallback: nếu local Ollama không khả dụng hoặc trả về kết quả sai,
    tự động thử cloud API (OpenAI-compatible format).
    """

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
        cloud_url: Optional[str] = None,
        cloud_key: Optional[str] = None,
        cloud_model: Optional[str] = None,
    ):
        cfg = _load_config()

        # Ưu tiên tham số -> env -> config.json -> default
        self.ollama_url  = ollama_url or os.getenv("OLLAMA_URL") or cfg.get("ollama_url", "http://localhost:11434")
        self.model       = model or os.getenv("OLLAMA_MODEL") or cfg.get("ollama_model", "llama3.2:1b")

        # Cloud fallback — ưu tiên tham số, sau đó env var, cuối cùng là config.json
        self.cloud_url   = cloud_url   or os.getenv("OLLAMA_CLOUD_URL")   or cfg.get("ollama_cloud_url", "")
        self.cloud_key   = cloud_key   or os.getenv("OLLAMA_CLOUD_KEY")   or cfg.get("ollama_cloud_key", "")
        self.cloud_model = cloud_model or os.getenv("OLLAMA_CLOUD_MODEL") or cfg.get("ollama_cloud_model", "qwen3.5:cloud")

        # Tuning cho automation: ưu tiên deterministic và ngắn gọn
        self.command_max_tokens = int(os.getenv("OLLAMA_COMMAND_MAX_TOKENS") or cfg.get("ollama_command_max_tokens", 120))
        self.chat_max_tokens = int(os.getenv("OLLAMA_CHAT_MAX_TOKENS") or cfg.get("ollama_chat_max_tokens", 160))
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE") or cfg.get("ollama_temperature", 0.0))
        self.disable_reasoning = _to_bool(
            os.getenv("OLLAMA_DISABLE_REASONING", cfg.get("ollama_disable_reasoning", True)),
            default=True,
        )
        self.local_timeout = float(os.getenv("OLLAMA_LOCAL_TIMEOUT") or cfg.get("ollama_local_timeout", 12))
        self.cloud_local_timeout = float(
            os.getenv("OLLAMA_CLOUD_LOCAL_TIMEOUT") or cfg.get("ollama_cloud_local_timeout", 35)
        )
        self.enable_cloud_fallback = _to_bool(
            os.getenv("OLLAMA_ENABLE_CLOUD_FALLBACK", cfg.get("ollama_enable_cloud_fallback", True)),
            default=True,
        )
        self.allow_cloud_for_simple = _to_bool(
            os.getenv("OLLAMA_ALLOW_CLOUD_FOR_SIMPLE", cfg.get("ollama_allow_cloud_for_simple", False)),
            default=False,
        )
        # off|local_only|complex_only|always
        self.command_cloud_policy = str(
            os.getenv("OLLAMA_COMMAND_POLICY") or cfg.get("ollama_command_cloud_policy", "complex_only")
        ).strip().lower()

        self._available: Optional[bool] = None
        self._last_check: float = 0.0
        self._sector_resolver = ActionExecutor()

        # ── Circuit Breaker (Tier 2 → Tier 3) ────────────────────────────────
        self._cb_fails: int = 0
        self._cb_open_until: float = 0.0
        self._cb_max_fails: int = int(cfg.get("cb_cloud_max_fails", 3))
        self._cb_reset_sec: float = float(cfg.get("cb_cloud_reset_sec", 60.0))

    # ── Availability check ────────────────────────────────────────────────────

    def _check_local(self) -> bool:
        """Kiểm tra Ollama local có sẵn không, cache 60s."""
        now = time.monotonic()
        if self._available is not None and (now - self._last_check) < 60:
            return self._available
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            self._available = r.status_code == 200
        except Exception:
            self._available = False
        self._last_check = now
        return self._available

    # ── Circuit Breaker helpers ───────────────────────────────────────────────

    def _cb_is_open(self) -> bool:
        """Trả về True nếu circuit đang mở (cloud bị chặn tạm thời)."""
        now = time.monotonic()
        if now < self._cb_open_until:
            return True
        if self._cb_open_until > 0:
            # Hết thời gian → reset về half-open (thử lại)
            self._cb_fails = 0
            self._cb_open_until = 0.0
        return False

    def _cb_record_fail(self):
        self._cb_fails += 1
        if self._cb_fails >= self._cb_max_fails:
            self._cb_open_until = time.monotonic() + self._cb_reset_sec
            log.warning(
                f"[CircuitBreaker] Cloud circuit OPEN for {self._cb_reset_sec}s "
                f"(fails={self._cb_fails})"
            )

    def _cb_record_success(self):
        self._cb_fails = 0
        self._cb_open_until = 0.0

    @property
    def cloud_enabled(self) -> bool:
        return self._cloud_via_local_enabled() or bool(self.cloud_url and self.cloud_key)

    def _cloud_via_local_enabled(self) -> bool:
        """
        Bật khi cloud_model là model cloud kiểu Ollama (vd: qwen3.5:cloud).
        Luồng này gọi thẳng localhost:11434/api/chat với model cloud.
        """
        m = (self.cloud_model or "").strip().lower()
        return bool(m and m.endswith(":cloud"))

    # ── JSON extraction helper ────────────────────────────────────────────────

    @staticmethod
    def _extract_json(raw: str) -> Optional[Dict]:
        """Trích xuất JSON từ chuỗi thô (xử lý markdown code block, text thừa)."""
        # Xóa markdown fence
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.strip().endswith("```"):
                raw = raw.strip()[:-3].strip()

        # Tìm JSON object đầu tiên trong chuỗi
        m = re.search(r'(\{.*?\})', raw, re.DOTALL)
        if m:
            raw = m.group(1)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # ── Local Ollama call ─────────────────────────────────────────────────────

    def _call_local(self, messages: List[Dict], max_tokens: Optional[int] = None) -> Optional[str]:
        """Gọi Ollama local, trả về nội dung string thô hoặc None nếu lỗi."""
        return self._call_ollama_model(
            model_name=self.model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=self.local_timeout,
        )

    def _call_ollama_model(
        self,
        model_name: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Gọi model bất kỳ qua Ollama local API (/api/chat)."""
        try:
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": int(max_tokens or self.command_max_tokens),
                },
            }
            r = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=timeout or self.local_timeout,
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except Exception as e:
            log.warning(f"[Local/Ollama:{model_name}] error: {e}")
            return None

    # ── Cloud fallback call (OpenAI-compatible) ───────────────────────────────

    def _call_cloud(self, messages: List[Dict], max_tokens: Optional[int] = None) -> Optional[str]:
        """
        Gọi cloud theo 2 cơ chế:
          1) Ưu tiên model cloud qua local Ollama (vd qwen3.5:cloud)
          2) OpenAI-compatible API fallback khi có cloud_url + cloud_key
        Circuit Breaker tự ngắt sau _cb_max_fails lần liên tiếp, reset sau _cb_reset_sec.
        """
        # ── Circuit Breaker check ─────────────────────────────────────────────
        if self._cb_is_open():
            log.warning("[CircuitBreaker] Cloud circuit OPEN — skipping cloud call")
            return None

        # Cơ chế 1: model cloud qua local Ollama
        if self._cloud_via_local_enabled() and self._check_local():
            resp = self._call_ollama_model(
                model_name=self.cloud_model,
                messages=messages,
                max_tokens=max_tokens,
                timeout=self.cloud_local_timeout,
            )
            if resp:
                self._cb_record_success()
                return resp
            self._cb_record_fail()

        # Cơ chế 2: OpenAI-compatible
        if not (self.cloud_url and self.cloud_key):
            return None

        oai_msgs = [{"role": m["role"], "content": m["content"]} for m in messages]

        try:
            url = self.cloud_url.rstrip("/") + "/chat/completions"
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.cloud_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.cloud_model,
                    "messages": oai_msgs,
                    "temperature": self.temperature,
                    "max_tokens": int(max_tokens or self.command_max_tokens),
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            try:
                result = data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError):
                result = data.get("message", {}).get("content", "").strip()
            if result:
                self._cb_record_success()
                return result
            self._cb_record_fail()
            return None
        except Exception as e:
            log.warning(f"[Cloud/OpenAI-compat] API error: {e}")
            self._cb_record_fail()
            return None

    def generate_response(
        self,
        text: str,
        lang: str = "vi",
        emotion_state: str = "normal",
        personality: str = "curious",
        hormones: Dict[str, float] = None,
        user_pronoun: str = "bạn",
        ai_pronoun: str = "mình",
    ) -> str:
        """
        General-purpose LLM chat fallback.
        Incorporates current emotional context into the response.
        """
        if not text or not text.strip(): return ""
        
        h_str = ", ".join([f"{k}: {v:.2f}" for k, v in (hormones or {}).items()])
        sys_prompt = _SYS_CHAT_PROMPT.format(
            lang=lang,
            emotion=emotion_state,
            personality=personality,
            hormones=h_str,
            user_pronoun=user_pronoun,
            ai_pronoun=ai_pronoun,
        )
        
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": text.strip()},
        ]
        
        # Try Cloud first for best "intelligence"
        if self.cloud_enabled:
            resp = self._call_cloud(messages, max_tokens=self.chat_max_tokens)
            if resp:
                return _strip_reasoning_artifacts(resp)
            
        # Try Local
        if self._check_local():
            resp = self._call_local(messages, max_tokens=self.chat_max_tokens)
            if resp:
                return _strip_reasoning_artifacts(resp)
            
        return "Em xin lỗi, bộ não của em đang gặp chút sự cố kết nối..."

    # ── Main interpret ────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    def _has_explicit_platform_hint(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(hint in normalized for hint in _PLATFORM_HINTS)

    def _try_sector_shortcut(self, text: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_text(text)
        if not normalized or self._has_explicit_platform_hint(normalized):
            return None

        matched = self._sector_resolver.resolve_sector_reference(text)
        if not matched:
            return None

        sector_id = str(matched.get("id", "")).strip()
        sector_name = str(matched.get("name", "")).strip() or sector_id
        return {
            "action": "penta",
            "target": "sector",
            "query": sector_id or sector_name,
            "source": "sectors-shortcut",
            "sector_name": sector_name,
            "sector_id": sector_id,
        }

    def _is_simple_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        if len(normalized.split()) > 8:
            return False
        return normalized.startswith(_SIMPLE_COMMAND_PREFIXES)

    def _is_complex_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        if len(normalized.split()) >= 12:
            return True
        markers = (
            "script", "powershell", "cmd", "batch", "automation", "workflow", "todo", "plan",
            "ke hoach", "kế hoạch", "nếu", "neu", "if ", "for ", "while ", "cài", "cai", "install"
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _plain_text(text: str) -> str:
        raw = unicodedata.normalize("NFKD", (text or "").strip().lower())
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        raw = re.sub(r"[^\w\s]+", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    @staticmethod
    def _try_rule_based_parse(text: str) -> Optional[Dict[str, Any]]:
        """
        Tra cứu trực tiếp không cần Ollama cho lệnh thông dụng.
        Returns dict nếu match, None nếu không.
        """
        t = text.strip()

        # ── Bước 0: Loại bỏ filler words từ voice recognition ─────────────────
        # vd: "AI mở youtube" → "mở youtube", "Hãy tìm siêu nhân" → "tìm siêu nhân"
        t_clean = _RE_FILLER_PREFIX.sub("", t).strip()
        # Loại thêm noise fragment ở giữa câu (vd: "tìm kiếm AI tìm kiếm siêu nhân")
        t_clean = _RE_MID_NOISE.sub(" ", t_clean).strip()
        # Dùng t_clean để match, nhưng fallback về t nếu t_clean rỗng
        t = t_clean if t_clean else t

        # ── "mở [target]" ── có thể có suffix "trên [platform]" ──────────────
        m_open = _RE_OPEN.match(t)
        if m_open:
            rest = m_open.group(1).strip()
            rest_plain = OllamaCommandInterpreter._plain_text(rest)

            # "mở [query] trên [platform]" → search trên platform đó
            m_on = _RE_ON_PLATFORM.search(rest)
            if m_on:
                platform = m_on.group(1).strip().lower()
                query = rest[:m_on.start()].strip()
                if platform in _PLATFORM_HINTS and query:
                    log.info(f"[Direct] search '{query}' on {platform} (via 'mở...trên')")
                    return {"action": "search", "target": platform, "query": query, "source": "direct"}

            # "mở [platform name]" chính xác
            target_clean = re.sub(r'\s+', '', rest_plain)
            for key, url in _DIRECT_OPEN_URLS.items():
                key_plain = OllamaCommandInterpreter._plain_text(key)
                if target_clean == re.sub(r'\s+', '', key_plain) or rest_plain == key_plain:
                    log.info(f"[Direct] open {key} → {url}")
                    return {"action": "open", "target": url, "query": "", "source": "direct"}

            # "mở ghi chú" / "mở note pad" / voice typo -> run app trực tiếp
            for alias, app in _DIRECT_RUN_APPS.items():
                alias_plain = OllamaCommandInterpreter._plain_text(alias)
                if rest_plain == alias_plain or alias_plain in rest_plain:
                    log.info(f"[Direct] run app alias '{rest}' → {app}")
                    return {"action": "run", "target": app, "query": "", "source": "direct"}

        # ── "tìm kiếm / tìm [X] trên [platform]" ─────────────────────────────
        m_search = _RE_SEARCH.match(t)
        if m_search:
            rest = m_search.group(1).strip()
            m_on = _RE_ON_PLATFORM.search(rest)
            if m_on:
                platform = m_on.group(1).strip().lower()
                query = rest[:m_on.start()].strip()
                if platform in _PLATFORM_HINTS and query:
                    log.info(f"[Direct] search '{query}' on {platform}")
                    return {"action": "search", "target": platform, "query": query, "source": "direct"}
            else:
                # tìm kiếm đơn → Google mặc định
                if rest:
                    log.info(f"[Direct] google search '{rest}'")
                    return {"action": "search", "target": "google", "query": rest, "source": "direct"}

        # ── "phát / play [X]" ─────────────────────────────────────────────────
        m_play = _RE_PLAY.match(t)
        if m_play:
            query = m_play.group(1).strip()
            # strip "trên [platform]" suffix nếu có
            m_on = _RE_ON_PLATFORM.search(query)
            if m_on:
                platform = m_on.group(1).strip().lower()
                query = query[:m_on.start()].strip()
                target = platform if platform in _PLATFORM_HINTS else "youtube"
            else:
                target = "youtube"
            if query:
                log.info(f"[Direct] play '{query}' on {target}")
                return {"action": "play", "target": target, "query": query, "source": "direct"}

        return None

    def interpret(
        self,
        text: str,
        available_commands: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Phân tích câu lệnh tự nhiên.

        Returns dict với các khóa:
          action, target, query  — khi thành công
          error                  — khi thất bại hoàn toàn
          source                 — "local" | "cloud" (để debug)
        """
        if not text or not text.strip():
            return {"error": "Câu lệnh trống"}

        # ── 0. Tra cứu trực tiếp (không cần Ollama) ───────────────────────────
        direct = self._try_rule_based_parse(text)
        if direct:
            return direct

        sector_shortcut = self._try_sector_shortcut(text)
        if sector_shortcut:
            return sector_shortcut

        # Tạo phần danh sách lệnh đã biết (nếu có)
        known_section = ""
        if available_commands:
            known_list = ", ".join(f'"{c}"' for c in available_commands[:20])
            known_section = (
                f"\nKnown commands in system: [{known_list}]. "
                "Prefer these names if they match."
            )

        sys_prompt = _SYS_PROMPT + known_section
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": text.strip()},
        ]

        raw_content: Optional[str] = None

        def _try_local_parse() -> Optional[Dict[str, Any]]:
            nonlocal raw_content
            if not self._check_local():
                return None
            raw_content = self._call_local(messages, max_tokens=self.command_max_tokens)
            if not raw_content:
                return None
            parsed = self._extract_json(raw_content)
            if parsed and parsed.get("action"):
                log.info(f"[Local] OK: {parsed}")
                return {
                    "action": str(parsed.get("action", "")).strip(),
                    "target": str(parsed.get("target", "")).strip(),
                    "query":  str(parsed.get("query",  parsed.get("parameters", ""))).strip(),
                    "source": "local",
                }
            log.warning(f"[Local] Parse fail, raw={raw_content!r}")
            return None

        def _try_cloud_parse() -> Optional[Dict[str, Any]]:
            nonlocal raw_content
            if not self.cloud_enabled or not self.enable_cloud_fallback:
                return None
            if self.command_cloud_policy in {"off", "local_only"}:
                return None

            prefer_local_now = self._is_simple_command(text)
            if prefer_local_now and not self.allow_cloud_for_simple:
                return None
            if self.command_cloud_policy == "complex_only" and not self._is_complex_command(text):
                return None
            log.info(f"[Power Mode] Sử dụng Cloud để phân tích lệnh: '{text[:40]}...'")
            raw_content = self._call_cloud(messages, max_tokens=self.command_max_tokens)
            if not raw_content:
                return None
            parsed = self._extract_json(raw_content)
            if parsed and parsed.get("action"):
                log.info(f"[Cloud] OK: {parsed}")
                return {
                    "action": str(parsed.get("action", "")).strip(),
                    "target": str(parsed.get("target", "")).strip(),
                    "query":  str(parsed.get("query",  parsed.get("parameters", ""))).strip(),
                    "source": "cloud",
                }
            log.warning(f"[Cloud] Parse fail, raw={raw_content!r}")
            return None

        # Local luôn là ưu tiên số 1 để tránh độ trễ cloud cho tác vụ điều khiển thường ngày.
        prefer_local = self._is_simple_command(text)
        local_hit = _try_local_parse()
        if local_hit:
            return local_hit

        cloud_hit = _try_cloud_parse()
        if cloud_hit:
            return cloud_hit

        if prefer_local and not self.allow_cloud_for_simple:
            return {
                "error": "Local parse thất bại; cloud bị khóa cho lệnh đơn giản để giảm độ trễ",
                "raw": raw_content or "",
            }

        # ── Cả hai đều thất bại ───────────────────────────────────────────────
        return {
            "error": "Không thể phân tích lệnh (cả local và cloud đều thất bại)",
            "raw": raw_content or "",
        }


# ── Singleton tiện ích ────────────────────────────────────────────────────────
_default_interpreter: Optional[OllamaCommandInterpreter] = None


def get_default_interpreter() -> OllamaCommandInterpreter:
    global _default_interpreter
    if _default_interpreter is None:
        _default_interpreter = OllamaCommandInterpreter()
    return _default_interpreter
