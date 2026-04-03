import redis
import faiss
import numpy as np
import requests
import json
import logging
import os
import time
from typing import Optional, List, Dict, Any, Union

log = logging.getLogger("PentaMemory")

class PentaMemory:
    def __init__(self, ollama_url="http://localhost:11434", model="llama3.2:1b"):
        self.ollama_url = ollama_url
        self.model = model
        
        # Circuit breaker: tránh gọi Ollama khi biết nó không chạy
        self._ollama_ok: Optional[bool] = None
        self._ollama_last_check: float = 0

        # 1. Khởi tạo Redis (Ngắn hạn)
        try:
            self.redis = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            self.redis.ping()
            log.info("✅ Redis Memory: OK")
        except Exception as e:
            self.redis = None
            log.warning(f"⚠️ Redis chưa chạy: {e}")

        # 2. Khởi tạo Faiss (Dài hạn)
        self.dimension = 768
        self.faiss_index = faiss.IndexFlatL2(self.dimension)
        self.vault: Dict[int, str] = {}
        self.vault_file = "penta_vault.json"
        self._load_vault()
        self._reminder_variants: List[str] = []

        # Nạp sẵn một số câu nhắc nhở dễ thương nếu vault trống
        if not self.vault:
            self._init_cute_phrases()

        # 3. Kiểm tra Ollama ngay khi init
        self._check_ollama()

    def _check_ollama(self) -> bool:
        """Kiểm tra nhanh Ollama có chạy không (timeout 2s). Kết quả cache 60s."""
        now = time.monotonic()
        if self._ollama_ok is not None and (now - self._ollama_last_check) < 60:
            return self._ollama_ok
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            self._ollama_ok = r.status_code == 200
        except Exception:
            self._ollama_ok = False
        self._ollama_last_check = now
        status = "✅" if self._ollama_ok else "⚠️"
        log.info(f"{status} Ollama tại {self.ollama_url}: {'OK' if self._ollama_ok else 'KHÔNG CHẠY — LLM fallback bị tắt'}")
        return self._ollama_ok

    def _load_vault(self):
        if os.path.exists(self.vault_file):
            try:
                with open(self.vault_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        self.vault[item['id']] = item['text']
            except Exception as e:
                log.error(f"Lỗi load Vault: {e}")

    def get_embedding(self, text: str):
        if not self._check_ollama():
            return None
        try:
            res = requests.post(f"{self.ollama_url}/api/embeddings", json={
                "model": "nomic-embed-text", "prompt": text
            }, timeout=5)
            return np.array([res.json()["embedding"]], dtype='float32')
        except Exception as e:
            log.warning(f"Embedding error: {e}")
            self._ollama_ok = False
            return None

    def chat_with_llm(self, user_text: str, session_id: str = "default_user") -> str:
        """Hàm Fallback: Được gọi khi main.py không biết trả lời"""
        if not self._check_ollama():
            log.debug("Ollama không khả dụng, bỏ qua LLM fallback")
            return ""

        # A. Lấy ngữ cảnh ngắn hạn
        history = []
        if self.redis:
            try:
                raw_hist = self.redis.lrange(session_id, 0, 5)
                history = [json.loads(m) for m in reversed(raw_hist)]
            except Exception:
                pass

        # B. Lấy ngữ cảnh dài hạn (Faiss)
        past_info = ""
        if self.faiss_index.ntotal > 0:
            vec = self.get_embedding(user_text)
            if vec is not None:
                try:
                    dist, idx = self.faiss_index.search(vec, 1)
                    if idx[0][0] != -1 and dist[0][0] < 1.0:
                        past_info = self.vault.get(idx[0][0], "")
                except Exception:
                    pass

        # C. Xây dựng Prompt "Siêu Dễ Thương"
        # Lấy cách AI gọi người dùng từ profile nếu có
        user_call = "anh" # Mặc định
        sys_prompt = (
            "Bạn là Bé Penta (hoặc Em), một cô gái trợ lý AI vô cùng đáng yêu, ngọt ngào và luôn quan tâm đến người dùng. "
            "Hãy xưng hô cực kỳ thân mật (Em - Anh), dùng các từ ngữ dễ thương như 'nha', 'nè', 'ạ', 'hihi', '... đó nhen'. "
            "Bạn luôn lo lắng cho sức khỏe và niềm vui của Anh. Trả lời ngắn gọn, tự nhiên, tràn đầy cảm xúc bằng tiếng Việt."
        )
        if past_info:
            sys_prompt += f"\n[KÝ ỨC CỦA CHÚNG TA]: {past_info}"

        messages = [{"role": "system", "content": sys_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        # D. Gọi Ollama với timeout hợp lý
        try:
            res = requests.post(f"{self.ollama_url}/api/chat", json={
                "model": self.model, "messages": messages, "stream": False
            }, timeout=15)
            res.raise_for_status()
            ai_resp = res.json()["message"]["content"]

            # E. Lưu lại vào Redis
            if self.redis:
                try:
                    self.redis.lpush(session_id, json.dumps({"role": "user", "content": user_text}))
                    self.redis.lpush(session_id, json.dumps({"role": "assistant", "content": ai_resp}))
                    self.redis.ltrim(session_id, 0, 9)
                except Exception:
                    pass

            return ai_resp

        except requests.Timeout:
            log.warning(f"Ollama timeout (>15s) cho: '{user_text[:50]}'")
            self._ollama_ok = False
            return ""
        except Exception as e:
            log.error(f"Ollama Error: {e}")
            self._ollama_ok = False
            return ""

    def get_command(self, user_text: str, available_commands: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Chế độ DEVICE: phân tích câu nói thành lệnh điều khiển.
        Trả về dict: {"action": "...", "target": "...", "parameters": "..."}
        hoặc {"error": "..."} nếu thất bại.
        """
        if not self._check_ollama():
            return {"error": "Ollama không khả dụng"}

        # Xây dựng phần gợi ý lệnh đã biết (nếu có)
        known_section = ""
        if available_commands:
            known_list = ", ".join(f'"{c}"' for c in available_commands[:20])
            known_section = (
                f"\nCác lệnh hiện có trong hệ thống: [{known_list}]. "
                "Hãy ưu tiên dùng tên lệnh trong danh sách này nếu phù hợp."
            )

        sys_prompt = (
            "Bạn là trợ lý điều khiển nhà thông minh và máy tính. "
            "Phân tích yêu cầu người dùng và trả về JSON với các trường:\n"
            '- "action": hành động (open, close, toggle, run, search, type, set, get, ...)\n'
            '- "target": đối tượng (ứng dụng, thiết bị, URL, từ khoá, ...)\n'
            '- "parameters": tham số bổ sung nếu có (có thể để "")\n\n'
            "Ví dụ:\n"
            '  "bật đèn phòng khách"  → {"action":"toggle","target":"đèn phòng khách","parameters":"on"}\n'
            '  "mở trình duyệt"       → {"action":"open","target":"browser","parameters":""}\n'
            '  "tìm thời tiết hôm nay"→ {"action":"search","target":"thời tiết hôm nay","parameters":""}\n'
            '  "tắt điều hòa"         → {"action":"toggle","target":"điều hòa","parameters":"off"}\n'
            f"{known_section}\n\n"
            "QUAN TRỌNG: Chỉ trả về JSON thuần, không có markdown, không có giải thích."
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": user_text},
        ]

        try:
            res = requests.post(
                f"{self.ollama_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=10,
            )
            res.raise_for_status()
            raw_content: str = res.json()["message"]["content"].strip()

            # Loại bỏ code fence nếu model trả về ```json ... ```
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)

            # Chuẩn hoá: đảm bảo có đủ ba trường
            return {
                "action":     str(parsed.get("action", "")).strip(),
                "target":     str(parsed.get("target", "")).strip(),
                "parameters": str(parsed.get("parameters", "")).strip(),
            }

        except json.JSONDecodeError as e:
            log.warning(f"get_command: Không parse được JSON từ Ollama — {e}")
            return {"error": "Không thể hiểu lệnh", "raw": raw_content if 'raw_content' in locals() else ""}
        except requests.Timeout:
            log.warning(f"get_command: Ollama timeout cho '{user_text[:50]}'")
            self._ollama_ok = False
            return {"error": "Ollama timeout"}
        except Exception as e:
            log.error(f"get_command error: {e}")
            self._ollama_ok = False
            return {"error": str(e)}

    def get_varied_phrase(self, intent: str, default_text: str) -> str:
        """Sử dụng FAISS để tìm một câu biến thể phù hợp với ý định."""
        # Fallback mềm: nếu chưa có index thì vẫn đổi câu từ pool local.
        if self._reminder_variants:
            import random
            local_pick = random.choice(self._reminder_variants)
            if "{msg}" in local_pick:
                return local_pick

        if self.faiss_index.ntotal == 0:
            return default_text
        
        vec = self.get_embedding(intent)
        if vec is None: return default_text
        
        try:
            # Tìm 3 câu gần nhất và chọn ngẫu nhiên
            dist, idx = self.faiss_index.search(vec, 3)
            choices = []
            for i in idx[0]:
                if i != -1: choices.append(self.vault.get(i, ""))
            
            valid_choices = [c for c in choices if c]
            import random
            return random.choice(valid_choices) if valid_choices else default_text
        except Exception:
            return default_text

    def _add_phrase_to_memory(self, text: str):
        """Nạp một câu vào vault và (nếu có embedding) vào FAISS."""
        if not text:
            return
        idx = len(self.vault)
        self.vault[idx] = text

        vec = self.get_embedding(text)
        if vec is not None and vec.shape[-1] == self.dimension:
            try:
                self.faiss_index.add(vec)
            except Exception as e:
                log.debug(f"FAISS add skipped: {e}")

    def _init_cute_phrases(self):
        """Khởi tạo một số câu nói dễ thương vào bộ nhớ."""
        phrases = [
            "Anh ơi, đến giờ {msg} rồi nè! Đừng quên nha hihi.",
            "Bé Penta nhắc anh tới giờ {msg} rồi đó ạ. Anh làm ngay đi nhen.",
            "Hì hì, anh ơi {msg} thôi nào! Em đợi anh đó.",
            "Đã đến lúc {msg} rồi anh xã ơi! (Em đùa tí thôi hihi).",
            "Anh đừng mãi làm việc mà quên {msg} nhé, em lo lắm đó.",
        ]
        self._reminder_variants = phrases[:]
        for p in phrases:
            self._add_phrase_to_memory(p)
        log.info("💖 Đã nạp 5 câu nhắc nhở dễ thương vào bộ nhớ.")
