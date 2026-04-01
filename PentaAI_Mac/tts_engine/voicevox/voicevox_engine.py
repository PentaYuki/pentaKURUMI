# ╔══════════════════════════════════════════════════════════════╗
# ║  🌸  VoiceVox Engine  —  Zero Latency Edition v5 (0.15.0)    ║
# ╚══════════════════════════════════════════════════════════════╝

import ctypes, gc, os, queue, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from voicevox_core import VoicevoxCore, METAS
except ImportError:
    print("❌ Không tìm thấy voicevox_core! Vui lòng cài đặt bản 0.15.0")
    VoicevoxCore = None
    METAS = []

IDLE_TIMEOUT   = 900
N_STARTER      = "ん"
CHUNK_TIMEOUT  = 8.0
LOAD_TIMEOUT   = 15.0
MAX_CHUNK_JP   = 20
MAX_CHUNK_MIX  = 50

_RE_JP_SEP    = re.compile(r'[。、！？…\n]+')
_RE_HAS_JP    = re.compile(r'[\u3000-\u9fff\uff00-\uffef]')
_RE_LATIN     = re.compile(r'[a-zA-Z]{3,}')
_RE_MIXED_SEP = re.compile(r'[。、！？…\n,，.．\s]+')

@dataclass
class SynthParams:
    speed:      float = 1.0
    pitch:      float = 0.0
    intonation: float = 1.0
    volume:     float = 1.0
    style_idx:  int   = 0

class TextValidator:
    @staticmethod
    def check(text: str) -> tuple[bool, str]:
        t = text.strip()
        if not t:
            return False, "Text rỗng"
        if not _RE_HAS_JP.search(t):
            latin = _RE_LATIN.findall(t)
            if latin:
                return False, (
                    f"VoiceVox chỉ đọc tiếng Nhật! "
                    f"Phát hiện: '{', '.join(latin[:3])}'"
                )
            return False, "Text không chứa ký tự tiếng Nhật"
        return True, ""

    @staticmethod
    def clean(text: str) -> str:
        t = re.sub(r'[\x00-\x1f\x7f]', '', text)
        t = t.replace('...', '…').replace('--', '—')
        t = re.sub(r'https?://\S+', '', t)
        return t.strip()

    @staticmethod
    def split_chunks(text: str) -> list[str]:
        is_mixed = bool(_RE_LATIN.search(text))
        sep      = _RE_MIXED_SEP if is_mixed else _RE_JP_SEP
        max_len  = MAX_CHUNK_MIX if is_mixed else MAX_CHUNK_JP
        parts    = [p.strip() for p in sep.split(text) if p.strip()]
        if not parts:
            return [text.strip()]
        chunks = []
        for part in parts:
            if len(part) <= max_len:
                chunks.append(part)
            else:
                words = part.split() if is_mixed else list(part)
                buf   = ""
                for w in words:
                    if len(buf) + len(w) + 1 > max_len and buf:
                        chunks.append(buf.strip()); buf = w
                    else:
                        buf += (" " if is_mixed and buf else "") + w
                if buf.strip(): chunks.append(buf.strip())
        return [c for c in chunks if c] or [text.strip()]


class VoicevoxEngine:
    def __init__(self, root_dir: str):
        p = Path(root_dir).resolve()
        self.root = p.parent if p.name.lower() == "tts" else p

        self.dict_dir = self._find_dict_dir()

        print(f"\n📂 Engine root  : {self.root}")
        print(f"📂 Dict dir     : {self.dict_dir}")

        self.core    = None
        self._cache: dict[str, dict] = {}
        self._n_wav: dict[tuple, bytes] = {}
        self._q      = queue.Queue()
        self._busy   = False
        self._last   = time.monotonic()
        self._pool   = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vvox-synth")
        self._lock   = threading.Lock()

        self._boot()
        threading.Thread(target=self._player,   daemon=True, name="vvox-play").start()
        threading.Thread(target=self._gc_watch, daemon=True, name="vvox-gc"  ).start()
        self._preload_all()

    def _find_dict_dir(self) -> Path:
        candidates = [
            self.root / "tts" / "open_jtalk_dic_utf_8-1.11",
            self.root / "open_jtalk_dic_utf_8-1.11",
            self.root / "dict",
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return c
        default = self.root / "tts" / "open_jtalk_dic_utf_8-1.11"
        return default

    def _boot(self):
        if hasattr(os, "add_dll_directory") and sys.platform == "win32":
            try: os.add_dll_directory(str(self.root))
            except: pass

        if sys.platform == "win32":
            libs = ("voicevox_onnxruntime.dll", "voicevox_core.dll")
        elif sys.platform == "darwin":
            libs = ("libonnxruntime.dylib", "libvoicevox_core.dylib")
        else:
            libs = ("libonnxruntime.so", "libvoicevox_core.so")

        for lib in libs:
            p = self.root / lib
            if p.exists():
                try:
                    ctypes.CDLL(str(p))
                    print(f"   ✅ Loaded {lib}")
                except Exception as e:
                    print(f"   ⚠️ Lỗi load {lib}: {e}")

        if not self.dict_dir.exists():
            print(f"⚠️ CẢNH BÁO: Không tìm thấy từ điển OpenJTalk tại {self.dict_dir}")
            print("Vui lòng tải open_jtalk_dic_utf_8-1.11 và đặt vào đúng thư mục!")

        if VoicevoxCore is None:
            return

        print("🚀 Khởi tạo VoicevoxCore (0.15.0)...")
        try:
            self.core = VoicevoxCore(
                acceleration_mode="AUTO",
                open_jtalk_dict_dir=self.dict_dir
            )
            print(f"✅ VoicevoxCore khởi tạo thành công! (GPU Mode: {self.core.is_gpu_mode})")
        except Exception as e:
            print(f"❌ Lỗi khởi tạo VoicevoxCore: {e}")

    def _get_meta(self, vvm: str):
        uuid_str = vvm.replace(".vvm", "")
        for meta in METAS:
            if str(meta.speaker_uuid) == uuid_str:
                return meta
        return METAS[0] if METAS else None

    def _preload_all(self):
        if not METAS or not self.core:
            return
        
        print(f"📦 Preload model đầu tiên để warm-up...")
        first_meta = METAS[0]
        vvm = f"{first_meta.speaker_uuid}.vvm"

        def _do_load():
            try:
                self._load(vvm)
                sid = first_meta.styles[0].id
                key = (sid, 1.0, 0.0, 1.0, 1.0)
                wav = self._raw_synth(N_STARTER, sid)
                if wav: self._n_wav[key] = wav
                print(f"✅ Preload xong: {first_meta.name}")
            except Exception as e:
                print(f"⚠️ Lỗi preload: {e}")

        threading.Thread(target=_do_load, daemon=True).start()

    def speak_stream(self, text: str, vvm: str,
                     params: Optional[SynthParams] = None):
        if not self.core: return
        params = params or SynthParams()
        clean  = TextValidator.clean(text)
        ok, warn = TextValidator.check(clean)
        if not ok:
            print(f"⚠️  [Engine] {warn}")
            self._speak_warning(vvm, params)
            return

        self._last = time.monotonic()
        self._busy = True
        style_id   = self._style_id(vvm, params.style_idx)

        n_key = (style_id, params.speed, params.pitch, params.intonation, params.volume)
        n_wav = self._n_wav.get(n_key)
        if n_wav is None:
            n_wav = self._synthesize(N_STARTER, style_id, params)
            if n_wav: self._n_wav[n_key] = n_wav
        if n_wav:
            self._q.put(n_wav)

        threading.Thread(
            target=self._stream_worker,
            args=(clean, style_id, params),
            daemon=True, name="vvox-stream",
        ).start()

    def _speak_warning(self, vvm: str, params: SynthParams):
        try:
            style_id = self._style_id(vvm, params.style_idx)
            wav = self._synthesize("テキストが認識できません", style_id, params)
            if wav: self._q.put(wav)
        except: pass

    def get_audio(self, text: str, vvm: str,
                  params: Optional[SynthParams] = None) -> bytes:
        if not self.core: return b""
        params = params or SynthParams()
        clean  = TextValidator.clean(text)
        ok, warn = TextValidator.check(clean)
        if not ok:
            print(f"⚠️  [Engine] get_audio: {warn}")
            return b""
        style_id = self._style_id(vvm, params.style_idx)
        return self._synthesize(clean, style_id, params)

    def scan_models(self) -> list[dict]:
        """Trả về danh sách các model có sẵn trong thư viện."""
        result = []
        if not METAS: return result
        
        ICONS  = ['🌸','⚔','🌙','⭐','🎭','🔥','🌊','💫','🎵','🌺','🦋','🌟']

        for i, meta in enumerate(METAS):
            vvm = f"{meta.speaker_uuid}.vvm"
            entry = {
                "vvm"   : vvm,
                "name"  : meta.name,
                "icon"  : ICONS[i % len(ICONS)],
                "valid" : True,
                "error" : "",
                "cached": vvm in self._cache,
            }
            result.append(entry)
        return result

    def get_styles(self, vvm: str) -> list[tuple[int, str]]:
        try:
            entry = self._load(vvm)
            return entry["styles"]
        except:
            return [(0, "Normal")]

    def stop(self):
        while not self._q.empty():
            try: self._q.get_nowait()
            except: break
        self._busy = False
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
        except: pass

    def warm_new(self, vvm: str):
        if not self.core: return
        try:
            entry  = self._load(vvm)
            styles = entry["styles"]
            name   = entry["name"]
            for sid, _ in styles:
                key = (sid, 1.0, 0.0, 1.0, 1.0)
                if key not in self._n_wav:
                    wav = self._raw_synth(N_STARTER, sid)
                    if wav: self._n_wav[key] = wav
            print(f"✅ [Engine] Warm-up: {name} ({len(styles)} styles)")
        except Exception as e:
            print(f"⚠️  [Engine] warm_new {vvm}: {e}")

    def remove_model(self, vvm: str) -> bool:
        with self._lock:
            self._evict_cache_locked(vvm)
        return True

    def _evict_cache(self, vvm: str):
        with self._lock:
            self._evict_cache_locked(vvm)

    def _evict_cache_locked(self, vvm: str):
        entry = self._cache.pop(vvm, None)
        if entry:
            for sid, _ in entry.get("styles", []):
                for key in list(self._n_wav.keys()):
                    if key[0] == sid:
                        del self._n_wav[key]

    def _load(self, vvm: str) -> dict:
        with self._lock:
            if vvm in self._cache:
                return self._cache[vvm]

            meta = self._get_meta(vvm)
            if not meta:
                raise ValueError(f"Không tìm thấy model: {vvm}")

            styles = [(s.id, s.name) for s in meta.styles]
            
            # Load tất cả các style của nhân vật này vào core
            for sid, _ in styles:
                if not self.core.is_model_loaded(sid):
                    print(f"   📂 Loading speaker_id: {sid} ({meta.name})")
                    self.core.load_model(sid)

            entry = {
                "model_id": meta.speaker_uuid,
                "styles"  : styles,
                "name"    : meta.name,
            }
            self._cache[vvm] = entry
            return entry

    def _style_id(self, vvm: str, style_idx: int = 0) -> int:
        entry  = self._load(vvm)
        styles = entry["styles"]
        idx    = max(0, min(style_idx, len(styles) - 1))
        return styles[idx][0]

    def _raw_synth(self, text: str, style_id: int) -> bytes:
        try:
            if not self.core.is_model_loaded(style_id):
                self.core.load_model(style_id)
            return self.core.tts(text, style_id)
        except: return b""

    def _synthesize(self, text: str, style_id: int,
                    params: Optional[SynthParams] = None) -> bytes:
        if not text.strip(): return b""
        try:
            if not self.core.is_model_loaded(style_id):
                self.core.load_model(style_id)
                
            aq = self.core.audio_query(text, style_id)
            if params:
                aq.speed_scale      = params.speed
                aq.pitch_scale      = params.pitch
                aq.intonation_scale = params.intonation
                aq.volume_scale     = params.volume
            return self.core.synthesis(aq, style_id)
        except Exception as e:
            print(f"⚠️ Lỗi tổng hợp âm thanh: {e}")
            return self._raw_synth(text, style_id)

    def _synth_with_timeout(self, chunk, style_id, params):
        future = self._pool.submit(self._synthesize, chunk, style_id, params)
        try:
            return future.result(timeout=CHUNK_TIMEOUT)
        except FutureTimeout:
            future.cancel()
            print(f"   ⏰ Timeout '{chunk[:15]}'")
            return None
        except Exception as e:
            print(f"   ❌ Chunk lỗi '{chunk[:15]}': {e}")
            return None

    def _stream_worker(self, text, style_id, params):
        try:
            chunks = TextValidator.split_chunks(text)
            for i, chunk in enumerate(chunks):
                if not self._busy:
                    break
                t0  = time.perf_counter()
                wav = self._synth_with_timeout(chunk, style_id, params)
                if wav:
                    self._q.put(wav)
                    print(f"   ⚡ [{i+1}/{len(chunks)}] '{chunk[:14]}' → {(time.perf_counter()-t0)*1000:.0f}ms")
        except Exception as e:
            print(f"⚠️  [Engine] stream: {e}")
        finally:
            deadline = time.monotonic() + 30.0
            while not self._q.empty() and time.monotonic() < deadline:
                time.sleep(0.05)
            self._busy = False

    def _player(self):
        import sys
        import subprocess
        import tempfile
        
        while True:
            try:
                wav = self._q.get(timeout=0.05)
                if wav:
                    try:
                        if sys.platform == "win32":
                            import winsound
                            winsound.PlaySound(wav, winsound.SND_MEMORY)
                        elif sys.platform == "darwin":
                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                                f.write(wav)
                                tmp_path = f.name
                            subprocess.run(["afplay", tmp_path])
                            os.remove(tmp_path)
                    except Exception as e:
                        print(f"⚠️  [Player] Lỗi phát âm thanh: {e}")
                self._q.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                print(f"⚠️  [Player] queue error: {e}")

    def _gc_watch(self):
        while True:
            time.sleep(60)
            if time.monotonic() - self._last > IDLE_TIMEOUT and self._cache:
                print("♻️  [Engine] Idle → giải phóng cache")
                with self._lock:
                    self._cache.clear()
                    self._n_wav.clear()
                gc.collect()
