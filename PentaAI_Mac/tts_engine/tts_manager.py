#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS Manager — module tổng hợp tiếng nói đa ngôn ngữ.

Hỗ trợ:
  VI  → Valtec (fallback: Edge TTS vi-VN-HoaiMyNeural)
  JP  → VoiceVox (fallback: Edge TTS ja-JP-NanamiNeural)
  ZH  → Edge TTS zh-CN-XiaoxiaoNeural
  KO  → Edge TTS ko-KR-SunHiNeural
  EN  → Edge TTS en-US-AvaNeural

Dùng bởi ai_server.py — không phụ thuộc vào FastAPI.
"""

import audioop
import logging
import os
import re
import struct
import sys
from typing import Optional, Tuple

log = logging.getLogger("TTS_Manager")

# ─── Đường dẫn ─────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))   # tts_engine/
_ROOT   = os.path.dirname(_HERE)                        # PentaAI_Mac/

sys.path.append(os.path.join(_HERE, "voicevox"))
sys.path.append(os.path.join(_HERE, "valtec"))

# ─── Singleton engines ─────────────────────────────────────────────────────
_vv_engine   = None   # VoicevoxEngine
_valtec_tts  = None   # ValtecEngine


# ═══════════════════════════════════════════════════════════════════════════════
#  KHỞI TẠO ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def init_voicevox():
    """Khởi tạo VoiceVox engine (tiếng Nhật). Gọi an toàn nhiều lần."""
    global _vv_engine
    if _vv_engine is None:
        try:
            from voicevox_engine import VoicevoxEngine
            _vv_engine = VoicevoxEngine(os.path.join(_HERE, "voicevox"))
            log.info("✅ Voicevox sẵn sàng")
        except Exception as e:
            log.warning(f"[TTS] Voicevox không khả dụng: {e}")
    return _vv_engine


def init_valtec():
    """Khởi tạo Valtec engine (tiếng Việt). Gọi an toàn nhiều lần."""
    global _valtec_tts
    if _valtec_tts is None:
        try:
            from valtec_server import ValtecEngine
            _valtec_tts = ValtecEngine()
            log.info("✅ Valtec sẵn sàng")
        except Exception as e:
            log.warning(f"[TTS] Valtec không khả dụng: {e}")
    return _valtec_tts


def reset_engines():
    """Reset cả hai engine về None (dùng sau upgrade module, reinit bằng init_*)."""
    global _vv_engine, _valtec_tts
    _vv_engine = None
    _valtec_tts = None
    log.info("[TTS] Engines đã được reset")


def init_all():
    """Khởi tạo cả Voicevox + Valtec."""
    init_voicevox()
    init_valtec()


def get_voicevox():
    return _vv_engine


def get_valtec():
    return _valtec_tts


# ═══════════════════════════════════════════════════════════════════════════════
#  NHẬN DIỆN NGÔN NGỮ
# ═══════════════════════════════════════════════════════════════════════════════

def detect_language(text: str) -> str:
    """
    Tự động nhận diện ngôn ngữ từ text.
    Thứ tự ưu tiên: KO → JP → ZH → VI → EN → vi (mặc định)

    Logic:
      - KO : có ký tự Hangul (한글)
      - JP : có Hiragana / Katakana (có thể kèm CJK)
      - ZH : có CJK nhưng KHÔNG có Hiragana/Katakana (loại JP ra)
      - VI : có dấu thanh điệu tiếng Việt HOẶC từ khoá thông dụng
      - EN : còn lại có ký tự Latin
      - vi : mặc định nếu không rõ
    """
    txt = text or ""

    # Korean — Hangul syllables / Jamo
    if re.search(r'[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]', txt):
        return 'ko'
    # Japanese — hiragana or katakana
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', txt):
        return 'jp'
    # Chinese — CJK without any kana
    if re.search(r'[\u4E00-\u9FFF\u3400-\u4DBF]', txt):
        return 'zh'

    lower = txt.lower()
    # Vietnamese — diacritics
    if re.search(
        r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]',
        lower,
    ):
        return 'vi'
    # Vietnamese — common informal keywords (ASCII typed without diacritics)
    if re.search(
        r'\b(anh|em|chi|minh|ban|oi|ơi|nha|nhe|ne|nè|roi|thoi|di|nhé|đây|đó|'
        r'lich|thu|hom nay|duoc|được|vay|vậy|sao|the|thế|lam|làm|ok nha|uh|uhm)\b',
        lower,
    ):
        return 'vi'

    return 'en' if re.search(r'[a-zA-Z]', txt) else 'vi'


# ═══════════════════════════════════════════════════════════════════════════════
#  AUDIO HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def resample_wav(wav_bytes: bytes, target_rate: int = 44100) -> bytes:
    """Chuyển sample rate WAV về target_rate mà không dùng thư viện bên ngoài."""
    try:
        if len(wav_bytes) < 44:
            return wav_bytes
        channels        = struct.unpack('<H', wav_bytes[22:24])[0]
        sample_rate     = struct.unpack('<I', wav_bytes[24:28])[0]
        bits_per_sample = struct.unpack('<H', wav_bytes[34:36])[0]
        if sample_rate == target_rate:
            return wav_bytes
        if bits_per_sample != 16:
            return wav_bytes
        offset = 12
        while offset + 8 <= len(wav_bytes):
            if wav_bytes[offset:offset + 4] == b'data':
                break
            offset += 8 + struct.unpack('<I', wav_bytes[offset + 4:offset + 8])[0]
        else:
            return wav_bytes
        chunk_size = struct.unpack('<I', wav_bytes[offset + 4:offset + 8])[0]
        pcm = wav_bytes[offset + 8: offset + 8 + chunk_size]
        pcm, _ = audioop.ratecv(pcm, 2, channels, sample_rate, target_rate, None)
        header = bytearray(wav_bytes[:44])
        struct.pack_into('<I', header,  4, 36 + len(pcm))
        struct.pack_into('<I', header, 24, target_rate)
        struct.pack_into('<I', header, 28, target_rate * channels * 2)
        struct.pack_into('<I', header, 40, len(pcm))
        return bytes(header) + pcm
    except Exception:
        return wav_bytes


# ═══════════════════════════════════════════════════════════════════════════════
#  TỔNG HỢP AUDIO
# ═══════════════════════════════════════════════════════════════════════════════

async def _edge_tts(text: str, voice: str = "en-US-AvaNeural", rate: float = 1.0) -> bytes:
    """Tổng hợp via Edge TTS (Microsoft online)."""
    try:
        import edge_tts
        r_str = f"{int((rate - 1) * 100):+d}%"
        comm  = edge_tts.Communicate(text, voice, rate=r_str)
        data  = b""
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                data += chunk["data"]
        return data
    except Exception as e:
        log.error(f"[Edge-TTS] {e}")
        return b""


async def synth_vi(text: str, speaker: str = "NF", speed: float = 1.0) -> bytes:
    """Tiếng Việt: Valtec (offline) → Edge TTS fallback."""
    import asyncio
    valtec = get_valtec()
    if valtec:
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, lambda: valtec._raw_synth(text, speaker, speed)
            )
            return resample_wav(raw)
        except Exception as e:
            log.warning(f"[TTS-VI] Valtec lỗi: {e}")
    return await _edge_tts(text, voice="vi-VN-HoaiMyNeural", rate=speed)


async def synth_jp(
    text: str,
    speed: float = 1.0,
    speaker_id: int = -1,
    strict: bool = True,
) -> bytes:
    """
    Tiếng Nhật: VoiceVox (offline) → Edge TTS fallback.

    speaker_id : style ID của VoiceVox (-1 = dùng model đầu tiên)
    strict     : True → không fallback sang Edge khi VoiceVox chưa sẵn
    """
    import asyncio
    vv = get_voicevox()
    if vv:
        try:
            from voicevox_engine import SynthParams
            loop   = asyncio.get_event_loop()
            models = vv.scan_models()
            vvm    = models[0]["vvm"]
            sp     = SynthParams(speed=speed)
            if speaker_id >= 0:
                try:
                    from voicevox_core import METAS
                    for meta in METAS:
                        for style in meta.styles:
                            if style.id == speaker_id:
                                vvm = f"{meta.speaker_uuid}.vvm"
                                break
                    sp.style_idx = speaker_id
                except Exception:
                    pass
            raw = await loop.run_in_executor(None, lambda: vv.get_audio(text, vvm, sp))
            return resample_wav(raw)
        except Exception as e:
            log.warning(f"[TTS-JP] VoiceVox lỗi: {e}")
    if strict:
        log.warning("[TTS-JP] Bỏ qua — VoiceVox chưa sẵn (strict mode)")
        return b""
    return await _edge_tts(text, voice="ja-JP-NanamiNeural", rate=speed)


def list_voicevox_speakers() -> list:
    """
    Trả về danh sách tất cả speaker/style VoiceVox đang tải.
    [{"id": int, "name": str, "style": str, "label": str}, ...]
    """
    try:
        from voicevox_core import METAS
        result = []
        for meta in METAS:
            for style in meta.styles:
                result.append({
                    "id":    style.id,
                    "name":  meta.name,
                    "style": style.name,
                    "label": f"{meta.name} – {style.name} (ID {style.id})",
                })
        return result
    except Exception:
        return []


def list_valtec_speakers() -> list:
    """Trả về danh sách speaker Valtec (tiếng Việt) đang tải. [] nếu chưa sẵn."""
    valtec = get_valtec()
    if valtec is None:
        return []
    try:
        spks = valtec.tts.list_speakers()
        return list(spks) if spks else []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTING CHÍNH
# ═══════════════════════════════════════════════════════════════════════════════

async def synthesize(
    text:                str,
    speaker:             str           = "NF",
    speed:               float         = 1.0,
    force_lang:          Optional[str] = None,
    strict:              bool          = True,
    zh_voice:            str           = "zh-CN-XiaoxiaoNeural",
    ko_voice:            str           = "ko-KR-SunHiNeural",
    voicevox_speaker_id: int           = -1,
) -> Tuple[bytes, bool]:
    """
    Tổng hợp âm thanh theo ngôn ngữ.

    Trả về (wav_bytes, is_edge_tts):
      is_edge_tts=False → audio từ engine offline (Valtec / VoiceVox)
      is_edge_tts=True  → audio từ Edge TTS online

    Params:
      force_lang : ép ngôn ngữ ('vi'|'jp'|'zh'|'ko'|'en'), bỏ auto-detect
      strict     : True → không fallback chéo engine khi offline engine lỗi
      zh_voice   : giọng Edge TTS cho tiếng Trung
      ko_voice   : giọng Edge TTS cho tiếng Hàn
    """
    lang = force_lang or detect_language(text)

    if lang == 'vi':
        valtec = get_valtec()
        if valtec:
            return await synth_vi(text, speaker, speed), False
        if strict:
            log.warning("[TTS] Bỏ qua câu VI vì Valtec chưa sẵn (strict mode)")
            return b"", False
        return await _edge_tts(text, voice="vi-VN-HoaiMyNeural", rate=speed), True

    if lang == 'jp':
        wav = await synth_jp(text, speed, speaker_id=voicevox_speaker_id, strict=strict)
        return wav, (wav == b"" or get_voicevox() is None)

    if lang == 'zh':
        return await _edge_tts(text, voice=zh_voice or "zh-CN-XiaoxiaoNeural", rate=speed), True

    if lang == 'ko':
        return await _edge_tts(text, voice=ko_voice or "ko-KR-SunHiNeural", rate=speed), True

    # EN / mặc định
    return await _edge_tts(text, rate=speed), True
