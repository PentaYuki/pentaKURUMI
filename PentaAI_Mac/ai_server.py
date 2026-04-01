#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Unified Server — Mac Mini (Standalone)
VERSION 5.2 - Tách Ollama interpreter + tích hợp điều khiển Windows
- Sử dụng ollama_command.py để phân tích lệnh
- Có thể gửi lệnh đến Windows qua PentaKuru API
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
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional, List, Dict, Any, Union

import tinytuya
import requests
import websockets

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# --- Module tách riêng cho Ollama command ---
from ollama_command import OllamaCommandInterpreter, get_default_interpreter

# ─── Cấu hình môi trường ───────────────────────────────────────────
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, "tts_engine", "voicevox"))
sys.path.append(os.path.join(ROOT, "tts_engine", "valtec"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("UnifiedServer")

# ─── Config file ───────────────────────────────────────────────────
CONFIG_FILE = os.path.join(ROOT, "config.json")

DEFAULT_CONFIG = {
    "auth_token":       "abc",
    "tuya_device_id":   "a302e2ffce2957e759pajf",
    "tuya_local_key":   "4Vgvg$X:;r0u0H3!",
    "tuya_ip":          "192.168.1.64",
    "tuya_version":     3.3,
    "pc_tailscale_ip":  "100.116.207.30",
    "pc_mac_address":   "AA:BB:CC:DD:EE:FF",
    "pc_ssh_user":      "username",
    "pc_api_port":      7777,               # cổng của PentaKuru trên Windows
    "pc_auth_token":    "",                 # token xác thực (nếu có)
    "chat_tts":         True,
    "chat_speaker":     "NF",
    "chat_speed":       1.0,
    "ai_timeout":       30,
    "ollama_url":       "http://localhost:11434",
    "ollama_model":     "llama3.2:1b",
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(saved)
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def get(key, default=None):
    cfg = load_config()
    if key in cfg:
        return cfg[key]
    return DEFAULT_CONFIG.get(key, default)
# ─── Auth dependency ────────────────────────────────────────────────
async def verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if token != get("auth_token"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token

# ─── PentaAI và TTS ────────────────────────────────────────────────
_ai_instance = None
_vv_engine = None
_valtec_tts = None
_ollama_ready = None

AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "44100"))
TTS_TIMEOUT_PER_SENTENCE = float(os.getenv("TTS_TIMEOUT", "8.0"))
TTS_MAX_RETRIES = 2

def init_ai():
    global _ai_instance
    if _ai_instance is None:
        log.info("🚀 Đang khởi động PentaAI...")
        t0 = time.perf_counter()
        from main import PentaAI
        _ai_instance = PentaAI()
        log.info(f"✅ PentaAI sẵn sàng ({(time.perf_counter()-t0)*1000:.0f}ms)")
    return _ai_instance

def init_voicevox():
    global _vv_engine
    if _vv_engine is None:
        try:
            from voicevox_engine import VoicevoxEngine, SynthParams
            VOICEVOX_DIR = os.getenv("VOICEVOX_DIR", os.path.join(ROOT, "tts_engine", "voicevox"))
            _vv_engine = VoicevoxEngine(VOICEVOX_DIR)
            log.info("✅ Voicevox Engine sẵn sàng")
        except Exception as e:
            log.warning(f"⚠️ Không khởi tạo Voicevox: {e}")
            _vv_engine = None
    return _vv_engine

def init_valtec():
    global _valtec_tts
    if _valtec_tts is None:
        try:
            from valtec_server import ValtecEngine, TextValidatorVI
            _valtec_tts = ValtecEngine()
            log.info("✅ Valtec TTS sẵn sàng")
        except Exception as e:
            log.warning(f"⚠️ Không khởi tạo Valtec: {e}")
            _valtec_tts = None
    return _valtec_tts

def check_ollama():
    global _ollama_ready
    try:
        r = requests.get(f"{get('ollama_url')}/api/tags", timeout=2)
        _ollama_ready = r.status_code == 200
    except:
        _ollama_ready = False
    if _ollama_ready:
        log.info("✅ Ollama sẵn sàng")
    else:
        log.warning("⚠️ Ollama không khả dụng – device command sẽ bị tắt")
    return _ollama_ready

# ─── Gửi lệnh đến Windows (PentaKuru) ──────────────────────────────
async def send_to_windows(cmd: str) -> dict:
    """Gửi lệnh (PowerShell, chương trình) đến Windows qua API /run của PentaKuru."""
    pc_ip = get("pc_tailscale_ip")
    port = get("pc_api_port", 7777)
    url = f"http://{pc_ip}:{port}/run"
    auth_token = get("pc_auth_token", "")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    payload = {"cmd": cmd}
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(url, json=payload, headers=headers, timeout=10)
        )
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Các hàm TTS (giữ nguyên) ──────────────────────────────────────
_SENT_RE = re.compile(r'(?<=[.!?।。！？])\s+|(?<=\n)')

def split_sentences(text: str, min_chars: int = 500) -> list[str]:
    parts = [p.strip() for p in _SENT_RE.split(text) if p.strip()]
    if not parts:
        return [text.strip()] if text.strip() else []
    result = []
    buf = ""
    for part in parts:
        buf = (buf + " " + part).strip() if buf else part
        if len(buf) >= min_chars:
            result.append(buf)
            buf = ""
    if buf:
        if result:
            result[-1] = result[-1] + " " + buf
        else:
            result.append(buf)
    return result

def detect_language(text: str) -> str:
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text):
        return 'jp'
    if re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', text.lower()):
        return 'vi'
    if re.search(r'[a-zA-Z]', text):
        return 'en'
    return 'vi'

def resample_wav(wav_bytes: bytes, target_rate: int = 44100) -> bytes:
    try:
        if len(wav_bytes) < 44: return wav_bytes
        channels = struct.unpack('<H', wav_bytes[22:24])[0]
        sample_rate = struct.unpack('<I', wav_bytes[24:28])[0]
        bits_per_sample = struct.unpack('<H', wav_bytes[34:36])[0]
        if sample_rate == target_rate: return wav_bytes
        if bits_per_sample != 16: return wav_bytes
        offset = 12
        data_offset = -1
        data_size = 0
        while offset + 8 <= len(wav_bytes):
            chunk_id = wav_bytes[offset:offset+4]
            chunk_size = struct.unpack('<I', wav_bytes[offset+4:offset+8])[0]
            if chunk_id == b'data':
                data_offset = offset + 8
                data_size = chunk_size
                break
            offset += 8 + chunk_size
        if data_offset == -1: return wav_bytes
        pcm_data = wav_bytes[data_offset:data_offset+data_size]
        pcm_data, _ = audioop.ratecv(pcm_data, 2, channels, sample_rate, target_rate, None)
        header = bytearray()
        header.extend(b'RIFF')
        header.extend(struct.pack('<I', 36 + len(pcm_data)))
        header.extend(b'WAVE')
        header.extend(b'fmt ')
        header.extend(struct.pack('<I', 16))
        header.extend(struct.pack('<H', 1))
        header.extend(struct.pack('<H', channels))
        header.extend(struct.pack('<I', target_rate))
        header.extend(struct.pack('<I', target_rate * channels * 2))
        header.extend(struct.pack('<H', channels * 2))
        header.extend(struct.pack('<H', 16))
        header.extend(b'data')
        header.extend(struct.pack('<I', len(pcm_data)))
        return bytes(header) + pcm_data
    except Exception as e:
        log.warning(f"Lỗi resample_wav: {e}")
        return wav_bytes

def _valtec_synth_sync(text: str, speaker: str, speed: float) -> bytes:
    from valtec_server import TextValidatorVI
    clean_text = TextValidatorVI.clean(text) if TextValidatorVI else text
    if not clean_text.strip():
        clean_text = text
    raw_wav = _valtec_tts._raw_synth(clean_text, speaker, speed)
    return resample_wav(raw_wav, AUDIO_SAMPLE_RATE)

def _voicevox_synth_sync(text: str, speed: float) -> bytes:
    from voicevox_engine import SynthParams
    models = _vv_engine.scan_models()
    if not models:
        raise Exception("Không có model .vvm")
    vvm_name = models[0]["vvm"]
    params = SynthParams(speed=speed)
    raw_wav = _vv_engine.get_audio(text, vvm_name, params)
    return resample_wav(raw_wav, AUDIO_SAMPLE_RATE)

async def generate_voicevox_audio(text: str, speed: float) -> bytes:
    if not _vv_engine:
        raise Exception("Voicevox chưa sẵn sàng")
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _voicevox_synth_sync, text, speed)
    except Exception as e:
        if "chỉ đọc tiếng Nhật" in str(e):
            log.warning(f"⚠️ VoiceVox từ chối đọc tiếng Anh: '{text}'. Chuyển sang Valtec...")
            return await generate_valtec_audio(text, get("chat_speaker"), speed)
        raise e

async def generate_valtec_audio(text: str, speaker: str, speed: float) -> bytes:
    if not _valtec_tts:
        raise Exception("Valtec chưa sẵn sàng")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _valtec_synth_sync, text, speaker, speed)

# ─── Tuya và PC control ────────────────────────────────────────────
def get_outlet():
    return tinytuya.OutletDevice(
        dev_id    = get("tuya_device_id"),
        address   = get("tuya_ip"),
        local_key = get("tuya_local_key"),
        version   = float(get("tuya_version")),
    )

def outlet_control(turn_on: bool) -> bool:
    try:
        d = get_outlet()
        d.set_socketPersistent(False)
        d.turn_on() if turn_on else d.turn_off()
        log.info(f"Ổ điện {'BẬT' if turn_on else 'TẮT'}")
        return True
    except Exception as e:
        log.error(f"Tuya error: {e}")
        return False

def outlet_status() -> str:
    try:
        d = get_outlet()
        d.set_socketPersistent(False)
        data = d.status()
        state = data.get("dps", {}).get("1", None)
        if state is True:  return "on"
        if state is False: return "off"
        return "unknown"
    except Exception as e:
        log.error(f"Tuya status error: {e}")
        return "unknown"

def pc_ping() -> bool:
    pc_ip = get("pc_tailscale_ip")
    try:
        result = subprocess.run(["ping", "-c", "1", "-W", "2", pc_ip],
                                capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

# ─── FastAPI app ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    import atexit
    log.info("⚙️  Server đang khởi động — warm-up AI & TTS...")
    ai = init_ai()
    init_voicevox()
    init_valtec()
    check_ollama()
    # Đăng ký atexit để save hormone khi tắt server
    def _save_on_exit():
        try:
            if _ai_instance and hasattr(_ai_instance, 'emotion') and _ai_instance.emotion:
                _ai_instance.emotion.flush()
                log.info("💾 Hormone state saved on exit.")
        except Exception as e:
            log.warning("Hormone exit save failed: %s", e)
    atexit.register(_save_on_exit)
    yield
    # Shutdown: save state trước khi dừng
    try:
        if _ai_instance and hasattr(_ai_instance, 'emotion') and _ai_instance.emotion:
            _ai_instance.emotion.flush()
            log.info("💾 Hormone state saved on shutdown.")
    except Exception as e:
        log.warning("Hormone shutdown save failed: %s", e)
    log.info("👋 Server đã tắt")

app = FastAPI(title="PentaAI Unified Server", version="5.3", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Pydantic models ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    text:    str
    tts:     bool  = True
    speaker: str   = "NF"
    speed:   float = 1.0

class ChatResponse(BaseModel):
    text:             str
    audio_b64:        Optional[str] = None
    ai_latency_ms:    int
    total_latency_ms: Optional[int] = None
    tts_error:        Optional[str] = None

class OllamaCommandRequest(BaseModel):
    text:               str
    available_commands: List[str] = []

class OllamaCommandResponse(BaseModel):
    action:     Optional[str] = None
    target:     Optional[str] = None
    parameters: Optional[str] = None
    error:      Optional[str] = None
    raw:        Optional[str] = None
    windows_result: Optional[Dict] = None   # thêm field để trả về kết quả từ Windows nếu execute=true

# ─── WebSocket semaphore ───────────────────────────────────────────
MAX_WS_CLIENTS = 4
_ws_semaphore = asyncio.Semaphore(MAX_WS_CLIENTS)

async def safe_send_json(websocket: WebSocket, data: dict) -> bool:
    try:
        await websocket.send_json(data)
        return True
    except Exception as e:
        log.warning(f"⚠️ Không thể gửi message: {e}")
        return False

# ─── Endpoints ──────────────────────────────────────────────────────

@app.get("/")
async def root():
    return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <title>PentaAI Unified Server v5.3</title>
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        .status { background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 20px 0; }
        code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <h1>🎤 PentaAI Unified Server v5.3</h1>
    <div class="status">
        <strong>✅ Server đang chạy trên Mac mini</strong><br>
        WebSocket Chat: <code>ws://localhost:9090/ws/chat</code><br>
        HTTP Chat: <code>http://localhost:9090/api/chat</code><br>
        Ollama Command: <code>http://localhost:9090/api/ollama_command</code><br>
        Execute PC Command: <code>http://localhost:9090/api/execute_pc_command</code><br>
        <strong>Hormone Status: <code>http://localhost:9090/api/hormone_status</code></strong><br>
        <strong>Hormone Reset: <code>http://localhost:9090/api/hormone_reset</code> [POST, auth]</strong><br>
        Health: <code>http://localhost:9090/api/health</code>
    </div>
    <p>Đã tích hợp Ollama interpreter riêng biệt, hỗ trợ gửi lệnh đến Windows qua PentaKuru.</p>
    <p>❤️ Hệ thống hormone v2.0: Temperament + EpisodicMemory + ProactiveEngine.</p>
</body>
</html>
    """)

@app.get("/api/health")
async def health_check():
    return {
        "status":        "ok",
        "version":       "5.3",
        "ai_ready":      _ai_instance is not None,
        "ollama_ready":  _ollama_ready,
        "tts_vi":        _valtec_tts is not None,
        "tts_jp":        _vv_engine is not None,
        "tuya_configured": bool(get("tuya_device_id")),
        "audio_sample_rate": AUDIO_SAMPLE_RATE,
    }


@app.get("/api/hormone_status")
async def hormone_status():
    """
    Trả về trạng thái hormone hiện tại của AI.
    Không yêu cầu xác thực — dành cho debug và monitor.
    """
    ai = init_ai()
    try:
        status = ai.get_hormone_status()
        return {"status": "ok", "data": status}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)}
        )


@app.post("/api/hormone_reset")
async def hormone_reset(token: str = Depends(verify_token)):
    """
    Reset hormone về baseline (dùng khi muốn khởi động lại cảm xúc).
    Yêu cầu xác thực.
    """
    ai = init_ai()
    try:
        if ai.emotion:
            from hormone.hormone_core import PERSONALITY_BASELINES
            baseline = PERSONALITY_BASELINES.get('curious', {})
            ai.emotion.hormone.levels = baseline.copy()
            ai.emotion.hormone.save()
            new_state = ai.emotion.hormone.get_emotional_state()
            log.info("🔄 Hormone reset to baseline: %s", new_state)
            return {"status": "ok", "new_state": new_state, "levels": baseline}
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "Hormone system not available"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)}
        )

# ─── Config endpoints (cần xác thực) ───────────────────────────────
@app.get("/api/config")
async def get_config_api(token: str = Depends(verify_token)):
    cfg = load_config()
    safe = cfg.copy()
    if safe.get("tuya_local_key"):
        safe["tuya_local_key"] = safe["tuya_local_key"][:4] + "****"
    if safe.get("auth_token"):
        safe["auth_token"] = safe["auth_token"][:6] + "****"
    if safe.get("pc_auth_token"):
        safe["pc_auth_token"] = safe["pc_auth_token"][:4] + "****"
    return {"status": "ok", "config": safe}

@app.post("/api/config")
async def set_config_api(request: Request, token: str = Depends(verify_token)):
    data = await request.json()
    if not data:
        return JSONResponse(content={"error": "Body JSON rỗng"}, status_code=400)
    cfg = load_config()
    allowed = set(DEFAULT_CONFIG.keys()) - {"auth_token"}
    updated = []
    for k, v in data.items():
        if k in allowed:
            cfg[k] = v
            updated.append(k)
    save_config(cfg)
    log.info(f"Config updated: {updated}")
    return {"status": "ok", "updated": updated}

@app.post("/api/config/token")
async def set_token(request: Request, token: str = Depends(verify_token)):
    data = await request.json() or {}
    new_token = data.get("new_token", "").strip()
    if len(new_token) < 8:
        return JSONResponse(content={"error": "Token quá ngắn (tối thiểu 8 ký tự)"}, status_code=400)
    cfg = load_config()
    cfg["auth_token"] = new_token
    save_config(cfg)
    return {"status": "ok", "message": "Token đã cập nhật"}
@app.post("/api/config/pc_token")
async def set_pc_token(request: Request, token: str = Depends(verify_token)):
    """
    Cập nhật token cho PentaKuru (Windows). Yêu cầu xác thực bằng token chính.
    Body JSON: {"pc_token": "your_token"}
    """
    data = await request.json() or {}
    pc_token = data.get("pc_token", "").strip()
    if len(pc_token) < 4:
        return JSONResponse(content={"error": "Token quá ngắn (tối thiểu 4 ký tự)"}, status_code=400)
    cfg = load_config()
    cfg["pc_auth_token"] = pc_token
    save_config(cfg)
    log.info(f"PentaKuru token updated (length {len(pc_token)})")
    return {"status": "ok", "message": "PentaKuru token đã cập nhật"}
# ─── Status & control endpoints ────────────────────────────────────
@app.get("/api/status")
async def system_status(token: str = Depends(verify_token)):
    power = outlet_status()
    pc_online = pc_ping()
    return {
        "outlet_power":    power,
        "pc_online":       pc_online,
        "pc_ip":           get("pc_tailscale_ip"),
        "ai_server_ready": True,
        "tuya_configured": bool(get("tuya_device_id")),
        "server":          "Unified AI Server",
    }

@app.post("/api/turn-on-pc")
async def turn_on_pc(token: str = Depends(verify_token)):
    if not get("tuya_device_id"):
        return JSONResponse(content={"error": "Chưa cấu hình Tuya"}, status_code=400)
    success = outlet_control(True)
    if success:
        return {"status": "ok", "message": "Ổ điện bật, PC đang khởi động (~30-60s)"}
    return JSONResponse(content={"status": "error", "message": "Không kết nối được ổ điện"}, status_code=500)

@app.post("/api/turn-off-pc")
async def turn_off_pc(token: str = Depends(verify_token)):
    success = outlet_control(False)
    return {"status": "ok" if success else "error"}

@app.post("/api/restart-outlet")
async def restart_outlet(token: str = Depends(verify_token)):
    outlet_control(False)
    await asyncio.sleep(3)
    outlet_control(True)
    return {"status": "ok", "message": "Đã restart ổ điện"}

@app.post("/api/start-ai")
async def start_ai(token: str = Depends(verify_token)):
    # Trên Mac mini, server đã chạy sẵn
    return {"status": "ok", "message": "AI server đang chạy"}

# ─── Ollama Command với tuỳ chọn execute ───────────────────────────
@app.post("/api/ollama_command", response_model=OllamaCommandResponse)
async def ollama_command(
    req: OllamaCommandRequest,
    execute: bool = False,
    token: str = Depends(verify_token)
):
    """Phân tích câu lệnh tự nhiên. Nếu execute=true, sẽ thực thi lệnh PC nếu có thể."""
    interpreter = get_default_interpreter()
    result = interpreter.interpret(req.text, req.available_commands)

    windows_result = None
    if execute and "error" not in result:
        action = result.get("action", "")
        target = result.get("target", "")
        params = result.get("parameters", "")
        # Nếu action thuộc nhóm có thể thực thi trên Windows
        if action in ["open", "run", "close", "type", "search"] and target:
            cmd = target
            if params:
                cmd += " " + params
            windows_result = await send_to_windows(cmd)
            log.info(f"Executed on Windows: {cmd} → {windows_result}")
            # Ghi log kết quả

    return OllamaCommandResponse(
        action=result.get("action"),
        target=result.get("target"),
        parameters=result.get("parameters"),
        error=result.get("error"),
        raw=result.get("raw"),
        windows_result=windows_result,
    )

# ─── Endpoint mới: thực thi trực tiếp lệnh PC (không cần gọi riêng execute) ──
@app.post("/api/execute_pc_command")
async def execute_pc_command(req: OllamaCommandRequest, token: str = Depends(verify_token)):
    interpreter = get_default_interpreter()
    result = interpreter.interpret(req.text, req.available_commands)

    if "error" in result:
        return JSONResponse(status_code=400, content={"error": result["error"], "parsed": result})

    action = result.get("action", "").lower()
    target = result.get("target", "").strip()
    params = result.get("parameters", "").strip()

    # Map tên web phổ biến thành URL
    web_map = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "facebook": "https://www.facebook.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        # thêm các site khác nếu cần
    }

    # Xử lý theo action
    if action in ["open", "run", "close", "type", "search"] and target:
        # Nếu target là từ khóa trong web_map, chuyển thành URL và dùng start
        if target.lower() in web_map:
            cmd = f"start {web_map[target.lower()]}"
        elif target.startswith("http://") or target.startswith("https://"):
            cmd = f"start {target}"
        else:
            # Fallback: coi target là tên ứng dụng hoặc file
            cmd = target
        if params:
            cmd += " " + params
        win_result = await send_to_windows(cmd)
        log.info(f"Executed on Windows: {cmd} → {win_result}")
        return win_result
    else:
        return JSONResponse(status_code=400, content={
            "error": "Command not recognized for PC execution",
            "parsed": result
        })
# ─── Teach endpoint (giữ nguyên) ───────────────────────────────────
@app.post("/api/teach")
async def teach(request: Request, token: str = Depends(verify_token)):
    data = await request.json() or {}
    fact = data.get("fact", "").strip()
    if not fact:
        return JSONResponse(content={"error": "Thiếu field fact"}, status_code=400)

    ai = init_ai()
    try:
        response = ai.chat(f"dạy {fact}")
        return {"status": "ok", "response": response}
    except Exception as e:
        log.error(f"Teach error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

# ─── Chat (HTTP) ───────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, token: str = Depends(verify_token)):
    t0 = time.perf_counter()
    loop = asyncio.get_event_loop()
    ai = init_ai()
    response_text = await loop.run_in_executor(None, ai.chat, req.text)

    run_match = re.search(r'<RUN>(.*?)</RUN>', response_text, re.IGNORECASE | re.DOTALL)
    if run_match:
        response_text = re.sub(r'<RUN>.*?</RUN>', '', response_text, flags=re.IGNORECASE | re.DOTALL).strip()
        if not response_text:
            response_text = "Dạ, em đã thực hiện xong."

    result = ChatResponse(text=response_text, ai_latency_ms=int((time.perf_counter() - t0) * 1000))

    if req.tts and response_text:
        try:
            lang = detect_language(response_text)
            if lang in ['jp', 'en']:
                if _vv_engine:
                    wav_bytes = await asyncio.wait_for(
                        generate_voicevox_audio(response_text, req.speed),
                        timeout=TTS_TIMEOUT_PER_SENTENCE * 3
                    )
                else:
                    raise Exception("Không có VoiceVox để đọc Tiếng Anh/Nhật")
            elif lang == 'vi':
                if _valtec_tts:
                    wav_bytes = await asyncio.wait_for(
                        generate_valtec_audio(response_text, req.speaker, req.speed),
                        timeout=TTS_TIMEOUT_PER_SENTENCE * 3
                    )
                else:
                    raise Exception("Không có Valtec để đọc Tiếng Việt")
            else:
                raise Exception("Không có TTS Engine phù hợp")

            if wav_bytes:
                result.audio_b64 = base64.b64encode(wav_bytes).decode()
                result.total_latency_ms = int((time.perf_counter() - t0) * 1000)
        except asyncio.TimeoutError:
            result.tts_error = "TTS timeout"
        except Exception as e:
            result.tts_error = str(e)

    return result

# ─── WebSocket Chat (giữ nguyên, không thay đổi) ───────────────────
@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket endpoint cho chat real-time với TTS streaming."""
    # Kiểm tra semaphore để giới hạn số lượng client
    if _ws_semaphore.locked() and _ws_semaphore._value == 0:
        await websocket.accept()
        await websocket.send_json({"type": "error", "msg": "Server bận (max connections). Thử lại sau."})
        await websocket.close()
        log.warning("⚠️ WS client bị từ chối vì semaphore đầy")
        return

    await websocket.accept()
    client_addr = websocket.client.host if websocket.client else "?"
    log.info(f"🔌 WS client kết nối: {client_addr}")

    async with _ws_semaphore:
        ai = init_ai()
        while True:
            try:
                raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=120)
            except asyncio.TimeoutError:
                # Gửi ping để giữ kết nối
                if not await safe_send_json(websocket, {"type": "ping"}):
                    break
                continue
            except WebSocketDisconnect:
                log.info(f"🔌 WS client ngắt kết nối: {client_addr}")
                break
            except Exception as e:
                log.info(f"🔌 WS client ngắt kết nối ({type(e).__name__}): {client_addr}")
                break

            try:
                raw = json.loads(raw_text)
                text = (raw.get("text") or "").strip()
                speaker = raw.get("speaker", get("chat_speaker"))
                speed = float(raw.get("speed", get("chat_speed")))

                if not text:
                    await safe_send_json(websocket, {"type": "error", "msg": "Tin nhắn rỗng"})
                    continue

                log.info(f"💬 WS [{client_addr}]: '{text[:60]}'")
                t0 = time.perf_counter()
                loop = asyncio.get_event_loop()

                try:
                    response_text = await asyncio.wait_for(
                        loop.run_in_executor(None, ai.chat, text),
                        timeout=35.0
                    )
                except asyncio.TimeoutError:
                    response_text = "Xin lỗi, em đang xử lý chậm. Bạn hỏi lại nhé."
                    log.warning(f"⏱ AI timeout >35s cho: '{text[:60]}'")

                # Xử lý tag <RUN> (nếu có)
                run_match = re.search(r'<RUN>(.*?)</RUN>', response_text, re.IGNORECASE | re.DOTALL)
                if run_match:
                    response_text = re.sub(r'<RUN>.*?</RUN>', '', response_text, flags=re.IGNORECASE | re.DOTALL).strip()
                    if not response_text:
                        response_text = "Dạ, em đã thực hiện xong."

                ai_ms = int((time.perf_counter() - t0) * 1000)
                log.info(f"✅ WS AI reply [{ai_ms}ms]: '{response_text[:60]}'")

                # Gửi phần text trước
                if not await safe_send_json(websocket, {
                    "type": "text",
                    "text": response_text,
                    "ai_latency_ms": ai_ms
                }):
                    break

                # Chuẩn bị TTS streaming
                sentences = split_sentences(response_text)
                if sentences:
                    if not await safe_send_json(websocket, {
                        "type": "tts_start",
                        "total_sentences": len(sentences),
                        "msg": "Đang chuẩn bị audio..."
                    }):
                        break

                tts_success_count = 0
                tts_error_count = 0

                for i, sentence in enumerate(sentences):
                    if not sentence.strip():
                        continue

                    lang = detect_language(sentence)
                    wav_bytes = None
                    t_tts = time.perf_counter()

                    if not await safe_send_json(websocket, {
                        "type": "tts_progress",
                        "current": i + 1,
                        "total": len(sentences),
                        "sentence_preview": sentence[:30] + "..." if len(sentence) > 30 else sentence
                    }):
                        log.warning(f"⚠️ Client ngắt giữa TTS chunk {i+1}/{len(sentences)}")
                        break

                    for retry in range(TTS_MAX_RETRIES):
                        try:
                            if lang in ['jp', 'en']:
                                if _vv_engine:
                                    wav_bytes = await asyncio.wait_for(
                                        generate_voicevox_audio(sentence, speed),
                                        timeout=TTS_TIMEOUT_PER_SENTENCE
                                    )
                                else:
                                    log.warning(f"⚠️ Bỏ qua câu JP/EN '{sentence[:30]}' vì không có VoiceVox.")
                                    break
                            elif lang == 'vi':
                                if _valtec_tts:
                                    wav_bytes = await asyncio.wait_for(
                                        generate_valtec_audio(sentence, speaker, speed),
                                        timeout=TTS_TIMEOUT_PER_SENTENCE
                                    )
                                else:
                                    log.warning(f"⚠️ Bỏ qua câu VI '{sentence[:30]}' vì không có Valtec.")
                                    break
                            break
                        except asyncio.TimeoutError:
                            log.warning(f"⚠️ TTS timeout (retry {retry+1}/{TTS_MAX_RETRIES}) cho chunk {i+1}")
                            if retry == TTS_MAX_RETRIES - 1:
                                tts_error_count += 1
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            log.error(f"🔴 TTS synthesis error chunk {i}: {e}")
                            tts_error_count += 1
                            break

                    if wav_bytes:
                        tts_ms = int((time.perf_counter() - t_tts) * 1000)
                        log.info(f"🔊 TTS chunk {i+1}/{len(sentences)} [{tts_ms}ms, {len(wav_bytes)//1024}KB]: '{sentence[:30]}'")
                        audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
                        if not await safe_send_json(websocket, {
                            "type": "audio_chunk",
                            "index": i,
                            "total": len(sentences),
                            "size_bytes": len(wav_bytes),
                            "sample_rate": AUDIO_SAMPLE_RATE,
                            "audio_b64": audio_b64
                        }):
                            break
                        tts_success_count += 1

                total_ms = int((time.perf_counter() - t0) * 1000)
                await safe_send_json(websocket, {
                    "type": "audio_end",
                    "total_latency_ms": total_ms,
                    "tts_success": tts_success_count,
                    "tts_errors": tts_error_count
                })
                log.info(f"✅ WS session hoàn thành [{total_ms}ms] - TTS: {tts_success_count} OK, {tts_error_count} errors")

            except WebSocketDisconnect:
                log.info(f"🔌 WS client ngắt kết nối trong lúc xử lý: {client_addr}")
                break
            except json.JSONDecodeError as e:
                log.error(f"🔴 JSON decode error: {e}")
                await safe_send_json(websocket, {"type": "error", "msg": "Invalid JSON format"})
            except Exception as e:
                log.error(f"🔴 WS handler error: {e}", exc_info=True)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
