#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: mlx_client.py
Quản lý MLX-vLLM (Qwen2.5-7B-Instruct-4bit) — Tier 2 trong chuỗi fallback.
Thay thế bonsai_client.py (Bonsai-8B / llama-server).

Chuỗi fallback:
  Ollama 1B  →  MLX-vLLM Qwen2.5-7B (tier 2, file này)  →  Cloud (tier 3)

Chế độ hoạt động:
  - EMBEDDED (ưu tiên): Import trực tiếp mlx_vllm thư viện vào process.
    Không có overhead mạng. Engine được tái sử dụng sau lần load đầu tiên.
  - HTTP (fallback): Gọi HTTP đến endpoint mlx-vllm serve đang chạy bên ngoài.

STREAMING:
  - chat()             : blocking, trả về str (tương thích với BonsaiClient cũ)
  - chat_stream()      : streaming token-by-token, yield (token, ttft)
  - chat_stream_full() : streaming với callbacks on_token / on_done

Config (config.json keys):
  mlx_enabled              : bool   (default true)
  mlx_model                : str    (default "mlx-community/Qwen2.5-7B-Instruct-4bit")
  mlx_host                 : str    (default "127.0.0.1")
  mlx_port                 : int    (default 8000)
  mlx_max_tokens           : int    (default 512)
  mlx_temperature          : float  (default 0.0)
  mlx_startup_timeout_sec  : float  (default 120)
  mlx_call_timeout_sec     : float  (default 60)
  mlx_embedded             : bool   (default true)  — dùng embedded mode

Backward compat aliases (giữ nguyên từ bonsai_client.py):
  BonsaiClient  → MLXClient
  get_bonsai_client() → get_mlx_client()
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

log = logging.getLogger("MLXClient")

# Đảm bảo import được mlx_vllm từ thư mục local
_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # PentaAI_Mac/
_MLX_VLLM_PATH = os.path.join(_MODULE_DIR, "mlx-vllm")
if os.path.isdir(_MLX_VLLM_PATH) and _MLX_VLLM_PATH not in sys.path:
    sys.path.insert(0, _MLX_VLLM_PATH)
    logging.info(f"[MLX] Added local mlx-vllm to sys.path: {_MLX_VLLM_PATH}")


# ── Config loader ──────────────────────────────────────────────────────────────

def _load_config() -> Dict[str, Any]:
    cfg_path = os.path.join(_MODULE_DIR, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ── MLX-vLLM engine loader ─────────────────────────────────────────────────────

_ENGINE_LOCK = threading.Lock()
_ENGINE_INSTANCE = None          # mlx_vllm engine hoặc None
_ENGINE_LOAD_FAILED = False      # Tránh retry sau khi biết fail
_ENGINE_MODEL_NAME: str = ""


def _try_load_embedded_engine(model_name: str) -> Optional[Any]:
    """
    Thử import và khởi tạo mlx_vllm engine trực tiếp trong process.
    Trả về engine object hoặc None nếu thư viện chưa cài.
    """
    global _ENGINE_INSTANCE, _ENGINE_LOAD_FAILED, _ENGINE_MODEL_NAME

    if _ENGINE_LOAD_FAILED:
        return None
    if _ENGINE_INSTANCE is not None and _ENGINE_MODEL_NAME == model_name:
        return _ENGINE_INSTANCE

    with _ENGINE_LOCK:
        # Double-check sau khi acquire lock
        if _ENGINE_INSTANCE is not None and _ENGINE_MODEL_NAME == model_name:
            return _ENGINE_INSTANCE
        if _ENGINE_LOAD_FAILED:
            return None

        try:
            # Sử dụng trực tiếp mlx-lm wrapper cho embedded mode vì nó hỗ trợ generate_stream (sync)
            # MLXEngine/AsyncLLMEngine là các class async cho continuous batching, không hợp với sync stream
            engine_cls = _make_mlx_lm_engine_class()

            if engine_cls is None:
                raise ImportError("Không tìm thấy mlx-lm wrapper để chạy embedded mode")

            msg_start = f"🚀 [MLX] Đang load model '{model_name}' vào RAM (lần đầu có thể mất 10-30s)..."
            log.info(msg_start)
            print(f"\n{msg_start}\n")
            t0 = time.monotonic()
            
            instance = engine_cls(model_name)

            elapsed = time.monotonic() - t0
            msg_done = f"✅ [MLX] Model '{model_name}' load xong trong {elapsed:.1f}s. Hệ thống đã sẵn sàng cho chat 0.3s!"
            log.info(msg_done)
            print(f"\n{msg_done}\n")

            _ENGINE_INSTANCE = instance
            _ENGINE_MODEL_NAME = model_name
            return _ENGINE_INSTANCE

        except ImportError as e:
            msg = f"[MLX] Không tìm thấy thư viện mlx_vllm hoặc mlx-lm: {e}. Sẽ dùng HTTP mode."
            log.warning(msg)
            print(f"\n⚠️  {msg}\n")
            _ENGINE_LOAD_FAILED = True
            return None
        except Exception as e:
            msg = f"[MLX] Lỗi nghiêm trọng khi load engine: {e}"
            log.error(msg)
            print(f"\n❌ {msg}\n")
            import traceback
            traceback.print_exc()
            _ENGINE_LOAD_FAILED = True
            return None


def _make_mlx_lm_engine_class():
    """
    Tạo engine class wrapper cho mlx_lm (mlx-lm) nếu mlx_vllm.AsyncLLMEngine
    không tồn tại. Đây là giải pháp tương thích khi mlx_vllm version khác nhau.
    """
    try:
        from mlx_lm import load, generate, stream_generate
        from mlx_lm.models.cache import KVCache, trim_prompt_cache, make_prompt_cache
        import mlx.core as mx
        
        try:
            from mlx_lm.sample_utils import make_sampler
        except ImportError:
            make_sampler = None

        class _MLXLMEngine:
            """
            Wrapper mỏng cho mlx_lm.load + stream_generate.
            Giao diện tương thích với AsyncLLMEngine/MLXEngine của mlx_vllm.
            """

            def __init__(self, model_name: str):
                log.info(f"[MLX-LM] Loading '{model_name}' via mlx_lm...")
                self._model, self._tokenizer = load(model_name)
                self._model_name = model_name
                self._cache = None
                self._cache_tokens = []
                log.info(f"[MLX-LM] Model '{model_name}' ready with KV Cache support ✅")

            def _update_cache(self, prompt: str) -> List[int]:
                """
                So sánh prompt mới với tokens đã có trong cache. 
                Trả về đoạn tokens mới cần xử lý.
                """
                # Infer special tokens (giống logic trong stream_generate)
                add_special = self._tokenizer.bos_token is None or not prompt.startswith(self._tokenizer.bos_token)
                new_tokens = self._tokenizer.encode(prompt, add_special_tokens=add_special)
                
                if self._cache is None:
                    self._cache = make_prompt_cache(self._model)
                    self._cache_tokens = []
                
                # Tìm điểm khác biệt đầu tiên
                match_len = 0
                for a, b in zip(self._cache_tokens, new_tokens):
                    if a == b:
                        match_len += 1
                    else:
                        break
                
                # Truncate cache nếu history bị roll or change
                if match_len < len(self._cache_tokens):
                    trim_len = len(self._cache_tokens) - match_len
                    trim_prompt_cache(self._cache, trim_len)
                    self._cache_tokens = self._cache_tokens[:match_len]
                
                # Trả về các tokens chưa có trong cache
                return new_tokens[match_len:]

            def generate_sync(
                self,
                prompt: str,
                max_tokens: int = 128,
                temperature: float = 0.0,
            ) -> str:
                """Blocking generate — dùng cho chat()."""
                new_tokens = self._update_cache(prompt)
                
                kwargs = {"max_tokens": max_tokens, "prompt_cache": self._cache}
                if make_sampler:
                    kwargs["sampler"] = make_sampler(temp=temperature)
                else:
                    kwargs["temp"] = temperature

                # Gọi generate với tokens dôi ra
                resp = generate(
                    self._model,
                    self._tokenizer,
                    prompt=mx.array(new_tokens),
                    verbose=False,
                    **kwargs
                )
                # Cập nhật cache_tokens sau khi gen xong (cần track output tokens nếu muốn cache cả câu trả lời)
                # Tuy nhiên với chat history, ta chỉ cần cache phần prompt của turn tiếp theo.
                # Turn tiếp theo sẽ gửi "System + History + New User", nên cache sẽ tự động hit phần System+History.
                self._cache_tokens.extend(new_tokens)
                return resp

            def generate_stream(
                self,
                prompt: str,
                max_tokens: int = 128,
                temperature: float = 0.0,
            ):
                """
                Sync streaming generator — sử dụng KV Cache để bỏ qua history cũ.
                """
                new_tokens = self._update_cache(prompt)
                
                kwargs = {"max_tokens": max_tokens, "prompt_cache": self._cache}
                if make_sampler:
                    kwargs["sampler"] = make_sampler(temp=temperature)
                else:
                    kwargs["temp"] = temperature

                try:
                    # Truyền mx.array tokens thay vì string để stream_generate dùng cache đúng chỗ
                    for response in stream_generate(
                        self._model,
                        self._tokenizer,
                        prompt=mx.array(new_tokens),
                        **kwargs
                    ):
                        if response:
                            text = getattr(response, "text", response)
                            if isinstance(text, str):
                                yield text
                    
                    # Quan trọng: Cập nhật token list để lần sau skip được part này
                    self._cache_tokens.extend(new_tokens)
                    
                except Exception as e:
                    log.warning(f"[MLX-LM] generate_stream error: {e}")

            def format_messages(self, messages: List[Dict]) -> str:
                """Áp dụng chat template nếu tokenizer có hỗ trợ."""
                try:
                    if hasattr(self._tokenizer, "apply_chat_template"):
                        return self._tokenizer.apply_chat_template(
                            messages,
                            tokenize=False,
                            add_generation_prompt=True,
                        )
                except Exception:
                    pass
                # Fallback: nối thủ công
                parts = []
                for m in messages:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    parts.append(f"<|{role}|>\n{content}")
                parts.append("<|assistant|>")
                return "\n".join(parts)

        return _MLXLMEngine

    except ImportError:
        log.warning("[MLX] mlx-lm cũng chưa cài. Chỉ dùng được HTTP mode.")
        return None


# ── HTTP client helpers ────────────────────────────────────────────────────────

def _http_chat(
    base_url: str,
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> Optional[str]:
    """Gọi HTTP /v1/chat/completions (blocking). Dùng khi embedded mode fail."""
    try:
        import requests
        r = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "mlx-model",
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[MLX/HTTP] chat error: {e}")
        return None


def _http_chat_stream(
    base_url: str,
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> Iterator[str]:
    """Streaming qua HTTP SSE. Yield từng token string."""
    try:
        import requests
        with requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "mlx-model",
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
            timeout=timeout,
            stream=True,
        ) as r:
            r.raise_for_status()
            for raw_line in r.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
    except Exception as e:
        log.warning(f"[MLX/HTTP] stream error: {e}")


def _http_health(base_url: str, timeout: float = 2.0) -> bool:
    try:
        import requests
        r = requests.get(f"{base_url}/health", timeout=timeout)
        return r.status_code in (200, 503)
    except Exception:
        return False


# ── MLXClient ─────────────────────────────────────────────────────────────────

class MLXClient:
    """
    Client MLX-vLLM nhúng trực tiếp — thay thế BonsaiClient.

    API backward-compatible với BonsaiClient:
      chat(messages)                 → Tuple[Optional[str], float]
      chat_stream(messages)          → Iterator[Tuple[str, float]]
      chat_stream_full(messages, ...) → None
      is_available()                 → bool
      set_keepalive(active)          → None  (no-op — không còn subprocess)
      set_sleep_notify(cb)           → None  (no-op — không còn idle sleep)
      shutdown()                     → None  (cleanup)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        embedded: Optional[bool] = None,
        startup_timeout: Optional[float] = None,
        call_timeout: Optional[float] = None,
    ):
        cfg = _load_config()

        self.model = model or cfg.get(
            "mlx_model", "mlx-community/Qwen2.5-7B-Instruct-4bit"
        )
        self.host = host or cfg.get("mlx_host", "127.0.0.1")
        self.port = int(port or cfg.get("mlx_port", 8000))
        self.base_url = f"http://{self.host}:{self.port}"

        self.max_tokens = int(
            max_tokens if max_tokens is not None else cfg.get("mlx_max_tokens", 512)
        )
        self.temperature = float(
            temperature if temperature is not None else cfg.get("mlx_temperature", 0.0)
        )
        self.embedded = bool(
            embedded if embedded is not None else cfg.get("mlx_embedded", True)
        )
        self.startup_timeout = float(
            startup_timeout if startup_timeout is not None
            else cfg.get("mlx_startup_timeout_sec", 120.0)
        )
        self.call_timeout = float(
            call_timeout if call_timeout is not None
            else cfg.get("mlx_call_timeout_sec", 60.0)
        )

        # Backward compat attributes — giữ để code cũ không crash
        self._keepalive: bool = False
        self._sleep_notify_cb = None
        self._last_route: str = "mlx"

        # Khởi tạo engine non-blocking (tải trong background thread)
        if self.embedded:
            self._engine_ready = False
            self._init_thread = threading.Thread(
                target=self._init_engine_bg,
                daemon=True,
                name="mlx-engine-init",
            )
            self._init_thread.start()
        else:
            self._engine_ready = False
            log.info("[MLX] Embedded mode tắt — chỉ dùng HTTP mode")

    def _init_engine_bg(self) -> None:
        """Tải MLX engine trong background thread để không block server startup."""
        engine = _try_load_embedded_engine(self.model)
        self._engine_ready = engine is not None
        if not self._engine_ready:
            log.info("[MLX] Embedded engine không khả dụng — fallback sang HTTP mode")

    def _get_engine(self) -> Optional[Any]:
        """Trả về engine nếu đã sẵn sàng, None nếu chưa/lỗi."""
        if not self.embedded:
            return None
        return _ENGINE_INSTANCE if _ENGINE_INSTANCE is not None else None

    def _format_prompt(self, messages: List[Dict]) -> str:
        """Áp dụng chat template nếu engine có hỗ trợ."""
        engine = self._get_engine()
        if engine and hasattr(engine, "format_messages"):
            try:
                return engine.format_messages(messages)
            except Exception:
                pass
        # Fallback manual format (Qwen2.5 style)
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = str(m.get("content", ""))
            if role == "system":
                parts.append(f"<|im_start|>system\n{content}<|im_end|>")
            elif role == "user":
                parts.append(f"<|im_start|>user\n{content}<|im_end|>")
            elif role == "assistant":
                parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    # ── Public API ──────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
    ) -> Tuple[Optional[str], float]:
        """
        Blocking call — tương thích với BonsaiClient.chat().
        Trả về (text, elapsed_sec) hoặc (None, 0.0) nếu lỗi.

        ⚠️ Dùng chat_stream() để có perceived latency thấp (~150-300ms first token).
        """
        _max = int(max_tokens or self.max_tokens)
        t_start = time.monotonic()
        
        # Chờ engine sẵn sàng nếu đang ở chế độ embedded để tránh fallback nhầm sang Ollama
        if self.embedded and not self.is_available():
            log.info("[MLX] Engine đang nạp, chờ tối đa 15s...")
            self.wait_ready(timeout=15.0)

        engine = self._get_engine()

        if engine and hasattr(engine, "generate_sync"):
            # Embedded mode — gọi trực tiếp không qua network
            try:
                prompt = self._format_prompt(messages)
                raw = engine.generate_sync(
                    prompt,
                    max_tokens=_max,
                    temperature=self.temperature,
                )
                elapsed = time.monotonic() - t_start
                text = str(raw or "").strip()
                if text:
                    log.debug(f"[MLX/embedded] chat() in {elapsed:.3f}s ({_max} max_tok)")
                    return text, elapsed
            except Exception as e:
                log.warning(f"[MLX/embedded] generate_sync error: {e}")

        # HTTP mode
        text = _http_chat(
            self.base_url, messages, _max, self.temperature, self.call_timeout
        )
        elapsed = time.monotonic() - t_start
        if text:
            log.debug(f"[MLX/HTTP] chat() in {elapsed:.3f}s")
            return text, elapsed

        log.warning("[MLX] chat() thất bại cả embedded lẫn HTTP")
        return None, 0.0

    def chat_stream(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        on_first_token: Optional[Callable] = None,
    ) -> Iterator[Tuple[str, float]]:
        """
        STREAMING call — yield (token, ttft) từng token ngay khi model generate.
        ttft = time-to-first-token (chỉ khác 0 cho token đầu tiên).

        Tương thích với BonsaiClient.chat_stream().

        Cách dùng:
            for token, ttft in mlx.chat_stream(messages):
                if ttft > 0:
                    log.info(f"TTFT: {ttft:.3f}s")
                ws.send(json.dumps({"type": "token", "text": token}))
        """
        _max = int(max_tokens or self.max_tokens)
        t_request_start = time.monotonic()
        first_token_received = False

        # Chờ engine sẵn sàng để ưu tiên tốc độ 0.3s của MLX
        if self.embedded and not self.is_available():
            log.info("[MLX] Engine đang nạp, chờ tối đa 15s để đạt tốc độ streaming 0.3s...")
            self.wait_ready(timeout=15.0)

        engine = self._get_engine()

        token_gen = None

        if engine and hasattr(engine, "generate_stream"):
            # Embedded mode streaming
            try:
                prompt = self._format_prompt(messages)
                token_gen = engine.generate_stream(
                    prompt,
                    max_tokens=_max,
                    temperature=self.temperature,
                )
                log.debug("[MLX/embedded] stream started")
            except Exception as e:
                log.warning(f"[MLX/embedded] generate_stream setup error: {e}")
                token_gen = None

        if token_gen is None:
            # HTTP SSE streaming
            log.debug("[MLX/HTTP] stream started")
            token_gen = _http_chat_stream(
                self.base_url, messages, _max, self.temperature, self.call_timeout
            )

        try:
            for token in token_gen:
                if not token:
                    continue
                ttft = 0.0
                if not first_token_received:
                    ttft = time.monotonic() - t_request_start
                    first_token_received = True
                    log.debug(f"[MLX] First token in {ttft:.3f}s")
                    if callable(on_first_token):
                        try:
                            on_first_token(ttft)
                        except Exception:
                            pass
                yield (token, ttft)
        except Exception as e:
            log.warning(f"[MLX] chat_stream() error: {e}")
            return

    def chat_stream_full(
        self,
        messages: List[Dict],
        on_token: Callable,
        on_done: Optional[Callable] = None,
        on_first_token: Optional[Callable] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        """
        Streaming với callbacks — tương thích với BonsaiClient.chat_stream_full().

        Dùng với WebSocket:
            def send_token(t, ttft):
                ws.send(json.dumps({"type": "token", "text": t, "ttft": ttft}))
            def send_done(full):
                ws.send(json.dumps({"type": "done", "text": full}))
            mlx.chat_stream_full(messages, on_token=send_token, on_done=send_done)
        """
        full_text: List[str] = []
        for token, ttft in self.chat_stream(
            messages, max_tokens=max_tokens, on_first_token=on_first_token
        ):
            full_text.append(token)
            try:
                on_token(token, ttft)
            except Exception as e:
                log.debug(f"[MLX] on_token callback error: {e}")

        if on_done:
            try:
                on_done("".join(full_text))
            except Exception as e:
                log.debug(f"[MLX] on_done callback error: {e}")

    def is_available(self) -> bool:
        """
        Kiểm tra nhanh xem MLX có khả dụng không.
        - Embedded: kiểm tra engine đã load
        - HTTP: ping /health
        """
        engine = self._get_engine()
        if engine is not None:
            return True
        # Nếu đang trong quá trình load (background thread còn chạy)
        if self.embedded and self._init_thread.is_alive():
            return False  # Chưa sẵn sàng
        # HTTP fallback check
        return _http_health(self.base_url, timeout=1.5)

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """
        Chờ engine load xong. Dùng khi muốn warm-up trước.
        Trả về True nếu sẵn sàng trong thời gian timeout.
        """
        if not self.embedded:
            return _http_health(self.base_url, timeout=timeout or self.startup_timeout)

        t_limit = time.monotonic() + (timeout or self.startup_timeout)
        while time.monotonic() < t_limit:
            if _ENGINE_INSTANCE is not None:
                return True
            if _ENGINE_LOAD_FAILED:
                # Engine load fail, thử HTTP
                return _http_health(self.base_url, timeout=2.0)
            if not self._init_thread.is_alive():
                return _ENGINE_INSTANCE is not None
            time.sleep(1.0)
        return _ENGINE_INSTANCE is not None

    # ── Backward compat stubs (BonsaiClient interface) ─────────────────────────

    def set_keepalive(self, active: bool) -> None:
        """No-op — không còn subprocess cần giữ alive. Giữ để backward compat."""
        self._keepalive = active
        log.debug(f"[MLX] set_keepalive({active}) — no-op (embedded mode)")

    def set_sleep_notify(self, cb) -> None:
        """No-op — không còn idle sleep mode. Giữ để backward compat."""
        self._sleep_notify_cb = cb

    def can_wake_now(self) -> bool:
        """Tương thích BonsaiClient.can_wake_now(). MLX luôn sẵn sàng nếu loaded."""
        return self.is_available()

    def shutdown(self) -> None:
        """Cleanup — engine không cần shutdown riêng (Python GC dọn dẹp)."""
        log.debug("[MLX] shutdown() called — engine sống đến khi process exit")

    # ── bonsai_ aliases ────────────────────────────────────────────────────────
    # Các thuộc tính này được ai_server.py và pentami_chat.py truy cập trực tiếp

    @property
    def _ensure_awake(self):
        """Alias cho backward compat — trả về method kiểm tra is_available."""
        return self.is_available

    def __repr__(self) -> str:
        mode = "embedded" if self._get_engine() else "HTTP"
        return (
            f"<MLXClient model={self.model!r} mode={mode} "
            f"available={self.is_available()}>"
        )


# ── Async wrapper cho FastAPI / asyncio context ────────────────────────────────

class AsyncMLXClient:
    """
    Wrapper async cho MLXClient — dùng trong FastAPI endpoints và WebSocket handlers.
    Chạy blocking calls trong ThreadPoolExecutor để không block event loop.
    """

    def __init__(self, client: Optional[MLXClient] = None):
        self._client = client or get_mlx_client()

    async def chat(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
    ) -> Tuple[Optional[str], float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._client.chat(messages, max_tokens=max_tokens),
        )

    async def chat_stream(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        on_first_token: Optional[Callable] = None,
    ):
        """Async generator — yield (token, ttft)."""
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce():
            try:
                for pair in self._client.chat_stream(
                    messages,
                    max_tokens=max_tokens,
                    on_first_token=on_first_token,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, pair)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, _SENTINEL)

        threading.Thread(target=_produce, daemon=True, name="mlx-async-stream").start()

        while True:
            item = await q.get()
            if item is _SENTINEL:
                break
            yield item

    async def wait_ready(self, timeout: Optional[float] = None) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._client.wait_ready(timeout=timeout),
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    # Forward all other attribute accesses to underlying client
    def __getattr__(self, name: str):
        return getattr(self._client, name)


# ── Singleton ─────────────────────────────────────────────────────────────────

_default_mlx: Optional[MLXClient] = None
_mlx_singleton_lock = threading.Lock()


def get_mlx_client() -> MLXClient:
    """Lấy MLXClient singleton (thread-safe)."""
    global _default_mlx
    if _default_mlx is None:
        with _mlx_singleton_lock:
            if _default_mlx is None:
                _default_mlx = MLXClient()
    return _default_mlx


def get_async_mlx_client() -> AsyncMLXClient:
    """Lấy AsyncMLXClient wrapper (dùng trong FastAPI/asyncio)."""
    return AsyncMLXClient(get_mlx_client())


# ── Backward compatibility aliases ────────────────────────────────────────────
# Giữ để các file cũ import BonsaiClient / get_bonsai_client không bị crash

BonsaiClient = MLXClient
get_bonsai_client = get_mlx_client
