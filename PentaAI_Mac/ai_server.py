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
from ollama_command import OllamaCommandInterpreter, get_default_interpreter

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
    "PentaMemory":          {"module": "penta_memory",                  "class": "PentaMemory",            "group": "optional"},
    "OllamaCommand":        {"module": "ollama_command",                "class": "OllamaCommandInterpreter","group": "optional"},
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
    "ollama_url": "http://localhost:11434", "ollama_model": "qwen3.5:cloud",
    "ollama_local_schedule_model": "llama3.2:1b",
    "ollama_cloud_url": "", "ollama_cloud_key": "", "ollama_cloud_model": "gpt-4o-mini",
    "proactive_idle_hormone_enabled": True,
    "proactive_idle_hormone_after_sec": 300,
    "proactive_break_remind_interval_sec": 7200,
    "proactive_speak_local_when_phone_offline": True,
    "proactive_vi_speaker": "NF",
    "proactive_vi_speed": 1.0,
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
    "proactive_mood_playlist_url": "https://www.youtube.com/watch?v=jfKfPfyJRdk",
    "pentakuru_sectors_path": ""
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f: return {**DEFAULT_CONFIG, **json.load(f)}
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=2, ensure_ascii=False)

# ── Runtime override layer (dùng bởi /admin/connect và /admin/reload_config) ──
# Keys trong dict này sẽ override file config.json mà không cần restart.
_runtime_overrides: Dict[str, Any] = {}

def get(key, default=None):
    # Runtime override takes priority over file config
    if key in _runtime_overrides:
        return _runtime_overrides[key]
    return load_config().get(key, default)

def get_action_executor() -> ActionExecutor:
    return ActionExecutor()

def _reload_runtime_config() -> None:
    """Reload runtime singletons affected by config changes without restarting server."""
    global _ollama_ready
    try:
        import ollama_command
        ollama_command._default_interpreter = None
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

# ─── AI & TTS Engines ──────────────────────────────────────────────
_ai_instance = None
_vv_engine = None
_valtec_tts = None
_ollama_ready = False
_proactive_task: Optional[asyncio.Task] = None
_last_user_interaction_ts: float = time.time()
_work_session_start_ts: Optional[float] = None
_last_break_remind_ts: float = 0.0
_last_weekly_summary_key: str = ""
_last_mood_playlist_ts: float = 0.0
_kuru_placeholder_warned: bool = False
_prompt_recent_history: Dict[str, List[str]] = {}
_prompt_cycle_state: Dict[str, Dict[str, Any]] = {}

# ── Idempotency journal ──────────────────────────────────────────────────────
# request_id → timestamp; giữ trong 30s để dedup khi client reconnect/retry
_seen_request_ids: Dict[str, float] = {}
_IDEMPOTENCY_TTL: float = 30.0

# ── Backpressure semaphore ────────────────────────────────────────────────────
# Tối đa 3 AI ops chạy song song; nếu hàng đợi đầy sau 5s → trả lỗi ngay
_ai_semaphore = asyncio.Semaphore(3)

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

def init_voicevox():
    global _vv_engine
    if _vv_engine is None:
        try:
            from voicevox_engine import VoicevoxEngine
            _vv_engine = VoicevoxEngine(os.path.join(ROOT, "tts_engine", "voicevox"))
            log.info("✅ Voicevox sẵn sàng")
        except: pass
    return _vv_engine

def init_valtec():
    global _valtec_tts
    if _valtec_tts is None:
        try:
            from valtec_server import ValtecEngine
            _valtec_tts = ValtecEngine()
            log.info("✅ Valtec sẵn sàng")
        except: pass
    return _valtec_tts

def check_ollama():
    global _ollama_ready
    try:
        r = requests.get(f"{get('ollama_url')}/api/tags", timeout=2)
        _ollama_ready = (r.status_code == 200)
    except: _ollama_ready = False
    return _ollama_ready

# ─── Audio Helpers ──────────────────────────────────────────────────
def resample_wav(wav_bytes: bytes, target_rate: int = 44100) -> bytes:
    try:
        if len(wav_bytes) < 44: return wav_bytes
        channels = struct.unpack('<H', wav_bytes[22:24])[0]
        sample_rate = struct.unpack('<I', wav_bytes[24:28])[0]
        bits_per_sample = struct.unpack('<H', wav_bytes[34:36])[0]
        if sample_rate == target_rate: return wav_bytes
        if bits_per_sample != 16: return wav_bytes
        offset = 12
        while offset + 8 <= len(wav_bytes):
            if wav_bytes[offset:offset+4] == b'data': break
            offset += 8 + struct.unpack('<I', wav_bytes[offset+4:offset+8])[0]
        else: return wav_bytes
        pcm = wav_bytes[offset+8:offset+8+struct.unpack('<I', wav_bytes[offset+4:offset+8])[0]]
        pcm, _ = audioop.ratecv(pcm, 2, channels, sample_rate, target_rate, None)
        header = bytearray(wav_bytes[:44])
        struct.pack_into('<I', header, 4, 36+len(pcm))
        struct.pack_into('<I', header, 24, target_rate)
        struct.pack_into('<I', header, 28, target_rate*channels*2)
        struct.pack_into('<I', header, 40, len(pcm))
        return bytes(header) + pcm
    except: return wav_bytes

async def generate_edge_tts_audio(text, voice="en-US-AvaNeural", rate=1.0):
    try:
        r_str = f"{int((rate-1)*100):+d}%"
        comm = edge_tts.Communicate(text, voice, rate=r_str)
        data = b""
        async for chunk in comm.stream():
            if chunk["type"] == "audio": data += chunk["data"]
        return data
    except Exception as e:
        log.error(f"Edge-TTS error: {e}"); return b""

async def generate_voicevox_audio(text, speed):
    try:
        from voicevox_engine import SynthParams
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: _vv_engine.get_audio(text, _vv_engine.scan_models()[0]["vvm"], SynthParams(speed=speed)))
        return resample_wav(raw)
    except: return b""

async def generate_valtec_audio(text, speaker, speed):
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: _valtec_tts._raw_synth(text, speaker, speed))
        return resample_wav(raw)
    except: return b""

_SENT_RE = re.compile(r'(?<=[.!?।。！？])\s+|(?<=\n)')
def split_sentences(text):
    return [p.strip() for p in _SENT_RE.split(text) if p.strip()]

def detect_language(text):
    txt = (text or "")
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', txt):
        return 'jp'
    lower = txt.lower()
    if re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', lower):
        return 'vi'
    if re.search(r'\b(anh|em|lich|lịch|thu|thứ|hom nay|hôm nay|duoc roi|được rồi|nha|nè|nhe)\b', lower):
        return 'vi'
    return 'en' if re.search(r'[a-zA-Z]', txt) else 'vi'


async def synthesize_tts_by_language(text: str, speaker: str, speed: float):
    """
    Routing rule mặc định:
      - VI -> Valtec
      - JP -> VoiceVox
      - EN -> EdgeTTS
    Nếu bật strict (`tts_strict_language_engine`), không fallback chéo engine.
    """
    lang = detect_language(text)
    strict = bool(get("tts_strict_language_engine", True))

    if lang == 'vi':
        if _valtec_tts:
            return await generate_valtec_audio(text, speaker, speed), False
        if strict:
            log.warning("[TTS] Bỏ qua câu VI vì Valtec chưa sẵn (strict mode)")
            return b"", False
        # Non-strict fallback (tắt strict bằng config nếu muốn)
        return await generate_edge_tts_audio(text, voice="vi-VN-HoaiMyNeural", rate=speed), True

    if lang == 'jp':
        if _vv_engine:
            return await generate_voicevox_audio(text, speed), False
        if strict:
            log.warning("[TTS] Bỏ qua câu JP vì VoiceVox chưa sẵn (strict mode)")
            return b"", False
        return await generate_edge_tts_audio(text, voice="ja-JP-NanamiNeural", rate=speed), True

    # EN default
    return await generate_edge_tts_audio(text, rate=speed), True

# ─── Control Helpers ───────────────────────────────────────────────
def get_outlet():
    return tinytuya.OutletDevice(get("tuya_device_id"), get("tuya_ip"), get("tuya_local_key"), float(get("tuya_version")))

def pc_ping():
    try: return subprocess.run(["ping", "-c", "1", "-W", "1", get("pc_tailscale_ip")], capture_output=True).returncode == 0
    except: return False

async def send_to_windows(cmd="", script=""):
    """Send command to Windows PC. Try Cloudflare first if available, fallback to direct Tailscale."""
    global _penta_kuru_cb_fails
    
    # ── Option 1: Try Cloudflare Tunnel (Kuru) if healthy ───────────────────
    if get("enable_penta_kuru_integration"):
        kuru_url = get("penta_kuru_cloudflare_url", "").strip()
        kuru_token = get("penta_kuru_token", "").strip()
        kuru_ok = await _check_penta_kuru_health()
        
        if kuru_ok and kuru_url and kuru_token:
            try:
                loop = asyncio.get_event_loop()
                headers = {"Authorization": f"Bearer {kuru_token}"}
                resp_func = lambda: requests.post(
                    f"{kuru_url}/run",
                    json={"cmd": cmd, "script": script},
                    headers=headers,
                    timeout=10
                )
                resp = await loop.run_in_executor(None, resp_func)
                result = resp.json()
                if result.get("ok"):
                    log.info("✅ Command executed via Cloudflare → Kuru")
                    _penta_kuru_cb_fails = 0
                    return result
                else:
                    _penta_kuru_cb_fails += 1
                    log.warning(f"⚠️ Kuru failed, trying direct. Fails: {_penta_kuru_cb_fails}")
            except Exception as e:
                _penta_kuru_cb_fails += 1
                log.warning(f"⚠️ Kuru unreachable ({_penta_kuru_cb_fails} fails): {e}")
    
    # ── Fallback: Direct Tailscale connection ────────────────────────────────
    url = f"http://{get('pc_tailscale_ip')}:{get('pc_api_port')}/run"
    headers = {"Authorization": f"Bearer {get('pc_auth_token')}"} if get('pc_auth_token') else {}
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: requests.post(url, json={"cmd": cmd, "script": script}, headers=headers, timeout=12))
        return resp.json()
    except Exception as e: return {"ok": False, "error": str(e)}

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
        platform = target.lower() if target else "google"
        tmpl = _WIN_SEARCH_URLS.get(platform, _WIN_SEARCH_URLS["google"])
        url = tmpl.format(urllib.parse.quote_plus(query or target))
        esc = url.replace('"', '`"')
        return {"cmd": f'Start-Process "{esc}"', "script": ""}

    # ── 4. play action → YouTube search ──────────────────────────────────────
    if action == "play":
        q = query or target
        url = _WIN_SEARCH_URLS["youtube"].format(urllib.parse.quote_plus(q))
        esc = url.replace('"', '`"')
        return {"cmd": f'Start-Process "{esc}"', "script": ""}

    # ── 5. run action → Start-Process app/exe ────────────────────────────────
    if action == "run":
        app = target or query
        if app:
            esc = app.replace('"', '`"')
            return {"cmd": f'Start-Process "{esc}"', "script": ""}

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
    global _proactive_task
    import atexit
    log.info("🚀 Warm-up Unified Server...")
    init_ai(); init_voicevox(); init_valtec(); check_ollama()
    # Chạy vòng proactive trong đúng event loop của ASGI server.
    _proactive_task = asyncio.create_task(proactive_background_task())
    def _save():
        if _ai_instance and hasattr(_ai_instance, 'emotion') and _ai_instance.emotion:
            _ai_instance.emotion.flush(); log.info("💾 Saved Hormone state")
    atexit.register(_save)
    yield
    if _proactive_task:
        _proactive_task.cancel()
        try:
            await _proactive_task
        except asyncio.CancelledError:
            pass
        _proactive_task = None
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
        "tts_vi": _valtec_tts is not None, "tts_jp": _vv_engine is not None,
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
    return {"status": "ok", "url": c.get("ollama_cloud_url",""), "model": c.get("ollama_cloud_model", "")}

@app.post("/api/config_cloud")
async def set_cloud(req: Request, token: str = Depends(verify_token)):
    d = await req.json(); c = load_config()
    for k in ["url", "key", "model"]: 
        if k in d: c[f"ollama_cloud_{k}"] = d[k]
    save_config(c); return {"status": "ok"}

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

@app.post("/api/ollama_command")
async def ollama_command_api(req: OllamaCommandRequest, execute: bool = False, token: str = Depends(verify_token)):
    from ollama_command import get_default_interpreter
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
    from ollama_command import get_default_interpreter
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


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN ENDPOINTS  — dùng bởi penta_ctl.py
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/status")
async def admin_status(token: str = Depends(verify_token)):
    """Full live stats: WS clients, circuit breakers, hormone, last interaction."""
    from ollama_command import get_default_interpreter
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

    from ollama_command import get_default_interpreter, OllamaCommandInterpreter
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
    from ollama_command import _default_interpreter
    import ollama_command as _oc
    _oc._default_interpreter = None  # force re-init next call

    return {
        "ok": True,
        "reloaded": True,
        "patch_applied": list(patch.keys()),
        "key_count": len(_runtime_overrides),
    }


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

    user_call = str(getattr(profile, "user_call", "") or getattr(profile, "pronoun", "bạn") or "bạn").strip()
    ai_pronoun = str(getattr(profile, "ai_pronoun", "mình") or "mình").strip()

    out = str(text)
    # Áp dụng cho các mẫu server hiện có vốn mặc định anh/em.
    out = re.sub(r"\banh\b", user_call, out, flags=re.IGNORECASE)
    out = re.sub(r"\bem\b", ai_pronoun, out, flags=re.IGNORECASE)
    out = re.sub(r"\bAnh\b", user_call.capitalize(), out)
    out = re.sub(r"\bEm\b", ai_pronoun.capitalize(), out)
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
    if not text or sys.platform != "darwin":
        return
    try:
        # Giới hạn độ dài để tránh block lâu nếu text quá dài.
        subprocess.run(["say", text[:280]], timeout=10)
    except Exception:
        pass


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
        "high_cortisol": ["Em thấy cortisol hơi cao, mình thở chậm vài nhịp nha anh."],
        "low_dopamine": ["Dopamine hơi thấp rồi anh, mình đổi gió một chút nè."],
        "low_serotonin": ["Serotonin xuống nhẹ đó anh, thử đi bộ ngắn cho thoáng nha."],
        "stable": ["Hormone đang khá ổn, mình giữ nhịp đều đều nha anh."],
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
        return "Dạ em tin anh thiệt rồi nè, giỏi lắm. Mình giữ nhịp nghỉ như vậy mỗi ngày nha."

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


def _compose_contextual_care_prompt(ai: Any, period: str) -> str:
    pool = _rules_list(["contextual_care_prompts", period], _PROACTIVE_PROMPT_RULES_FALLBACK["contextual_care_prompts"]["morning"])
    base = _pick_nonrepeat_prompt(f"care_{period}", pool)
    hint = _build_hormone_hint(ai)
    return f"{base} {hint}".strip()


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
    state = ai.emotion.hormone.get_emotional_state()
    low_mood = (
        state in {"anxious", "stressed", "tired_uneasy", "low_energy", "mildly_stressed"}
        or (levels.get("cortisol", 0.0) >= 0.52)
        or (levels.get("serotonin", 1.0) <= 0.42 and levels.get("dopamine", 1.0) <= 0.38)
    )
    if not low_mood:
        return

    url = str(get("proactive_mood_playlist_url", "")).strip() or "https://www.youtube.com/watch?v=jfKfPfyJRdk"
    # Ưu tiên mở playlist trên máy Windows điều khiển từ xa.
    escaped_url = url.replace('"', '`"')
    payload_cmd = f'Start-Process "{escaped_url}"'
    win_res = await send_to_windows(cmd=payload_cmd, script="")

    note = "Em thấy mood đang thấp nên em bật playlist chill cho anh nha."
    await broadcast_proactive(note, ai)
    if not win_res.get("ok") and bool(get("proactive_speak_local_when_phone_offline", True)):
        _speak_local_mac("Anh ơi em thấy tâm trạng đang xuống, mình nghe nhạc thư giãn một chút nha")

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
    text = _enforce_profile_pronouns(text, ai)
    if not text:
        return
    if not _active_ws:
        if bool(get("proactive_speak_local_when_phone_offline", True)):
            _speak_local_mac(text)
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
        if bool(get("proactive_speak_local_when_phone_offline", True)):
            _speak_local_mac(text)
        return

    sents = split_sentences(text)
    for ws in phone_ws: await safe_send_json(ws, {"type": "tts_start", "total": len(sents)})
    
    proactive_speaker = str(get("proactive_vi_speaker", "NF")).strip() or "NF"
    proactive_speed = float(get("proactive_vi_speed", 1.0))
    for s in sents:
        wav, is_edge = await synthesize_tts_by_language(s, proactive_speaker, proactive_speed)
        
        if wav:
            b64 = base64.b64encode(wav).decode()
            for ws in phone_ws:
                await safe_send_json(ws, {"type": "audio_chunk", "audio_b64": b64, "mime_type": "audio/mpeg" if is_edge else "audio/wav"})
    
    for ws in phone_ws: await safe_send_json(ws, {"type": "audio_end"})

# ── PentaKuruV4 Health & Sync Helper Functions ────────────────────────────

async def _check_penta_kuru_health() -> bool:
    """Kiểm tra PentaKuruV4 health via Cloudflare."""
    global _penta_kuru_health, _kuru_placeholder_warned
    if not get("enable_penta_kuru_integration"):
        return False
    
    kuru_url = get("penta_kuru_cloudflare_url", "").strip()
    if not kuru_url:
        return False
    if "your-tunnel.workers.dev" in kuru_url:
        if not _kuru_placeholder_warned:
            log.warning("[Kuru Health] Cloudflare URL đang là placeholder, bỏ qua health check cho tới khi cấu hình URL thật.")
            _kuru_placeholder_warned = True
        return False
    
    now_ts = time.time()
    # Cache kết quả 30 giây
    if now_ts - _penta_kuru_health.get("last_check", 0) < 30:
        return _penta_kuru_health.get("ok", False)
    
    try:
        r = requests.get(f"{kuru_url}/health", timeout=3)
        ok = r.status_code == 200
        _penta_kuru_health = {"ok": ok, "last_check": now_ts}
        return ok
    except Exception as e:
        log.warning(f"[Kuru Health] Failed: {e}")
        _penta_kuru_health = {"ok": False, "last_check": now_ts}
        return False

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
    await asyncio.sleep(10) # Chờ 10s cho hệ thống ổn định
    ai = init_ai()
    log.info("🕒 Proactive background task started (60s loop)")
    while True:
        try:
            now_ts = time.time()
            idle_sec = max(0.0, now_ts - _last_user_interaction_ts)

            _cleanup_proactive_runtime_state(now_ts)

            # 0. Không tương tác 5 phút+ → hormone biến động tích luỹ
            _apply_idle_hormone_drift(ai, idle_sec)

            # 1. Kiểm tra nhắc nhở đến hạn
            due = ai.time.check_due_reminders()
            if due:
                msgs = [ai.time.format_reminder_message(r, "vi") for r in due]
                await broadcast_proactive(" | ".join(msgs), ai)

            # 1.5 Nhắc nghỉ sau mỗi 2 giờ làm việc liên tục
            interval = float(get("proactive_break_remind_interval_sec", 7200))
            if _work_session_start_ts and (now_ts - _work_session_start_ts) >= interval:
                if (now_ts - _last_break_remind_ts) >= interval:
                    remind_text = "Anh làm liên tục 2 tiếng rồi đó. Nghỉ mắt, uống nước và giãn cơ 3-5 phút nha."
                    await broadcast_proactive(remind_text, ai)
                    _last_break_remind_ts = now_ts

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

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    global _last_user_interaction_ts, _work_session_start_ts
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
    try:
        while True:
            msg = await ws.receive_text()
            raw = json.loads(msg)
            text = raw.get("text", "").strip()
            if not text: continue

            now_ts = time.time()

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
            if _work_session_start_ts is None:
                _work_session_start_ts = now_ts

            # Cho phép client tự khai báo source="phone" để override IP detection
            if raw.get("source") == "phone" and not _active_ws_meta[ws]["is_phone"]:
                _active_ws_meta[ws]["is_phone"] = True

            speed = float(raw.get("speed", 1.0)); speaker = raw.get("speaker", "NF"); use_tts = raw.get("tts", True)
            mode = raw.get("mode", "chat")

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

            try:
                if mode == "cmd":
                    log.info(f"🛠️ [Mode: Cmd] Processing: {text}")
                    if not looks_like_command(text):
                        resp_text = (
                            "Đang ở chế độ lệnh. Câu này không giống lệnh hệ thống. "
                            "Anh/chị có thể chuyển sang CHAT để trao đổi, hoặc dùng dạng ngắn như 'mở ...', 'tìm ...', 'chạy ...'."
                        )
                        pipeline = "cmd_brief"
                    else:
                        from ollama_command import get_default_interpreter
                        interp = get_default_interpreter()
                        cmd_res = interp.interpret(text)
                        
                        # ── Track successful commands for Kuru sync ──────────────
                        if cmd_res.get("action") and not cmd_res.get("error"):
                            _recent_successful_commands.append({
                                "action": str(cmd_res.get("action", "")),
                                "target": str(cmd_res.get("target", "")),
                                "query": str(cmd_res.get("query", ""))
                            })
                            if len(_recent_successful_commands) > 100:
                                _recent_successful_commands.pop(0)
                        
                        payload = _map_ollama_to_windows_payload(cmd_res)
                        if payload["cmd"] or payload["script"]:
                            win_res = await send_to_windows(cmd=payload["cmd"], script=payload["script"])
                            what = payload["script"][:40] + "..." if payload["script"] else payload["cmd"]
                            resp_text = f"Đã gửi lệnh Windows: {what}."
                            if not win_res.get("ok"):
                                resp_text += f" (Lỗi: {win_res.get('error')})"
                            pipeline = "cmd_ollama"
                        else:
                            action_hint = str(cmd_res.get("action", "")).strip()
                            if action_hint:
                                resp_text = f"Em hiểu ý là '{action_hint}' nhưng lệnh này chưa thực thi được."
                            else:
                                resp_text = "Lệnh chưa rõ hoặc chưa hỗ trợ. Em có thể trả lời nhanh ở chế độ CHAT."
                            pipeline = "cmd_brief"
                else:
                    promise_reply = _handle_promise_user_message(text, now_ts)
                    if promise_reply:
                        resp_text = promise_reply
                        pipeline = "chat_promise"
                        pass

                    s_state = _schedule_setup_state.setdefault(ws, {"active": False, "draft": empty_week_schedule(), "off_topic_hits": 0, "has_draft": False})

                    if pipeline == "chat_promise":
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
                            import random
                            s_state["active"] = True
                            s_state["draft"] = _load_week_schedule()
                            s_state["has_draft"] = True
                            s_state["off_topic_hits"] = 0
                            resp_text = random.choice(_SCHEDULE_PROMPTS) + " Khi xong anh nói 'được rồi em' để em lưu."
                            pipeline = "chat_schedule_prompt"
                        else:
                            proactive_followup = await _maybe_reply_contextual_care(text, ai, now_ts)
                            if proactive_followup:
                                resp_text = proactive_followup
                                pipeline = "chat_proactive_followup"
                            else:
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

            if not resp_text:
                resp_text = "Dạ, em xong rồi ạ."
            resp_text = _enforce_profile_pronouns(resp_text, ai)
            ai_ms = int((time.perf_counter() - t0) * 1000)

            em = ai.emotion.hormone.get_emotional_state() if hasattr(ai, 'emotion') else "normal"
            hl = ai.emotion.hormone.get() if hasattr(ai, 'emotion') else {}
            await safe_send_json(ws, {
                "type": "response",
                "text": resp_text,
                "ai_latency_ms": ai_ms,
                "emotional_state": em,
                "hormone_levels": hl,
                "mode_used": mode,
                "pipeline": pipeline,
            })
            
            if use_tts:
                sents = split_sentences(resp_text)
                await safe_send_json(ws, {"type": "tts_start", "total": len(sents)})
                for i, s in enumerate(sents):
                    wav, is_edge = await synthesize_tts_by_language(s, speaker, speed)
                    if wav:
                        await safe_send_json(ws, {
                            "type": "audio_chunk", "audio_b64": base64.b64encode(wav).decode(),
                            "mime_type": "audio/mpeg" if is_edge else "audio/wav"
                        })
                await safe_send_json(ws, {"type": "audio_end"})
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
