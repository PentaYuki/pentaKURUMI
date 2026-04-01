# /Users/gooleseswsq1gmail.com/Documents/PentaMiv1/PentaAI_Mac/tts_engine/valtec/valtec_server.py

import os
import sys
import re
import time
import queue
import threading
import subprocess
import tempfile
import io
import soundfile as sf
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

# ── 0. CẤU HÌNH ĐƯỜNG DẪN SOURCE CODE VALTEC ──────────────────────────────
# Lấy đường dẫn thư mục hiện tại (tts_engine/valtec)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Đường dẫn tới thư mục source code valtec_tts vừa clone về
VALTEC_SOURCE_DIR = os.path.join(CURRENT_DIR, "valtec_tts")

# Thêm thư mục source code vào sys.path để Python tìm thấy file infer.py và src/
if VALTEC_SOURCE_DIR not in sys.path:
    sys.path.insert(0, VALTEC_SOURCE_DIR)

try:
    # Import class TTS từ source code local
    from valtec_tts.tts import TTS
except ImportError as e:
    print(f"❌ Lỗi Import Valtec: {e}")
    print("Vui lòng chạy lệnh: git clone https://github.com/tronghieuit/valtec-tts.git valtec_tts")
    sys.exit(1)

# ── 1. CƠ CHẾ CHUNKING (CẮT CÂU) GIỐNG VOICEVOX ───────────────────────────
CHUNK_TIMEOUT  = 15.0
MAX_CHUNK_VI   = 30 # Tối đa 30 từ mỗi chunk tiếng Việt
_RE_VI_SEP     = re.compile(r'[。、！？…\n,.\?!]+')

class TextValidatorVI:
    @staticmethod
    def clean(text: str) -> str:
        t = re.sub(r'[\x00-\x1f\x7f]', '', text)
        t = t.replace('...', '…').replace('--', '—')
        t = re.sub(r'https?://\S+', '', t)
        return t.strip()

    @staticmethod
    def split_chunks(text: str) -> list[str]:
        parts = [p.strip() for p in _RE_VI_SEP.split(text) if p.strip()]
        if not parts:
            return [text.strip()]
        chunks = []
        for part in parts:
            words = part.split()
            if len(words) <= MAX_CHUNK_VI:
                chunks.append(part)
            else:
                buf = []
                for w in words:
                    buf.append(w)
                    if len(buf) >= MAX_CHUNK_VI:
                        chunks.append(" ".join(buf))
                        buf = []
                if buf:
                    chunks.append(" ".join(buf))
        return [c for c in chunks if c] or [text.strip()]

# ── 2. ENGINE XỬ LÝ ĐA LUỒNG & HÀNG ĐỢI ──────────────────────────────────
class ValtecEngine:
    def __init__(self):
        self.tts = None
        self._q = queue.Queue()
        self._busy = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="valtec-synth")
        
        self._boot()
        
        threading.Thread(target=self._player, daemon=True, name="valtec-play").start()

    def _boot(self):
        print("🚀 Đang nạp Valtec Model vào RAM (CPU Mac Mini)...")
        # Khởi tạo TTS. Vì đang dùng source local, nó sẽ tự động tìm thấy infer.py
        self.tts = TTS(device="cpu")
        print(f"✅ [🇻🇳 Valtec Engine] Sẵn sàng! Các giọng đọc: {self.tts.list_speakers()}")

    def _raw_synth(self, text: str, speaker: str = "NF", speed: float = 1.0) -> bytes:
        if not self.tts: return b""
        try:
            audio_array, sr = self.tts.synthesize(text, speaker=speaker, speed=speed)
            buffer = io.BytesIO()
            sf.write(buffer, audio_array, sr, format="WAV")
            return buffer.getvalue()
        except Exception as e:
            print(f"❌ Lỗi sinh âm thanh Valtec: {e}")
            return b""

    def _synth_with_timeout(self, chunk: str, speaker: str, speed: float):
        future = self._pool.submit(self._raw_synth, chunk, speaker, speed)
        try:
            return future.result(timeout=CHUNK_TIMEOUT)
        except FutureTimeout:
            print(f"   ⏰ Timeout Valtec '{chunk[:15]}'")
            return None

    def _stream_worker(self, text: str, speaker: str, speed: float):
        try:
            chunks = TextValidatorVI.split_chunks(text)
            for i, chunk in enumerate(chunks):
                if not self._busy: break
                
                t0 = time.perf_counter()
                wav_bytes = self._synth_with_timeout(chunk, speaker, speed)
                
                if wav_bytes:
                    self._q.put(wav_bytes)
                    print(f"   ⚡ [Valtec {i+1}/{len(chunks)}] '{chunk[:15]}...' → {(time.perf_counter()-t0)*1000:.0f}ms")
        except Exception as e:
            print(f"⚠️ [Valtec] stream lỗi: {e}")
        finally:
            deadline = time.monotonic() + 30.0
            while not self._q.empty() and time.monotonic() < deadline:
                time.sleep(0.05)
            self._busy = False

    def speak_stream(self, text: str, speaker: str = "NF", speed: float = 1.0):
        clean_txt = TextValidatorVI.clean(text)
        if not clean_txt: return
        
        self._busy = True
        threading.Thread(
            target=self._stream_worker,
            args=(clean_txt, speaker, speed),
            daemon=True,
            name="valtec-stream"
        ).start()

    def _player(self):
        while True:
            try:
                wav_bytes = self._q.get(timeout=0.05)
                if wav_bytes:
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                            f.write(wav_bytes)
                            tmp_path = f.name
                        
                        subprocess.run(["afplay", tmp_path])
                        os.remove(tmp_path)
                    except Exception as e:
                        print(f"⚠️ [Valtec Player] Lỗi phát âm thanh: {e}")
                self._q.task_done()
            except queue.Empty:
                pass

    def stop(self):
        self._busy = False
        while not self._q.empty():
            try: self._q.get_nowait()
            except: break
        subprocess.run(["killall", "afplay"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    engine = ValtecEngine()
    print("\n▶️ Đang test đọc âm thanh...")
    
    doan_van = "Xin chào bạn. Đây là hệ thống kiểm tra giọng nói Valtec trên Mac Mini. Nó sẽ cắt câu này ra. Và đọc ngay lập tức câu đầu tiên. Bạn không cần phải chờ đợi lâu nữa."
    
    engine.speak_stream(doan_van, speaker="NF")
    time.sleep(15) 