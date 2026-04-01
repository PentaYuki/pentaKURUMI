#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Web Server — v5.1
Trang web chat + dashboard kiểm tra hệ thống.

TTS ưu tiên:
  1. Valtec   → tiếng Việt  (server WAV qua WebSocket)
  2. Voicevox → tiếng Nhật/Anh (server WAV qua WebSocket)
  3. Web Speech API → fallback trình duyệt

User Profile:
  GET  /api/profile  → lấy tên + đại từ
  POST /api/profile  → {"name":"Minh","pronoun":"anh"} → lưu vào UserProfile
"""

import sys, os, struct, json, logging, re, time, asyncio, importlib, base64
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, "tts_engine", "voicevox"))
sys.path.append(os.path.join(ROOT, "tts_engine", "valtec"))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("PentaAI")

AI_HOST           = os.getenv("AI_HOST", "0.0.0.0")
AI_PORT           = int(os.getenv("AI_PORT", "9090"))
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "44100"))
TTS_TIMEOUT       = float(os.getenv("TTS_TIMEOUT", "8.0"))
TTS_MAX_RETRIES   = 2
DEFAULT_SPEAKER   = os.getenv("TTS_SPEAKER", "NF")
VOICEVOX_DIR      = os.getenv("VOICEVOX_DIR", os.path.join(ROOT, "tts_engine", "voicevox"))

# ── Module Registry ──────────────────────────────────────────────────────
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
    "TimeAwareness":        {"module": "core.time_awareness",           "class": "TimeAwareness",          "group": "optional"},
    "UserProfile":          {"module": "core.user_profile",             "class": "UserProfile",            "group": "optional"},
}

def check_modules():
    results = {}
    for name, info in _MODULES.items():
        try:
            mod = importlib.import_module(info["module"])
            ok  = getattr(mod, info["class"], None) is not None
            results[name] = {"status": "ok" if ok else "missing_class",
                             "group": info["group"], "module": info["module"]}
        except ImportError as e:
            results[name] = {"status": "import_error", "group": info["group"],
                             "module": info["module"], "error": str(e).split("\n")[0][:80]}
        except Exception as e:
            results[name] = {"status": "error", "group": info["group"],
                             "module": info["module"], "error": str(e)[:80]}
    return results

# ── TTS ───────────────────────────────────────────────────────────────────
_vv_engine  = None
_valtec_tts = None

def init_voicevox():
    global _vv_engine
    if _vv_engine is not None: return _vv_engine
    try:
        from voicevox_engine import VoicevoxEngine
        _vv_engine = VoicevoxEngine(VOICEVOX_DIR)
        log.info("✅ Voicevox sẵn sàng (JP/EN)")
    except Exception as e:
        log.warning(f"⚠️ Voicevox: {e}")
    return _vv_engine

def init_valtec():
    global _valtec_tts
    if _valtec_tts is not None: return _valtec_tts
    try:
        from valtec_server import ValtecEngine
        _valtec_tts = ValtecEngine()
        log.info("✅ Valtec TTS sẵn sàng (VI)")
    except Exception as e:
        log.warning(f"⚠️ Valtec: {e}")
    return _valtec_tts

def resample_wav(data: bytes, target: int = 44100) -> bytes:
    try:
        import audioop
        if len(data) < 44: return data
        ch   = struct.unpack('<H', data[22:24])[0]
        sr   = struct.unpack('<I', data[24:28])[0]
        bits = struct.unpack('<H', data[34:36])[0]
        if sr == target or bits != 16: return data
        offset = 12; doff = -1; dsz = 0
        while offset + 8 <= len(data):
            cid = data[offset:offset+4]; csz = struct.unpack('<I', data[offset+4:offset+8])[0]
            if cid == b'data': doff = offset + 8; dsz = csz; break
            offset += 8 + csz
        if doff == -1: return data
        pcm, _ = audioop.ratecv(data[doff:doff+dsz], 2, ch, sr, target, None)
        h = bytearray()
        h += b'RIFF'; h += struct.pack('<I', 36+len(pcm))
        h += b'WAVEfmt '; h += struct.pack('<I', 16); h += struct.pack('<H', 1)
        h += struct.pack('<H', ch); h += struct.pack('<I', target)
        h += struct.pack('<I', target*ch*2); h += struct.pack('<H', ch*2)
        h += struct.pack('<H', 16); h += b'data'; h += struct.pack('<I', len(pcm))
        return bytes(h) + pcm
    except Exception: return data

def _valtec_sync(text: str, speaker: str, speed: float) -> bytes:
    try:
        from valtec_server import TextValidatorVI
        clean = TextValidatorVI.clean(text)
    except Exception:
        clean = text
    raw = _valtec_tts._raw_synth(clean or text, speaker, speed)
    return resample_wav(raw, AUDIO_SAMPLE_RATE)

def _voicevox_sync(text: str, speed: float) -> bytes:
    from voicevox_engine import SynthParams
    models = _vv_engine.scan_models()
    if not models: raise RuntimeError("Không có model .vvm")
    raw = _vv_engine.get_audio(text, models[0]["vvm"], SynthParams(speed=speed))
    return resample_wav(raw, AUDIO_SAMPLE_RATE)

async def tts_valtec(text, speaker, speed):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _valtec_sync, text, speaker, speed)

async def tts_voicevox(text, speed):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _voicevox_sync, text, speed)
    except Exception as e:
        if "tiếng Nhật" in str(e) or "japanese" in str(e).lower():
            return await tts_valtec(text, DEFAULT_SPEAKER, speed)
        raise

# ── Helpers ───────────────────────────────────────────────────────────────
_SENT_RE = re.compile(r'(?<=[.!?।。！？])\s+|(?<=\n)')

def split_sentences(text: str, min_chars: int = 80) -> List[str]:
    parts = [p.strip() for p in _SENT_RE.split(text) if p.strip()]
    if not parts: return [text.strip()] if text.strip() else []
    result, buf = [], ""
    for p in parts:
        buf = (buf+" "+p).strip() if buf else p
        if len(buf) >= min_chars: result.append(buf); buf = ""
    if buf:
        if result: result[-1] += " " + buf
        else: result.append(buf)
    return result

def detect_lang(text: str) -> str:
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text): return 'jp'
    if re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]',
                 text.lower()): return 'vi'
    if re.search(r'[a-zA-Z]', text): return 'en'
    return 'vi'

async def safe_send(ws: WebSocket, data: dict) -> bool:
    try: await ws.send_json(data); return True
    except Exception: return False

# ── Global state ──────────────────────────────────────────────────────────
_ai           = None
_mod_status   = {}
_emb_backend  = "unknown"

def init_ai():
    global _ai, _emb_backend
    if _ai is not None: return _ai
    try:
        from main import PentaAI
        t0 = time.perf_counter()
        _ai = PentaAI()
        ms  = int((time.perf_counter()-t0)*1000)
        try: _emb_backend = _ai.phrase_engine._embedder.backend
        except Exception: pass
        log.info(f"✅ PentaAI ({ms}ms) | embedder={_emb_backend}")
    except Exception as e:
        log.error(f"❌ PentaAI: {e}")
    return _ai

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mod_status
    _mod_status = check_modules()
    ok  = sum(1 for v in _mod_status.values() if v["status"]=="ok")
    err = sum(1 for v in _mod_status.values() if v["status"]!="ok")
    log.info(f"📦 Modules: {ok} OK / {err} lỗi")
    init_ai(); init_valtec(); init_voicevox()
    yield
    if _ai:
        try:
            if hasattr(_ai,"emotion") and _ai.emotion: _ai.emotion.flush()
        except Exception: pass
    log.info("👋 Server tắt")

app = FastAPI(title="PentaAI", version="5.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    ok  = sum(1 for v in _mod_status.values() if v["status"]=="ok")
    err = sum(1 for v in _mod_status.values() if v["status"]!="ok")
    em = hl = None
    if _ai and hasattr(_ai,"emotion") and _ai.emotion:
        try:
            em = _ai.emotion.hormone.get_emotional_state()
            hl = {k:round(v,3) for k,v in _ai.emotion.hormone.get().items()}
        except Exception: pass
    return {"status":"ok","ai_ready":_ai is not None,"embedder_backend":_emb_backend,
            "tts_vi":_valtec_tts is not None,"tts_jp":_vv_engine is not None,
            "modules_ok":ok,"modules_error":err,"emotional_state":em,"hormone_levels":hl}

@app.get("/api/modules")
async def modules():
    return JSONResponse({"modules": _mod_status})

@app.get("/api/stats")
async def stats():
    if not _ai: return {"error":"AI chưa sẵn sàng"}
    try: return _ai.get_stats()
    except Exception as e: return {"error":str(e)}

@app.get("/api/profile")
async def get_profile():
    """Trả về tên và đại từ người dùng hiện tại từ UserProfile."""
    if not _ai or not hasattr(_ai,"profile"):
        return {"name":"","pronoun":"bạn"}
    p = _ai.profile
    return {"name": getattr(p,"name","") or "", "pronoun": getattr(p,"pronoun","bạn") or "bạn"}

@app.post("/api/profile")
async def set_profile(request: Request):
    """Cập nhật tên/đại từ rồi lưu vào UserProfile."""
    data = await request.json()
    if not _ai or not hasattr(_ai,"profile"):
        return JSONResponse({"error":"AI chưa sẵn sàng"}, status_code=503)
    p = _ai.profile
    name    = (data.get("name") or "").strip()
    pronoun = (data.get("pronoun") or "bạn").strip()
    if name:    p.name    = name
    if pronoun: p.pronoun = pronoun
    try:
        if   hasattr(p,"save"):  p.save()
        elif hasattr(p,"flush"): p.flush()
    except Exception: pass
    log.info(f"👤 Profile: name={name!r} pronoun={pronoun!r}")
    return {"status":"ok","name":name,"pronoun":pronoun}

# ── WebSocket ─────────────────────────────────────────────────────────────
_ws_sem = asyncio.Semaphore(8)

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    client = websocket.client.host if websocket.client else "?"
    log.info(f"🔌 WS connect: {client}")

    async with _ws_sem:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=120)
            except asyncio.TimeoutError:
                if not await safe_send(websocket, {"type":"ping"}): break
                continue
            except WebSocketDisconnect: break
            except Exception: break

            try:
                payload = json.loads(raw)
                text    = (payload.get("text") or "").strip()
                speaker = payload.get("speaker", DEFAULT_SPEAKER)
                speed   = float(payload.get("speed", 1.0))
                use_tts = payload.get("tts", True)

                if not text:
                    await safe_send(websocket, {"type":"error","msg":"Tin nhắn rỗng"})
                    continue

                t0   = time.perf_counter()
                loop = asyncio.get_event_loop()

                # AI
                if _ai:
                    try:
                        resp = await asyncio.wait_for(
                            loop.run_in_executor(None, _ai.chat, text), timeout=30.0)
                    except asyncio.TimeoutError:
                        resp = "Xin lỗi, em đang xử lý chậm. Bạn thử lại nhé."
                else:
                    resp = f"PentaAI chưa sẵn sàng. Bạn đã nói: {text}"

                resp = re.sub(r'<RUN>.*?</RUN>', '', resp, flags=re.IGNORECASE|re.DOTALL).strip()
                if not resp: resp = "Dạ, em đã thực hiện xong."

                ai_ms = int((time.perf_counter()-t0)*1000)
                em = None
                if _ai and hasattr(_ai,"emotion") and _ai.emotion:
                    try: em = _ai.emotion.hormone.get_emotional_state()
                    except Exception: pass

                # Gửi text + thông báo TTS nào sẵn sàng
                if not await safe_send(websocket, {
                    "type":"response","text":resp,"ai_latency_ms":ai_ms,
                    "emotional_state":em,
                    "tts_vi_ready":_valtec_tts is not None,
                    "tts_jp_ready":_vv_engine   is not None,
                }): break

                log.info(f"✅ [{ai_ms}ms] '{resp[:60]}'")

                # TTS streaming
                if use_tts and (_valtec_tts or _vv_engine):
                    sentences = split_sentences(resp)
                    if sentences:
                        await safe_send(websocket, {"type":"tts_start","total":len(sentences)})

                    ok_count = err_count = 0
                    for i, sent in enumerate(sentences):
                        if not sent.strip(): continue
                        lang = detect_lang(sent)
                        wav  = None

                        await safe_send(websocket, {
                            "type":"tts_progress","current":i+1,"total":len(sentences),
                            "preview":sent[:40]})

                        for attempt in range(TTS_MAX_RETRIES):
                            try:
                                if lang in ('jp','en') and _vv_engine:
                                    wav = await asyncio.wait_for(
                                        tts_voicevox(sent, speed), timeout=TTS_TIMEOUT)
                                elif lang == 'vi' and _valtec_tts:
                                    wav = await asyncio.wait_for(
                                        tts_valtec(sent, speaker, speed), timeout=TTS_TIMEOUT)
                                else:
                                    # Engine không có cho ngôn ngữ này → fallback client
                                    await safe_send(websocket,
                                        {"type":"tts_fallback","text":sent,"lang":lang})
                                break
                            except asyncio.TimeoutError:
                                log.warning(f"TTS timeout attempt {attempt+1}")
                                if attempt == TTS_MAX_RETRIES-1:
                                    err_count += 1
                                    await safe_send(websocket,
                                        {"type":"tts_fallback","text":sent,"lang":lang})
                            except Exception as e:
                                log.error(f"TTS error: {e}")
                                err_count += 1
                                await safe_send(websocket,
                                    {"type":"tts_fallback","text":sent,"lang":lang})
                                break

                        if wav:
                            if not await safe_send(websocket, {
                                "type":"audio_chunk","index":i,"total":len(sentences),
                                "size_bytes":len(wav),"sample_rate":AUDIO_SAMPLE_RATE,
                                "audio_b64":base64.b64encode(wav).decode(),
                            }): break
                            ok_count += 1

                    await safe_send(websocket, {
                        "type":"audio_end","tts_success":ok_count,"tts_errors":err_count,
                        "total_ms":int((time.perf_counter()-t0)*1000)})

            except WebSocketDisconnect: break
            except json.JSONDecodeError:
                await safe_send(websocket, {"type":"error","msg":"JSON không hợp lệ"})
            except Exception as e:
                log.error(f"WS error: {e}", exc_info=True)
                await safe_send(websocket, {"type":"error","msg":str(e)})

    log.info(f"🔌 WS disconnect: {client}")

# ── HTML ──────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PentaAI Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0b0e14;--sf:#121620;--sf2:#1a2030;
  --bd:#232b3e;--bd2:#2d3a52;
  --ac:#4f9cf9;--ac2:#7c3aed;
  --gn:#22d3a5;--am:#f59e0b;--rd:#f87171;--pk:#f472b6;
  --tx:#e2e8f0;--tx2:#8899bb;--tx3:#4a5a7a;
  --mono:'JetBrains Mono',monospace;--sans:'Syne',sans-serif;
}
html,body{height:100%;background:var(--bg);color:var(--tx);font-family:var(--sans);overflow:hidden}
.app{display:grid;grid-template-columns:292px 1fr;grid-template-rows:52px 1fr;height:100vh}

/* Topbar */
.topbar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;background:var(--sf);border-bottom:1px solid var(--bd);z-index:10}
.logo{font-size:15px;font-weight:800;letter-spacing:-.02em}.logo span{color:var(--ac)}
.vtag{font-family:var(--mono);font-size:10px;color:var(--tx3);
  background:var(--sf2);border:1px solid var(--bd);padding:2px 8px;border-radius:4px}
.topbar-r{display:flex;align-items:center;gap:12px}
.conn{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;color:var(--tx2)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--gn);flex-shrink:0}
.dot.r{background:var(--rd)}.dot.a{background:var(--am);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* Sidebar */
.sb{background:var(--sf);border-right:1px solid var(--bd);overflow-y:auto;display:flex;flex-direction:column}
.sb::-webkit-scrollbar{width:4px}
.sb::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:2px}
.sbs{padding:14px 16px;border-bottom:1px solid var(--bd)}
.slbl{font-family:var(--mono);font-size:9px;letter-spacing:.12em;color:var(--tx3);
  text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}

/* Status */
.scard{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:8px}
.srow{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.srow:last-child{margin-bottom:0}
.snm{font-family:var(--mono);font-size:11px;color:var(--tx2)}
.pill{font-family:var(--mono);font-size:9px;padding:2px 7px;border-radius:20px;font-weight:700;letter-spacing:.05em}
.ok{background:rgba(34,211,165,.15);color:var(--gn);border:1px solid rgba(34,211,165,.3)}
.err{background:rgba(248,113,113,.15);color:var(--rd);border:1px solid rgba(248,113,113,.3)}
.warn{background:rgba(245,158,11,.15);color:var(--am);border:1px solid rgba(245,158,11,.3)}
.info{background:rgba(79,156,249,.15);color:var(--ac);border:1px solid rgba(79,156,249,.3)}

/* TTS rows */
.trow{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.ten{font-family:var(--mono);font-size:10px;color:var(--tx2);flex:1}
.tdot{width:7px;height:7px;border-radius:50%;flex-shrink:0}

/* Hormone */
.hbars{display:flex;flex-direction:column;gap:6px}
.hrow{display:flex;align-items:center;gap:8px}
.hnm{font-family:var(--mono);font-size:9px;color:var(--tx3);width:82px;flex-shrink:0}
.htr{flex:1;height:4px;background:var(--bd);border-radius:2px;overflow:hidden}
.hfi{height:100%;border-radius:2px;transition:width .7s ease}
.hv{font-family:var(--mono);font-size:9px;color:var(--tx3);width:32px;text-align:right}

/* Emotion badge */
.embg{display:inline-flex;align-items:center;gap:6px;background:var(--sf2);
  border:1px solid var(--bd2);border-radius:20px;padding:3px 10px;
  font-family:var(--mono);font-size:10px;color:var(--ac)}

/* KB stats */
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.sbox{background:var(--sf2);border:1px solid var(--bd);border-radius:6px;padding:8px;text-align:center}
.sv{font-family:var(--mono);font-size:18px;font-weight:700;color:var(--ac)}
.sl{font-family:var(--mono);font-size:9px;color:var(--tx3);margin-top:2px}

/* Profile form */
.pf{display:flex;flex-direction:column;gap:8px}
.prow{display:flex;flex-direction:column;gap:4px}
.plbl{font-family:var(--mono);font-size:9px;color:var(--tx3)}
.pinp{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);
  border-radius:6px;padding:6px 10px;font-family:var(--mono);font-size:11px;outline:none;
  transition:border-color .2s;width:100%}
.pinp:focus{border-color:var(--ac)}
.phr{display:flex;gap:6px}
.psel{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx2);
  border-radius:6px;padding:6px 8px;font-family:var(--mono);font-size:11px;outline:none;flex:1}
.bsv{background:var(--ac);border:none;color:white;border-radius:6px;
  padding:6px 14px;font-family:var(--mono);font-size:10px;cursor:pointer;transition:background .2s}
.bsv:hover{background:#3b82f6}
.psaved{font-family:var(--mono);font-size:9px;color:var(--gn);display:none;margin-top:2px}

/* TTS controls */
.trow2{display:flex;align-items:center;justify-content:space-between;padding:6px 0}
.tl{font-family:var(--mono);font-size:11px;color:var(--tx2)}
.sw{position:relative;width:36px;height:20px;cursor:pointer}
.sw input{opacity:0;width:0;height:0}
.sw-t{position:absolute;inset:0;background:var(--bd2);border-radius:20px;transition:background .2s}
.sw input:checked+.sw-t{background:var(--ac)}
.sw-th{position:absolute;top:3px;left:3px;width:14px;height:14px;
  background:white;border-radius:50%;transition:transform .2s}
.sw input:checked+.sw-t .sw-th{transform:translateX(16px)}
.rsl{width:100%;accent-color:var(--ac);margin-top:4px}
.csel{width:100%;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx2);
  padding:5px 8px;border-radius:6px;font-family:var(--mono);font-size:10px;outline:none}

/* Chat */
.chat{display:flex;flex-direction:column;overflow:hidden}
.msgs{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px}
.msgs::-webkit-scrollbar{width:4px}
.msgs::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:2px}
.msg{display:flex;gap:10px;animation:mIn .25s ease-out}
@keyframes mIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.msg.u{flex-direction:row-reverse}
.av{width:30px;height:30px;border-radius:8px;flex-shrink:0;display:flex;
  align-items:center;justify-content:center;font-size:12px;font-weight:700}
.msg.ai .av{background:rgba(79,156,249,.15);color:var(--ac);border:1px solid rgba(79,156,249,.2)}
.msg.u .av{background:rgba(124,58,237,.15);color:var(--ac2);border:1px solid rgba(124,58,237,.2)}
.mb{max-width:72%;display:flex;flex-direction:column;gap:4px}
.msg.u .mb{align-items:flex-end}
.bbl{padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.6;word-break:break-word}
.msg.ai .bbl{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);border-radius:4px 12px 12px 12px}
.msg.u  .bbl{background:linear-gradient(135deg,#2563eb,#4f46e5);color:white;border-radius:12px 4px 12px 12px}
.mm{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:9px;color:var(--tx3)}
.lat{background:rgba(34,211,165,.1);color:var(--gn);border:1px solid rgba(34,211,165,.2);
  padding:1px 5px;border-radius:4px;font-size:9px}
.emm{background:rgba(79,156,249,.1);color:var(--ac);border:1px solid rgba(79,156,249,.2);
  padding:1px 5px;border-radius:4px;font-size:9px}

/* Typing */
.typing{display:none}.typing.on{display:flex}
.td-wrap{display:flex;gap:4px;padding:12px 16px}
.td{width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:td 1.2s infinite}
.td:nth-child(2){animation-delay:.2s}.td:nth-child(3){animation-delay:.4s}
@keyframes td{0%,80%,100%{transform:scale(1)}40%{transform:scale(1.3)}}

/* TTS bar */
.ttsbar{display:none;align-items:center;gap:8px;padding:8px 24px;
  background:rgba(79,156,249,.05);border-top:1px solid rgba(79,156,249,.1);
  font-family:var(--mono);font-size:11px;color:var(--ac)}
.ttsbar.on{display:flex}
.wave{display:flex;gap:2px;align-items:center;height:14px}
.wb{width:3px;background:var(--ac);border-radius:2px;animation:wv .8s infinite ease-in-out}
.wb:nth-child(1){height:4px;animation-delay:0s}.wb:nth-child(2){height:8px;animation-delay:.1s}
.wb:nth-child(3){height:14px;animation-delay:.2s}.wb:nth-child(4){height:8px;animation-delay:.1s}
.wb:nth-child(5){height:4px;animation-delay:0s}
@keyframes wv{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.8)}}

/* Input */
.inpbar{padding:16px 24px;background:var(--sf);border-top:1px solid var(--bd);
  display:flex;gap:10px;align-items:flex-end}
textarea#inp{width:100%;background:var(--sf2);border:1px solid var(--bd2);
  border-radius:10px;padding:11px 14px;color:var(--tx);font-family:var(--sans);
  font-size:14px;resize:none;min-height:44px;max-height:120px;outline:none;
  line-height:1.5;transition:border-color .2s}
textarea#inp:focus{border-color:var(--ac)}
textarea#inp::placeholder{color:var(--tx3)}
.sndbtn{width:44px;height:44px;border-radius:10px;flex-shrink:0;background:var(--ac);
  border:none;cursor:pointer;color:white;font-size:16px;display:flex;
  align-items:center;justify-content:center;transition:background .2s,transform .1s}
.sndbtn:hover{background:#3b82f6}.sndbtn:active{transform:scale(.95)}

/* Buttons */
.bgh{background:none;border:1px solid var(--bd2);color:var(--tx2);border-radius:6px;
  padding:5px 10px;cursor:pointer;font-family:var(--mono);font-size:10px;transition:all .15s}
.bgh:hover{background:var(--sf2);color:var(--tx)}
.ibtn{background:none;border:none;color:var(--tx3);cursor:pointer;font-size:14px;
  padding:2px;transition:color .15s}
.ibtn:hover{color:var(--ac)}

/* Modal */
#modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
  z-index:100;align-items:center;justify-content:center}
#modal-bg.on{display:flex}
.modal{background:var(--sf);border:1px solid var(--bd2);border-radius:16px;
  padding:24px;width:480px;max-height:80vh;overflow-y:auto}
.modal::-webkit-scrollbar{width:4px}
.modal::-webkit-scrollbar-thumb{background:var(--bd2)}
.mtitle{font-size:16px;font-weight:800;color:var(--tx);margin-bottom:16px;
  display:flex;align-items:center;gap:8px}
.xbtn{margin-left:auto;background:none;border:none;color:var(--tx3);cursor:pointer;font-size:18px}
.gph{font-family:var(--mono);font-size:9px;color:var(--tx3);letter-spacing:.12em;
  text-transform:uppercase;padding:10px 0 5px;border-bottom:1px solid var(--bd);margin-bottom:4px}
.ci{display:flex;align-items:flex-start;gap:10px;padding:6px 0;
  border-bottom:1px solid rgba(255,255,255,.03)}
.cn{font-family:var(--mono);font-size:11px;color:var(--tx2);flex:1}
.cs{font-family:var(--mono);font-size:10px}
.cs.ok{color:var(--gn)}.cs.err{color:var(--rd)}.cs.warn{color:var(--am)}
.ce{font-family:var(--mono);font-size:9px;color:var(--tx3);padding-left:16px;padding-bottom:3px}
.md{width:6px;height:6px;border-radius:50%;flex-shrink:0;margin-top:3px}
.md.ok{background:var(--gn)}.md.err{background:var(--rd)}.md.warn{background:var(--am)}

/* Welcome */
.welcome{text-align:center;padding:32px 24px;color:var(--tx3);font-family:var(--mono);
  font-size:12px;line-height:1.8;border:1px dashed var(--bd);border-radius:12px;
  margin:auto;max-width:400px}
.welcome h3{font-family:var(--sans);font-size:15px;color:var(--tx2);font-weight:600;margin-bottom:8px}
</style>
</head>
<body>
<div class="app">

<!-- Topbar -->
<header class="topbar">
  <div style="display:flex;align-items:center;gap:10px">
    <div class="logo">Penta<span>AI</span></div>
    <span class="vtag">v5.1</span>
  </div>
  <div class="topbar-r">
    <button class="bgh" onclick="openModal()">⬡ Kiểm tra hệ thống</button>
    <div class="conn">
      <div class="dot" id="conn-dot"></div>
      <span id="conn-txt">Đang kết nối...</span>
    </div>
  </div>
</header>

<!-- Sidebar -->
<aside class="sb">

  <!-- Trạng thái -->
  <div class="sbs">
    <div class="slbl">Trạng thái <button class="ibtn" onclick="refreshHealth()" title="Làm mới">↻</button></div>
    <div class="scard">
      <div class="srow"><span class="snm">AI Engine</span><span class="pill" id="p-ai">…</span></div>
      <div class="srow"><span class="snm">Embedder</span><span class="pill" id="p-emb">…</span></div>
      <div class="srow"><span class="snm">Modules</span><span class="pill" id="p-mod">…</span></div>
      <div class="srow"><span class="snm">Cảm xúc</span>
        <div class="embg"><span id="em-ic">🌙</span><span id="em-tx">—</span></div></div>
    </div>
    <!-- TTS engines -->
    <div style="margin-top:4px">
      <div class="slbl" style="margin-bottom:6px">TTS Engine</div>
      <div class="trow">
        <div class="tdot" id="d-vi" style="background:var(--tx3)"></div>
        <span class="ten">Valtec (Tiếng Việt)</span>
        <span class="pill" id="p-vi">…</span>
      </div>
      <div class="trow">
        <div class="tdot" id="d-jp" style="background:var(--tx3)"></div>
        <span class="ten">Voicevox (JP / EN)</span>
        <span class="pill" id="p-jp">…</span>
      </div>
      <div class="trow">
        <div class="tdot" id="d-ws" style="background:var(--tx3)"></div>
        <span class="ten">Web Speech (fallback)</span>
        <span class="pill" id="p-ws">…</span>
      </div>
    </div>
  </div>

  <!-- Danh tính người dùng -->
  <div class="sbs">
    <div class="slbl">Danh tính người dùng</div>
    <div class="pf">
      <div class="prow">
        <span class="plbl">Tên của bạn</span>
        <input class="pinp" id="pf-name" type="text" placeholder="Nhập tên..." maxlength="40">
      </div>
      <div class="prow">
        <span class="plbl">Đại từ xưng hô (AI gọi bạn bằng)</span>
        <div class="phr">
          <select class="psel" id="pf-pronoun">
            <option value="bạn">bạn</option>
            <option value="anh">anh</option>
            <option value="chị">chị</option>
            <option value="em">em</option>
            <option value="mình">mình</option>
            <option value="tôi">tôi</option>
          </select>
          <button class="bsv" onclick="saveProfile()">Lưu</button>
        </div>
      </div>
      <div class="psaved" id="pf-saved">✓ Đã lưu thành công</div>
    </div>
  </div>

  <!-- Hormone -->
  <div class="sbs">
    <div class="slbl">Hormone</div>
    <div class="hbars" id="h-bars">
      <div style="font-family:var(--mono);font-size:10px;color:var(--tx3)">Đang tải...</div>
    </div>
  </div>

  <!-- KB Stats -->
  <div class="sbs">
    <div class="slbl">Knowledge Base</div>
    <div class="sgrid">
      <div class="sbox"><div class="sv" id="s-ph">—</div><div class="sl">PHRASES</div></div>
      <div class="sbox"><div class="sv" id="s-fa">—</div><div class="sl">FACTS</div></div>
      <div class="sbox"><div class="sv" id="s-pa">—</div><div class="sl">PATTERNS</div></div>
      <div class="sbox"><div class="sv" id="s-sy">—</div><div class="sl">SYNONYMS</div></div>
    </div>
  </div>

  <!-- TTS Controls -->
  <div class="sbs">
    <div class="slbl">Điều khiển giọng nói</div>
    <div class="trow2">
      <span class="tl">Bật TTS</span>
      <label class="sw"><input type="checkbox" id="tts-on" checked>
        <div class="sw-t"><div class="sw-th"></div></div></label>
    </div>
    <div style="margin-top:4px">
      <div style="display:flex;justify-content:space-between;margin-bottom:3px">
        <span style="font-family:var(--mono);font-size:10px;color:var(--tx3)">Tốc độ</span>
        <span style="font-family:var(--mono);font-size:10px;color:var(--tx2)" id="rate-lbl">1.0×</span>
      </div>
      <input type="range" class="rsl" id="tts-rate" min="0.5" max="2" step="0.1" value="1"
             oninput="document.getElementById('rate-lbl').textContent=parseFloat(this.value).toFixed(1)+'×'">
    </div>
    <div style="margin-top:10px">
      <div class="plbl" style="margin-bottom:4px">Speaker Valtec (VI)</div>
      <select id="spk-sel" class="csel">
        <option value="NF">NF — Nữ Miền Nam</option>
        <option value="NN">NN — Nam Miền Nam</option>
        <option value="NB">NB — Nam Miền Bắc</option>
        <option value="FB">FB — Nữ Miền Bắc</option>
      </select>
    </div>
    <div style="margin-top:8px">
      <div class="plbl" style="margin-bottom:4px">Giọng Web Speech (fallback)</div>
      <select id="ws-voice" class="csel"><option value="">Đang tải giọng...</option></select>
    </div>
  </div>

</aside>

<!-- Chat -->
<main class="chat">
  <div class="msgs" id="msgs">
    <div class="welcome">
      <h3>PentaAI đã sẵn sàng</h3>
      Thiết lập tên của bạn ở thanh bên trái<br>
      để AI xưng hô đúng.<br><br>
      Dạy AI:<br><code>nếu nghe "A" thì nói "B"</code>
    </div>
  </div>

  <div class="ttsbar" id="ttsbar">
    <div class="wave"><div class="wb"></div><div class="wb"></div><div class="wb"></div>
      <div class="wb"></div><div class="wb"></div></div>
    <span id="ttsbar-tx">Đang đọc...</span>
    <button class="bgh" onclick="stopAll()" style="margin-left:auto;padding:3px 8px">Dừng</button>
  </div>

  <div class="typing" id="typing">
    <div class="msg ai" style="padding:0 24px 8px">
      <div class="av">AI</div>
      <div class="bbl" style="padding:8px 14px">
        <div class="td-wrap"><div class="td"></div><div class="td"></div><div class="td"></div></div>
      </div>
    </div>
  </div>

  <div class="inpbar">
    <textarea id="inp" rows="1" placeholder="Nhắn tin... (Enter gửi, Shift+Enter xuống dòng)"></textarea>
    <button class="sndbtn" onclick="send()">➤</button>
  </div>
</main>
</div>

<!-- Modal -->
<div id="modal-bg">
  <div class="modal">
    <div class="mtitle">⬡ Kiểm tra hệ thống
      <button class="xbtn" onclick="closeModal()">✕</button></div>
    <div id="modal-body">
      <div style="font-family:var(--mono);font-size:12px;color:var(--tx3);text-align:center;padding:20px">Đang tải...</div>
    </div>
  </div>
</div>

<script>
const EICONS={neutral:'😐',happy:'😊',excited_warm:'🤩',content_loving:'🥰',
  curious_energetic:'🧐',calm_confident:'😌',tired_uneasy:'😪',mildly_stressed:'😟',
  sleepy_calm:'😴',low_energy:'🔋',stressed:'😰',anxious:'😨',guarded:'🫤',surprised_alert:'😲'};
const HC={dopamine:'#4f9cf9',serotonin:'#22d3a5',oxytocin:'#f472b6',
  cortisol:'#f87171',adrenaline:'#fb923c',GABA:'#a78bfa',norepinephrine:'#fbbf24'};

let ws,wsOk=false,wsVoices=[],audioQ=[],playing=false,ttsViOk=false,ttsJpOk=false;

/* ── WebSocket ── */
function connect(){
  const proto=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(`${proto}://${location.host}/ws/chat`);
  ws.onopen=()=>{wsOk=true;setConn(true);refreshHealth();refreshStats();loadProfile();loadVoices()};
  ws.onclose=()=>{wsOk=false;setConn(false);setTimeout(connect,3000)};
  ws.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.type==='response'){
      hideTyping();appendAI(d.text,d.ai_latency_ms,d.emotional_state);
      if(d.emotional_state) setEmotion(d.emotional_state);
      ttsViOk=!!d.tts_vi_ready; ttsJpOk=!!d.tts_jp_ready;
      // Nếu cả hai engine không có → Web Speech ngay
      if(!ttsViOk&&!ttsJpOk&&document.getElementById('tts-on').checked) wsSay(d.text);
    } else if(d.type==='audio_chunk'){
      playChunk(d.audio_b64);
    } else if(d.type==='tts_fallback'){
      // Server không có engine cho ngôn ngữ này
      if(document.getElementById('tts-on').checked) wsSay(d.text);
    } else if(d.type==='tts_start'){
      showBar('Đang chuẩn bị giọng đọc...');
    } else if(d.type==='tts_progress'){
      showBar(`Đang đọc (${d.current}/${d.total}): ${d.preview}`);
    } else if(d.type==='audio_end'){
      if(!audioQ.length&&!playing) hideBar();
    } else if(d.type==='error'){
      hideTyping(); appendSys('⚠️ '+d.msg);
    }
  };
}

function setConn(ok){
  document.getElementById('conn-dot').className='dot'+(ok?'':' r');
  document.getElementById('conn-txt').textContent=ok?'Kết nối':'Mất kết nối – thử lại...';
}

/* ── Send ── */
function send(){
  const ta=document.getElementById('inp'),text=ta.value.trim();
  if(!text||!wsOk) return;
  stopAll(); appendUser(text);
  ta.value=''; ta.style.height='auto'; showTyping();
  ws.send(JSON.stringify({
    text, tts:document.getElementById('tts-on').checked,
    speaker:document.getElementById('spk-sel').value,
    speed:parseFloat(document.getElementById('tts-rate').value)
  }));
}

/* ── Messages ── */
const getMsgs=()=>document.getElementById('msgs');
const scrollBot=()=>{const c=getMsgs();c.scrollTop=c.scrollHeight};
const rmWelcome=()=>{const w=getMsgs().querySelector('.welcome');if(w)w.remove()};
const esc=t=>t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
const nowt=()=>new Date().toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'});

function appendUser(text){
  rmWelcome();
  const d=document.createElement('div'); d.className='msg u';
  d.innerHTML=`<div class="av">U</div><div class="mb"><div class="bbl">${esc(text)}</div>
    <div class="mm">${nowt()}</div></div>`;
  getMsgs().appendChild(d); scrollBot();
}
function appendAI(text,ms,em){
  rmWelcome();
  let meta=`<span>${nowt()}</span>`;
  if(ms) meta+=`<span class="lat">${ms}ms</span>`;
  if(em) meta+=`<span class="emm">${EICONS[em]||'🌀'} ${em}</span>`;
  const d=document.createElement('div'); d.className='msg ai';
  d.innerHTML=`<div class="av">AI</div><div class="mb"><div class="bbl">${esc(text)}</div>
    <div class="mm">${meta}</div></div>`;
  getMsgs().appendChild(d); scrollBot();
}
function appendSys(text){
  const d=document.createElement('div');
  d.style.cssText='font-family:var(--mono);font-size:11px;color:var(--rd);text-align:center;padding:8px';
  d.textContent=text; getMsgs().appendChild(d); scrollBot();
}
function showTyping(){document.getElementById('typing').classList.add('on');scrollBot()}
function hideTyping(){document.getElementById('typing').classList.remove('on')}

/* ── Server WAV playback ── */
function playChunk(b64){
  const bin=atob(b64),arr=new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
  audioQ.push(URL.createObjectURL(new Blob([arr],{type:'audio/wav'})));
  if(!playing) processQ();
}
async function processQ(){
  if(!audioQ.length){playing=false;hideBar();return}
  playing=true; showBar('Đang phát...');
  const a=new Audio(audioQ.shift());
  a.onended=()=>processQ(); a.onerror=()=>processQ();
  try{await a.play()}catch(e){processQ()}
}

/* ── Web Speech fallback ── */
let wsUtter=null;
function wsSay(text){
  const synth=window.speechSynthesis; if(!synth) return;
  wsStop();
  const clean=text.replace(/\(.*?\)/g,'').replace(/<[^>]*>/g,'').trim();
  if(!clean) return;
  const u=new SpeechSynthesisUtterance(clean);
  u.rate=parseFloat(document.getElementById('tts-rate').value)||1;
  const idx=parseInt(document.getElementById('ws-voice').value);
  if(!isNaN(idx)&&wsVoices[idx]) u.voice=wsVoices[idx];
  u.onstart=()=>showBar('[Web Speech] '+clean.substring(0,30)+'...');
  u.onend=u.onerror=()=>{hideBar();wsUtter=null};
  wsUtter=u; synth.speak(u);
}
function wsStop(){if(window.speechSynthesis) window.speechSynthesis.cancel(); wsUtter=null}
function stopAll(){wsStop();audioQ=[];playing=false;hideBar()}
function showBar(t){document.getElementById('ttsbar').classList.add('on');document.getElementById('ttsbar-tx').textContent=t}
function hideBar(){document.getElementById('ttsbar').classList.remove('on')}

/* ── Health ── */
async function refreshHealth(){
  try{
    const d=await fetch('/api/health').then(r=>r.json());
    pill('p-ai',d.ai_ready?'ok':'err',d.ai_ready?'OK':'Lỗi');
    pill('p-emb','ok',(d.embedder_backend||'tfidf').toUpperCase());
    const tot=(d.modules_ok||0)+(d.modules_error||0),pct=tot?Math.round(d.modules_ok/tot*100):0;
    pill('p-mod',pct>=80?'ok':pct>=50?'warn':'err',`${d.modules_ok}/${tot}`);
    if(d.emotional_state) setEmotion(d.emotional_state);
    if(d.hormone_levels)  drawHormones(d.hormone_levels);
    setTTSStatus('vi',!!d.tts_vi,'d-vi','p-vi');
    setTTSStatus('jp',!!d.tts_jp,'d-jp','p-jp');
    const wsOK=!!window.speechSynthesis;
    document.getElementById('d-ws').style.background=wsOK?'var(--gn)':'var(--rd)';
    pill('p-ws',wsOK?'ok':'err',wsOK?'Có sẵn':'Không hỗ trợ');
  }catch(e){}
}
function setTTSStatus(type,ready,dotId,pillId){
  document.getElementById(dotId).style.background=ready?'var(--gn)':'var(--rd)';
  pill(pillId,ready?'ok':'err',ready?'Hoạt động':'Không có');
}
function pill(id,cls,lbl){
  const e=document.getElementById(id);
  e.className='pill '+cls; e.textContent=lbl;
}
function setEmotion(s){
  document.getElementById('em-ic').textContent=EICONS[s]||'🌀';
  document.getElementById('em-tx').textContent=s;
}
function drawHormones(lvl){
  const c=document.getElementById('h-bars'); c.innerHTML='';
  ['dopamine','serotonin','oxytocin','cortisol','adrenaline','GABA','norepinephrine'].forEach(h=>{
    const v=lvl[h]??0,pct=Math.min(100,Math.round(v/1.5*100)),col=HC[h]||'#4f9cf9';
    c.innerHTML+=`<div class="hrow"><span class="hnm">${h.substring(0,12)}</span>
      <div class="htr"><div class="hfi" style="width:${pct}%;background:${col}"></div></div>
      <span class="hv">${v.toFixed(2)}</span></div>`;
  });
}

/* ── Stats ── */
async function refreshStats(){
  try{
    const d=await fetch('/api/stats').then(r=>r.json()); if(d.error) return;
    document.getElementById('s-ph').textContent=d.total_phrases ??d.phrases ??'—';
    document.getElementById('s-fa').textContent=d.total_facts   ??d.facts   ??'—';
    document.getElementById('s-pa').textContent=d.total_patterns??d.patterns??'—';
    document.getElementById('s-sy').textContent=d.total_synonyms??d.synonyms??'—';
  }catch(e){}
}

/* ── Profile ── */
async function loadProfile(){
  try{
    const d=await fetch('/api/profile').then(r=>r.json());
    if(d.name) document.getElementById('pf-name').value=d.name;
    if(d.pronoun){
      const sel=document.getElementById('pf-pronoun');
      for(const o of sel.options) if(o.value===d.pronoun){sel.value=d.pronoun;break}
    }
  }catch(e){}
}
async function saveProfile(){
  const name=document.getElementById('pf-name').value.trim();
  const pronoun=document.getElementById('pf-pronoun').value;
  try{
    await fetch('/api/profile',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,pronoun})});
    const s=document.getElementById('pf-saved');
    s.style.display='block';setTimeout(()=>s.style.display='none',2000);
  }catch(e){alert('Lỗi: '+e.message)}
}

/* ── Modal ── */
async function openModal(){
  document.getElementById('modal-bg').classList.add('on');
  document.getElementById('modal-body').innerHTML=
    '<div style="font-family:var(--mono);font-size:12px;color:var(--tx3);text-align:center;padding:20px">⟳ Đang quét...</div>';
  try{
    const d=await fetch('/api/modules').then(r=>r.json());
    renderModal(d.modules);
  }catch(e){
    document.getElementById('modal-body').innerHTML=
      `<div style="color:var(--rd);font-family:var(--mono);font-size:12px;padding:12px">Lỗi: ${e.message}</div>`;
  }
}
function renderModal(mods){
  const groups={core:'⚙ Core',engine:'🔧 Engine',hormone:'🧬 Hormone',optional:'📦 Optional'};
  const grp={core:[],engine:[],hormone:[],optional:[]};
  for(const[n,i] of Object.entries(mods))(grp[i.group]||grp.optional).push({name:n,...i});
  const total=Object.values(mods).length,ok=Object.values(mods).filter(v=>v.status==='ok').length;
  let html=`<div style="display:flex;gap:8px;margin-bottom:14px">
    <div class="sbox" style="flex:1;background:rgba(34,211,165,.08);border-color:rgba(34,211,165,.3)">
      <div class="sv" style="color:var(--gn)">${ok}</div><div class="sl">OK</div></div>
    <div class="sbox" style="flex:1;background:rgba(248,113,113,.08);border-color:rgba(248,113,113,.3)">
      <div class="sv" style="color:var(--rd)">${total-ok}</div><div class="sl">LỖI</div></div>
    <div class="sbox" style="flex:1"><div class="sv">${Math.round(ok/total*100)}%</div>
      <div class="sl">ĐẦY ĐỦ</div></div></div>`;
  for(const[gk,gl] of Object.entries(groups)){
    const items=grp[gk]; if(!items?.length) continue;
    html+=`<div class="gph">${gl}</div>`;
    for(const it of items){
      const isOk=it.status==='ok',isWarn=it.status==='missing_class';
      const c=isOk?'ok':isWarn?'warn':'err';
      html+=`<div class="ci"><div class="md ${c}"></div>
        <div class="cn">${it.name}</div>
        <div class="cs ${c}">${isOk?'✓ ok':isWarn?'△ warn':'✗ '+it.status}</div></div>`;
      if(it.error) html+=`<div class="ce">${it.error}</div>`;
    }
  }
  document.getElementById('modal-body').innerHTML=html;
}
function closeModal(){document.getElementById('modal-bg').classList.remove('on')}
document.getElementById('modal-bg').addEventListener('click',e=>{if(e.target===e.currentTarget)closeModal()});

/* ── Web Speech voices ── */
function loadVoices(){
  const synth=window.speechSynthesis; if(!synth) return;
  function fill(){
    wsVoices=synth.getVoices();
    const sel=document.getElementById('ws-voice'); sel.innerHTML='';
    const vi=wsVoices.filter(v=>v.lang.startsWith('vi'));
    const rest=wsVoices.filter(v=>!v.lang.startsWith('vi'));
    [...vi,...rest].forEach(v=>{
      const idx=wsVoices.indexOf(v),o=document.createElement('option');
      o.value=idx; o.textContent=`${v.lang} — ${v.name}`;
      if(v.lang.startsWith('vi')) o.style.color='#22d3a5';
      sel.appendChild(o);
    });
  }
  fill();
  if(synth.onvoiceschanged!==undefined) synth.onvoiceschanged=fill;
}

/* ── Input ── */
const ta=document.getElementById('inp');
ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
ta.addEventListener('input',()=>{ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,120)+'px'});

setInterval(()=>{if(wsOk)refreshHealth()},30000);
connect();
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

if __name__ == "__main__":
    import uvicorn
    log.info("=" * 55)
    log.info("🤖 PentaAI Web Server v5.1")
    log.info(f"📡 http://{AI_HOST}:{AI_PORT}")
    log.info("🔊 TTS: Valtec (VI) + Voicevox (JP) + Web Speech fallback")
    log.info("👤 User profile: /api/profile")
    log.info("=" * 55)
    uvicorn.run(app, host=AI_HOST, port=AI_PORT, log_level="info")
