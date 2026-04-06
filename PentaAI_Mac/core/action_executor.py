#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: core/action_executor.py
Nhận dict từ OllamaCommandInterpreter và thực thi hành động tương ứng.

Các action được hỗ trợ:
  open   → mở URL / app
  search → tìm kiếm trên YouTube/Google/...
  play   → phát nhạc/video trên YouTube
  run    → chạy app macOS
  fetch  → (Phase 4) tải nội dung web
  setup  → (Phase 5) điều khiển hệ thống macOS
  penta  → (Phase 5) gọi quick-link từ pentaKuruV4
"""

import logging
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, Optional, List

from core.web_actions import WebActions

log = logging.getLogger("ActionExecutor")

# ── In-memory sectors pushed from PentaKuRu via HTTP ────────────────────────
# Được ghi bởi POST /api/kuru/sectors trên AI server.
# Ưu tiên cao hơn file trên đĩa; không bao giờ None (dict rỗng = chưa có dữ liệu).
_injected_sectors: Dict[str, Dict[str, Any]] = {}


def inject_sectors(data: Dict[str, Any]) -> int:
    """
    Nạp sectors từ PentaKuRu vào bộ nhớ AI server.
    data: dict index → {name, url, exe_path, ...}
    Trả về số sector đã ghi.
    """
    global _injected_sectors
    _injected_sectors = {str(k): v for k, v in data.items() if isinstance(v, dict)}
    log.info(f"[ActionExecutor] Đã nhận {len(_injected_sectors)} sectors từ PentaKuRu")
    return len(_injected_sectors)


def get_injected_sectors() -> Dict[str, Dict[str, Any]]:
    """Trả về bản sao của sectors đang được cache trong bộ nhớ."""
    return dict(_injected_sectors)


# ── Từ khoá nhận biết câu lệnh (không cần gọi Ollama) ───────────────────────
COMMAND_TRIGGERS = [
    # Tiếng Việt (có dấu)
    "mở ", "tìm ", "tìm kiếm", "phát ", "bật ", "tắt ", "chạy ",
    "truy cập", "vào trang", "lấy dữ liệu", "tải về",
    # Tiếng Việt không dấu (voice recognition thường bỏ dấu)
    "mo ", "tim ", "tim kiem", "phat ", "bat ", "tat ", "chay ",
    "search",
    # Tên platform
    "youtube", "google", "bing", "wikipedia", "github",
    # Tiếng Anh
    "open ", "play ", "search ", "find ",
]


def looks_like_command(text: str) -> bool:
    """
    Kiểm tra nhanh (không cần AI) xem câu có phải lệnh không.
    Giúp tránh gọi Ollama cho mọi tin nhắn chat thông thường.
    """
    t = text.lower().strip()
    return any(t.startswith(kw) or kw in t for kw in COMMAND_TRIGGERS)


class ActionExecutor:
    """
    Lớp thực thi lệnh trung tâm.

    Luồng:
      text → OllamaCommandInterpreter.interpret() → dict
           → ActionExecutor.execute(dict)
           → {ok, msg, url?, action}
    """

    def __init__(self):
        self.web = WebActions()
        self._sectors_cache: Dict[str, Dict[str, Any]] = {}
        self._sectors_mtime: Optional[float] = None
        self._sectors_path = self._resolve_sectors_path()

    def execute(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thực thi lệnh đã được parse bởi OllamaCommandInterpreter.

        Args:
            cmd: dict với các khóa: action, target, query (hoặc parameters)
        Returns:
            dict: {ok: bool, msg: str, url: str|None, action: str}
        """
        if not cmd:
            return {"ok": False, "msg": "Lệnh trống", "action": None}

        if "error" in cmd:
            return {"ok": False, "msg": cmd["error"], "action": None}

        action = cmd.get("action", "").lower().strip()
        target = cmd.get("target", "").strip()
        # Hỗ trợ cả key "query" (schema mới) và "parameters" (schema cũ)
        query  = (cmd.get("query") or cmd.get("parameters") or "").strip()

        log.info(f"[Executor] action={action!r} target={target!r} query={query!r}")

        try:
            return self._dispatch(action, target, query)
        except Exception as e:
            log.error(f"[Executor] Exception: {e}", exc_info=True)
            return {"ok": False, "msg": f"Lỗi thực thi: {e}", "action": action}

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _dispatch(self, action: str, target: str, query: str) -> Dict[str, Any]:
        if action == "open":
            return self._do_open(target, query)
        elif action == "search":
            return self._do_search(target, query)
        elif action == "play":
            # "phát nhạc X" → YouTube search
            return self.web.play_youtube(query or target)
        elif action == "run":
            return self._do_run(target)
        elif action == "fetch":
            # Phase 4 — placeholder
            return {
                "ok": False,
                "msg": "Tính năng fetch web đang được phát triển (Phase 4)",
                "action": "fetch",
            }
        elif action == "setup":
            # Phase 5 — placeholder
            return {
                "ok": False,
                "msg": "Tính năng điều khiển hệ thống đang được phát triển (Phase 5)",
                "action": "setup",
            }
        elif action == "penta":
            return self._do_penta(target, query)
        else:
            if action:
                log.warning(f"[Executor] action chưa hỗ trợ: {action!r}")
                return {
                    "ok": False,
                    "msg": f"Chưa hỗ trợ lệnh '{action}'",
                    "action": action,
                }
            return {"ok": False, "msg": "Không nhận ra lệnh", "action": action}

    def _resolve_sectors_path(self) -> Optional[Path]:
        env_path = os.getenv("PENTAKURU_SECTORS_PATH", "").strip()
        if env_path:
            return Path(env_path).expanduser()

        config_path = Path(__file__).resolve().parents[1] / "config.json"
        try:
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                configured = str(config.get("pentakuru_sectors_path", "")).strip()
                if configured:
                    return Path(configured).expanduser()
        except Exception as e:
            log.warning(f"[Executor] Không đọc được cấu hình sectors path: {e}")

        repo_default = Path(__file__).resolve().parents[2] / "PentakuruV4" / "data" / "sectors.json"
        return repo_default

    @staticmethod
    def _normalize_lookup_text(text: str) -> str:
        """Chuẩn hóa text để so sánh - hỗ trợ tiếng Việt tốt hơn."""
        cleaned = unicodedata.normalize("NFKD", (text or "").strip().lower())
        cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
        cleaned = re.sub(r"[^\w\s./:-]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        
        # Xử lý các lỗi voice recognition phổ biến tiếng Việt
        voice_fixes = {
            "youtuber": "youtube",
            "youtobe": "youtube",
            "youtobe": "youtube",
            "youto": "youtube",
            "face book": "facebook",
            "face bok": "facebook",
            "facebok": "facebook",
            "insta gram": "instagram",
            "insta": "instagram",
            "tik tok": "tiktok",
            "tik tok": "tiktok",
            "note pad": "notepad",
            "note pat": "notepad",
            "note bad": "notepad",
            "notebat": "notepad",
            "note bat": "notepad",
            "note bát": "notepad",
            "ghi chu": "notepad",
            "ghi chú": "notepad",
            "so tay": "notepad",
            "sổ tay": "notepad",
            "gugle": "google",
            "gu gơ": "google",
            "guogle": "google",
            "gooogle": "google",
            "bing": "bing",
            "bings": "bing",
            "wiki": "wikipedia",
            "wikipidia": "wikipedia",
            "wikipedya": "wikipedia",
            "zalo": "zalo",
            "za lo": "zalo",
            "shopee": "shopee",
            "sho pee": "shopee",
            "shop pe": "shopee",
            "lazada": "lazada",
            "la za da": "lazada",
            "grab": "grab",
            "grap": "grab",
            "github": "github",
            "git hub": "github",
            "git hab": "github",
            "discord": "discord",
            "dis cord": "discord",
            "discode": "discord",
            "netflix": "netflix",
            "net flix": "netflix",
            "netflex": "netflix",
            "spotify": "spotify",
            "spotyfi": "spotify",
            "spotifi": "spotify",
            "gmail": "gmail",
            "g mail": "gmail",
            "gmeil": "gmail",
        }
        
        for wrong, correct in voice_fixes.items():
            cleaned = cleaned.replace(wrong, correct)
        
        return cleaned

    def _load_sectors(self) -> List[Dict[str, Any]]:
        # Ưu tiên 1: sectors được PentaKuRu push qua HTTP (in-memory)
        if _injected_sectors:
            result = []
            for idx, payload in _injected_sectors.items():
                if not isinstance(payload, dict):
                    continue
                result.append({
                    "id": str(idx),
                    "name": str(payload.get("name", "")).strip(),
                    "url": str(payload.get("url", "")).strip(),
                    "exe_path": str(payload.get("exe_path", "")).strip(),
                })
            return result

        # Ưu tiên 2: đọc file sectors.json từ đường dẫn đã cấu hình
        if not self._sectors_path or not self._sectors_path.exists():
            return []

        try:
            current_mtime = self._sectors_path.stat().st_mtime
            if self._sectors_mtime == current_mtime and self._sectors_cache:
                return list(self._sectors_cache.values())

            raw = json.loads(self._sectors_path.read_text(encoding="utf-8"))
            cache: Dict[str, Dict[str, Any]] = {}
            for idx, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                sector = {
                    "id": str(idx),
                    "name": str(payload.get("name", "")).strip(),
                    "url": str(payload.get("url", "")).strip(),
                    "exe_path": str(payload.get("exe_path", "")).strip(),
                }
                cache[str(idx)] = sector

            self._sectors_cache = cache
            self._sectors_mtime = current_mtime
            return list(cache.values())
        except Exception as e:
            log.warning(f"[Executor] Không đọc được sectors.json: {e}")
            self._sectors_cache = {}
            self._sectors_mtime = None
            return []

    def _sector_candidates(self, sector: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        if sector.get("name"):
            candidates.append(self._normalize_lookup_text(sector["name"]))
        if sector.get("url"):
            candidates.append(self._normalize_lookup_text(sector["url"]))
        if sector.get("exe_path"):
            candidates.append(self._normalize_lookup_text(sector["exe_path"]))
        if sector.get("id"):
            candidates.append(self._normalize_lookup_text(sector["id"]))
        return [candidate for candidate in candidates if candidate]

    def _resolve_sector_by_id(self, sector_id: str) -> Optional[Dict[str, Any]]:
        sid = str(sector_id or "").strip()
        if not sid:
            return None
        for sector in self._load_sectors():
            if sector.get("id") == sid:
                return sector
        return None

    @staticmethod
    def _similarity_score(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _resolve_sector_alias(self, text: str) -> Optional[Dict[str, Any]]:
        """Tìm sector phù hợp với text nhập vào - hỗ trợ tiếng Việt voice recognition."""
        needle = self._normalize_lookup_text(text)
        if len(needle) < 2:
            return None

        best_match: Optional[Dict[str, Any]] = None
        best_score = 0
        best_debug = ""
        
        for sector in self._load_sectors():
            for candidate in self._sector_candidates(sector):
                if not candidate:
                    continue
                score = 0
                debug_reason = ""
                
                # Exact match
                if needle == candidate:
                    score = 100
                    debug_reason = "exact"
                # Needle contains candidate (e.g., "youtube" in "youtube.com")
                elif candidate in needle and len(candidate) >= 3:
                    score = 85
                    debug_reason = "candidate_in_needle"
                # Candidate contains needle (e.g., "youtube" in "youtube")
                elif needle in candidate and len(needle) >= 3:
                    score = 80
                    debug_reason = "needle_in_candidate"
                # Token-based matching for multi-word names
                elif len(needle) >= 3:
                    needle_tokens = set(needle.split())
                    candidate_tokens = set(candidate.split())
                    if needle_tokens and candidate_tokens:
                        overlap = len(needle_tokens & candidate_tokens) / max(1, len(needle_tokens))
                        if overlap >= 0.5:  # Giảm từ 0.75 xuống 0.5 cho voice input
                            score = int(overlap * 85)
                            debug_reason = f"token_overlap_{overlap:.2f}"
                
                # Fuzzy matching - giảm threshold cho voice input
                if score < 70:
                    fuzzy = self._similarity_score(needle, candidate)
                    # Giảm threshold từ 0.88 xuống 0.75 cho voice recognition
                    if fuzzy >= 0.75:
                        fuzzy_score = int(fuzzy * 100)
                        if fuzzy_score > score:
                            score = fuzzy_score
                            debug_reason = f"fuzzy_{fuzzy:.3f}"
                    # Đặc biệt cho app names ngắn (3-8 chars)
                    elif len(needle) <= 8 and len(candidate) <= 8:
                        if fuzzy >= 0.65:  # Thêm threshold thấp hơn cho app names
                            score = int(fuzzy * 90)
                            debug_reason = f"short_fuzzy_{fuzzy:.3f}"
                
                if score > best_score:
                    best_score = score
                    best_match = sector
                    best_debug = debug_reason

        # Giảm threshold từ 70 xuống 60 cho voice input
        threshold = 60
        if best_score >= threshold:
            log.info(f"[Sector] Matched '{text}' → '{best_match.get('name')}' (score={best_score}, {best_debug})")
            return best_match
        
        log.debug(f"[Sector] No match for '{text}' (best_score={best_score}, threshold={threshold})")
        return None

    def get_sectors_debug(self, query: str = "") -> Dict[str, Any]:
        sectors = self._load_sectors()
        matched = None
        if query:
            matched = self.resolve_sector_reference(query)
        return {
            "sectors_path": str(self._sectors_path) if self._sectors_path else "",
            "exists": bool(self._sectors_path and self._sectors_path.exists()),
            "count": len(sectors),
            "query": query,
            "matched": matched,
            "sectors": sectors,
        }

    def resolve_sector_reference(self, text: str) -> Optional[Dict[str, Any]]:
        lookup = str(text or "").strip()
        if not lookup:
            return None
        if lookup.isdigit():
            return self._resolve_sector_by_id(lookup)
        return self._resolve_sector_alias(lookup)

    def _open_sector_match(self, sector: Dict[str, Any], action: str) -> Dict[str, Any]:
        name = sector.get("name") or sector.get("url") or sector.get("exe_path") or sector.get("id")
        url = sector.get("url", "")
        path = sector.get("exe_path", "")

        if url:
            result = self.web.open_url(url)
        elif path:
            result = self.web.open_path(path)
        else:
            return {"ok": False, "msg": f"Sector '{name}' không có URL hoặc đường dẫn", "action": action}

        result.setdefault("action", action)
        result["source"] = "sectors"
        result["sector_name"] = name
        result["sector_id"] = sector.get("id")
        return result

    def _do_penta(self, target: str, query: str) -> Dict[str, Any]:
        lookup = query.strip() or target.strip()
        if not lookup:
            return {"ok": False, "msg": "Không rõ sector PentaKuru cần mở", "action": "penta"}

        sector = None
        if lookup.isdigit():
            sector = self._resolve_sector_by_id(lookup)

        if sector is None and query.strip().isdigit():
            sector = self._resolve_sector_by_id(query.strip())

        if sector is None:
            sector = self._resolve_sector_alias(lookup)

        if sector is None and target.strip() and target.strip().lower() not in {"link", "sector", "shortcut"}:
            sector = self._resolve_sector_alias(target)

        if sector is None:
            return {"ok": False, "msg": f"Không tìm thấy sector phù hợp cho '{lookup}'", "action": "penta"}

        return self._open_sector_match(sector, "penta")

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _do_open(self, target: str, query: str) -> Dict[str, Any]:
        """Mở URL, app hoặc sector - tự động dò sector trước."""
        if not target:
            return {"ok": False, "msg": "Không rõ cần mở gì", "action": "open"}

        t_low = target.lower()

        # ƯU TIÊN 1: Kiểm tra sector trước (cho phép "mở youtube" mở sector YouTube)
        sector = self._resolve_sector_alias(target) or self._resolve_sector_alias(query)
        if sector:
            log.info(f"[Open] Found sector for '{target}' → {sector.get('name')}")
            return self._open_sector_match(sector, "open")

        # ƯU TIÊN 2: Nếu target là tên platform + có query → search trên platform đó
        platforms = list(self.web.SEARCH_ENGINES.keys())
        if query and any(p in t_low for p in platforms):
            return self.web.search_on(target, query)

        # ƯU TIÊN 3: Nếu target là URL hoặc domain
        if "." in target or target.startswith("http"):
            return self.web.open_url(target)

        # ƯU TIÊN 4: Kiểm tra xem có phải platform name không (không có query)
        if any(p == t_low for p in platforms):
            # Mở trang chủ platform
            for key, url in self.web.SEARCH_ENGINES.items():
                if key == t_low:
                    base_url = url.split("?")[0]
                    return self.web.open_url(base_url)

        # ƯU TIÊN 5: Thử mở app macOS
        result = self.web.open_app(target)
        if result["ok"]:
            return result

        # Fallback: Google search
        return self.web.search_google(target)

    def _do_search(self, target: str, query: str) -> Dict[str, Any]:
        """Tìm kiếm - ưu tiên sector nếu có."""
        # Nếu không có query, target có thể chính là query
        if not query:
            query, target = target, "google"
        if not query:
            return {"ok": False, "msg": "Không có từ khoá tìm kiếm", "action": "search"}

        # Kiểm tra sector trước
        sector = self._resolve_sector_alias(query)
        if sector:
            return self._open_sector_match(sector, "search")

        # Kiểm tra platform
        platform_hint = (target or "").lower().strip()
        explicit_platform = any(key in platform_hint for key in self.web.SEARCH_ENGINES.keys())
        
        return self.web.search_on(target or "google", query)

    def _do_run(self, target: str) -> Dict[str, Any]:
        """Chạy ứng dụng - ưu tiên sector nếu có."""
        if not target:
            return {"ok": False, "msg": "Không rõ app cần chạy", "action": "run"}
        
        # ƯU TIÊN 1: Kiểm tra sector
        sector = self._resolve_sector_alias(target)
        if sector:
            return self._open_sector_match(sector, "run")
        
        # ƯU TIÊN 2: Thử mở app macOS
        result = self.web.open_app(target)
        if result["ok"]:
            return result
        
        # Fallback: Google search
        return self.web.search_google(target)
