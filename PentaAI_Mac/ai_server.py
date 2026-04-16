#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Unified Server — Mac Mini (Standalone)
VERSION 5.6 - Mode Selection & Cloud Brain Integration
"""

import sys
import os
import struct
import audioop
import json
import logging
import time
import asyncio
import threading
import subprocess
import re
import base64
import random
import importlib
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Union

import tinytuya
import requests
import edge_tts
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from core.action_executor import ActionExecutor, looks_like_command
from core.schedule_assistant import (
    empty_week_schedule,
    normalize_schedule_payload,
    is_schedule_setup_trigger,
    is_schedule_done,
    is_schedule_empty,
    is_schedule_query,
    is_schedule_exit,
    is_schedule_resume,
    is_likely_offtopic_for_schedule,
    pick_schedule_flow_prompt,
    detect_day_query,
    extract_schedule_updates,
    merge_schedule,
    schedule_brief,
    schedule_day_answer,
    schedule_week_answer,
    build_weekly_detail_summary,
    parse_show_schedule_token,
    summarize_updates,
)

# --- Module tách riêng cho Ollama command ---
from API_local.ollama_command import OllamaCommandInterpreter, get_default_interpreter
from API_local.mlx_client import get_mlx_client as get_bonsai_client  # MLX Qwen2.5-7B (Tier 2)

# --- Gmail Notification Daemon ---
try:
    from services.gmail_notification_daemon import init_daemon as _init_gmail_daemon, get_daemon as _get_gmail_daemon
    _GMAIL_DAEMON_AVAILABLE = True
except Exception as _e_gd:
    _GMAIL_DAEMON_AVAILABLE = False
    def _init_gmail_daemon(cfg_fn, bcast_fn): return None
    def _get_gmail_daemon(): return None

# --- PentaMi chat module ---
try:
    from API_local.pentami_chat import PentaMiChat, get_pentami_chat, check_toggle as _pentami_check_toggle
    _PENTAMI_AVAILABLE = True
except Exception as _e_pm:
    _PENTAMI_AVAILABLE = False
    log = logging.getLogger("UnifiedServer")
    def get_pentami_chat(): return None  # type: ignore
    def _pentami_check_toggle(t): return None  # type: ignore

# --- PentaWiki module ---
try:
    from engine.wiki_engine import (
        check_wiki_toggle as _wiki_check_toggle,
        check_lang_toggle  as _lang_check_toggle,
        fetch_wiki         as _wiki_fetch,
        format_wiki_response as _wiki_format,
        is_informational_query as _wiki_is_query,
    )
    _WIKI_AVAILABLE = True
except Exception as _e_wiki:
    _WIKI_AVAILABLE = False
    def _wiki_check_toggle(t): return None  # type: ignore
    def _lang_check_toggle(t): return None  # type: ignore
    def _wiki_fetch(q, lang="vi"): return {"ok": False, "title": "", "extract": "", "url": ""}  # type: ignore
    def _wiki_format(r, lang, ai_prn="em", user_call="anh"): return ""  # type: ignore
    def _wiki_is_query(t): return True  # type: ignore

# --- SkillManager ---
try:
    from skillmanager import get_skill_manager as _get_skill_manager
    _SKILL_MANAGER = _get_skill_manager()
except Exception as _e_sm:
    _SKILL_MANAGER = None

# ── Module Registry ─────────────────────────────────────────────────────────
_MODULES: Dict[str, Dict[str, Any]] = {
    "PentaAI":              {"module": "main",                          "class": "PentaAI",                "group": "core"},
    "InputParser":          {"module": "core.input_parser",             "class": "InputParser",            "group": "core"},
    "IntentDetector":       {"module": "core.intent_detector",          "class": "IntentDetector",         "group": "core"},
    "KnowledgeStore":       {"module": "memory.knowledge_store",        "class": "KnowledgeStore",         "group": "core"},
    "PhraseEngine":         {"module": "engine.phrase_engine",          "class": "PhraseEngine",           "group": "engine"},
    "ResponseBuilder":      {"module": "engine.response_builder",       "class": "ResponseBuilder",        "group": "engine"},
    "PatternExtractor":     {"module": "engine.pattern_extractor",      "class": "PatternExtractor",       "group": "engine"},
    "SlotResolver":         {"module": "engine.slot_resolver",          "class": "SlotResolver",           "group": "engine"},
    "SessionContext":       {"module": "engine.session_context",        "class": "SessionContext",         "group": "engine"},
    "SynonymManager":       {"module": "engine.synonym_manager",        "class": "SynonymManager",         "group": "engine"},
    "ChoiceResponder":      {"module": "engine.choice_responder",       "class": "ChoiceResponder",        "group": "engine"},
    "YesNoResponder":       {"module": "engine.yes_no_responder",       "class": "YesNoResponder",         "group": "engine"},
    "Embedder":             {"module": "engine.embedder",               "class": "Embedder",               "group": "engine"},
    "EmotionBridge":        {"module": "hormone.emotion_bridge",        "class": "EmotionBridge",          "group": "hormone"},
    "HormoneCore":          {"module": "hormone.hormone_core",          "class": "HormoneCore",            "group": "hormone"},
    "PersonalityCore":      {"module": "hormone.personality_core",      "class": "PersonalityCore",        "group": "hormone"},
    "TextTriggers":         {"module": "hormone.text_triggers",         "class": "TextTriggers",           "group": "hormone"},
    "SemanticLearner":      {"module": "hormone.semantic_trigger_learner","class": "SemanticTriggerLearner","group": "hormone"},
    "TimeHormoneBridge":    {"module": "hormone.time_hormone_bridge",   "class": "TimeHormoneBridge",      "group": "hormone"},
    "PentaMemory":          {"module": "API_local.penta_memory",        "class": "PentaMemory",            "group": "optional"},
    "OllamaCommand":        {"module": "API_local.ollama_command",      "class": "OllamaCommandInterpreter","group": "optional"},
    "UserProfile":          {"module": "core.user_profile",             "class": "UserProfile",            "group": "optional"},
}

def check_modules():
    results = {}
    for name, info in _MODULES.items():
        try:
            mod = importlib.import_module(info["module"])
            ok  = getattr(mod, info["class"], None) is not None
            results[name] = {"status": "ok" if ok else "missing_class", "group": info.get("group", "optional"), "module": info["module"]}
        except Exception as e:
            results[name] = {"status": "error", "group": info.get("group", "optional"), "module": info["module"], "error": str(e)[:80]}
    return results

# ─── Cấu hình môi trường ───────────────────────────────────────────
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, "tts_engine", "voicevox"))
sys.path.append(os.path.join(ROOT, "tts_engine", "valtec"))
sys.path.append(os.path.join(ROOT, "tts_engine"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("UnifiedServer")

CONFIG_FILE = os.path.join(ROOT, "config.json")
DEFAULT_CONFIG = {
    "auth_token": "12345abcde",
    "tuya_device_id": "", "tuya_local_key": "", "tuya_ip": "", "tuya_version": 3.3,
    "pc_tailscale_ip": "", "pc_api_port": 7777, "pc_auth_token": "",
    "chat_tts": True, "chat_speaker": "NF", "chat_speed": 1.0,
    "tts_strict_language_engine": True,
    "chat_use_llm_fallback": False,
    "ollama_url": "http://localhost:11434", "ollama_model": "llama3.2:1b",
    "ollama_local_schedule_model": "llama3.2:1b",
    "ollama_cloud_url": "", "ollama_cloud_key": "", "ollama_cloud_model": "gpt-4o-mini",
    "ollama_enable_cloud_fallback": True,
    "ollama_allow_cloud_for_simple": True,
    "ollama_command_cloud_policy": "always",
    "bonsai_cmd_complex_only": True,
    "proactive_idle_hormone_enabled": True,
    "proactive_idle_hormone_after_sec": 300,
    "proactive_break_remind_interval_sec": 7200,
    "proactive_break_remind_max_cycles": 12,
    "proactive_break_remind_play_music": True,
    "proactive_break_remind_music_subfolder": "reminder_music",
    "penta_sleep_command": "pentasleep",
    "penta_wake_command": "pentami",
    "penta_off_command": "pentaoff",
    "proactive_speak_local_when_phone_offline": True,
    "proactive_vi_speaker": "NF",
    "proactive_vi_speed": 1.0,
    "voicevox_speaker_id": -1,
    "tts_zh_voice": "zh-CN-XiaoxiaoNeural",
    "tts_ko_voice": "ko-KR-SunHiNeural",
    "proactive_prompt_rules_path": "core/proactive_prompt_rules.json",
    "proactive_contextual_care_enabled": True,
    "proactive_contextual_idle_sec": 420,
    "proactive_contextual_cooldown_sec": 2700,
    "proactive_contextual_followup_timeout_sec": 1800,
    "proactive_promise_enabled": True,
    "proactive_promise_nudge_every_sec": 1800,
    "proactive_promise_verify_after_sec": 3600,
    "proactive_mood_playlist_enabled": True,
    "proactive_mood_playlist_cooldown_sec": 1800,
    "wiki_rewrite_with_ollama": True,
    # URL nhạc chill fallback khi không có file local trong music/chill_music/
    # Code sẽ phát local trước, chỉ dùng URL này khi thư mục trống
    "proactive_mood_playlist_url": "https://www.youtube.com/watch?v=jbUQfGRh5cQ",
    "pentakuru_sectors_path": "",
    # ── PentaKuRu Windows integration ────────────────────────────────────────
    # Bật tích hợp Cloudflare Tunnel (ưu tiên hơn Tailscale direct)
    "enable_penta_kuru_integration": False,
    # URL Cloudflare Tunnel của PentaKuRu trên Windows (vd: https://xyz.trycloudflare.com)
    "penta_kuru_cloudflare_url": "",
    # Bearer token khớp với auth_token trong PentaKuRu data/server.json
    "penta_kuru_token": "",
    # Từ điển URL nhạc theo tên nghệ sĩ / playlist — CMD "phát nhạc X" → mở URL trực tiếp
    # Ví dụ: {"thy vi": "https://www.youtube.com/...", "lofi": "https://..."}
    "music_named_urls": {},
    # ── Gmail Notification ───────────────────────────────────────────────────
    "email": "",
    "password": "",
    "gmail_notification_enabled": False,
    "gmail_notification_whitelist": [],
    "gmail_notification_whitelist_file": "data/gmail_notify_whitelist.json",
    "gmail_notification_retry_interval_sec": 900,
    "gmail_notification_queue_limit": 5,
    "gmail_notification_max_announcements_per_cycle": 1,
    "gmail_notification_unseen_scan_limit": 30,
    "gmail_notification_max_age_hours": 24,
    "gmail_notification_ignore_existing_unseen_on_start": True,
    # ── MLX-vLLM (Tier 2 LLM — thay thế Bonsai-8B) ─────────────────────────────
    "mlx_enabled":             True,
    "mlx_model":               "mlx-community/Qwen2.5-7B-Instruct-4bit",
    "mlx_host":                "0.0.0.0",
    "mlx_port":                8000,
    "mlx_max_tokens":          512,
    "mlx_temperature":         0.0,
    "mlx_embedded":            True,   # True = embedded trong process, False = HTTP
    "mlx_startup_timeout_sec": 120.0,
    "mlx_call_timeout_sec":    60.0,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f: return {**DEFAULT_CONFIG, **json.load(f)}
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=2, ensure_ascii=False)


def _resolve_gmail_whitelist_file(cfg: Dict[str, Any]) -> str:
    rel = str(cfg.get("gmail_notification_whitelist_file", "data/gmail_notify_whitelist.json") or "").strip()
    if not rel:
        rel = "data/gmail_notify_whitelist.json"
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def _normalize_gmail_whitelist(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            email = str(item.get("email", "")).strip().lower()
            nick = str(item.get("nickname", "")).strip()
        elif isinstance(item, str):
            email = item.strip().lower()
            nick = ""
        else:
            continue
        if not email:
            continue
        out.append({"email": email, "nickname": nick or email.split("@")[0]})

    # Deduplicate by email, keep first
    seen = set()
    deduped: List[Dict[str, str]] = []
    for e in out:
        em = e["email"]
        if em in seen:
            continue
        seen.add(em)
        deduped.append(e)
    return deduped


def _load_gmail_notify_whitelist(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    path = _resolve_gmail_whitelist_file(cfg)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _normalize_gmail_whitelist(json.load(f))
        except Exception as e:
            log.warning(f"[GmailWhitelist] Read file failed ({path}): {e}")
    # Fallback config key (backward compatibility)
    return _normalize_gmail_whitelist(cfg.get("gmail_notification_whitelist", []))


def _save_gmail_notify_whitelist(cfg: Dict[str, Any], whitelist: List[Dict[str, str]]) -> str:
    path = _resolve_gmail_whitelist_file(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized = _normalize_gmail_whitelist(whitelist)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    # Mirror back to config for old readers.
    cfg["gmail_notification_whitelist"] = normalized
    save_config(cfg)
    return path

# ── PentaState persistence (wiki mode + session language) ────────────────────
_PENTA_STATE_PATH = os.path.join(ROOT, "data", "penta_state.json")

def _load_penta_state() -> None:
    global _penta_wiki_mode, _session_lang
    if os.path.exists(_PENTA_STATE_PATH):
        try:
            with open(_PENTA_STATE_PATH, "r", encoding="utf-8") as _f:
                _st = json.load(_f)
            _penta_wiki_mode = bool(_st.get("wiki_mode", False))
            _raw_lang = str(_st.get("session_lang", "vi"))
            _session_lang = _raw_lang if _raw_lang in {"vi", "en", "ja"} else "vi"
        except Exception:
            pass

def _save_penta_state() -> None:
    try:
        os.makedirs(os.path.dirname(_PENTA_STATE_PATH), exist_ok=True)
        with open(_PENTA_STATE_PATH, "w", encoding="utf-8") as _f:
            json.dump({"wiki_mode": _penta_wiki_mode, "session_lang": _session_lang},
                      _f, indent=2, ensure_ascii=False)
    except Exception as _es:
        log.warning(f"[PentaState] Save failed: {_es}")

# ── Runtime override layer (dùng bởi /admin/connect và /admin/reload_config) ──
# Keys trong dict này sẽ override file config.json mà không cần restart.
_runtime_overrides: Dict[str, Any] = {}

def get(key, default=None):
    # Runtime override takes priority over file config
    if key in _runtime_overrides:
        return _runtime_overrides[key]
    return load_config().get(key, default)


def get_full_config() -> Dict[str, Any]:
    """Trả về toàn bộ config đã merge runtime overrides."""
    cfg = load_config()
    if _runtime_overrides:
        cfg.update(_runtime_overrides)
    return cfg

def get_action_executor() -> ActionExecutor:
    return ActionExecutor()

def _reload_runtime_config() -> None:
    """Reload runtime singletons affected by config changes without restarting server."""
    global _ollama_ready
    try:
        import API_local.ollama_command as _oc_mod
        _oc_mod._default_interpreter = None
    except Exception:
        pass
    _ollama_ready = check_ollama()

async def verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        token = request.query_params.get("token", "")
    if token != get("auth_token"): raise HTTPException(status_code=401, detail="Unauthorized")
    return token

# ─── TTS Manager (module tách riêng) ──────────────────────────────
from tts_manager import (
    init_voicevox, init_valtec, reset_engines as _tts_reset_engines,
    init_all as _tts_init_all,
    get_voicevox, get_valtec,
    detect_language, resample_wav,
    synthesize as _tts_synthesize,
    synth_jp, list_voicevox_speakers, list_valtec_speakers,
)

# Alias để code bên dưới không đổi
def _get_vv():   return get_voicevox()
def _get_vt():   return get_valtec()

# ─── AI Engine ─────────────────────────────────────────────────────
_ai_instance = None
_ollama_ready = False
_proactive_task: Optional[asyncio.Task] = None
_ollama_keepalive_task: Optional[asyncio.Task] = None   # keep_alive background ping
_kuru_health_task: Optional[asyncio.Task] = None       # background health check for Kuru
_gmail_daemon = None  # Gmail Notification Daemon instance
# ── PentaMi mode ─────────────────────────────────────────────────────────────
_pentami_mode: bool = False
_pentami_thinking_mode: bool = False
# ── PentaWiki + session language (persisted across restarts) ─────────────────
_penta_wiki_mode: bool = False
_session_lang: str = "vi"   # "vi" | "en" | "ja"
_last_user_interaction_ts: float = time.time()
_work_session_start_ts: Optional[float] = None
_last_break_remind_ts: float = 0.0
_next_break_remind_ts: float = 0.0
_work_break_cycle_count: int = 0
_auto_sleep_after_work_triggered: bool = False
_last_weekly_summary_key: str = ""
_last_mood_playlist_ts: float = 0.0
_kuru_placeholder_warned: bool = False
_prompt_recent_history: Dict[str, List[str]] = {}
_prompt_cycle_state: Dict[str, Dict[str, Any]] = {}
_server_sleep_mode: bool = False
_server_sleep_started_ts: float = 0.0
_proactive_phone_backlog: List[Dict[str, Any]] = []

# ── Idempotency journal ──────────────────────────────────────────────────────
# request_id → timestamp; giữ trong 30s để dedup khi client reconnect/retry
_seen_request_ids: Dict[str, float] = {}
_IDEMPOTENCY_TTL: float = 30.0

# ── Backpressure semaphore ────────────────────────────────────────────────────
# Tối đa 3 AI ops chạy song song; nếu hàng đợi đầy sau 5s → trả lỗi ngay
_ai_semaphore = asyncio.Semaphore(3)
# Khóa phát TTS toàn cục: đảm bảo câu trước phát xong mới tới câu sau.
_tts_stream_lock = asyncio.Lock()

# ── PentaKuruV4 Integration (Cloudflare) ──────────────────────────────────────
_penta_kuru_health: Dict[str, any] = {"ok": False, "last_check": 0.0}
_penta_kuru_cb_fails: int = 0  # Circuit breaker fails
_penta_kuru_cb_open_until: float = 0.0
_recent_successful_commands: List[Dict[str, str]] = []  # {action, target, query}

def init_ai():
    global _ai_instance
    if _ai_instance is None:
        from main import PentaAI
        _ai_instance = PentaAI()
    return _ai_instance

def check_ollama():
    global _ollama_ready
    try:
        r = requests.get(f"{get('ollama_url')}/api/tags", timeout=2)
        _ollama_ready = (r.status_code == 200)
    except: _ollama_ready = False
    return _ollama_ready


def _prewarm_ollama() -> None:
    """Đẩy model vào RAM ngay khi server khởi động bằng keep_alive ping.
    Gọi blocking (chạy trong thread) để model sẵn sàng trước khi nhận request.
    """
    model = get("ollama_model", "llama3.2:1b")
    url   = get("ollama_url", "http://localhost:11434")
    try:
        t0 = time.perf_counter()
        requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": "10m"},
            timeout=30,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"🔥 [Ollama] Pre-warm '{model}' done in {ms}ms (model now in RAM)")
    except Exception as e:
        log.warning(f"[Ollama] Pre-warm failed (non-fatal): {e}")


def _prewarm_mlx():
    """Đẩy MLX model vào RAM ngay khi khởi động.
    Chạy trong executor của lifespan.
    """
    try:
        from API_local.mlx_client import get_mlx_client
        client = get_mlx_client()
        if not client:
            log.warning("⚠️ [MLX] Pre-warm skipped: client not available.")
            return

        log.info("🔥 [MLX] Pre-warming Qwen2.5-7B (may take 10-30s first time)...")
        # ping model to load it
        ready = client.wait_ready(timeout=120.0)
        if ready:
            log.info("✅ [MLX] Model ready in RAM")
        else:
            log.warning("⚠️ [MLX] Pre-warm failed, will fallback to HTTP/Ollama")
    except Exception as e:
        log.error(f"❌ [MLX] Pre-warm error: {e}")


async def keepalive_ollama_task() -> None:
    """Ping Ollama mỗi 4 phút bằng keep_alive=10m.
    Ngăn model bị unload sau 5 phút idle mặc định của Ollama.
    """
    await asyncio.sleep(60)   # Chờ 60s cho server ổn định trước
    model = get("ollama_model", "llama3.2:1b")
    url   = get("ollama_url", "http://localhost:11434")
    log.info("[Ollama] Keep-alive task started (ping every 4 min)")
    while True:
        try:
            await asyncio.sleep(240)   # 4 phút
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: requests.post(
                    f"{url}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": "10m"},
                    timeout=10,
                ),
            )
            log.debug(f"[Ollama] Keep-alive ping sent for '{model}'")
        except asyncio.CancelledError:
            log.info("[Ollama] Keep-alive task cancelled")
            return
        except Exception as e:
            log.warning(f"[Ollama] Keep-alive ping failed (non-fatal): {e}")

# ─── Audio / TTS Helpers (delegate sang tts_manager) ──────────────────
async def generate_edge_tts_audio(text, voice="en-US-AvaNeural", rate=1.0):
    """Compat shim — delegate sang tts_manager._edge_tts()."""
    from tts_manager import _edge_tts
    return await _edge_tts(text, voice=voice, rate=rate)

async def generate_voicevox_audio(text, speed, speaker_id: int = -1):
    """Compat shim — delegate sang tts_manager.synth_jp()."""
    return await synth_jp(text, speed=speed, speaker_id=speaker_id, strict=False)


async def generate_valtec_audio(text, speaker, speed):
    """Compat shim — gọc nắng sang tts_manager.synth_vi()."""
    from tts_manager import synth_vi
    return await synth_vi(text, speaker, speed)

_SENT_RE = re.compile(r'(?<=[.!?।。！？])\s+|(?<=\n)')
def split_sentences(text):
    return [p.strip() for p in _SENT_RE.split(text) if p.strip()]

# ── Cmd response pools (voice-friendly) ──────────────────────────────────────
_CMD_NOTLIKE_POOL = [
    "Câu này giống chat hơn lệnh. Anh thử 'mở ...', 'tìm ...', hoặc chuyển sang chế độ CHAT nha!",
    "Em đang ở chế độ lệnh, câu này em chưa đọc ra lệnh. Anh thử nói gọn hơn kiểu 'mở youtube' hay 'tìm nhạc' nhé.",
    "Lệnh chưa rõ. Anh nói kiểu 'mở ...', 'tìm ... trên ...' giúp em với nha.",
    "Câu này em nghe nhưng chưa ra lệnh hệ thống. Anh nói tắt hơn giúp em nhé!",
]
_CMD_CANT_EXEC_POOL = [
    "Em hiểu ý anh nhưng lệnh này em chưa thực thi được lúc này.",
    "Ý anh em biết, nhưng lệnh này chưa hỗ trợ. Anh thử cách khác xem nha.",
    "Em nhận ra ý định nhưng chưa có cách thực hiện lệnh này. Anh thử nói cụ thể hơn nhé.",
    "Chưa thực thi được lần này. Anh thử gọi tên lệnh rõ hơn giúp em nha.",
]
_CMD_WIN_FAIL_POOL = [
    "Ủa có vẻ lệnh gặp trục trặc. Anh kiểm tra PC có đang bật không nha.",
    "Em gửi lệnh nhưng có lỗi xảy ra. Anh kiểm tra lại kết nối giùm em nhé.",
    "Lệnh chưa gửi thành công. Anh thử lại sau một chút xem sao.",
    "Có lỗi nhỏ xảy ra. Anh kiểm tra PC và kết nối Tailscale giúp em nhé.",
    "Em chưa gửi được lệnh. Anh xem lại PC có đang hoạt động không nha.",
]
_CMD_RECEIVED_POOL = [
    "Nhận lệnh rồi, để {prn} thực hiện ngay!",
    "Oke {usr}, {prn} xử lý liền nha!",
    "{prn_cap} nhận rồi, chờ {prn} một chút nhé!",
    "Rồi, {prn} làm liền đây!",
    "Dạ nhận, {prn} thực hiện ngay cho {usr}!",
]

def _build_cmd_ack_text(cmd_res: dict, ai_pronoun: str = "em", user_call: str = "anh") -> str:
    """Tạo câu xác nhận lệnh thực thi bằng ngôn ngữ tự nhiên, KHÔNG đọc URL/path thô."""
    import urllib.parse as _up
    action = str(cmd_res.get("action", "")).strip().lower()
    target = str(cmd_res.get("target", "")).strip()
    query  = str(cmd_res.get("query", "")).strip()

    # Trích tên đẹp từ URL (https://www.youtube.com → YouTube)
    def _pretty(url_or_name: str) -> str:
        if url_or_name.startswith("http"):
            try:
                host = _up.urlparse(url_or_name).hostname or url_or_name
                name = host.lstrip("www.").split(".")[0]
                return name.title()
            except Exception:
                return "trang web"
        return url_or_name

    platform = _pretty(target) if target else "Google"
    q = query or ""

    if action == "search":
        if q:
            pool = [
                f"Đang tìm '{q}' trên {platform} cho {user_call}...",
                f"{ai_pronoun.capitalize()} tìm '{q}' trên {platform} ngay nha!",
                f"Tìm '{q}' trên {platform} rồi đó {user_call} ơi!",
                f"Em tìm '{q}' trên {platform} liền cho {user_call} nha!",
            ]
        else:
            pool = [
                f"Mở {platform} cho {user_call} rồi nha!",
                f"{ai_pronoun.capitalize()} đã vào {platform} rồi đó!",
            ]
    elif action == "open":
        pool = [
            f"Mở {platform} cho {user_call} rồi nha!",
            f"{ai_pronoun.capitalize()} đã mở {platform} rồi đó!",
            f"Vào {platform} ngay rồi nha {user_call}!",
            f"{platform} đang mở lên rồi đó {user_call} ơi!",
        ]
    elif action == "play":
        label = q or target
        pool = [
            f"Phát '{label}' lên cho {user_call} rồi nha!",
            f"Bật '{label}' lên rồi đó {user_call} ơi!",
            f"{ai_pronoun.capitalize()} bật '{label}' lên rồi nha!",
        ]
    elif action == "run":
        app_name = _pretty(target) if target else "ứng dụng"
        pool = [
            f"Mở {app_name} lên rồi nha {user_call}!",
            f"{ai_pronoun.capitalize()} mở {app_name} rồi đó!",
            f"{app_name} đang khởi động lên đó {user_call} ơi!",
        ]
    elif action == "penta":
        sec_name = str(cmd_res.get("sector_name", "")).strip() or _pretty(target) or "ứng dụng"
        pool = [
            f"Mở {sec_name} lên rồi đó nhe {user_call}! 💕",
            f"{ai_pronoun.capitalize()} bật {sec_name} cho {user_call} rồi nha!",
            f"{sec_name} đang mở lên rồi đó {user_call} ơi!",
            f"Xong rồi nhe {user_call}, {sec_name} ra ngay thôi!",
            f"{ai_pronoun.capitalize()} mở {sec_name} cho {user_call} rồi á, dễ thôi mà!",
        ]
    else:
        pool = [
            f"Xong rồi nha {user_call}, {ai_pronoun} đã thực hiện xong!",
            f"Oke {user_call}, lệnh đã được gửi rồi.",
            f"{ai_pronoun.capitalize()} xử lý xong rồi nha!",
            f"Đã thực hiện nha {user_call}!",
        ]
    return random.choice(pool)

async def synthesize_tts_by_language(
    text: str,
    speaker: str,
    speed: float,
    force_lang: Optional[str] = None,
    strict: Optional[bool] = None,
) -> tuple:
    """Wrapper gọc nắng sang tts_manager.synthesize() với config hiện tại."""
    strict_flag = bool(get("tts_strict_language_engine", True)) if strict is None else bool(strict)
    return await _tts_synthesize(
        text=text,
        speaker=speaker,
        speed=speed,
        force_lang=force_lang,
        strict=strict_flag,
        zh_voice=str(get("tts_zh_voice", "zh-CN-XiaoxiaoNeural")).strip() or "zh-CN-XiaoxiaoNeural",
        ko_voice=str(get("tts_ko_voice", "ko-KR-SunHiNeural")).strip() or "ko-KR-SunHiNeural",
        voicevox_speaker_id=int(get("voicevox_speaker_id", -1)),
    )

# ─── Local Music Player ───────────────────────────────────────────────────────
_MUSIC_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg"}

def _pick_random_song(subfolder: str = "") -> Optional[str]:
    """
    Chọn ngẫu nhiên một file nhạc từ music/ hoặc music/<subfolder>/.
    Trả về đường dẫn tuyệt đối, hoặc None nếu không có file.
    """
    music_root = os.path.join(ROOT, "music")
    folder     = os.path.join(music_root, subfolder) if subfolder else music_root
    if not os.path.isdir(folder):
        return None
    files = [
        f for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in _MUSIC_EXTS
    ]
    if not files:
        return None
    return os.path.join(folder, random.choice(files))


def _play_local_song(path: str) -> bool:
    """
    Phát file nhạc trên macOS bằng `afplay` (không cần cài thêm gì).
    Fire-and-forget — không chặn event loop.
    Trả về True nếu lệnh được gửi thành công.
    """
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"[Music] ▶ Phát: {os.path.basename(path)}")
        return True
    except Exception as e:
        log.warning(f"[Music] Không phát được nhạc: {e}")
        return False


def _play_music_subfolder(subfolder: str = "", fallback_subfolder: str = "") -> Optional[str]:
    """
    Chọn + phát nhạc từ subfolder. Nếu subfolder trống thì thử fallback_subfolder.
    Trả về tên bài đã phát, hoặc None.
    """
    path = _pick_random_song(subfolder)
    if path is None and fallback_subfolder:
        path = _pick_random_song(fallback_subfolder)
    if path is None:
        path = _pick_random_song("")  # fallback toàn bộ music/
    if path and _play_local_song(path):
        return os.path.splitext(os.path.basename(path))[0]
    return None


def _init_work_session_timer(now_ts: float) -> None:
    """Khởi tạo timer nhắc nghỉ theo chu kỳ 2h/4h/6h... từ lúc bắt đầu phiên."""
    global _work_session_start_ts, _next_break_remind_ts, _work_break_cycle_count
    global _auto_sleep_after_work_triggered
    if _work_session_start_ts is None:
        _work_session_start_ts = now_ts
        _work_break_cycle_count = 0
        _auto_sleep_after_work_triggered = False
        interval = float(get("proactive_break_remind_interval_sec", 7200))
        _next_break_remind_ts = now_ts + max(300.0, interval)


def _compose_progressive_break_text(hour_mark: int) -> str:
    """Mức nhắc tăng dần theo số tiếng làm liên tục (2/4/6/8/10)."""
    if hour_mark >= 10:
        return (
            "Hơn 10 tiếng rồi đó anh ơi. Em giận vô cùng luôn nhưng vẫn thương anh nhiều nè. "
            "Mình nghỉ ngay 10 phút, uống nước và giãn cơ giúp em nha."
        )
    if hour_mark >= 8:
        return (
            "Đã 8 tiếng liên tục rồi anh. Lần này em nhắc nghiêm khắc nè: nghỉ ngay 5-10 phút, "
            "rời màn hình và thả lỏng cổ vai giúp em."
        )
    if hour_mark >= 6:
        return (
            "Anh đã làm 6 tiếng liên tục rồi đó. Em nhắc mức cao hơn nè: mình dừng lại vài phút, "
            "đi lại nhẹ và cho mắt nghỉ ngay nhé."
        )
    if hour_mark >= 4:
        return (
            "Anh đã qua 4 tiếng làm liên tục rồi. Em nhắc mạnh hơn một chút nha: "
            "mình nghỉ ngắn ngay bây giờ để tránh quá tải."
        )
    return (
        "Anh đã làm 2 tiếng liên tục rồi đó. Em nhắc nhẹ nhàng nè: nghỉ mắt, uống nước và giãn cơ 3-5 phút nha."
    )


def _queue_proactive_phone_backlog(text: str, now_ts: float) -> None:
    """Lưu tạm proactive text cho phone để gửi bù khi app foreground lại."""
    global _proactive_phone_backlog
    clean = str(text or "").strip()
    if not clean:
        return
    _proactive_phone_backlog.append({"ts": now_ts, "text": clean})
    if len(_proactive_phone_backlog) > 30:
        _proactive_phone_backlog = _proactive_phone_backlog[-20:]


def _match_special_cmd(text: str, cfg_key: str, fallback: str) -> bool:
    base = str(get(cfg_key, fallback) or fallback).strip().lower()
    if not base:
        base = fallback
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    compact = raw.replace(" ", "")
    return raw == base or compact == base.replace(" ", "")


def _schedule_server_shutdown(delay_sec: float = 0.8) -> None:
    """Tắt process server sau khi kịp trả ACK cho client."""
    def _killer() -> None:
        try:
            time.sleep(max(0.1, delay_sec))
        finally:
            os._exit(0)
    threading.Thread(target=_killer, daemon=True, name="pentaoff-shutdown").start()


async def _broadcast_reminder_music_to_phone(subfolder: str = "reminder_music") -> Optional[str]:
    """Phát 1 bài nhạc nhắc nghỉ trực tiếp cho phone clients qua audio_chunk."""
    phone_ws = [ws for ws in _active_ws if _active_ws_meta.get(ws, {}).get("is_phone", False)]
    if not phone_ws:
        return None

    path = _pick_random_song(subfolder) or _pick_random_song("")
    if not path:
        return None

    ext = os.path.splitext(path)[1].lower()
    if ext not in {".mp3", ".wav"}:
        return None

    try:
        with open(path, "rb") as f:
            blob = f.read()
        if not blob:
            return None

        mime = "audio/wav" if ext == ".wav" else "audio/mpeg"
        b64 = base64.b64encode(blob).decode()
        async with _tts_stream_lock:
            for ws in phone_ws:
                await safe_send_json(ws, {"type": "tts_start", "total": 1})
                await safe_send_json(ws, {"type": "audio_chunk", "audio_b64": b64, "mime_type": mime})
                await safe_send_json(ws, {"type": "audio_end"})

        return os.path.splitext(os.path.basename(path))[0]
    except Exception as e:
        log.warning(f"[ReminderMusic] Send failed: {e}")
        return None


# ─── Control Helpers ───────────────────────────────────────────────
def get_outlet():
    dev = tinytuya.OutletDevice(get("tuya_device_id"), get("tuya_ip"), get("tuya_local_key"))
    dev.set_version(float(get("tuya_version", 3.3)))
    return dev

def pc_ping():
    try: return subprocess.run(["ping", "-c", "1", "-W", "1", get("pc_tailscale_ip")], capture_output=True).returncode == 0
    except: return False

async def send_to_windows(cmd="", script=""):
    """Send command to Windows PC. Try Cloudflare first if available, fallback to direct Tailscale."""
    global _penta_kuru_cb_fails

    # ── Kiểm tra nhanh: không có phương thức nào được cấu hình → báo lỗi sớm ──
    _kuru_enabled = bool(get("enable_penta_kuru_integration"))
    _kuru_url     = str(get("penta_kuru_cloudflare_url", "")).strip()
    _ts_ip        = str(get("pc_tailscale_ip", "")).strip()
    
    log.info(f"[send_to_windows] Cloudflare={_kuru_enabled}, Tailscale={_ts_ip}")
    
    if not _kuru_enabled and not _ts_ip:
        log.warning("[send_to_windows] Chưa cấu hình kết nối PC (pc_tailscale_ip trống, Cloudflare tắt)")
        return {
            "ok": False,
            "error": "PC chưa được cấu hình. Mở ⚙ System → đặt pc_tailscale_ip (IP Tailscale/LAN của PC) và pc_auth_token.",
        }

    # ── Option 1: Try Cloudflare Tunnel (Kuru) if healthy ───────────────────
    if _kuru_enabled:
        kuru_url = _kuru_url
        kuru_token = str(get("penta_kuru_token", "")).strip()
        # Dùng cache ngay lập tức, không đợi health check thủ công
        kuru_ok = _penta_kuru_health.get("ok", False)
        log.info(f"[Cloudflare] CacheHealth={kuru_ok}, URL={kuru_url[:50] if kuru_url else 'N/A'}")

        if kuru_ok and kuru_url and kuru_token:
            try:
                loop = asyncio.get_event_loop()
                headers = {"Authorization": f"Bearer {kuru_token}"}
                resp_func = lambda: requests.post(
                    f"{kuru_url}/run",
                    json={"cmd": cmd, "script": script},
                    headers=headers,
                    timeout=5  # Giảm từ 10s xuống 5s để fallback nhanh hơn
                )
                resp = await loop.run_in_executor(None, resp_func)
                result = resp.json()
                if result.get("ok"):
                    log.info("✅ Command executed via Cloudflare → Kuru")
                    _penta_kuru_cb_fails = 0
                    return result
                else:
                    _penta_kuru_cb_fails += 1
                    log.warning(f"⚠️ Kuru failed ({result.get('error', 'unknown')}), trying direct. Fails: {_penta_kuru_cb_fails}")
            except Exception as e:
                _penta_kuru_cb_fails += 1
                log.warning(f"⚠️ Kuru unreachable ({_penta_kuru_cb_fails} fails): {e}")
    
    # ── Fallback: Direct Tailscale/LAN connection ──────────────────────────
    if not _ts_ip:
        return {"ok": False, "error": "pc_tailscale_ip chưa được đặt trong cấu hình."}
    url = f"http://{_ts_ip}:{get('pc_api_port', 7777)}/run"
    _pc_token = str(get('pc_auth_token', '')).strip()
    headers = {"Authorization": f"Bearer {_pc_token}"} if _pc_token else {}
    log.info(f"[Tailscale] Trying {url} (auth={'yes' if _pc_token else 'no'})")
    
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: requests.post(url, json={"cmd": cmd, "script": script}, headers=headers, timeout=12))
        result = resp.json()
        log.info(f"[Tailscale] ✅ Success: {result}")
        return result
    except Exception as e:
        log.error(f"[Tailscale] ❌ Failed: {e}")
        return {"ok": False, "error": f"Không kết nối được tới {_ts_ip}: {e}"}

def _looks_like_ps_script(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if "\n" in t:
        return True
    markers = [
        "powershell", "set-", "new-item", "remove-item", "start-process",
        "foreach", "if(", "if (", "$env:", "|", ";"
    ]
    low = t.lower()
    return any(m in low for m in markers)

_WIN_SEARCH_URLS: Dict[str, str] = {
    "youtube":   "https://www.youtube.com/results?search_query={}",
    "yt":        "https://www.youtube.com/results?search_query={}",
    "google":    "https://www.google.com/search?q={}",
    "gg":        "https://www.google.com/search?q={}",
    "bing":      "https://www.bing.com/search?q={}",
    "wikipedia": "https://vi.wikipedia.org/wiki/Special:Search?search={}",
    "wiki":      "https://vi.wikipedia.org/wiki/Special:Search?search={}",
    "github":    "https://github.com/search?q={}",
}

def _ps_single_quote(value: str) -> str:
    return (value or "").replace("'", "''")

def _map_ollama_to_windows_payload(res: Dict[str, Any]) -> Dict[str, str]:
    """
    Chuẩn hoá kết quả interpret() thành payload Windows cho PentakuruV4 /run.

    Web actions (open/search/play/run) → Start-Process PowerShell để mở browser/app.
    PS actions (ps_script/setup/install/…) → script hoặc cmd thô.
    """
    import urllib.parse

    action = str(res.get("action", "")).strip().lower()
    target = str(res.get("target", "")).strip()
    query  = str(res.get("query", "")).strip()

    # ── 1. PS/automation actions ──────────────────────────────────────────────
    script_actions = {"ps_script", "script", "install", "setup", "automation", "configure"}
    if action in script_actions:
        script_payload = query or target
        if _looks_like_ps_script(script_payload):
            return {"cmd": "", "script": script_payload}
        return {"cmd": script_payload, "script": ""}
    if query and _looks_like_ps_script(query):
        return {"cmd": "", "script": query}

    # ── 2. open action → Start-Process URL/app ────────────────────────────────
    if action == "open":
        if target:
            if target.startswith("http") or "." in target:
                url = target if target.startswith("http") else f"https://{target}"
                esc = url.replace('"', '`"')
                return {"cmd": f'Start-Process "{esc}"', "script": ""}
            # Tên app (Notepad, Chrome, …)
            esc = target.replace('"', '`"')
            return {"cmd": f'Start-Process "{esc}"', "script": ""}

    # ── 3. search action → Start-Process search URL ───────────────────────────
    if action == "search":
        # Nếu tìm nhạc trên YouTube → chuyển sang phát nhạc chill nội bộ
        _MUSIC_KW = {
            "nhac", "nhạc", "music", "song", "bai hat", "bài hát",
            "lofi", "chill", "relax", "buon", "buồn", "sad", "tam trang", "tâm trạng",
            "nghe nhac", "nghe nhạc", "playlist",
        }
        _platform = (target or "").lower()
        _query_low = (query or "").lower()
        _is_yt = _platform in {"youtube", "yt"}
        _is_music_query = any(kw in _query_low or kw in _platform for kw in _MUSIC_KW)
        if _is_yt and _is_music_query:
            return {"cmd": "", "script": "", "_local_play": "chill_music"}
        platform = _platform if _platform else "google"
        tmpl = _WIN_SEARCH_URLS.get(platform, _WIN_SEARCH_URLS["google"])
        url = tmpl.format(urllib.parse.quote_plus(query or target))
        esc = url.replace('"', '`"')
        return {"cmd": f'Start-Process "{esc}"', "script": ""}

    # ── 4. play action → phát nhạc nội bộ từ music/chill_music/ ──────────────
    if action == "play":
        # Luôn phát nhạc từ thư mục music/chill_music/ thay vì mở YouTube URL
        return {"cmd": "", "script": "", "_local_play": "chill_music"}

    # ── 5. run action → Start-Process app/exe ────────────────────────────────
    if action == "run":
        app = target or query
        if app:
            esc = app.replace('"', '`"')
            return {"cmd": f'Start-Process "{esc}"', "script": ""}

    # ── 5.2. close_window action → đóng đúng cửa sổ có tiêu đề khớp chính xác ──
    if action in {"close_window", "close"}:
        title = query or target
        if title and title.lower() != "window":
            exact_title = _ps_single_quote(title.strip())
            script = f"""
$targetTitle = '{exact_title}'
$matched = Get-Process | Where-Object {{
    $_.MainWindowHandle -ne 0 -and
    $_.MainWindowTitle -and
    $_.MainWindowTitle.Trim().Equals($targetTitle, [System.StringComparison]::InvariantCultureIgnoreCase)
}}

if (-not $matched) {{
    Write-Output "WINDOW_NOT_FOUND:$targetTitle"
    exit 4
}}

$closed = @()
foreach ($proc in $matched) {{
    try {{
        $null = $proc.CloseMainWindow()
        Start-Sleep -Milliseconds 1200
        if (-not $proc.HasExited) {{
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        }}
        $closed += $proc.MainWindowTitle
    }} catch {{
        Write-Output "WINDOW_CLOSE_ERROR:$($proc.MainWindowTitle):$($_.Exception.Message)"
        exit 5
    }}
}}

Write-Output ("WINDOW_CLOSED:" + ($closed -join " | "))
""".strip()
            return {"cmd": "", "script": script}

    # ── 5.5. penta action → mở sector bằng URL hoặc exe ─────────────────────
    if action == "penta":
        sector_url = str(res.get("sector_url", "")).strip()
        sector_exe = str(res.get("sector_exe", "")).strip()
        if sector_url:
            esc = sector_url.replace('"', '`"')
            return {"cmd": f'Start-Process "{esc}"', "script": ""}
        elif sector_exe:
            esc = sector_exe.replace('"', '`"')
            return {"cmd": f'Start-Process "{esc}"', "script": ""}
        return {"cmd": "", "script": ""}

    # ── 6. Fallback cho target/query chưa phân loại ───────────────────────────
    if target:
        if query and _looks_like_ps_script(query):
            return {"cmd": target, "script": query}
        return {"cmd": target, "script": ""}

    if query:
        if _looks_like_ps_script(query):
            return {"cmd": "", "script": query}
        return {"cmd": query, "script": ""}

    return {"cmd": "", "script": ""}

# ─── FastAPI Lifecycle ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _proactive_task, _gmail_daemon
    global _ollama_keepalive_task
    import atexit
    log.info("🚀 Warm-up Unified Server...")
    init_ai(); init_voicevox(); init_valtec()
    if check_ollama():
        # Pre-warm: đẩy model vào RAM ngay khi khởi động (chạy trong thread pool)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _prewarm_ollama)
    
    if get("mlx_prewarm_on_startup"):
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _prewarm_mlx)
    _load_penta_state()  # Khôi phục wiki mode + session language từ lần trước
    
    # --- Gmail Notification Daemon ---
    if _GMAIL_DAEMON_AVAILABLE:
        try:
            _server_loop = asyncio.get_running_loop()
            def _gmail_config_fn():
                return get_full_config()
            def _gmail_broadcast_fn(text: str):
                # Daemon chạy ở thread nền, cần gửi coroutine về event loop chính.
                fut = asyncio.run_coroutine_threadsafe(
                    broadcast_proactive(text, _ai_instance or init_ai()),
                    _server_loop,
                )

                def _on_done(_f):
                    try:
                        _f.result()
                    except Exception as _e:
                        log.error(f"[GmailDaemon->Broadcast] {_e}")

                fut.add_done_callback(_on_done)
            _gmail_daemon = _init_gmail_daemon(_gmail_config_fn, _gmail_broadcast_fn)
            _gmail_daemon.start()
            log.info("[Server Startup] ✅ Gmail Notification Daemon started")
        except Exception as e:
            log.error(f"[Server Startup] ❌ Gmail daemon init failed: {e}")
            _gmail_daemon = None
    
    # Chạy vòng proactive trong đúng event loop của ASGI server.
    _proactive_task = asyncio.create_task(proactive_background_task())
    # Keep-alive task: giữ Ollama model trong RAM, tránh cold-start
    _ollama_keepalive_task = asyncio.create_task(keepalive_ollama_task())
    # Kuru health monitor task: chạy ngầm để không gây trễ khi gửi lệnh
    _kuru_health_task = asyncio.create_task(kuru_health_monitor_task())
    def _save():
        if _ai_instance and hasattr(_ai_instance, 'emotion') and _ai_instance.emotion:
            _ai_instance.emotion.flush(); log.info("💾 Saved Hormone state")
    atexit.register(_save)
    yield
    
    # --- Shutdown Gmail Daemon ---
    if _gmail_daemon:
        _gmail_daemon.stop()
        log.info("[Server Shutdown] Gmail Notification Daemon stopped")
    
    if _proactive_task:
        _proactive_task.cancel()
        try:
            await _proactive_task
        except asyncio.CancelledError:
            pass
        _proactive_task = None
    if _ollama_keepalive_task:
        _ollama_keepalive_task.cancel()
        try:
            await _ollama_keepalive_task
        except asyncio.CancelledError:
            pass
    if _kuru_health_task:
        _kuru_health_task.cancel()
        try:
            await _kuru_health_task
        except asyncio.CancelledError:
            pass
    _save(); log.info("👋 Shutdown complete")

app = FastAPI(title="PentaAI Unified Server", version="5.6", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Pydantic Models ───────────────────────────────────────────────
class ChatRequest(BaseModel):
    text: str; tts: bool = True; speaker: str = "NF"; speed: float = 1.0
class OllamaCommandRequest(BaseModel):
    text: str; available_commands: List[str] = []

# ─── Endpoints ─────────────────────────────────────────────────────
@app.get("/")
async def root():
    return HTMLResponse(content="<h1>🎤 PentaAI Unified Server v5.6 Ready</h1>")

@app.get("/api/health")
async def health():
    ai = init_ai(); ok_mods = check_modules(); em = hl = None
    if ai and hasattr(ai, "emotion") and ai.emotion:
        em = ai.emotion.hormone.get_emotional_state()
        hl = {k: round(v, 3) for k, v in ai.emotion.hormone.get().items()}
    return {
        "status": "ok", "ai_ready": ai is not None,
        "tts_vi": get_valtec() is not None, "tts_jp": get_voicevox() is not None,
        "modules_ok": sum(1 for v in ok_mods.values() if v["status"]=="ok"),
        "emotional_state": em, "hormone_levels": hl
    }

@app.get("/api/hormone_status")
async def hormone_status():
    ai = init_ai()
    try: return {"status": "ok", "data": ai.get_hormone_status() if hasattr(ai, 'get_hormone_status') else {}}
    except: return {"status": "error"}

@app.post("/api/hormone_reset")
async def hormone_reset(token: str = Depends(verify_token)):
    ai = init_ai()
    if ai and ai.emotion:
        from hormone.hormone_core import PERSONALITY_BASELINES
        ai.emotion.hormone.levels = PERSONALITY_BASELINES.get('curious', {}).copy()
        ai.emotion.hormone.save()
        return {"status": "ok", "new_state": ai.emotion.hormone.get_emotional_state()}
    return {"status": "error"}

@app.get("/api/config")
async def get_config_api(token: str = Depends(verify_token)):
    c = load_config(); safe = c.copy()
    for k in ["auth_token", "tuya_local_key", "pc_auth_token"]:
        if safe.get(k): safe[k] = safe[k][:3] + "****"
    return {"status": "ok", "config": safe}

@app.post("/api/config")
async def set_config_api(req: Request, token: str = Depends(verify_token)):
    d = await req.json(); c = load_config()
    for k, v in d.items():
        if k in DEFAULT_CONFIG:
            c[k] = v
    save_config(c)
    _reload_runtime_config()
    return {"status": "ok"}

@app.get("/api/config_runtime")
async def get_config_runtime(token: str = Depends(verify_token)):
    return {"status": "ok", "config": load_config()}

@app.post("/api/config_runtime")
async def set_config_runtime(req: Request, token: str = Depends(verify_token)):
    d = await req.json()
    incoming = d.get("config") if isinstance(d, dict) and "config" in d else d
    if not isinstance(incoming, dict):
        return {"status": "error", "message": "Payload phải là object config"}

    c = load_config()
    for k, v in incoming.items():
        if k in DEFAULT_CONFIG:
            c[k] = v
    save_config(c)
    _reload_runtime_config()
    return {"status": "ok", "config": c}

@app.get("/api/config_cloud")
async def get_cloud(token: str = Depends(verify_token)):
    c = load_config()
    return {"status": "ok", "url": c.get("ollama_cloud_url",""), "model": c.get("ollama_cloud_model", ""), "local_model": c.get("ollama_model", "")}

@app.post("/api/config_cloud")
async def set_cloud(req: Request, token: str = Depends(verify_token)):
    d = await req.json(); c = load_config()
    for k in ["url", "key", "model"]: 
        if k in d: c[f"ollama_cloud_{k}"] = d[k]
    if "local_model" in d:
        c["ollama_model"] = d["local_model"]
    save_config(c)
    _reload_runtime_config()
    return {"status": "ok"}

@app.get("/api/status")
async def system_status(token: str = Depends(verify_token)):
    try:
        d = get_outlet(); st = d.status().get("dps",{}).get("1")
        power = "on" if st is True else ("off" if st is False else "unknown")
    except: power = "error"
    return {"outlet_power": power, "pc_online": pc_ping(), "pc_ip": get("pc_tailscale_ip")}

@app.post("/api/turn-on-pc")
async def turn_on_pc(token: str = Depends(verify_token)):
    try: get_outlet().turn_on(); return {"status": "ok"}
    except: return {"status": "error"}

@app.post("/api/turn-off-pc")
async def turn_off_pc(token: str = Depends(verify_token)):
    try: get_outlet().turn_off(); return {"status": "ok"}
    except: return {"status": "error"}

@app.get("/api/modules")
async def modules_api(token: str = Depends(verify_token)):
    return {"status": "ok", "modules": check_modules()}

@app.get("/api/schedule")
async def get_sch(token: str = Depends(verify_token)):
    return _load_week_schedule()

@app.post("/api/schedule")
async def set_sch(d: dict, token: str = Depends(verify_token)):
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "schedule.json"), "w", encoding="utf-8") as f:
        json.dump(normalize_schedule_payload(d), f, indent=2, ensure_ascii=False)
    return {"status": "ok"}


@app.get("/api/reminders/status")
async def reminders_status(token: str = Depends(verify_token)):
    ai = init_ai()
    ta = getattr(ai, "time", None)
    if not ta:
        return {"status": "error", "message": "TimeAwareness unavailable"}

    now = datetime.now()
    reminders = []
    due_count = 0
    for idx, r in enumerate(getattr(ta, "_reminders", []) or []):
        due = bool(ta._is_due(r, now))
        if due:
            due_count += 1
        reminders.append({
            "id": idx,
            "message": r.get("message", ""),
            "time": r.get("time"),
            "weekday": r.get("weekday"),
            "repeat": bool(r.get("repeat", False)),
            "lang": r.get("lang", "vi"),
            "created": r.get("created"),
            "is_due_now": due,
            "next_due": _reminder_next_due_iso(r, now),
        })

    reminders.sort(key=lambda x: x.get("next_due") or "")
    next_due = reminders[0].get("next_due") if reminders else None
    return {
        "status": "ok",
        "now": now.isoformat(),
        "total": len(reminders),
        "due_now": due_count,
        "next_due": next_due,
        "reminders": reminders,
    }

@app.post("/api/teach")
async def teach_api(req: Request, token: str = Depends(verify_token)):
    d = await req.json(); ai = init_ai()
    try:
        resp = ai.teach(d.get("text","")) if hasattr(ai, 'teach') else "Teach not supported"
        return {"status": "ok", "response": resp}
    except Exception as e: return {"status": "error", "message": str(e)}

# ─── Gmail Notification API ─────────────────────────────────────────
@app.get("/api/gmail_notify_whitelist")
async def gmail_notify_whitelist_get(token: str = Depends(verify_token)):
    """Lấy danh sách whitelist Gmail notification."""
    cfg = get_full_config()
    whitelist = _load_gmail_notify_whitelist(cfg)
    return {"status": "ok", "whitelist": whitelist, "file": _resolve_gmail_whitelist_file(cfg)}

@app.post("/api/gmail_notify_whitelist")
async def gmail_notify_whitelist_post(req: Request, token: str = Depends(verify_token)):
    """
    Thêm hoặc xóa entry trong whitelist.
    JSON: {"action": "add" | "remove", "email": "...", "nickname": "..."}
    """
    try:
        d = await req.json()
        action = d.get("action", "").lower()
        email = d.get("email", "").strip().lower()
        nickname = d.get("nickname", "").strip()

        cfg = get_full_config()
        whitelist = _load_gmail_notify_whitelist(cfg)

        # Bulk set mode from CLI
        if isinstance(d.get("whitelist"), list):
            path = _save_gmail_notify_whitelist(cfg, d.get("whitelist", []))
            return {
                "status": "ok",
                "message": "Whitelist replaced",
                "whitelist": _load_gmail_notify_whitelist(cfg),
                "file": path,
            }

        if not email:
            return {"status": "error", "message": "Email required"}
        
        if action == "add":
            # Check duplicate
            if any(e["email"].lower() == email for e in whitelist if isinstance(e, dict)):
                return {"status": "error", "message": "Email already in whitelist"}
            whitelist.append({"email": email, "nickname": nickname or email.split("@")[0]})
        elif action == "remove":
            whitelist = [e for e in whitelist if isinstance(e, dict) and e.get("email", "").lower() != email]
        else:
            return {"status": "error", "message": "Invalid action"}

        path = _save_gmail_notify_whitelist(cfg, whitelist)
        return {
            "status": "ok",
            "message": f"Action {action} completed",
            "whitelist": _load_gmail_notify_whitelist(cfg),
            "file": path,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/gmail_notify_queue")
async def gmail_notify_queue_get(token: str = Depends(verify_token)):
    """Lấy queue email chờ xử lý."""
    if not _gmail_daemon:
        return {"status": "error", "message": "Gmail daemon not available"}
    
    queue = _gmail_daemon.get_queue()
    return {"status": "ok", "queue": queue, "count": len(queue)}

@app.post("/api/gmail_notify_response")
async def gmail_notify_response_post(req: Request, token: str = Depends(verify_token)):
    """
    User trả lời email.
    JSON: {"uid": "...", "response": "yes" | "no"}
    """
    if not _gmail_daemon:
        return {"status": "error", "message": "Gmail daemon not available"}
    
    try:
        d = await req.json()
        uid = d.get("uid", "")
        response = d.get("response", "").lower()
        
        if response not in ("yes", "no", "1", "0", "true", "false", "có", "không"):
            return {"status": "error", "message": "Invalid response"}
        
        ok = _gmail_daemon.set_user_response(uid, response)
        return {"status": "ok" if ok else "error", "message": "Response recorded" if ok else "UID not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/gmail_notify_clear")
async def gmail_notify_clear_post(token: str = Depends(verify_token)):
    """Xóa toàn bộ queue Gmail notification."""
    if not _gmail_daemon:
        return {"status": "error", "message": "Gmail daemon not available"}
    n = _gmail_daemon.clear_queue()
    return {"status": "ok", "cleared": n}

@app.post("/api/gmail_notify_enable")
async def gmail_notify_enable_post(req: Request, token: str = Depends(verify_token)):
    """Bật/tắt Gmail notification."""
    try:
        d = await req.json()
        enabled = d.get("enabled", True)
        
        cfg = get_full_config()
        cfg["gmail_notification_enabled"] = bool(enabled)
        save_config(cfg)
        
        status = "enabled" if enabled else "disabled"
        return {"status": "ok", "message": f"Gmail notification {status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ollama_command")
async def ollama_command_api(req: OllamaCommandRequest, execute: bool = False, token: str = Depends(verify_token)):
    from API_local.ollama_command import get_default_interpreter
    interp = get_default_interpreter()
    res = interp.interpret(req.text, req.available_commands)
    win_res = None
    if execute:
        payload = _map_ollama_to_windows_payload(res)
        if payload["cmd"] or payload["script"]:
            win_res = await send_to_windows(cmd=payload["cmd"], script=payload["script"])
        else:
            win_res = {"ok": False, "error": "No executable cmd/script from parsed result"}
    return {**res, "windows_result": win_res}

@app.post("/api/execute_pc_command")
async def execute_pc_command(req: OllamaCommandRequest, token: str = Depends(verify_token)):
    from API_local.ollama_command import get_default_interpreter
    interp = get_default_interpreter()
    res = interp.interpret(req.text, req.available_commands)
    payload = _map_ollama_to_windows_payload(res)
    if not (payload["cmd"] or payload["script"]):
        return {"ok": False, "error": "No executable cmd/script parsed", "parsed": res}
    return await send_to_windows(cmd=payload["cmd"], script=payload["script"])

@app.get("/api/pentakuru_sectors_debug")
async def pentakuru_sectors_debug(q: str = "", token: str = Depends(verify_token)):
    executor = get_action_executor()
    return {"status": "ok", **executor.get_sectors_debug(q)}


@app.post("/api/kuru/sectors")
async def kuru_push_sectors(request: Request, token: str = Depends(verify_token)):
    """
    PentaKuRu gửi toàn bộ sectors lên AI server sau mỗi lần lưu.
    Body: {"sectors": {"0": {...}, "1": {...}, ...}}
    AI server lưu vào bộ nhớ — ActionExecutor dùng trực tiếp, không cần file.
    """
    from core.action_executor import inject_sectors
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON không hợp lệ")
    data = body.get("sectors", body)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="sectors phải là object {index: {...}}")
    count = inject_sectors(data)
    log.info(f"[KuruSectors] Đã nhận {count} sectors từ PentaKuRu")
    return {"ok": True, "received": count}


@app.get("/api/kuru/sectors")
async def kuru_get_sectors(token: str = Depends(verify_token)):
    """Trả về sectors hiện tại đang được cache trong bộ nhớ AI server."""
    from core.action_executor import get_injected_sectors
    data = get_injected_sectors()
    return {"ok": True, "count": len(data), "sectors": data}


# ══════════════════════════════════════════════════════════════════════════════
#  PENTAMI ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/pentami/status")
async def pentami_status(token: str = Depends(verify_token)):
    """Trạng thái chế độ PentaMi."""
    pm = get_pentami_chat() if _PENTAMI_AVAILABLE else None
    return {
        "available": _PENTAMI_AVAILABLE,
        "mode": _pentami_mode,
        "thinking_mode": _pentami_thinking_mode,
        "context_turns": pm.context_length() if pm else 0,
    }


@app.post("/api/pentami/toggle")
async def pentami_toggle(token: str = Depends(verify_token)):
    """Bật / tắt chế độ PentaMi."""
    global _pentami_mode, _pentami_thinking_mode
    if not _PENTAMI_AVAILABLE:
        return {"ok": False, "error": "pentami_chat module không khả dụng"}
    _pentami_mode = not _pentami_mode
    pm = get_pentami_chat()
    if _pentami_mode:
        _pentami_thinking_mode = False
        if hasattr(pm, "set_bonsai_thinking_mode"):
            pm.set_bonsai_thinking_mode(False)
        pm._bonsai.set_keepalive(False)
        pm._bonsai.set_sleep_notify(None)
    else:
        _pentami_thinking_mode = False
        if hasattr(pm, "set_bonsai_thinking_mode"):
            pm.set_bonsai_thinking_mode(False)
        pm._bonsai.set_keepalive(False)
        pm._bonsai.set_sleep_notify(None)

    status = "bật" if _pentami_mode else "tắt"
    return {"ok": True, "mode": _pentami_mode, "message": f"Chế độ PentaMi đã {status}!"}


@app.post("/api/pentami/on")
async def pentami_on(token: str = Depends(verify_token)):
    """Bật chế độ PentaMi."""
    global _pentami_mode, _pentami_thinking_mode
    if not _PENTAMI_AVAILABLE:
        return {"ok": False, "error": "pentami_chat module không khả dụng"}
    _pentami_mode = True
    _pentami_thinking_mode = False
    pm = get_pentami_chat()
    if hasattr(pm, "set_bonsai_thinking_mode"):
        pm.set_bonsai_thinking_mode(False)
    pm._bonsai.set_keepalive(False)
    pm._bonsai.set_sleep_notify(None)

    return {"ok": True, "mode": True, "message": "Chế độ PentaMi đã bật!"}


@app.post("/api/pentami/off")
async def pentami_off(token: str = Depends(verify_token)):
    """Tắt chế độ PentaMi và tự động xoá context hội thoại (giữ kiến thức đã học)."""
    global _pentami_mode, _pentami_thinking_mode
    _pentami_mode = False
    _pentami_thinking_mode = False
    if _PENTAMI_AVAILABLE:
        pm = get_pentami_chat()
        if hasattr(pm, "set_bonsai_thinking_mode"):
            pm.set_bonsai_thinking_mode(False)
        pm._bonsai.set_keepalive(False)
        pm._bonsai.set_sleep_notify(None)
        pm.clear_context()   # Xoá lịch sử chat, knowledge.json không bị ảnh hưởng
    return {"ok": True, "mode": False, "message": "Chế độ PentaMi đã tắt và lịch sử hội thoại đã được xoá. Kiến thức đã học vẫn được giữ lại."}


@app.post("/api/pentami/thinking_on")
async def pentami_thinking_on(token: str = Depends(verify_token)):
    """Bật PentamiT: auto dùng Bonsai cho câu phức tạp/sâu."""
    global _pentami_mode, _pentami_thinking_mode
    if not _PENTAMI_AVAILABLE:
        return {"ok": False, "error": "pentami_chat module không khả dụng"}
    _pentami_mode = True
    _pentami_thinking_mode = True
    pm = get_pentami_chat()
    if hasattr(pm, "set_bonsai_thinking_mode"):
        pm.set_bonsai_thinking_mode(True)
    pm._bonsai.set_keepalive(True)
    try:
        _loop = asyncio.get_running_loop()
        def _bonsai_sleep_notify(msg: str):
            asyncio.run_coroutine_threadsafe(
                broadcast_proactive(msg, init_ai()),
                _loop,
            )
        pm._bonsai.set_sleep_notify(_bonsai_sleep_notify)
    except Exception:
        pm._bonsai.set_sleep_notify(None)

    async def _prewarm():
        loop = asyncio.get_running_loop()
        ready = await loop.run_in_executor(None, pm._bonsai._ensure_awake)
        if not ready:
            log.warning("[PentaMiT] Pre-warm Bonsai thất bại")
    asyncio.create_task(_prewarm())
    return {"ok": True, "mode": True, "thinking_mode": True, "message": "Đã bật PentamiT (Thinking Bonsai)."}


@app.post("/api/pentami/thinking_off")
async def pentami_thinking_off(token: str = Depends(verify_token)):
    """Tắt PentamiT nhưng vẫn giữ PentaMi."""
    global _pentami_thinking_mode
    if not _PENTAMI_AVAILABLE:
        return {"ok": False, "error": "pentami_chat module không khả dụng"}
    _pentami_thinking_mode = False
    pm = get_pentami_chat()
    if hasattr(pm, "set_bonsai_thinking_mode"):
        pm.set_bonsai_thinking_mode(False)
    pm._bonsai.set_keepalive(False)
    pm._bonsai.set_sleep_notify(None)
    return {"ok": True, "mode": _pentami_mode, "thinking_mode": False, "message": "Đã tắt PentamiT."}


@app.post("/api/pentami/clear")
async def pentami_clear(token: str = Depends(verify_token)):
    """Xoá ngữ cảnh hội thoại PentaMi."""
    if not _PENTAMI_AVAILABLE:
        return {"ok": False, "error": "pentami_chat module không khả dụng"}
    pm = get_pentami_chat()
    pm.clear_context()
    return {"ok": True, "message": "Ngữ cảnh đã được xoá."}


# ══════════════════════════════════════════════════════════════════════════════
#  PENTAWIKI ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/wiki/status")
async def wiki_status(token: str = Depends(verify_token)):
    """Trả về trạng thái PentaWiki và ngôn ngữ phiên làm việc hiện tại."""
    return {
        "available": _WIKI_AVAILABLE,
        "wiki_mode": _penta_wiki_mode,
        "session_lang": _session_lang,
    }


@app.post("/api/wiki/on")
async def wiki_on(token: str = Depends(verify_token)):
    """Bật PentaWiki mode."""
    global _penta_wiki_mode
    if not _WIKI_AVAILABLE:
        return {"ok": False, "error": "wiki_engine module không khả dụng"}
    _penta_wiki_mode = True
    _save_penta_state()
    return {"ok": True, "wiki_mode": True, "session_lang": _session_lang}


@app.post("/api/wiki/off")
async def wiki_off(token: str = Depends(verify_token)):
    """Tắt PentaWiki mode."""
    global _penta_wiki_mode
    _penta_wiki_mode = False
    _save_penta_state()
    return {"ok": True, "wiki_mode": False}


@app.post("/api/wiki/lang")
async def wiki_set_lang(req: Request, token: str = Depends(verify_token)):
    """Đặt ngôn ngữ phiên: vi | en | ja."""
    global _session_lang
    data = await req.json()
    lang = str(data.get("lang", "vi")).strip().lower()
    if lang not in {"vi", "en", "ja"}:
        return {"ok": False, "error": "lang phải là vi, en, hoặc ja"}
    _session_lang = lang
    _save_penta_state()
    return {"ok": True, "session_lang": _session_lang}


@app.post("/api/wiki/search")
async def wiki_search_api(req: Request, token: str = Depends(verify_token)):
    """Tra cứu Wikipedia trực tiếp qua API (không cần bật wiki mode)."""
    data = await req.json()
    query = str(data.get("query", "")).strip()
    lang  = str(data.get("lang", _session_lang)).strip().lower()
    if not query:
        return {"ok": False, "error": "query rỗng"}
    if lang not in {"vi", "en", "ja"}:
        lang = _session_lang
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _wiki_fetch(query, lang))
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN ENDPOINTS  — dùng bởi penta_ctl.py
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/status")
async def admin_status(token: str = Depends(verify_token)):
    """Full live stats: WS clients, circuit breakers, hormone, last interaction."""
    from API_local.ollama_command import get_default_interpreter
    interp = get_default_interpreter()
    ai = init_ai()

    # Hormone snapshot
    hormones = {}
    emotion_state = "unknown"
    try:
        hormones = ai.emotion.hormone.get() if hasattr(ai, "emotion") else {}
        emotion_state = ai.emotion.hormone.get_emotional_state() if hasattr(ai, "emotion") else "unknown"
    except Exception:
        pass

    # WS clients
    ws_clients = [
        {"addr": m.get("addr", "?"), "is_phone": m.get("is_phone", False)}
        for m in _active_ws_meta.values()
    ]

    # Circuit breaker states
    kuru_cb_open = time.time() < _penta_kuru_cb_open_until
    ollama_cb_open = time.monotonic() < interp._cb_open_until

    now = time.time()
    idle_sec = int(now - _last_user_interaction_ts)
    work_sec = int(now - _work_session_start_ts) if _work_session_start_ts else 0

    return {
        "ok": True,
        "timestamp": int(now),
        "server_version": "5.6",
        "ws_clients": ws_clients,
        "ws_client_count": len(ws_clients),
        "has_phone": any(c["is_phone"] for c in ws_clients),
        "idle_sec": idle_sec,
        "work_session_sec": work_sec,
        "emotion_state": emotion_state,
        "hormones": hormones,
        "ollama": {
            "model": interp.model,
            "cloud_model": interp.cloud_model,
            "policy": interp.command_cloud_policy,
            "local_available": interp._available,
            "cb_fails": interp._cb_fails,
            "cb_open": ollama_cb_open,
            "cb_open_until_sec": max(0, int(interp._cb_open_until - time.monotonic())),
        },
        "penta_kuru": {
            "enabled": bool(get("enable_penta_kuru_integration")),
            "cloudflare_url": get("penta_kuru_cloudflare_url", ""),
            "health": _penta_kuru_health,
            "cb_fails": _penta_kuru_cb_fails,
            "cb_open": kuru_cb_open,
            "cb_open_until_sec": max(0, int(_penta_kuru_cb_open_until - now)),
            "recent_cmd_count": len(_recent_successful_commands),
        },
        "config_summary": {
            "cloud_policy": get("ollama_command_cloud_policy", "complex_only"),
            "enable_cloud_fallback": get("ollama_enable_cloud_fallback", True),
            "chat_use_llm_fallback": get("chat_use_llm_fallback", False),
            "enable_penta_kuru": get("enable_penta_kuru_integration", False),
        },
    }


@app.post("/admin/connect")
async def admin_connect(req: Request, token: str = Depends(verify_token)):
    """
    Đổi connection mode runtime.
    Body: {"mode": "cloudflare"|"tailscale"|"lan"|"all"|"test"}
    "test" chỉ ping tất cả và trả kết quả, không thay đổi config.
    """
    data = await req.json()
    mode = str(data.get("mode", "")).strip().lower()
    results: Dict[str, Any] = {}

    # Ping Cloudflare Kuru
    kuru_url = get("penta_kuru_cloudflare_url", "").strip()
    if kuru_url:
        try:
            r = requests.get(f"{kuru_url}/health", timeout=3)
            results["cloudflare"] = {"ok": r.status_code == 200, "latency_ms": int(r.elapsed.total_seconds() * 1000)}
        except Exception as e:
            results["cloudflare"] = {"ok": False, "error": str(e)}
    else:
        results["cloudflare"] = {"ok": False, "error": "URL chưa cấu hình"}

    # Ping Tailscale
    ts_ip = get("pc_tailscale_ip", "")
    ts_port = get("pc_api_port", 7777)
    if ts_ip:
        try:
            r = requests.get(f"http://{ts_ip}:{ts_port}/ping", timeout=3)
            results["tailscale"] = {"ok": r.status_code == 200, "latency_ms": int(r.elapsed.total_seconds() * 1000)}
        except Exception as e:
            results["tailscale"] = {"ok": False, "error": str(e)}
    else:
        results["tailscale"] = {"ok": False, "error": "IP chưa cấu hình"}

    if mode == "test":
        return {"ok": True, "mode": "test", "results": results}

    # Apply mode
    applied: Dict[str, bool] = {}
    if mode == "cloudflare":
        _runtime_overrides["enable_penta_kuru_integration"] = True
        applied = {"enable_penta_kuru_integration": True}
    elif mode == "tailscale":
        _runtime_overrides["enable_penta_kuru_integration"] = False
        applied = {"enable_penta_kuru_integration": False}
    elif mode == "lan":
        ts_ip_lan = get("pc_tailscale_ip", "")
        _runtime_overrides["enable_penta_kuru_integration"] = False
        applied = {"enable_penta_kuru_integration": False, "note": "đang dùng LAN direct"}
    elif mode == "all":
        _runtime_overrides["enable_penta_kuru_integration"] = True
        applied = {"enable_penta_kuru_integration": True, "note": "Cloudflare ưu tiên, fallback Tailscale"}
    else:
        return {"ok": False, "error": f"mode không hợp lệ: {mode!r}. Dùng: cloudflare|tailscale|lan|all|test"}

    return {"ok": True, "mode": mode, "applied": applied, "ping_results": results}


@app.post("/admin/test_cmd")
async def admin_test_cmd(req: Request, token: str = Depends(verify_token)):
    """
    Test pipeline lệnh verbose — không thực thi thực sự.
    Body: {"text": "mở youtube", "execute": false}
    Trả về: tier đã dùng, latency, JSON parse result, payload sẽ gửi.
    """
    data = await req.json()
    text = str(data.get("text", "")).strip()
    execute = bool(data.get("execute", False))

    if not text:
        return {"ok": False, "error": "Thiếu 'text'"}

    from API_local.ollama_command import get_default_interpreter, OllamaCommandInterpreter
    interp = get_default_interpreter()

    t0 = time.perf_counter()
    steps = []

    # Step 1: Rule-based
    rule_result = OllamaCommandInterpreter._try_rule_based_parse(text)
    t1 = time.perf_counter()
    steps.append({
        "tier": 1,
        "name": "Rule-based",
        "latency_ms": round((t1 - t0) * 1000, 2),
        "hit": rule_result is not None,
        "result": rule_result,
    })

    final_result = rule_result
    used_tier = 1

    if not rule_result:
        # Step 2: Local Ollama
        t2 = time.perf_counter()
        local_available = interp._check_local()
        if local_available:
            local_result = interp.interpret(text)
            t3 = time.perf_counter()
            used_tier = 2 if local_result.get("source") == "local" else 3
            steps.append({
                "tier": used_tier,
                "name": "Local Ollama" if used_tier == 2 else "Cloud",
                "latency_ms": round((t3 - t2) * 1000, 2),
                "hit": not local_result.get("error"),
                "result": local_result,
            })
            final_result = local_result
        else:
            steps.append({
                "tier": 2, "name": "Local Ollama",
                "latency_ms": 0, "hit": False,
                "result": {"error": "Ollama offline"},
            })

    # Step 3: Map to Windows payload
    payload = {"cmd": "", "script": ""}
    if final_result and not final_result.get("error"):
        payload = _map_ollama_to_windows_payload(final_result)

    total_ms = round((time.perf_counter() - t0) * 1000, 2)

    win_result = None
    if execute and (payload["cmd"] or payload["script"]):
        win_result = await send_to_windows(cmd=payload["cmd"], script=payload["script"])

    return {
        "ok": True,
        "input": text,
        "tier_used": used_tier,
        "total_latency_ms": total_ms,
        "steps": steps,
        "final_result": final_result,
        "windows_payload": payload,
        "windows_result": win_result,
        "executed": execute,
    }


@app.post("/admin/reload_config")
async def admin_reload_config(req: Request, token: str = Depends(verify_token)):
    """
    Live reload config.json mà không cần restart server.
    Có thể kèm body {"patch": {...}} để patch thêm keys.
    """
    global _runtime_overrides
    data = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    patch = data.get("patch", {}) if data else {}

    # Reload từ file
    try:
        cfg_path = os.path.join(ROOT, "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            fresh = json.load(f)
        _runtime_overrides.update(fresh)
    except Exception as e:
        return {"ok": False, "error": f"Không đọc được config.json: {e}"}

    # Áp patch nếu có
    if patch:
        for k, v in patch.items():
            _runtime_overrides[k] = v
        # Lưu lại vào file
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({**load_config(), **_runtime_overrides}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"ok": False, "error": f"Lưu config thất bại: {e}"}

    # Reset Ollama interpreter singleton để pick up new policy
    from API_local.ollama_command import _default_interpreter
    import API_local.ollama_command as _oc
    _oc._default_interpreter = None  # force re-init next call

    return {
        "ok": True,
        "reloaded": True,
        "patch_applied": list(patch.keys()),
        "key_count": len(_runtime_overrides),
    }



@app.get("/api/voicevox_speakers")
async def voicevox_speakers(token: str = Depends(verify_token)):
    """Trả về danh sách toàn bộ speaker/style của VoiceVox đang tải."""
    speakers = list_voicevox_speakers()
    if not speakers:
        return {"ok": False, "speakers": [], "error": "VoiceVox chưa sẵn sàng hoặc chưa có model"}
    return {"ok": True, "speakers": speakers}


@app.get("/api/valtec_speakers")
async def valtec_speakers_api(token: str = Depends(verify_token)):
    """Trả về danh sách speaker Valtec (tiếng Việt) đang tải."""
    speakers = list_valtec_speakers()
    # Fallback khi Valtec chưa load — trả về tên mặc định phổ biến
    if not speakers:
        speakers = ["NF", "NN", "SF", "SN"]
    return {"ok": True, "speakers": speakers, "loaded": get_valtec() is not None}


@app.post("/api/tts_test")
async def tts_test(req: Request, token: str = Depends(verify_token)):
    """
    Test phát thử giọng VoiceVox với speaker_id tuỳ chọn.
    Body: {"text": "...", "speaker_id": 0, "speed": 1.0}
    Trả về audio/wav (stream trực tiếp).
    """
    from fastapi.responses import Response as FResponse
    data = await req.json()
    text = (data.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text rỗng"}
    if get_voicevox() is None:
        return {"ok": False, "error": "VoiceVox chưa sẵn sàng"}
    speaker_id = int(data.get("speaker_id", -1))
    speed = float(data.get("speed", 1.0))
    wav = await synth_jp(text, speed=speed, speaker_id=speaker_id, strict=False)
    if not wav:
        return {"ok": False, "error": "Tổng hợp thất bại (check log server)"}
    return FResponse(content=wav, media_type="audio/wav")


@app.post("/admin/reset_ai")
async def admin_reset_ai(token: str = Depends(verify_token)):
    """
    Reset toàn bộ AI instance + Voicevox + Valtec.
    Dùng sau khi nâng cấp module mà không muốn restart server.
    """
    global _ai_instance
    try:
        if _ai_instance and hasattr(_ai_instance, "emotion") and _ai_instance.emotion:
            try: _ai_instance.emotion.flush()
            except Exception: pass
        _ai_instance = None
        _tts_reset_engines()
        import API_local.ollama_command as _oc
        _oc._default_interpreter = None
        # Reinit
        init_ai(); _tts_init_all()
        return {"ok": True, "message": "AI instance đã được reset và khởi tạo lại."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
@app.post("/admin/reload_prompt_rules")
async def admin_reload_prompt_rules(req: Request, token: str = Depends(verify_token)):
        """
        Reload prompt JSON runtime không cần restart.
        Body (optional):
            {
                "reset_usage_history": true,
                "reset_promise_state": false
            }
        """
        data = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
        reset_usage = bool(data.get("reset_usage_history", True)) if isinstance(data, dict) else True
        reset_promise = bool(data.get("reset_promise_state", False)) if isinstance(data, dict) else False

        rules = _reload_proactive_prompt_rules(reset_usage_history=reset_usage)
        if reset_promise:
                _reset_promise_state()

        return {
                "ok": True,
                "reloaded": True,
                "path": _PROACTIVE_PROMPT_RULES_PATH,
                "reset_usage_history": reset_usage,
                "reset_promise_state": reset_promise,
                "top_level_keys": list(rules.keys()),
                "promise_phase": _promise_state.get("phase", "idle"),
        }


def _has_phone_clients() -> bool:
    return any(meta.get("is_phone", False) for meta in _active_ws_meta.values())


def _enforce_profile_pronouns(text: str, ai: Any) -> str:
    """Giữ đại từ theo thiết lập ban đầu của user profile (nếu bật lock)."""
    if not text:
        return text
    profile = getattr(ai, "profile", None)
    if not profile or not bool(getattr(profile, "lock_pronoun", True)):
        return text
    if detect_language(text) != "vi":
        return text

    user_call  = str(getattr(profile, "user_call", "") or getattr(profile, "pronoun", "bạn") or "bạn").strip()
    ai_pronoun = str(getattr(profile, "ai_pronoun", "mình") or "mình").strip()

    # Dùng placeholder NULL bytes để tránh double-replacement khi
    # user_call / ai_pronoun giống hoặc chứa "anh"/"em" (vd: cặp em/anh ngược).
    _U = "\x00U\x00"
    _A = "\x00A\x00"
    out = str(text)
    out = re.sub(r"\banh\b", _U, out, flags=re.IGNORECASE)
    out = re.sub(r"\bem\b",  _A, out, flags=re.IGNORECASE)
    out = out.replace(_U, user_call)
    out = out.replace(_A, ai_pronoun)
    return out


def _is_wiki_like_query(text: str) -> bool:
    t = str(text or "").strip().lower()
    if not t:
        return False
    if len(t) <= 2:
        return False
    hints = (
        "wikipedia", "wiki", "là gì", "la gi", "ai là", "ai la",
        "ở đâu", "o dau", "khi nào", "khi nao", "bao nhiêu", "bao nhieu",
        "tiểu sử", "tieu su", "định nghĩa", "dinh nghia",
    )
    return any(h in t for h in hints)


async def _rewrite_wiki_answer_with_ollama(question: str, wiki_answer: str, lang: str, ai: Any) -> str:
    """Viết lại câu trả lời Wiki cho tự nhiên hơn, nhưng giữ nguyên dữ kiện cốt lõi."""
    base = str(wiki_answer or "").strip()
    if not base:
        return ""
    if not bool(get("wiki_rewrite_with_ollama", True)):
        return base

    rewrite_prompt = (
        "Dựa CHỈ trên thông tin sau từ Wikipedia, viết lại câu trả lời ngắn gọn, tự nhiên, không bịa thêm dữ kiện. "
        "Giữ nguyên các thông tin quan trọng, tối đa 4 câu.\n"
        f"Câu hỏi người dùng: {question}\n"
        f"Thông tin wiki: {base}"
    )
    try:
        rewritten = await _chat_in_lang_async(rewrite_prompt, lang, ai)
        return str(rewritten or "").strip() or base
    except Exception:
        return base


def _repair_vi_pronoun_subjects(text: str, ai: Any) -> str:
    """Sửa lỗi câu trả lời bị đảo vai xưng hô ở vị trí chủ ngữ đầu câu.

    Ví dụ thường gặp khi LLM trượt vai: "anh muốn... anh sẽ giúp anh...".
    """
    if not text:
        return text
    if detect_language(text) != "vi":
        return text

    profile = getattr(ai, "profile", None)
    if not profile:
        return text

    user_call = str(getattr(profile, "user_call", "") or getattr(profile, "pronoun", "anh") or "anh").strip()
    ai_pronoun = str(getattr(profile, "ai_pronoun", "em") or "em").strip()
    if not user_call or not ai_pronoun or user_call == ai_pronoun:
        return text

    out = str(text)

    # Câu mở đầu hay đầu vế mà AI lỡ dùng user_call làm chủ ngữ cho hành động của AI.
    subject_verbs = r"(?:muốn|sẽ|đang|xin|đã|vừa|nghĩ|trả lời|kiểm tra|xem|đọc|tìm|tra cứu|hỗ trợ|giúp)"
    out = re.sub(
        rf"(^|[.!?]\s+)({re.escape(user_call)})\s+({subject_verbs})\b",
        rf"\1{ai_pronoun} \3",
        out,
        flags=re.IGNORECASE,
    )

    # Mẫu lặp cụ thể gây khó chịu trong trợ lý.
    out = re.sub(
        rf"\b{re.escape(user_call)}\s+sẽ\s+giúp\s+{re.escape(user_call)}\b",
        f"{ai_pronoun} sẽ giúp {user_call}",
        out,
        flags=re.IGNORECASE,
    )

    return out


def _reminder_next_due_iso(reminder: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    now_dt = now or datetime.now()
    r_time = str(reminder.get("time") or "").strip()
    if not r_time:
        return None
    try:
        hh, mm = [int(x) for x in r_time.split(":", 1)]
    except Exception:
        return None

    wd = reminder.get("weekday")
    if wd is None:
        target = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target < now_dt:
            target = target + timedelta(days=1)
        return target.isoformat()

    try:
        wd_i = int(wd)
    except Exception:
        return None
    if wd_i < 0 or wd_i > 6:
        return None

    days_ahead = (wd_i - now_dt.weekday()) % 7
    target = (now_dt + timedelta(days=days_ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target < now_dt:
        target = target + timedelta(days=7)
    return target.isoformat()


def _speak_local_mac(text: str) -> None:
    """Fallback cuối: macOS `say` (không hỗ trợ dấu tiếng Việt tốt)."""
    if not text or sys.platform != "darwin":
        return
    try:
        subprocess.run(["say", text[:280]], timeout=10)
    except Exception:
        pass


async def _chat_in_lang_async(text: str, lang: str, ai: Any) -> str:
    """
    Gọi Ollama để trả lời bằng ngôn ngữ cụ thể (en / ja).
    Trả về chuỗi trống nếu Ollama không sẵn sàng.
    """
    if lang == "vi":
        return ""
    try:
        from API_local.ollama_command import get_default_interpreter
        interp = get_default_interpreter()
        if not interp._check_local():
            return ""
        profile   = getattr(ai, "profile", None)
        user_call = str(getattr(profile, "user_call", "") or getattr(profile, "pronoun", "you") or "you").strip()
        ai_prn    = str(getattr(profile, "ai_pronoun", "I") or "I").strip()
        sys_prompts = {
            "en": (
                f"You are a friendly AI assistant named Yuki. "
                f"Reply ONLY in English. The user's name is '{user_call}'. "
                f"Keep replies warm, concise (≤3 sentences), and helpful. No markdown."
            ),
            "ja": (
                f"あなたはYukiという名前の親切なAIアシスタントです。"
                f"必ず日本語のみで返答してください。ユーザーの名前は「{user_call}」です。"
                f"返答は温かく、簡潔（3文以内）にしてください。マークダウン不要。"
            ),
        }
        sys_prompt = sys_prompts.get(lang, "")
        if not sys_prompt:
            return ""
        model_name = str(get("ollama_model", "")).strip() or interp.model
        msgs = [
            {"role": "system",  "content": sys_prompt},
            {"role": "user",    "content": text.strip()},
        ]
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: interp._call_ollama_model(
                model_name=model_name, messages=msgs, max_tokens=220, timeout=18,
            ),
        )
        if raw:
            return re.sub(r"\s+", " ", raw.strip()).strip()
    except Exception as _e_lang:
        log.warning(f"[LangChat:{lang}] {_e_lang}")
    return ""


async def _speak_local_vi_async(text: str) -> None:
    """
    Phát TTS tiếng Việt tại Mac khi phone offline.
    Ưu tiên Valtec → Edge TTS vi-VN-HoaiMyNeural → macOS say.
    Audio được play qua afplay (không block event loop).
    """
    if not text or sys.platform != "darwin":
        return
    try:
        speaker = str(get("proactive_vi_speaker", "NF")).strip() or "NF"
        speed   = float(get("proactive_vi_speed", 1.0))
        if get_valtec():
            wav = await generate_valtec_audio(text, speaker, speed)
        else:
            wav = await generate_edge_tts_audio(text, voice="vi-VN-HoaiMyNeural", rate=speed)

        if wav:
            import tempfile
            suffix = ".wav" if get_valtec() else ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tf.write(wav)
                fname = tf.name
            try:
                proc = await asyncio.create_subprocess_exec(
                    "afplay", fname,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=60)
            except asyncio.TimeoutError:
                try: proc.kill()
                except Exception: pass
            finally:
                try: os.unlink(fname)
                except Exception: pass
        else:
            _speak_local_mac(text)
    except Exception as _e_vi:
        log.warning(f"[LocalVI TTS] error: {_e_vi}")
        _speak_local_mac(text)


def _apply_idle_hormone_drift(ai: Any, idle_seconds: float) -> None:
    if not getattr(ai, "emotion", None):
        return
    if not bool(get("proactive_idle_hormone_enabled", True)):
        return

    threshold = float(get("proactive_idle_hormone_after_sec", 300))
    if idle_seconds < threshold:
        return

    # Drift nhẹ và tích luỹ theo thời gian idle.
    intensity = min(1.8, 1.0 + ((idle_seconds - threshold) / 1800.0))
    changes = {
        "dopamine": -0.008 * intensity,
        "serotonin": -0.005 * intensity,
        "oxytocin": -0.004 * intensity,
        "cortisol": 0.007 * intensity,
        "GABA": 0.003,
    }
    if idle_seconds >= 900:
        changes["adrenaline"] = 0.002 * intensity

    ai.emotion.hormone.apply(changes)
    if getattr(ai.emotion, "personality", None):
        ai.emotion.personality.update(changes)


_SCHEDULE_PROMPTS = [
    "Dạ anh muốn lịch tuần như thế nào ạ? Anh ghi theo từng ngày giúp em nhé.",
    "Mình lên lịch tuần luôn nha. Anh muốn ngày nào có môn/công việc gì ạ?",
    "Anh mô tả lịch cho em theo kiểu: Thứ 2 ..., Thứ 3 ..., các ngày còn lại để trống cũng được ạ.",
    "Em sẵn sàng tạo lịch rồi nè. Anh gửi khung tuần mong muốn, em sẽ điền chuẩn cho anh.",
]
_schedule_setup_state: Dict[Any, Dict[str, Any]] = {}
_proactive_care_state: Dict[str, Any] = {
    "active": False,
    "period": "",
    "turns": 0,
    "last_prompt_ts": 0.0,
    "last_user_ts": 0.0,
    "slot_key": "",
}

_PROACTIVE_PROMPT_RULES_FALLBACK: Dict[str, Any] = {
    "contextual_care_prompts": {
        "morning": ["Chào buổi sáng anh nè, mình uống nước và khởi động nhẹ chút nha."],
        "noon": ["Buổi trưa rồi nè anh, nghỉ mắt vài phút và uống nước cho tỉnh nha."],
        "evening": ["Tối đến rồi anh, mình hạ nhịp nhẹ nhàng để cơ thể nghỉ ngơi sâu hơn nha."],
    },
    "hormone_hints": {
        "high_cortisol": ["Em thấy mình hơi căng một chút, mình thở chậm vài nhịp cho dịu lại nha anh."],
        "low_dopamine": ["Em thấy nhịp này hơi chùng xuống chút xíu, mình đổi gió nhẹ một chút nha anh."],
        "low_serotonin": ["Em thấy mình cần dịu lại một chút, anh thử ra chỗ thoáng hoặc đi bộ ngắn nha."],
        "stable": ["Em thấy mọi thứ đang khá êm."],
    },
    "evening_handoff_prompts": ["Tối em lại ghé hỏi thăm anh thêm một vòng nha."],
    "care_followup_fallback": {
        "morning": ["Sáng nay mình làm từng chút thôi cũng rất ổn rồi anh."],
        "noon": ["Trưa nghỉ ngắn chút xíu là chiều đỡ mệt hơn nhiều đó anh."],
        "evening": ["Tối nay mình dịu lại một chút nha anh, em ở đây với anh nè."],
    },
    "promise_timer": {
        "create_confirm": ["Em lưu mốc {time_label} rồi nha anh, tới giờ em sẽ nhắc nghỉ."],
        "due_level_1": ["Đến giờ nghỉ rồi đó anh ơi, mình giữ lời hứa nha."],
        "due_level_2": ["Em dỗi nhẹ đó nha, mình hứa nghỉ mà anh ơi."],
        "due_level_3": ["Em dỗi thêm rồi nè, anh nghỉ liền giúp em nha."],
        "extend_ack": ["Em dời mốc sang {time_label} rồi nha anh."],
        "done_ack": ["Em tin anh đã nghỉ rồi nè, một tiếng nữa em hỏi lại nhẹ nhàng nha."],
        "verify_after_1h": ["Sau 1 tiếng rồi nè anh, anh nghỉ thật chưa để em yên tâm nào?"],
        "not_yet_reply": ["Không sao anh, em dời thêm 30 phút rồi nhắc lại nha."],
    },
}

_PROACTIVE_PROMPT_RULES_PATH = os.path.join(ROOT, str(get("proactive_prompt_rules_path", "core/proactive_prompt_rules.json")))


def _load_proactive_prompt_rules() -> Dict[str, Any]:
    if os.path.exists(_PROACTIVE_PROMPT_RULES_PATH):
        try:
            with open(_PROACTIVE_PROMPT_RULES_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                merged = dict(_PROACTIVE_PROMPT_RULES_FALLBACK)
                merged.update(raw)
                return merged
        except Exception:
            pass
    return _PROACTIVE_PROMPT_RULES_FALLBACK


_PROACTIVE_PROMPT_RULES = _load_proactive_prompt_rules()
_promise_state: Dict[str, Any] = {
    "active": False,
    "phase": "idle",  # idle|waiting_due|nudging|verify_wait|verify_asked
    "due_ts": 0.0,
    "next_nudge_ts": 0.0,
    "ignore_count": 0,
    "verify_ts": 0.0,
}

_RE_PROMISE_DURATION = re.compile(r"(\d{1,3})\s*(phút|phut|tiếng|tieng|giờ|gio)\b", re.IGNORECASE)
_RE_PROMISE_CLOCK = re.compile(r"\b(?:lúc|luc)?\s*(\d{1,2})(?:[:h](\d{1,2}))?\b", re.IGNORECASE)


def _pick_nonrepeat_prompt(key: str, pool: List[str], max_recent: int = 4) -> str:
    clean_pool = [p.strip() for p in (pool or []) if str(p).strip()]
    if not clean_pool:
        return ""

    # Unique nhưng giữ thứ tự xuất hiện ban đầu
    uniq_pool = list(dict.fromkeys(clean_pool))
    state = _prompt_cycle_state.setdefault(key, {"remaining": [], "last": ""})

    remaining = [p for p in state.get("remaining", []) if p in uniq_pool]
    if not remaining:
        remaining = uniq_pool[:]
        random.shuffle(remaining)
        last = str(state.get("last", ""))
        if len(remaining) > 1 and last and remaining[0] == last:
            remaining[0], remaining[-1] = remaining[-1], remaining[0]

    picked = remaining.pop(0)
    state["remaining"] = remaining
    state["last"] = picked

    recent = _prompt_recent_history.setdefault(key, [])
    recent.append(picked)
    if len(recent) > max(8, max_recent * 3):
        del recent[: len(recent) - max(8, max_recent * 2)]

    return picked


def _reset_promise_state() -> None:
    _promise_state.update({
        "active": False,
        "phase": "idle",
        "due_ts": 0.0,
        "next_nudge_ts": 0.0,
        "ignore_count": 0,
        "verify_ts": 0.0,
    })


def _cleanup_proactive_runtime_state(now_ts: float) -> None:
    # Dọn cache lịch sử câu đã dùng, tránh phình bộ nhớ theo thời gian.
    for k in list(_prompt_recent_history.keys()):
        arr = _prompt_recent_history.get(k) or []
        if not arr:
            _prompt_recent_history.pop(k, None)
            continue
        if len(arr) > 24:
            _prompt_recent_history[k] = arr[-12:]

    # Dọn cycle state nếu key không còn dùng.
    valid_keys = set(_prompt_recent_history.keys())
    for k in list(_prompt_cycle_state.keys()):
        if k not in valid_keys:
            _prompt_cycle_state.pop(k, None)

    # Nếu promise đã quá hạn quá lâu mà user không tương tác thì tự xóa state.
    phase = str(_promise_state.get("phase", "idle"))
    if phase == "idle":
        return
    due_ts = float(_promise_state.get("due_ts", 0.0))
    verify_ts = float(_promise_state.get("verify_ts", 0.0))

    stale_due = (due_ts > 0 and (now_ts - due_ts) > 86400)
    stale_verify = (verify_ts > 0 and (now_ts - verify_ts) > 21600)
    if stale_due or stale_verify:
        _reset_promise_state()


def _reload_proactive_prompt_rules(reset_usage_history: bool = True) -> Dict[str, Any]:
    global _PROACTIVE_PROMPT_RULES
    _PROACTIVE_PROMPT_RULES = _load_proactive_prompt_rules()
    if reset_usage_history:
        _prompt_recent_history.clear()
        _prompt_cycle_state.clear()
    return _PROACTIVE_PROMPT_RULES


def _rules_list(path: List[str], fallback: Optional[List[str]] = None) -> List[str]:
    cur: Any = _PROACTIVE_PROMPT_RULES
    for seg in path:
        if not isinstance(cur, dict):
            return fallback or []
        cur = cur.get(seg)
    return cur if isinstance(cur, list) else (fallback or [])


def _render_prompt(template: str, **kwargs: Any) -> str:
    try:
        return str(template).format(**kwargs)
    except Exception:
        return str(template)


def _format_time_label(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _parse_promise_due_ts(text: str, now_ts: float) -> float:
    lowered = (text or "").lower()

    m = _RE_PROMISE_DURATION.search(lowered)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        sec = val * 60
        if unit in {"tiếng", "tieng", "giờ", "gio"}:
            sec = val * 3600
        return now_ts + max(300, sec)

    m2 = _RE_PROMISE_CLOCK.search(lowered)
    if m2 and ("lúc" in lowered or "luc" in lowered or "h" in lowered or ":" in lowered):
        hh = int(m2.group(1))
        mm = int(m2.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            now_lt = time.localtime(now_ts)
            target = time.mktime((
                now_lt.tm_year, now_lt.tm_mon, now_lt.tm_mday,
                hh, mm, 0,
                now_lt.tm_wday, now_lt.tm_yday, now_lt.tm_isdst
            ))
            if target <= now_ts:
                target += 86400
            return target

    return 0.0


def _promise_escalation_level(ignore_count: int) -> int:
    if ignore_count >= 4:
        return 3
    if ignore_count >= 2:
        return 2
    return 1


def _promise_create_or_update(due_ts: float, now_ts: float) -> str:
    _promise_state.update({
        "active": True,
        "phase": "waiting_due",
        "due_ts": due_ts,
        "next_nudge_ts": due_ts,
        "ignore_count": 0,
        "verify_ts": 0.0,
    })
    time_label = _format_time_label(due_ts)
    pool = _rules_list(["promise_timer", "create_confirm"], ["Em lưu mốc {time_label} rồi nha anh."])
    template = _pick_nonrepeat_prompt("promise_create_confirm", pool)
    return _render_prompt(template, time_label=time_label)


def _promise_extend(due_ts: float) -> str:
    _promise_state.update({
        "active": True,
        "phase": "waiting_due",
        "due_ts": due_ts,
        "next_nudge_ts": due_ts,
        "ignore_count": max(0, int(_promise_state.get("ignore_count", 0)) - 1),
        "verify_ts": 0.0,
    })
    pool = _rules_list(["promise_timer", "extend_ack"], ["Em dời mốc sang {time_label} rồi nha anh."])
    template = _pick_nonrepeat_prompt("promise_extend_ack", pool)
    return _render_prompt(template, time_label=_format_time_label(due_ts))


def _is_promise_setup_intent(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    has_rest = any(k in lowered for k in ["nghỉ", "nghi", "nghi ngoi", "nghỉ ngơi"])
    has_timer = any(k in lowered for k in ["nhắc", "nhac", "hẹn", "hen", "báo", "bao", "hứa", "hua", "mốc", "moc"])
    return has_rest and has_timer


def _handle_promise_user_message(text: str, now_ts: float) -> str:
    lowered = (text or "").lower()
    if not bool(get("proactive_promise_enabled", True)):
        return ""

    due_ts = _parse_promise_due_ts(text, now_ts)
    if _is_promise_setup_intent(text) and due_ts > 0:
        return _promise_create_or_update(due_ts, now_ts)

    active = bool(_promise_state.get("active", False))
    phase = str(_promise_state.get("phase", "idle"))
    if not active and phase == "idle":
        return ""

    done_keys = ["nghỉ rồi", "nghi roi", "em nghỉ rồi", "anh nghỉ rồi", "xong rồi", "đã nghỉ", "da nghi"]
    extend_keys = ["hứa tiếp", "hua tiep", "thêm", "them", "cho anh thêm", "dời", "doi", "lát nữa", "lat nua"]
    not_yet_keys = ["chưa", "chua", "chưa nghỉ", "chua nghi", "chưa thật", "chua that"]

    if any(k in lowered for k in done_keys):
        verify_after = float(get("proactive_promise_verify_after_sec", 3600))
        _promise_state.update({
            "active": True,
            "phase": "verify_wait",
            "verify_ts": now_ts + verify_after,
            "next_nudge_ts": 0.0,
        })
        pool = _rules_list(["promise_timer", "done_ack"], ["Em tin anh rồi nha, 1 tiếng nữa em hỏi lại nhẹ nhàng."])
        return _pick_nonrepeat_prompt("promise_done_ack", pool)

    if any(k in lowered for k in extend_keys):
        due = due_ts if due_ts > 0 else (now_ts + 1800)
        return _promise_extend(due)

    if phase == "verify_asked" and any(k in lowered for k in not_yet_keys):
        _promise_state.update({
            "active": True,
            "phase": "waiting_due",
            "due_ts": now_ts + 1800,
            "next_nudge_ts": now_ts + 1800,
            "ignore_count": 0,
            "verify_ts": 0.0,
        })
        pool = _rules_list(["promise_timer", "not_yet_reply"], ["Không sao anh, em dời thêm 30 phút rồi nhắc lại nha."])
        return _pick_nonrepeat_prompt("promise_not_yet", pool)

    if phase == "verify_asked" and any(k in lowered for k in ["rồi", "roi", "ổn", "on", "ok"]):
        _reset_promise_state()
        return "Dạ em tin anh thiệt rồi nè, giỏi lắm."

    return ""


async def _maybe_run_promise_timer(ai: Any, now_ts: float) -> None:
    if not bool(get("proactive_promise_enabled", True)):
        return

    active = bool(_promise_state.get("active", False))
    if not active:
        return

    phase = str(_promise_state.get("phase", "idle"))
    if phase == "verify_wait":
        verify_ts = float(_promise_state.get("verify_ts", 0.0))
        if verify_ts > 0 and now_ts >= verify_ts:
            pool = _rules_list(["promise_timer", "verify_after_1h"], ["Sau 1 tiếng rồi nè anh, anh nghỉ thật chưa?"])
            msg = _pick_nonrepeat_prompt("promise_verify", pool)
            if msg:
                await broadcast_proactive(msg, ai)
                _promise_state.update({"phase": "verify_asked", "next_nudge_ts": now_ts + 1800})
        return

    if phase not in {"waiting_due", "nudging", "verify_asked"}:
        return

    due_ts = float(_promise_state.get("due_ts", 0.0))
    next_nudge_ts = float(_promise_state.get("next_nudge_ts", 0.0))
    if due_ts <= 0:
        return
    if now_ts < due_ts or now_ts < next_nudge_ts:
        return

    level = _promise_escalation_level(int(_promise_state.get("ignore_count", 0)))
    pool = _rules_list(["promise_timer", f"due_level_{level}"], ["Đến giờ nghỉ rồi đó anh ơi, mình giữ lời hứa nha."])
    msg = _pick_nonrepeat_prompt(f"promise_due_l{level}", pool)
    if not msg:
        return

    await broadcast_proactive(msg, ai)
    nudge_every = float(get("proactive_promise_nudge_every_sec", 1800))
    _promise_state.update({
        "phase": "nudging",
        "ignore_count": int(_promise_state.get("ignore_count", 0)) + 1,
        "next_nudge_ts": now_ts + max(1800, nudge_every),
    })


def _load_week_schedule() -> Dict[str, str]:
    p = os.path.join(ROOT, "data", "schedule.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return normalize_schedule_payload(json.load(f) or {})
        except Exception:
            pass
    return empty_week_schedule()


def _get_care_period(now_ts: float) -> str:
    lt = time.localtime(now_ts)
    h = lt.tm_hour
    if 6 <= h < 9:
        return "morning"
    if 11 <= h < 14:
        return "noon"
    if 19 <= h < 22:
        return "evening"
    return ""


def _build_hormone_hint(ai: Any) -> str:
    if not getattr(ai, "emotion", None):
        return ""
    try:
        levels = ai.emotion.hormone.get()
    except Exception:
        return ""

    cortisol = float(levels.get("cortisol", 0.0))
    dopamine = float(levels.get("dopamine", 0.0))
    serotonin = float(levels.get("serotonin", 0.0))

    if cortisol >= 0.58:
        pool = _rules_list(["hormone_hints", "high_cortisol"], _PROACTIVE_PROMPT_RULES_FALLBACK["hormone_hints"]["high_cortisol"])
        return _pick_nonrepeat_prompt("hint_high_cortisol", pool)
    if dopamine <= 0.42:
        pool = _rules_list(["hormone_hints", "low_dopamine"], _PROACTIVE_PROMPT_RULES_FALLBACK["hormone_hints"]["low_dopamine"])
        return _pick_nonrepeat_prompt("hint_low_dopamine", pool)
    if serotonin <= 0.45:
        pool = _rules_list(["hormone_hints", "low_serotonin"], _PROACTIVE_PROMPT_RULES_FALLBACK["hormone_hints"]["low_serotonin"])
        return _pick_nonrepeat_prompt("hint_low_serotonin", pool)
    pool = _rules_list(["hormone_hints", "stable"], _PROACTIVE_PROMPT_RULES_FALLBACK["hormone_hints"]["stable"])
    return _pick_nonrepeat_prompt("hint_stable", pool)


def _sanitize_proactive_text(text: str) -> str:
    """Làm sạch câu proactive trước khi phát ra cho user.

    Mục tiêu:
    - Không để lộ các từ kỹ thuật như hormone/cortisol/dopamine.
    - Giữ câu nói theo góc nhìn trạng thái nội tại của AI, không gán sinh học đó cho user.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"(?i)\b(hormone|cortisol|dopamine|serotonin|oxytocin|adrenaline|gaba|norepinephrine)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:!?]){2,}", r"\1", cleaned)
    cleaned = cleaned.strip(" ,.;:-")
    return cleaned


def _rewrite_contextual_care_with_bonsai_sync(text: str, period: str, ai: Any) -> str:
    """Dùng Bonsai để đổi phrasing proactive care cho đỡ lặp, nhưng vẫn an toàn.

    Chỉ áp dụng cho contextual care prompt, có fallback ngay nếu Bonsai không sẵn.
    """
    base = _sanitize_proactive_text(text)
    if not base:
        return ""

    # Chỉ wake Bonsai khi người dùng bật PentamiT (thinking mode).
    if not _pentami_thinking_mode:
        return base

    if random.random() > 0.65:
        return base

    try:
        bonsai = get_bonsai_client()
        if not bonsai:
            return base

        profile = getattr(ai, "profile", None)
        user_pr = str(getattr(profile, "user_call", "anh") or "anh").strip()
        ai_pr = str(getattr(profile, "ai_pronoun", "em") or "em").strip()

        messages = [
            {
                "role": "system",
                "content": (
                    "Bạn là trợ lý nữ tiếng Việt tự nhiên và dịu dàng. "
                    f"Giữ cố định đại từ: người dùng là '{user_pr}', trợ lý là '{ai_pr}'. "
                    "Hãy viết lại 1 câu nhắc nhở chăm sóc ngắn gọn, tự nhiên, ấm áp, đỡ lặp phrasing. "
                    "Tuyệt đối không dùng các từ: hormone, cortisol, dopamine, serotonin, oxytocin, adrenaline, GABA, norepinephrine. "
                    "Không nói như trạng thái sinh học đó là của người dùng. "
                    "Giữ ý chính cũ, không thêm giải thích dài, không markdown, không emoji."
                ),
            },
            {
                "role": "user",
                "content": f"Ngữ cảnh: proactive_{period}. Viết lại câu này cho mới hơn: {base}",
            },
        ]

        raw, _elapsed = bonsai.chat(messages, max_tokens=72)
        rewritten = _sanitize_proactive_text((raw or "").strip().strip('"'))
        return rewritten or base
    except Exception:
        return base


def _compose_contextual_care_prompt(ai: Any, period: str) -> str:
    pool = _rules_list(["contextual_care_prompts", period], _PROACTIVE_PROMPT_RULES_FALLBACK["contextual_care_prompts"]["morning"])
    base = _pick_nonrepeat_prompt(f"care_{period}", pool)
    hint = _build_hormone_hint(ai)
    combined = f"{base} {hint}".strip()
    return _rewrite_contextual_care_with_bonsai_sync(combined, period, ai)


async def _maybe_send_contextual_care_prompt(ai: Any, now_ts: float, idle_sec: float) -> None:
    global _proactive_care_state
    if not bool(get("proactive_contextual_care_enabled", True)):
        return
    if idle_sec < float(get("proactive_contextual_idle_sec", 420)):
        return

    period = _get_care_period(now_ts)
    if not period:
        return

    lt = time.localtime(now_ts)
    slot_key = f"{lt.tm_year}-{lt.tm_yday}-{period}"
    if slot_key == str(_proactive_care_state.get("slot_key", "")):
        return

    cooldown = float(get("proactive_contextual_cooldown_sec", 2700))
    if (now_ts - float(_proactive_care_state.get("last_prompt_ts", 0.0))) < cooldown:
        return

    prompt = _compose_contextual_care_prompt(ai, period)
    await broadcast_proactive(prompt, ai)
    _proactive_care_state.update({
        "active": True,
        "period": period,
        "turns": 0,
        "last_prompt_ts": now_ts,
        "last_user_ts": 0.0,
        "slot_key": slot_key,
    })


def _fallback_care_followup(period: str) -> str:
    fallback = _PROACTIVE_PROMPT_RULES_FALLBACK["care_followup_fallback"]
    pool = _rules_list(["care_followup_fallback", period], fallback.get("evening", []))
    return _pick_nonrepeat_prompt(f"care_followup_{period}", pool)


def _generate_care_followup_sync(user_text: str, period: str, ai: Any) -> str:
    try:
        interp = get_default_interpreter()
        if not interp._check_local():
            return _fallback_care_followup(period)

        hormones = {}
        emotion_state = "neutral"
        if getattr(ai, "emotion", None):
            try:
                hormones = ai.emotion.hormone.get()
                emotion_state = ai.emotion.hormone.get_emotional_state()
            except Exception:
                hormones = {}

        h_short = ", ".join([
            f"dopamine={float(hormones.get('dopamine', 0.5)):.2f}",
            f"serotonin={float(hormones.get('serotonin', 0.5)):.2f}",
            f"cortisol={float(hormones.get('cortisol', 0.5)):.2f}",
            f"oxytocin={float(hormones.get('oxytocin', 0.5)):.2f}",
        ])

        profile = getattr(ai, "profile", None)
        user_pr = str(getattr(profile, "user_call", "") or getattr(profile, "pronoun", "bạn") or "bạn").strip()
        ai_pr = str(getattr(profile, "ai_pronoun", "mình") or "mình").strip()

        sys_prompt = (
            "Bạn là trợ lý nữ tiếng Việt dễ thương và đồng cảm. "
            f"Giữ cố định đại từ: người dùng là '{user_pr}', trợ lý là '{ai_pr}'. "
            "Hãy phản hồi NGẮN GỌN 1 câu (tối đa 24 từ), động viên nhẹ nhàng. "
            "Có thể gợi ý 1 hành động nhỏ tốt cho sức khỏe. "
            "Không markdown, không emoji, không giải thích dài dòng."
        )
        user_prompt = (
            f"Ngữ cảnh: proactive_{period}. Emotion={emotion_state}. Hormones: {h_short}. "
            f"Anh vừa trả lời: {user_text.strip()}"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]

        model_name = str(get("ollama_local_schedule_model", "")).strip() or interp.model
        raw = interp._call_ollama_model(model_name=model_name, messages=messages, max_tokens=72, timeout=10)
        if not raw:
            return _fallback_care_followup(period)

        cleaned = re.sub(r"\s+", " ", raw.strip().strip('"')).strip()
        return _enforce_profile_pronouns(cleaned[:220], ai) if cleaned else _fallback_care_followup(period)
    except Exception:
        return _fallback_care_followup(period)


async def _maybe_reply_contextual_care(user_text: str, ai: Any, now_ts: float) -> str:
    global _proactive_care_state
    if not bool(_proactive_care_state.get("active", False)):
        return ""

    timeout_sec = float(get("proactive_contextual_followup_timeout_sec", 1800))
    if (now_ts - float(_proactive_care_state.get("last_prompt_ts", 0.0))) > timeout_sec:
        _proactive_care_state["active"] = False
        return ""

    period = str(_proactive_care_state.get("period", "") or "morning")
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, lambda: _generate_care_followup_sync(user_text, period, ai))

    turns = int(_proactive_care_state.get("turns", 0)) + 1
    _proactive_care_state["turns"] = turns
    _proactive_care_state["last_user_ts"] = now_ts

    if turns >= 2 and period in {"morning", "noon"}:
        _proactive_care_state["active"] = False
        handoff_pool = _rules_list(["evening_handoff_prompts"], _PROACTIVE_PROMPT_RULES_FALLBACK["evening_handoff_prompts"])
        handoff = _pick_nonrepeat_prompt("evening_handoff", handoff_pool)
        return f"{reply} {handoff}".strip()

    if turns >= 2 and period == "evening":
        _proactive_care_state["active"] = False

    return reply


def _parse_schedule_with_local_ollama(text: str) -> Dict[str, str]:
    try:
        interp = get_default_interpreter()
        if not interp._check_local():
            return empty_week_schedule()

        model_name = str(get("ollama_local_schedule_model", "")).strip() or interp.model
        sys_prompt = (
            "Bạn là bộ trích xuất lịch tuần. Trả về JSON object DUY NHẤT với 7 key: "
            "monday,tuesday,wednesday,thursday,friday,saturday,sunday. "
            "Giá trị mỗi key là mô tả ngắn của lịch trong ngày, hoặc chuỗi rỗng nếu không có. "
            "Không markdown, không giải thích."
        )
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text.strip()},
        ]
        raw = interp._call_ollama_model(model_name=model_name, messages=msgs, max_tokens=220, timeout=12)
        parsed = interp._extract_json(raw or "") or {}
        if not isinstance(parsed, dict):
            return empty_week_schedule()
        return normalize_schedule_payload(parsed)
    except Exception:
        return empty_week_schedule()


def _save_week_schedule(schedule_data: Dict[str, str]) -> None:
    data_dir = os.path.join(ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    current_path = os.path.join(data_dir, "schedule.json")
    prev_path = os.path.join(data_dir, "schedule_prev.json")

    try:
        if os.path.exists(current_path):
            with open(current_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            with open(prev_path, "w", encoding="utf-8") as f:
                json.dump(old, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    with open(current_path, "w", encoding="utf-8") as f:
        json.dump(schedule_data, f, indent=2, ensure_ascii=False)


async def _maybe_open_mood_playlist(ai: Any, now_ts: float) -> None:
    global _last_mood_playlist_ts
    if not bool(get("proactive_mood_playlist_enabled", True)):
        return
    if not getattr(ai, "emotion", None):
        return

    cooldown = float(get("proactive_mood_playlist_cooldown_sec", 1800))
    if (now_ts - _last_mood_playlist_ts) < cooldown:
        return

    levels = ai.emotion.hormone.get()
    state  = ai.emotion.hormone.get_emotional_state()
    low_mood = (
        state in {"anxious", "stressed", "tired_uneasy", "low_energy", "mildly_stressed"}
        or (levels.get("cortisol", 0.0) >= 0.52)
        or (levels.get("serotonin", 1.0) <= 0.42 and levels.get("dopamine", 1.0) <= 0.38)
    )
    if not low_mood:
        return

    _ai_prn = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
    _usr_prn = (
        getattr(getattr(ai, "profile", None), "user_call", "")
        or getattr(getattr(ai, "profile", None), "pronoun", "anh")
    )

    # Phát nhạc chill từ thư mục music/chill_music (ưu tiên) hoặc music/
    song_name = _play_music_subfolder("chill_music")
    if song_name:
        note = (
            f"{_ai_prn.capitalize()} thấy mood đang thấp nên "
            f"{_ai_prn} bật nhạc chill cho {_usr_prn} nha. "
            f"Đang phát: {song_name}"
        )
    else:
        note = (
            f"{_ai_prn.capitalize()} thấy mood đang thấp, "
            f"{_usr_prn} nghỉ ngơi một chút nha. "
            f"(Thêm nhạc vào thư mục music/chill_music để {_ai_prn} phát nhé!)"
        )

    await broadcast_proactive(note, ai)
    _last_mood_playlist_ts = now_ts

# ── WebSocket Workflow ────────────────────────────────────────────
_active_ws: set = set()
# Lưu metadata mỗi WS: {ws: {"is_phone": bool, "addr": str}}
# is_phone=True → client là iPhone/thiết bị ngoài; is_phone=False → CLI browser trên Mac
_active_ws_meta: Dict = {}

async def broadcast_proactive(text: str, ai: Any):
    """Gửi tin nhắn tự phát tới toàn bộ client đang kết nối.
    Text → tất cả client.
    Audio TTS → chỉ phone client (tránh phát đôi qua CLI browser trên Mac).
    """
    text = _sanitize_proactive_text(_enforce_profile_pronouns(text, ai))
    if not text:
        return
    now_ts = time.time()
    if not _active_ws:
        _queue_proactive_phone_backlog(text, now_ts)
        if bool(get("proactive_speak_local_when_phone_offline", True)):
            # Dùng TTS tiếng Việt đúng thay vì macOS say (không hỗ trợ dấu Vi)
            asyncio.create_task(_speak_local_vi_async(text))
        return
    log.info(f"📢 [Broadcast] {text}")

    # Chuẩn bị data response
    em = ai.emotion.hormone.get_emotional_state() if hasattr(ai, 'emotion') else "normal"
    hl = ai.emotion.hormone.get() if hasattr(ai, 'emotion') else {}
    data = {"type": "response", "text": text, "ai_latency_ms": 0, "emotional_state": em, "hormone_levels": hl}

    # Broadcast text đến tất cả client
    to_remove = []
    for ws in list(_active_ws):
        if not await safe_send_json(ws, data): to_remove.append(ws)
    for ws in to_remove:
        _active_ws.discard(ws)
        _active_ws_meta.pop(ws, None)

    # TTS chỉ gửi đến phone client (không gửi lên CLI browser để tránh phát 2 lần)
    phone_ws = [ws for ws in _active_ws if _active_ws_meta.get(ws, {}).get("is_phone", False)]
    if not phone_ws:
        _queue_proactive_phone_backlog(text, now_ts)
        if bool(get("proactive_speak_local_when_phone_offline", True)):
            asyncio.create_task(_speak_local_vi_async(text))
        return

    async with _tts_stream_lock:
        sents = split_sentences(text)
        for ws in phone_ws:
            await safe_send_json(ws, {"type": "tts_start", "total": len(sents)})

        proactive_speaker = str(get("proactive_vi_speaker", "NF")).strip() or "NF"
        proactive_speed   = float(get("proactive_vi_speed", 1.0))
        for i, s in enumerate(sents):
            # force_lang="vi": nhắc nhở luôn là tiếng Việt, tránh detect_language sai
            wav, is_edge = await synthesize_tts_by_language(
                s, proactive_speaker, proactive_speed, force_lang="vi"
            )
            # Tránh mất câu khi strict mode trả về audio rỗng.
            if not wav and bool(get("tts_strict_language_engine", True)):
                log.warning(f"[Proactive TTS] Empty audio in strict mode, retry non-strict (sent={i + 1}/{len(sents)})")
                wav, is_edge = await synthesize_tts_by_language(
                    s,
                    proactive_speaker,
                    proactive_speed,
                    force_lang="vi",
                    strict=False,
                )
            if wav:
                b64 = base64.b64encode(wav).decode()
                for ws in phone_ws:
                    await safe_send_json(
                        ws,
                        {"type": "audio_chunk", "audio_b64": b64,
                         "mime_type": "audio/mpeg" if is_edge else "audio/wav"},
                    )
            else:
                log.warning(f"[Proactive TTS] Skip sentence because audio is still empty (sent={i + 1}/{len(sents)})")

        for ws in phone_ws:
            await safe_send_json(ws, {"type": "audio_end"})

# ── PentaKuruV4 Health & Sync Helper Functions ────────────────────────────

async def _check_penta_kuru_health(force: bool = False) -> bool:
    """Kiểm tra PentaKuruV4 health. Chỉ thực hiện request nếu force=True hoặc cache hết hạn."""
    global _penta_kuru_health, _kuru_placeholder_warned
    if not get("enable_penta_kuru_integration"):
        return False
    
    kuru_url = get("penta_kuru_cloudflare_url", "").strip()
    if not kuru_url:
        return False
    if "your-tunnel.workers.dev" in kuru_url:
        if not _kuru_placeholder_warned:
            log.warning("[Kuru Health] Cloudflare URL đang là placeholder. Tắt monitor.")
            _kuru_placeholder_warned = True
        return False
    
    now_ts = time.time()
    # Cache kết quả 60 giây nếu không ép buộc (force)
    if not force and now_ts - _penta_kuru_health.get("last_check", 0) < 60:
        return _penta_kuru_health.get("ok", False)
    
    try:
        # Chạy requests trong thread để không block event loop
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: requests.get(f"{kuru_url}/health", timeout=3))
        ok = r.status_code == 200
        _penta_kuru_health = {"ok": ok, "last_check": now_ts}
        return ok
    except Exception as e:
        log.debug(f"[Kuru Health] Background check failed: {e}")
        _penta_kuru_health = {"ok": False, "last_check": now_ts}
        return False


async def kuru_health_monitor_task() -> None:
    """Background task cập nhật trạng thái kết nối Cloudflare mỗi 60s."""
    log.info("[Kuru Monitor] Started")
    while True:
        try:
            await _check_penta_kuru_health(force=True)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            log.info("[Kuru Monitor] Stopped")
            return
        except Exception as e:
            log.error(f"[Kuru Monitor] Error: {e}")
            await asyncio.sleep(30)

async def _sync_commands_to_penta_kuru():
    """Gửi danh sách commands thành công tới PentaKuruV4."""
    global _penta_kuru_cb_fails, _penta_kuru_cb_open_until, _recent_successful_commands
    
    if not get("enable_penta_kuru_integration"):
        return
    
    # Kiểm tra circuit breaker
    now_ts = time.time()
    if now_ts < _penta_kuru_cb_open_until:
        log.warning("[Kuru CB] Circuit breaker OPEN — skipping sync")
        return
    
    kuru_url = get("penta_kuru_cloudflare_url", "").strip()
    kuru_token = get("penta_kuru_token", "").strip()
    
    if not (kuru_url and kuru_token):
        return
    
    try:
        r = requests.post(
            f"{kuru_url}/api/sync_commands",
           json={"commands": _recent_successful_commands[-50:]},
            headers={"Authorization": f"Bearer {kuru_token}"},
            timeout=5
        )
        if r.status_code == 200:
            _penta_kuru_cb_fails = 0
            log.info(f"✅ Synced {len(_recent_successful_commands)} commands to Kuru")
        else:
            _penta_kuru_cb_fails += 1
    except Exception as e:
        log.warning(f"[Kuru Sync] Error: {e}")
        _penta_kuru_cb_fails += 1
    
    # Circuit breaker logic
    max_fails = int(get("penta_kuru_circuit_breaker_max_fails", 3))
    reset_sec = int(get("penta_kuru_circuit_breaker_reset_sec", 120))
    
    if _penta_kuru_cb_fails >= max_fails:
        _penta_kuru_cb_open_until = now_ts + reset_sec
        log.warning(f"[Kuru CB] OPEN for {reset_sec}s (fails={_penta_kuru_cb_fails})")

async def proactive_background_task():
    """Vòng lặp kiểm tra nhắc nhở và cảm xúc chủ động mỗi 60 giây."""
    global _last_break_remind_ts, _last_weekly_summary_key
    global _next_break_remind_ts, _work_break_cycle_count
    global _auto_sleep_after_work_triggered, _server_sleep_mode, _server_sleep_started_ts
    await asyncio.sleep(10) # Chờ 10s cho hệ thống ổn định
    ai = init_ai()
    log.info("🕒 Proactive background task started (60s loop)")
    while True:
        try:
            if _server_sleep_mode:
                await asyncio.sleep(60)
                continue

            now_ts = time.time()
            idle_sec = max(0.0, now_ts - _last_user_interaction_ts)

            # Auto sleep sau 11 tiếng làm liên tục (tiếng = giờ làm việc).
            if _work_session_start_ts and not _auto_sleep_after_work_triggered:
                worked_hours = (now_ts - _work_session_start_ts) / 3600.0
                if worked_hours >= 11.0:
                    await broadcast_proactive(
                        "Anh đã chạm mốc 11 tiếng làm việc liên tục rồi. Em cho hệ thống vào PentaSleep để bảo vệ sức khỏe cho anh nha.",
                        ai,
                    )
                    _server_sleep_mode = True
                    _server_sleep_started_ts = now_ts
                    _auto_sleep_after_work_triggered = True
                    await asyncio.sleep(60)
                    continue

            _cleanup_proactive_runtime_state(now_ts)

            # 0. Không tương tác 5 phút+ → hormone biến động tích luỹ
            _apply_idle_hormone_drift(ai, idle_sec)

            # 1. Kiểm tra nhắc nhở đến hạn
            due = ai.time.check_due_reminders()
            if due:
                msgs = [ai.time.format_reminder_message(r, "vi") for r in due]
                await broadcast_proactive(" | ".join(msgs), ai)

            # 1.5 Nhắc nghỉ theo timer tăng dần: 2h, 4h, 6h... (đến khi sleep/off)
            interval = float(get("proactive_break_remind_interval_sec", 7200))
            max_cycles = int(get("proactive_break_remind_max_cycles", 12))
            if _work_session_start_ts and _next_break_remind_ts > 0 and now_ts >= _next_break_remind_ts:
                if _work_break_cycle_count < max_cycles:
                    _work_break_cycle_count += 1
                    hour_mark = int((_work_break_cycle_count * interval) / 3600)
                    remind_text = _compose_progressive_break_text(hour_mark)
                    await broadcast_proactive(remind_text, ai)

                    if bool(get("proactive_break_remind_play_music", True)):
                        _song = await _broadcast_reminder_music_to_phone(
                            str(get("proactive_break_remind_music_subfolder", "reminder_music") or "reminder_music")
                        )
                        if _song:
                            await broadcast_proactive(
                                f"Em gửi thêm một bài nhắc nghỉ cho anh nè: {_song}. Nghe xong mình quay lại làm tiếp nhé.",
                                ai,
                            )

                    _last_break_remind_ts = now_ts

                # Lên mốc kế tiếp theo bội số interval kể từ đầu phiên.
                if _work_session_start_ts:
                    _next_break_remind_ts = _work_session_start_ts + ((_work_break_cycle_count + 1) * interval)

            # 1.6 Mood thấp -> tự mở playlist YouTube thư giãn (có cooldown)
            await _maybe_open_mood_playlist(ai, now_ts)
            
            # 2. Proactive theo khung giờ (sáng/trưa/tối) + hormone hint
            await _maybe_send_contextual_care_prompt(ai, now_ts, idle_sec)

            # 2.1 Lời hứa nghỉ ngơi: đến hạn thì nhắc 30 phút/lần và tăng cấp dỗi
            await _maybe_run_promise_timer(ai, now_ts)

            # 3. Tổng kết tuần vào tối Chủ nhật (1 lần/tuần)
            lt = time.localtime(now_ts)
            week_key = f"{lt.tm_year}-W{lt.tm_yday // 7}"
            if lt.tm_wday == 6 and lt.tm_hour >= 20 and _last_weekly_summary_key != week_key:
                try:
                    cur_path = os.path.join(ROOT, "data", "schedule.json")
                    prev_path = os.path.join(ROOT, "data", "schedule_prev.json")
                    cur = json.load(open(cur_path, "r", encoding="utf-8")) if os.path.exists(cur_path) else {}
                    prev = json.load(open(prev_path, "r", encoding="utf-8")) if os.path.exists(prev_path) else {}
                    summary = build_weekly_detail_summary(cur, prev)
                    await broadcast_proactive(summary, ai)
                except Exception:
                    pass
                _last_weekly_summary_key = week_key
                    
            # 4. PentaKuruV4 health check & command sync (Cloudflare integration)
            if get("enable_penta_kuru_integration"):
                kuru_health = await _check_penta_kuru_health()
                if kuru_health:
                    await _sync_commands_to_penta_kuru()
                
        except Exception as e:
            log.error(f"Proactive task error: {e}")
        await asyncio.sleep(60)

async def safe_send_json(ws, data):
    try: await ws.send_json(data); return True
    except: return False


_STREAM_HEAD_NOISE_RE = re.compile(
    r"^(?:\s)*(?:assistant|bot|ai|penta\s*mi|pentami|senpai|nè|nha|ê)(?:\s*[:,-]+\s*|\s+)",
    re.IGNORECASE,
)


def _sanitize_stream_head_text(text: str) -> str:
    t = str(text or "")
    if not t:
        return ""
    t = _STREAM_HEAD_NOISE_RE.sub("", t, count=1)
    t = re.sub(r"\btôts\b", "tốt", t, flags=re.IGNORECASE)
    t = re.sub(r"\btôt\b", "tốt", t, flags=re.IGNORECASE)
    return t


async def _stream_pentami_tokens(ws: WebSocket, pm, text: str, timeout_sec: float = 55.0) -> tuple[str, bool, str]:
    loop = asyncio.get_running_loop()
    token_queue: asyncio.Queue = asyncio.Queue()
    started_at = time.perf_counter()

    def _worker() -> None:
        try:
            for token in pm.chat_stream(text):
                loop.call_soon_threadsafe(token_queue.put_nowait, ("token", token))
            route = "bonsai"
            if hasattr(pm, "get_last_route"):
                try:
                    route = str(pm.get_last_route() or "bonsai")
                except Exception:
                    route = "bonsai"
            loop.call_soon_threadsafe(token_queue.put_nowait, ("done", route))
        except Exception as exc:
            loop.call_soon_threadsafe(token_queue.put_nowait, ("error", str(exc)))

    threading.Thread(target=_worker, daemon=True, name="pentami-ws-stream").start()

    parts: List[str] = []
    head_buffer = ""
    head_token_count = 0
    head_flushed = False
    while True:
        remaining = timeout_sec - (time.perf_counter() - started_at)
        if remaining <= 0:
            route = "bonsai"
            if hasattr(pm, "get_last_route"):
                try:
                    route = str(pm.get_last_route() or "bonsai")
                except Exception:
                    route = "bonsai"
            return "".join(parts).strip(), True, route

        try:
            item_type, payload = await asyncio.wait_for(token_queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            route = "bonsai"
            if hasattr(pm, "get_last_route"):
                try:
                    route = str(pm.get_last_route() or "bonsai")
                except Exception:
                    route = "bonsai"
            return "".join(parts).strip(), True, route

        if item_type == "token":
            token = str(payload or "")
            if not token:
                continue

            if not head_flushed:
                head_buffer += token
                head_token_count += 1
                should_flush = (
                    len(head_buffer) >= 80
                    or head_token_count >= 8
                    or bool(re.search(r"[.!?\n]", head_buffer))
                )
                if not should_flush:
                    continue

                cleaned_head = _sanitize_stream_head_text(head_buffer)
                head_flushed = True
                if cleaned_head:
                    parts.append(cleaned_head)
                    await safe_send_json(ws, {
                        "type": "token",
                        "text": cleaned_head,
                        "pipeline": "pentami_stream",
                    })
                continue

            parts.append(token)
            await safe_send_json(ws, {
                "type": "token",
                "text": token,
                "pipeline": "pentami_stream",
            })
            continue

        if item_type == "done":
            if not head_flushed and head_buffer:
                cleaned_head = _sanitize_stream_head_text(head_buffer)
                if cleaned_head:
                    parts.append(cleaned_head)
                    await safe_send_json(ws, {
                        "type": "token",
                        "text": cleaned_head,
                        "pipeline": "pentami_stream",
                    })
            route = str(payload or "bonsai")
            return "".join(parts).strip(), False, route

        if item_type == "error":
            log.warning(f"[PentaMi] stream worker error: {payload}")
            if not head_flushed and head_buffer:
                cleaned_head = _sanitize_stream_head_text(head_buffer)
                if cleaned_head:
                    parts.append(cleaned_head)
            route = "bonsai"
            if hasattr(pm, "get_last_route"):
                try:
                    route = str(pm.get_last_route() or "bonsai")
                except Exception:
                    route = "bonsai"
            return "".join(parts).strip(), False, route

        route = "bonsai"
        if hasattr(pm, "get_last_route"):
            try:
                route = str(pm.get_last_route() or "bonsai")
            except Exception:
                route = "bonsai"
        return "".join(parts).strip(), False, route

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    global _last_user_interaction_ts, _work_session_start_ts, _session_lang
    global _penta_wiki_mode, _pentami_mode, _pentami_thinking_mode
    global _server_sleep_mode, _server_sleep_started_ts, _next_break_remind_ts
    global _work_break_cycle_count, _auto_sleep_after_work_triggered
    await ws.accept()
    # ── Token auth (critical: check before any data is processed) ────────────
    _ws_token = ws.query_params.get("token", "")
    if _ws_token != get("auth_token"):
        log.warning(f"🚫 WS Auth rejected from {ws.client.host if ws.client else '?'}")
        await ws.close(code=4001, reason="Unauthorized")
        return
    ai = init_ai()
    _active_ws.add(ws)
    client_addr = ws.client.host if ws.client else "127.0.0.1"
    # Phone client = kết nối từ ngoài localhost (Tailscale IP, LAN IP, …)
    _LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
    is_phone = client_addr.strip() not in _LOOPBACK
    _active_ws_meta[ws] = {"is_phone": is_phone, "addr": client_addr}
    log.info(f"🔌 WS Client: {client_addr} ({'phone' if is_phone else 'cli'})")

    if is_phone and _proactive_phone_backlog:
        for item in list(_proactive_phone_backlog):
            _txt = str(item.get("text", "")).strip()
            if not _txt:
                continue
            await safe_send_json(ws, {
                "type": "response",
                "text": _txt,
                "ai_latency_ms": 0,
                "pipeline": "proactive_backlog",
            })
        _proactive_phone_backlog.clear()

    try:
        while True:
            msg = await ws.receive_text()
            raw = json.loads(msg)
            text = raw.get("text", "").strip()
            if not text: continue

            now_ts = time.time()

            if _match_special_cmd(text, "penta_off_command", "pentaoff"):
                await safe_send_json(ws, {
                    "type": "response",
                    "text": "Đã nhận lệnh PentaOff. Em sẽ tắt server ngay bây giờ.",
                    "ai_latency_ms": 0,
                    "pipeline": "system_poweroff",
                })
                _schedule_server_shutdown(0.9)
                continue

            if _match_special_cmd(text, "penta_sleep_command", "pentasleep"):
                if not _server_sleep_mode:
                    _server_sleep_mode = True
                    _server_sleep_started_ts = now_ts
                    await safe_send_json(ws, {
                        "type": "response",
                        "text": "Đã vào PentaSleep. Em tạm ngủ và sẽ bỏ qua mọi câu cho tới khi anh gọi 'pentami'.",
                        "ai_latency_ms": 0,
                        "pipeline": "system_sleep_on",
                    })
                else:
                    await safe_send_json(ws, {
                        "type": "response",
                        "text": "Em đang ở PentaSleep rồi nè anh.",
                        "ai_latency_ms": 0,
                        "pipeline": "system_sleep_on",
                    })
                continue

            if _server_sleep_mode:
                _wake_norm = str(text or "").strip().lower().replace(" ", "")
                # Chấp nhận: "pentami", "pentamion", "bật pentami", "bat pentami"
                is_wake = (_match_special_cmd(text, "penta_wake_command", "pentami") or 
                           _wake_norm in {"pentamion", "pentami", "bậtpentami", "batpentami"})
                if is_wake:
                    _server_sleep_mode = False
                    _server_sleep_started_ts = 0.0
                    # Wake = bắt đầu một phiên làm việc mới, reset nhịp 2/4/6... và auto-sleep flag.
                    _work_session_start_ts = now_ts
                    _work_break_cycle_count = 0
                    _auto_sleep_after_work_triggered = False
                    interval = float(get("proactive_break_remind_interval_sec", 7200))
                    _next_break_remind_ts = now_ts + max(300.0, interval)
                    await safe_send_json(ws, {
                        "type": "response",
                        "text": "Em đã thức dậy từ PentaSleep rồi nha anh. Mình tiếp tục bình thường nhé.",
                        "ai_latency_ms": 0,
                        "pipeline": "system_sleep_off",
                    })
                else:
                    await safe_send_json(ws, {
                        "type": "response",
                        "text": "Em đang ngủ (PentaSleep). Anh nhắn 'pentami' để đánh thức em nha.",
                        "ai_latency_ms": 0,
                        "pipeline": "system_sleep_blocked",
                    })
                continue

            # ── Idempotency dedup ────────────────────────────────────────────
            req_id = raw.get("request_id", "")
            if req_id:
                # Purge expired entries
                expired = [k for k, v in _seen_request_ids.items() if now_ts - v > _IDEMPOTENCY_TTL]
                for k in expired:
                    del _seen_request_ids[k]
                if req_id in _seen_request_ids:
                    log.info(f"[Idempotency] Duplicate request_id={req_id!r} — skipped")
                    await safe_send_json(ws, {"type": "duplicate", "request_id": req_id})
                    continue
                _seen_request_ids[req_id] = now_ts

            _last_user_interaction_ts = now_ts
            _init_work_session_timer(now_ts)

            # Cho phép client tự khai báo source="phone" để override IP detection
            if raw.get("source") == "phone" and not _active_ws_meta[ws]["is_phone"]:
                _active_ws_meta[ws]["is_phone"] = True

            speed = float(raw.get("speed", 1.0)); speaker = raw.get("speaker") or str(get("chat_speaker", "NF")).strip() or "NF"; use_tts = raw.get("tts", True)
            mode = raw.get("mode", "chat")

            # Auto-route CMD đã tắt: mode chỉ chuyển khi người dùng bật toggle/kéo sang CMD.

            # ── Backpressure guard ───────────────────────────────────────────
            _sem_acquired = False
            try:
                await asyncio.wait_for(_ai_semaphore.acquire(), timeout=5.0)
                _sem_acquired = True
            except asyncio.TimeoutError:
                await safe_send_json(ws, {
                    "type": "error",
                    "text": "Hệ thống đang bận, anh/chị vui lòng thử lại sau nhé.",
                })
                continue

            t0 = time.perf_counter()
            resp_text = ""
            pipeline = "unknown"
            _suppress_immediate_reply = False
            _wiki_related: List[str] = []

            try:
                if mode == "cmd":
                    log.info(f"🛠️ [Mode: Cmd] Processing: {text}")
                    if not looks_like_command(text):
                        resp_text = random.choice(_CMD_NOTLIKE_POOL)
                        pipeline = "cmd_brief"
                    else:
                        from API_local.ollama_command import get_default_interpreter
                        interp = get_default_interpreter()

                        _ai_prn  = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                        _usr_prn = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                   getattr(getattr(ai, "profile", None), "pronoun", "anh")

                        # Thiết lập callback thông báo khi Bonsai được kích hoạt
                        _loop = asyncio.get_event_loop()
                        def _on_bonsai_upgrade():
                            coro = safe_send_json(ws, {
                                "type": "response",
                                "text": f"{_ai_prn.capitalize()} đang dùng suy luận nâng cao (Bonsai) để phân tích lệnh này, chờ {_ai_prn} một chút nhé...",
                                "ai_latency_ms": 0,
                                "pipeline": "cmd_bonsai_thinking",
                            })
                            asyncio.run_coroutine_threadsafe(coro, _loop)
                        interp.bonsai_notify_cb = _on_bonsai_upgrade

                        # Gửi xác nhận nhận lệnh trước khi chạy
                        _ack_tmpl = random.choice(_CMD_RECEIVED_POOL)
                        _ack_text = _ack_tmpl.format(
                            prn=_ai_prn,
                            prn_cap=_ai_prn.capitalize(),
                            usr=_usr_prn,
                        )
                        await safe_send_json(ws, {
                            "type": "response",
                            "text": _ack_text,
                            "ai_latency_ms": 0,
                            "pipeline": "cmd_received",
                        })

                        # Chạy interpret trong executor để không chặn event loop
                        cmd_res = await asyncio.get_event_loop().run_in_executor(
                            None, interp.interpret, text
                        )
                        interp.bonsai_notify_cb = None  # Dọn callback sau khi dùng

                        # ── Track successful commands for Kuru sync ──────────────
                        if cmd_res.get("action") and not cmd_res.get("error"):
                            _recent_successful_commands.append({
                                "action": str(cmd_res.get("action", "")),
                                "target": str(cmd_res.get("target", "")),
                                "query": str(cmd_res.get("query", ""))
                            })
                            if len(_recent_successful_commands) > 100:
                                _recent_successful_commands.pop(0)

                        # ── Special handler: setup action → Tuya power control ──────────────
                        # PRIMARY: Check original user text for clear power + device intent (catches parsing errors)
                        user_text_lower = text.lower()
                        power_keywords_off = {"tắt", "tat", "shutdown", "off", "power off"}
                        power_keywords_on = {"bật", "bat", "startup", "on", "power on"}
                        device_keywords = {"pc", "may", "máy", "máy tính", "may tinh", "computer", "nguồn", "nguon", "power"}
                        
                        has_clear_off_intent = any(kw in user_text_lower for kw in power_keywords_off) and any(kw in user_text_lower for kw in device_keywords)
                        has_clear_on_intent = any(kw in user_text_lower for kw in power_keywords_on) and any(kw in user_text_lower for kw in device_keywords)
                        
                        # Execute power control immediately when intent is clear.
                        # This avoids bad LLM parses (e.g. "Tắt PC" -> setup volume 0) falling through to Tailscale.
                        should_handle_power = (has_clear_off_intent or has_clear_on_intent) and get("tuya_device_id") and get("tuya_ip")
                        
                        if should_handle_power:
                            try:
                                outlet = get_outlet()
                                if has_clear_off_intent:
                                    outlet.turn_off()
                                    resp_text = f"{_ai_prn.capitalize()} đã tắt ổ điện rồi nha {_usr_prn}. PC sẽ tắt trong vài giây."
                                    pipeline = "cmd_tuya_off"
                                    log.info(f"✅ [Tuya] Turned off outlet successfully for: {text}")
                                elif has_clear_on_intent:
                                    outlet.turn_on()
                                    resp_text = f"{_ai_prn.capitalize()} đã bật ổ điện rồi nha {_usr_prn}. PC sẽ khởi động trong vài giây."
                                    pipeline = "cmd_tuya_on"
                                    log.info(f"✅ [Tuya] Turned on outlet successfully for: {text}")
                                else:
                                    # Should not reach here
                                    raise Exception("Unknown power intent")
                                
                                await safe_send_json(ws, {
                                    "type": "response",
                                    "text": resp_text,
                                    "ai_latency_ms": int((time.perf_counter() - t0) * 1000),
                                    "pipeline": pipeline,
                                })
                                if use_tts:
                                    await speak(resp_text, speaker=speaker, speed=speed, lang=_session_lang)
                                continue
                            except Exception as e:
                                log.error(f"❌ [Tuya] Failed to control outlet: {e}")
                                resp_text = f"{_ai_prn.capitalize()} không {'tắt' if has_clear_off_intent else 'bật'} được ổ điện {_usr_prn} ơi. Kiểm tra cấu hình Tuya xem sao."
                                await safe_send_json(ws, {
                                    "type": "response",
                                    "text": resp_text,
                                    "ai_latency_ms": int((time.perf_counter() - t0) * 1000),
                                    "pipeline": "cmd_tuya_fail",
                                })
                                if use_tts:
                                    await speak(resp_text, speaker=speaker, speed=speed, lang=_session_lang)
                                continue

                        payload = _map_ollama_to_windows_payload(cmd_res)
                        
                        _deferred_play_payload = None  # reset mỗi lượt
                        _local_play_sub = payload.get("_local_play", "")
                        if payload["cmd"] or payload["script"] or _local_play_sub:
                            if _local_play_sub:
                                # Phát nhạc nội bộ (Mac) — hoãn sang sau TTS để không đè nhau
                                _deferred_play_payload = {"_local_play": _local_play_sub}
                                win_res = {"ok": True, "deferred": True}
                            elif bool(payload.get("_is_play")):
                                # Legacy: Windows play hoãn
                                _deferred_play_payload = payload
                                win_res = {"ok": True, "deferred": True}
                            else:
                                win_res = await send_to_windows(cmd=payload["cmd"], script=payload["script"])
                            # Dùng câu xác nhận tự nhiên thay vì đọc URL/path thô
                            resp_text = _build_cmd_ack_text(cmd_res, _ai_prn, _usr_prn)
                            if not win_res.get("ok"):
                                _err_hint = str(win_res.get("error", ""))
                                if "chưa được cấu hình" in _err_hint or "pc_tailscale_ip" in _err_hint:
                                    resp_text = (
                                        f"PC chưa được cấu hình {_ai_prn} ơi. "
                                        f"{_ai_prn.capitalize()} cần đặt địa chỉ IP Windows trong ⚙ System → pc_tailscale_ip nhé!"
                                    )
                                else:
                                    resp_text = random.choice(_CMD_WIN_FAIL_POOL)
                            pipeline = "cmd_ollama"
                        else:
                            _deferred_play_payload = None
                            action_hint = str(cmd_res.get("action", "")).strip()
                            _cmd_err   = str(cmd_res.get("error", "")).lower()
                            if "ollama" in _cmd_err or "timeout" in _cmd_err or "không phản hồi" in _cmd_err:
                                resp_text = (
                                    f"{_ai_prn.capitalize()} không diễn giải được lệnh vì Ollama đang offline. "
                                    f"{_usr_prn} kiểm tra Ollama chạy chưa rồi thử lại nhé!"
                                )
                            elif action_hint:
                                resp_text = random.choice(_CMD_CANT_EXEC_POOL)
                            else:
                                resp_text = random.choice(_CMD_NOTLIKE_POOL)
                            pipeline = "cmd_brief"
                else:
                    _deferred_play_payload = None
                    promise_reply = _handle_promise_user_message(text, now_ts)
                    if promise_reply:
                        resp_text = promise_reply
                        pipeline = "chat_promise"
                        pass

                    # ── Skill dispatch ────────────────────────────────────────
                    if pipeline == "unknown" and _SKILL_MANAGER:
                        _sk_ctx = {
                            "lang":       _session_lang,
                            "ai_pronoun": getattr(getattr(ai, "profile", None), "ai_pronoun", "em"),
                            "user_call":  (
                                getattr(getattr(ai, "profile", None), "user_call", "")
                                or getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            ),
                        }
                        _sk_res = _SKILL_MANAGER.dispatch(text, context=_sk_ctx)
                        if _sk_res:
                            resp_text = _sk_res["response"]
                            pipeline  = _sk_res.get("pipeline", "skill")
                            _meta = _sk_res.get("meta", {}) if isinstance(_sk_res, dict) else {}
                            _action = str(_meta.get("action", "")).strip().lower()
                            _detail = _meta.get("action_detail", {}) if isinstance(_meta, dict) else {}

                            # Execute side-effects for Gmail notification skill.
                            if _action == "enable":
                                cfg = get_full_config()
                                cfg["gmail_notification_enabled"] = True
                                save_config(cfg)
                            elif _action == "disable":
                                cfg = get_full_config()
                                cfg["gmail_notification_enabled"] = False
                                save_config(cfg)
                            elif _action == "check":
                                if _gmail_daemon:
                                    _q = _gmail_daemon.get_queue()
                                    if _q:
                                        _count = len(_q)
                                        _first = _q[0]
                                        _nick = _first.get("nickname", "người gửi")
                                        _subj = _first.get("subject", "(không tiêu đề)")
                                        resp_text = (
                                            f"Anh đang có {_count} email chờ xử lý. "
                                            f"Email đầu tiên từ {_nick}: {_subj}. "
                                            "Anh muốn em đọc ngay không?"
                                        )
                                    else:
                                        resp_text = "Hiện chưa có email nào trong hàng đợi Gmail notification."
                                else:
                                    resp_text = "Gmail notification daemon chưa sẵn sàng."
                            elif _action == "response":
                                if _gmail_daemon:
                                    _resp = str(_detail.get("user_response", "")).lower()
                                    _ok = _gmail_daemon.set_user_response("", _resp)
                                    if not _ok:
                                        resp_text = "Hiện chưa có thông báo email nào đang chờ xác nhận để em xử lý."
                                    else:
                                        # Với YES: daemon sẽ broadcast nội dung mail ngay,
                                        # nên bỏ câu trả lời trung gian để tránh cảm giác 2 câu chồng nhau.
                                        if _resp in {"yes", "có", "1", "true"}:
                                            _suppress_immediate_reply = True
                                else:
                                    resp_text = "Gmail notification daemon chưa sẵn sàng."
                            elif _action == "clear":
                                if _gmail_daemon:
                                    _n = _gmail_daemon.clear_queue()
                                    resp_text = f"Em đã xóa {_n} thông báo Gmail khỏi hàng đợi."
                                else:
                                    resp_text = "Gmail notification daemon chưa sẵn sàng."

                    s_state = _schedule_setup_state.setdefault(ws, {"active": False, "draft": empty_week_schedule(), "off_topic_hits": 0, "has_draft": False})

                    if pipeline != "unknown":
                        pass
                    elif pipeline == "chat_promise":
                        pass
                    elif (not s_state.get("active")) and is_schedule_resume(text) and s_state.get("has_draft"):
                        s_state["active"] = True
                        s_state["off_topic_hits"] = 0
                        resp_text = (
                            f"Mình tiếp tục lịch nha anh. Bản nháp hiện tại: {schedule_brief(normalize_schedule_payload(s_state.get('draft', {})))}. "
                            "Anh bổ sung thêm ngày nào nữa nhé."
                        )
                        pipeline = "chat_schedule_resume"
                    elif (not s_state.get("active")) and is_schedule_resume(text):
                        resp_text = "Hiện chưa có bản nháp lịch để tiếp tục. Anh nói 'sắp lịch cho anh' để bắt đầu mới nha."
                        pipeline = "chat_schedule_resume"

                    elif s_state.get("active"):
                        handled_active_control = False
                        if is_schedule_exit(text):
                            s_state["active"] = False
                            s_state["has_draft"] = True
                            resp_text = "Dạ em đã tạm dừng chế độ xếp lịch và giữ lại bản nháp. Khi cần anh nói 'tiếp tục lịch' nhé."
                            pipeline = "chat_schedule_pause"
                            handled_active_control = True
                        elif is_likely_offtopic_for_schedule(text):
                            lang_hint = detect_language(text)
                            s_state["off_topic_hits"] = int(s_state.get("off_topic_hits", 0)) + 1
                            if s_state["off_topic_hits"] >= 2:
                                s_state["active"] = False
                                s_state["has_draft"] = True
                                resp_text = pick_schedule_flow_prompt("pause_auto", lang_hint)
                                pipeline = "chat_schedule_pause_auto"
                            else:
                                resp_text = pick_schedule_flow_prompt("guard", lang_hint)
                                pipeline = "chat_schedule_guard"
                            handled_active_control = True
                        elif is_schedule_resume(text):
                            s_state["off_topic_hits"] = 0
                            resp_text = "Mình đang ở chế độ xếp lịch rồi nè anh, anh thêm nội dung tiếp giúp em nhé."
                            pipeline = "chat_schedule_guard"
                            handled_active_control = True

                        if handled_active_control:
                            pass
                        elif is_schedule_done(text):
                            schedule_data = normalize_schedule_payload(s_state.get("draft", {}))
                            _save_week_schedule(schedule_data)
                            s_state["active"] = False
                            s_state["has_draft"] = False
                            s_state["off_topic_hits"] = 0
                            resp_text = f"Dạ em đã lưu lịch tuần cho anh: {schedule_brief(schedule_data)}"
                            pipeline = "chat_schedule_finalize"
                        elif is_schedule_empty(text):
                            schedule_data = empty_week_schedule()
                            s_state["draft"] = schedule_data
                            _save_week_schedule(schedule_data)
                            s_state["active"] = False
                            s_state["has_draft"] = False
                            s_state["off_topic_hits"] = 0
                            resp_text = "Dạ em đã đặt lịch tuần về trạng thái trống hết rồi ạ."
                            pipeline = "chat_schedule_finalize"
                        else:
                            updates = extract_schedule_updates(text)
                            if not updates:
                                llm_parsed = _parse_schedule_with_local_ollama(text)
                                updates = {k: v for k, v in llm_parsed.items() if str(v).strip()}

                            if updates:
                                merged = merge_schedule(s_state.get("draft", {}), updates)
                                s_state["draft"] = merged
                                s_state["has_draft"] = True
                                s_state["off_topic_hits"] = 0
                                resp_text = (
                                    f"Em đã ghi: {summarize_updates(updates)}. "
                                    "Anh thêm ngày khác nữa không, hoặc nói 'được rồi em' để em lưu lịch."
                                )
                                pipeline = "chat_schedule_collect"
                            else:
                                resp_text = (
                                    "Em chưa tách được ngày cụ thể. Anh nói kiểu 'Thứ 2 ...; Thứ 3 ...' giúp em nha. "
                                    "Khi xong anh nói 'được rồi em'."
                                )
                                pipeline = "chat_schedule_collect"
                    else:
                        day_key = detect_day_query(text)
                        if day_key:
                            schedule_data = _load_week_schedule()
                            resp_text = schedule_day_answer(schedule_data, day_key)
                            pipeline = "chat_schedule_query_day"
                        elif is_schedule_query(text):
                            schedule_data = _load_week_schedule()
                            resp_text = schedule_week_answer(schedule_data)
                            pipeline = "chat_schedule_query_week"
                        elif is_schedule_setup_trigger(text):
                            s_state["active"] = True
                            s_state["draft"] = _load_week_schedule()
                            s_state["has_draft"] = True
                            s_state["off_topic_hits"] = 0
                            resp_text = random.choice(_SCHEDULE_PROMPTS) + " Khi xong anh nói 'được rồi em' để em lưu."
                            pipeline = "chat_schedule_prompt"

                        # ── PentaWiki toggle ────────────────────────────────────
                        elif _WIKI_AVAILABLE and _wiki_check_toggle(text):
                            _wiki_action = _wiki_check_toggle(text)
                            _ai_prn_wt   = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                            _usr_prn_wt  = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                           getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            _lang_labels = {"vi": "tiếng Việt", "en": "tiếng Anh", "ja": "tiếng Nhật"}
                            if _wiki_action == "on":
                                _penta_wiki_mode = True
                                _save_penta_state()
                                _ll = _lang_labels.get(_session_lang, "tiếng Việt")
                                resp_text = (
                                    f"{_ai_prn_wt.capitalize()} đã bật PentaWiki rồi nha {_usr_prn_wt}! "
                                    f"{_ai_prn_wt.capitalize()} sẽ dùng Wikipedia ({_ll}) để tra cứu cho {_usr_prn_wt} đó. "
                                    f"{_usr_prn_wt} hỏi gì {_ai_prn_wt} tra ngay nhé!"
                                )
                            else:
                                _penta_wiki_mode = False
                                _save_penta_state()
                                resp_text = (
                                    f"PentaWiki đã tắt rồi nha {_usr_prn_wt}! "
                                    f"{_ai_prn_wt.capitalize()} quay về chế độ chat thường nhé."
                                )
                            pipeline = "wiki_toggle"

                        # ── Language toggle ─────────────────────────────────────
                        elif _lang_check_toggle(text):
                            _new_lang    = _lang_check_toggle(text)
                            _ai_prn_lt   = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                            _usr_prn_lt  = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                           getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            _session_lang = _new_lang
                            _save_penta_state()
                            _lang_confirms = {
                                "vi": f"{_ai_prn_lt.capitalize()} chuyển về tiếng Việt rồi nha {_usr_prn_lt}! Mình nói chuyện tiếng Việt thôi nhé.",
                                "en": f"Switched to English mode! I'll reply in English from now on, {_usr_prn_lt}. Feel free to chat!",
                                "ja": f"日本語モードに切り替えました！これからは日本語でお答えしますよ、{_usr_prn_lt}さん。どうぞよろしくお願いします！",
                            }
                            resp_text = _lang_confirms.get(_new_lang, _lang_confirms["vi"])
                            pipeline = "lang_toggle"

                        # ── PentaWiki query ─────────────────────────────────────
                        elif _penta_wiki_mode and _WIKI_AVAILABLE and (_wiki_is_query(text) or _is_wiki_like_query(text)):
                            _ai_prn_wq  = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                            _usr_prn_wq = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                          getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            # Thông báo đang tra cứu
                            _seek_msgs = {
                                "vi": f"{_ai_prn_wq.capitalize()} đang tra sách, {_usr_prn_wq} đợi {_ai_prn_wq} nhé...",
                                "en": f"Let me look that up for you, {_usr_prn_wq}...",
                                "ja": f"調べていますので、少々お待ちください...",
                            }
                            await safe_send_json(ws, {
                                "type": "response",
                                "text": _seek_msgs.get(_session_lang, _seek_msgs["vi"]),
                                "ai_latency_ms": 0,
                                "pipeline": "wiki_searching",
                            })
                            _wiki_ollama_url   = get("ollama_url", "http://localhost:11434")
                            _wiki_ollama_model = get("ollama_local_schedule_model", "llama3.2:1b")
                            _wiki_res  = await asyncio.get_event_loop().run_in_executor(
                                None, lambda: _wiki_fetch(
                                    text, _session_lang,
                                    _wiki_ollama_url, _wiki_ollama_model
                                )
                            )
                            resp_text = _wiki_format(_wiki_res, _session_lang, _ai_prn_wq, _usr_prn_wq)
                            if _wiki_res.get("ok"):
                                resp_text = await _rewrite_wiki_answer_with_ollama(
                                    question=text,
                                    wiki_answer=resp_text,
                                    lang=_session_lang,
                                    ai=ai,
                                )
                            # Nếu không tìm thấy → dùng thông báo không found, KHÔNG fallback ai.chat
                            pipeline = "wiki_result"
                            # Gắn danh sách chủ đề liên quan vào pipeline tag để WS gửi xuống client
                            _wiki_related = _wiki_res.get("related", []) if _wiki_res.get("ok") else []

                        # ── PentaMi mode ───────────────────────────────────────
                        elif _PENTAMI_AVAILABLE and _pentami_check_toggle(text):
                            toggle_action = _pentami_check_toggle(text)
                            pm = get_pentami_chat()
                            _ai_pronoun = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                            _user_call  = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                          getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            if toggle_action == "on":
                                _pentami_mode = True
                                _pentami_thinking_mode = False
                                if hasattr(pm, "set_bonsai_thinking_mode"):
                                    pm.set_bonsai_thinking_mode(False)
                                pm._bonsai.set_keepalive(False)
                                pm._bonsai.set_sleep_notify(None)
                                resp_text = (
                                    f"Chế độ PentaMi đã bật rồi nha {_user_call}! "
                                    f"{_ai_pronoun.capitalize()} đây, "
                                    f"{_user_call} muốn tâm sự gì không nào?"
                                )
                            elif toggle_action == "on_thinking":
                                _pentami_mode = True
                                _pentami_thinking_mode = True
                                if hasattr(pm, "set_bonsai_thinking_mode"):
                                    pm.set_bonsai_thinking_mode(True)
                                pm._bonsai.set_keepalive(True)
                                def _bonsai_sleep_notify(msg: str):
                                    asyncio.run_coroutine_threadsafe(
                                        broadcast_proactive(msg, init_ai()),
                                        asyncio.get_event_loop(),
                                    )
                                pm._bonsai.set_sleep_notify(_bonsai_sleep_notify)
                                async def _prewarm():
                                    loop = asyncio.get_event_loop()
                                    ready = await loop.run_in_executor(None, pm._bonsai._ensure_awake)
                                    if not ready:
                                        log.warning("[PentaMiT] Pre-warm Bonsai thất bại")
                                asyncio.create_task(_prewarm())
                                resp_text = (
                                    f"Đã bật PentaMiT rồi nha {_user_call}! "
                                    f"{_ai_pronoun.capitalize()} sẽ tự dùng Bonsai cho câu khó/sâu để trả lời kỹ hơn."
                                )
                            elif toggle_action == "off_thinking":
                                _pentami_thinking_mode = False
                                if hasattr(pm, "set_bonsai_thinking_mode"):
                                    pm.set_bonsai_thinking_mode(False)
                                pm._bonsai.set_keepalive(False)
                                pm._bonsai.set_sleep_notify(None)
                                resp_text = (
                                    f"Đã tắt PentaMiT nha {_user_call}. "
                                    f"{_ai_pronoun.capitalize()} quay về trả lời nhanh bằng Ollama stream là chính."
                                )
                            elif toggle_action == "off":
                                _pentami_mode = False
                                _pentami_thinking_mode = False
                                if hasattr(pm, "set_bonsai_thinking_mode"):
                                    pm.set_bonsai_thinking_mode(False)
                                pm._bonsai.set_keepalive(False)
                                pm._bonsai.set_sleep_notify(None)
                                # Xoá context hội thoại khi tắt, giữ lại kiến thức đã học
                                pm.clear_context()
                                resp_text = (
                                    f"Chế độ PentaMi đã tắt nha {_user_call}. "
                                    f"{_ai_pronoun.capitalize()} đã lưu lại những gì đã học, "
                                    f"nhưng lịch sử trò chuyện thì đã xoá rồi nhé."
                                )
                            elif toggle_action == "clear":
                                pm.clear_context()
                                resp_text = (
                                    f"Xoá xong rồi ó! {_ai_pronoun.capitalize()} và "
                                    f"{_user_call} bắt đầu lại từ đầu nhé."
                                )
                            pipeline = "pentami_toggle"

                        elif _pentami_mode and _PENTAMI_AVAILABLE:
                            # PentaMi chat mode: dùng Bonsai-8B qua pentami_chat
                            pm = get_pentami_chat()
                            _ai_p = getattr(getattr(ai, "profile", None), "ai_pronoun", "em")
                            _u_p  = getattr(getattr(ai, "profile", None), "user_call", "") or \
                                    getattr(getattr(ai, "profile", None), "pronoun", "anh")
                            await safe_send_json(ws, {
                                "type": "response",
                                "text": f"{_ai_p.capitalize()} đang nghĩ câu trả lời cho {_u_p}, chờ {_ai_p} chút nha...",
                                "ai_latency_ms": 0,
                                "emotional_state": "normal",
                                "hormone_levels": {},
                                "pipeline": "pentami_thinking",
                            })
                            # Nếu Bonsai đang khởi động (chưa ready), báo người dùng trước
                            if _pentami_thinking_mode and (not pm._bonsai.is_available()):
                                if hasattr(pm._bonsai, "can_wake_now") and (not pm._bonsai.can_wake_now()):
                                    await safe_send_json(ws, {
                                        "type": "response",
                                        "text": f"{_ai_p.capitalize()} đang lỗi khởi động Bonsai nên tạm nghỉ thử lại một chút nha {_u_p}. Trong lúc này {_ai_p} vẫn sẽ cố trả lời bằng chế độ nhẹ.",
                                        "ai_latency_ms": 0,
                                        "emotional_state": "normal",
                                        "hormone_levels": {},
                                        "pipeline": "pentami_bonsai_retry_wait",
                                    })
                                else:
                                    await safe_send_json(ws, {
                                        "type": "response",
                                        "text": f"{_ai_p.capitalize()} đang thức dậy, {_ai_p} cần chút để khởi động GPU né, {_ai_p} sẽ trả lời ngay sau đó nhé...",
                                        "ai_latency_ms": 0,
                                        "emotional_state": "normal",
                                        "hormone_levels": {},
                                        "pipeline": "pentami_waking",
                                    })
                            try:
                                resp_text, _pentami_timed_out, _pentami_route = await _stream_pentami_tokens(
                                    ws,
                                    pm,
                                    text,
                                    timeout_sec=55.0,
                                )
                            except Exception as _pentami_stream_err:
                                log.warning(f"[PentaMi] stream failed, fallback to blocking chat: {_pentami_stream_err}")
                                resp_text = await asyncio.wait_for(
                                    asyncio.get_event_loop().run_in_executor(None, pm.chat, text),
                                    timeout=55.0,
                                )
                                _pentami_timed_out = False
                                _pentami_route = "bonsai"

                            if hasattr(pm, "postprocess_output") and resp_text.strip():
                                try:
                                    resp_text = pm.postprocess_output(resp_text)
                                except Exception:
                                    pass
                            if _pentami_timed_out:
                                resp_text = (
                                    f"{_ai_p.capitalize()} xin lỗi {_u_p}, "
                                    f"{_ai_p} suy nghĩ lâu quá mà chưa kịp — {_u_p} thử lại sau nhé!"
                                )
                            elif not resp_text.strip():
                                resp_text = (
                                    f"{_ai_p.capitalize()} chưa bật được Bonsai nên chưa phân tích sâu được câu này. "
                                    f"{_u_p} chờ {_ai_p} một chút rồi thử lại giúp {_ai_p} nha."
                                )
                            _route_map = {
                                "ollama_fast": "pentami_fast_ollama",
                                "ollama_fallback": "pentami_ollama_fallback",
                                "bonsai_fallback": "pentami_bonsai_fallback",
                                "bonsai": "pentami_bonsai",
                            }
                            pipeline = _route_map.get(str(_pentami_route), "pentami_bonsai")

                        else:
                            proactive_followup = await _maybe_reply_contextual_care(text, ai, now_ts)
                            if proactive_followup:
                                resp_text = proactive_followup
                                pipeline = "chat_proactive_followup"
                            else:
                                # Nếu đang ở chế độ ngôn ngữ khác tiếng Việt → dùng Ollama
                                if _session_lang != "vi":
                                    _lang_resp = await _chat_in_lang_async(text, _session_lang, ai)
                                    if _lang_resp:
                                        resp_text = _lang_resp
                                        pipeline  = f"chat_lang_{_session_lang}"
                                if not resp_text:
                                    # Chat mode: mặc định không dùng LLM fallback, chỉ bật khi config cho phép.
                                    if hasattr(ai, "enable_chat_llm_fallback"):
                                        ai.enable_chat_llm_fallback = bool(get("chat_use_llm_fallback", False))
                                    resp_text = await asyncio.get_event_loop().run_in_executor(None, ai.chat, text)
                                    cleaned_text, has_show_schedule = parse_show_schedule_token(resp_text)
                                    if has_show_schedule:
                                        schedule_data = _load_week_schedule()
                                        detail = schedule_week_answer(schedule_data)
                                        resp_text = f"{cleaned_text} {detail}".strip()
                                        pipeline = "chat_schedule_query_token"
                                    run_match = re.search(r'<RUN>(.*?)</RUN>', resp_text, re.IGNORECASE|re.DOTALL)
                                    if run_match:
                                        resp_text = re.sub(r'<RUN>.*?</RUN>', '', resp_text, flags=re.IGNORECASE|re.DOTALL).strip()
                                    if pipeline == "unknown":
                                        pipeline = "chat_core_llm" if bool(get("chat_use_llm_fallback", False)) else "chat_core"
            finally:
                if _sem_acquired:
                    _ai_semaphore.release()

            if _suppress_immediate_reply:
                continue

            if not resp_text:
                resp_text = "Dạ, em xong rồi ạ."
            resp_text = _enforce_profile_pronouns(resp_text, ai)
            resp_text = _repair_vi_pronoun_subjects(resp_text, ai)
            ai_ms = int((time.perf_counter() - t0) * 1000)

            em = ai.emotion.hormone.get_emotional_state() if hasattr(ai, 'emotion') else "normal"
            hl = ai.emotion.hormone.get() if hasattr(ai, 'emotion') else {}
            _ws_extra: dict = {}
            if pipeline == "wiki_result" and _wiki_related:
                _ws_extra["wiki_suggestions"] = _wiki_related
            await safe_send_json(ws, {
                "type": "response",
                "text": resp_text,
                "ai_latency_ms": ai_ms,
                "emotional_state": em,
                "hormone_levels": hl,
                "mode_used": mode,
                "pipeline": pipeline,
                **_ws_extra,
            })

            if use_tts:
                async with _tts_stream_lock:
                    # Strip URLs trước khi đọc TTS (URL không đọc được tự nhiên)
                    _tts_text = re.sub(r'https?://\S+', '', resp_text).strip()
                    sents = split_sentences(_tts_text)
                    await safe_send_json(ws, {"type": "tts_start", "total": len(sents)})
                    for i, s in enumerate(sents):
                        # TTS force_lang: ưu tiên theo pipeline → session language → auto-detect
                        if pipeline.startswith("pentami"):
                            fl = "vi"                          # PentaMi luôn tiếng Việt
                        elif pipeline in ("wiki_result", "lang_toggle") or pipeline.startswith("chat_lang_"):
                            fl = _session_lang                 # Wiki / lang mode → đúng ngôn ngữ
                        elif _session_lang != "vi":
                            fl = _session_lang                 # Toàn bộ phiên đang dùng ngôn ngữ khác
                        else:
                            fl = None                          # Auto-detect (default)
                        wav, is_edge = await synthesize_tts_by_language(s, speaker, speed, force_lang=fl)
                        # Nếu strict mode trả audio rỗng, retry non-strict để tránh mất nửa câu.
                        if not wav and bool(get("tts_strict_language_engine", True)):
                            log.warning(f"[TTS] Empty audio in strict mode, retry non-strict (sent={i + 1}/{len(sents)})")
                            wav, is_edge = await synthesize_tts_by_language(
                                s,
                                speaker,
                                speed,
                                force_lang=fl,
                                strict=False,
                            )
                        if wav:
                            await safe_send_json(ws, {
                                "type": "audio_chunk", "audio_b64": base64.b64encode(wav).decode(),
                                "mime_type": "audio/mpeg" if is_edge else "audio/wav"
                            })
                        else:
                            log.warning(f"[TTS] Skip sentence because audio is still empty (sent={i + 1}/{len(sents)})")
                    await safe_send_json(ws, {"type": "audio_end"})
                # Thực thi lệnh nhạc đã hoãn — sau khi TTS xong mới phát
                try:
                    if _deferred_play_payload:
                        _local_sub = _deferred_play_payload.get("_local_play")
                        if _local_sub:
                            # Phát nhạc nội bộ từ music/<subfolder>/
                            _play_music_subfolder(_local_sub)
                        elif _deferred_play_payload.get("cmd") or _deferred_play_payload.get("script"):
                            await send_to_windows(
                                cmd=_deferred_play_payload.get("cmd", ""),
                                script=_deferred_play_payload.get("script", ""),
                            )
                        _deferred_play_payload = None  # xóa sau khi dùng
                except NameError:
                    pass
    except WebSocketDisconnect:
        log.info(f"❌ WS Disconnected: {client_addr}")
    except Exception as e:
        log.error(f"WS Error: {e}")
    finally:
        _active_ws.discard(ws)
        _active_ws_meta.pop(ws, None)
        _schedule_setup_state.pop(ws, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
