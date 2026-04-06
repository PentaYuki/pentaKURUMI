#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: bonsai_client.py
Quản lý Bonsai-8B LLM (llama-server tại port 8081) — Tier 2 trong chuỗi fallback.

Chuỗi fallback:
  Ollama 1B  →  Bonsai-8B (tier 2, file này)  →  Cloud (tier 3)

STREAMING:
  - chat()         : stream=False, trả về str (tương thích cũ)
  - chat_stream()  : stream=True,  trả về Generator[str] — dùng để hiển thị
                     token từng chữ lên UI, perceived latency ~300ms thay vì 5-8s.

Chế độ sleep:
  - Server tự động tắt sau bonsai_idle_timeout_sec giây không hoạt động.
  - Khi có yêu cầu mới: tự động wake (khởi động lại) nếu auto_start = true.
  - Nếu server đang chạy sẵn (người dùng khởi động thủ công) → dùng luôn.

Config (config.json keys):
  bonsai_enabled              : bool   (default true)
  bonsai_host                 : str    (default "127.0.0.1")
  bonsai_port                 : int    (default 8081)
  bonsai_server_bin           : str    (default <workspace>/prism-llama.cpp/build/bin/llama-server)
  bonsai_model_path           : str    (default <workspace>/prism-llama.cpp/models/Bonsai-8B.gguf)
  bonsai_n_gpu_layers         : int    (default 99)
  bonsai_auto_start           : bool   (default true)
  bonsai_idle_timeout_sec     : float  (default 300)
  bonsai_startup_timeout_sec  : float  (default 90)
  bonsai_call_timeout_sec     : float  (default 45)
  bonsai_max_tokens           : int    (default 120)   ← giảm từ 256
  bonsai_temperature          : float  (default 0.0)
"""

import atexit
import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, Generator, Iterator, List, Optional

import requests

log = logging.getLogger("BonsaiClient")

_MODULE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # PentaAI_Mac/
_WORKSPACE_DIR = os.path.dirname(_MODULE_DIR)  # workspace root


def _load_config() -> Dict[str, Any]:
    cfg_path = os.path.join(_MODULE_DIR, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class BonsaiClient:
    """
    Client quản lý llama-server (Bonsai-8B).

    API chính:
      chat(messages)              → Optional[str]        : blocking, tương thích cũ
      chat_stream(messages)       → Iterator[str]        : streaming, token-by-token
      chat_stream_full(messages,
                       on_token,
                       on_done)                          : streaming với callbacks
      is_available()              → bool                 : ping nhanh
      shutdown()                                         : tắt server
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        server_bin: Optional[str] = None,
        model_path: Optional[str] = None,
        n_gpu_layers: Optional[int] = None,
        auto_start: Optional[bool] = None,
        idle_timeout: Optional[float] = None,
        startup_timeout: Optional[float] = None,
        call_timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        cfg = _load_config()

        self.host     = host or cfg.get("bonsai_host", "127.0.0.1")
        self.port     = int(port or cfg.get("bonsai_port", 8081))
        self.base_url = f"http://{self.host}:{self.port}"

        _default_bin = os.path.join(
            _WORKSPACE_DIR, "prism-llama.cpp", "build", "bin", "llama-server"
        )
        _default_model = os.path.join(
            _WORKSPACE_DIR, "prism-llama.cpp", "models", "Bonsai-8B.gguf"
        )
        self.server_bin   = server_bin  or cfg.get("bonsai_server_bin",   _default_bin)
        self.model_path   = model_path  or cfg.get("bonsai_model_path",   _default_model)
        self.n_gpu_layers = int(
            n_gpu_layers if n_gpu_layers is not None else cfg.get("bonsai_n_gpu_layers", 99)
        )
        self.auto_start = bool(
            auto_start if auto_start is not None else cfg.get("bonsai_auto_start", True)
        )

        self.idle_timeout    = float(idle_timeout    if idle_timeout    is not None else cfg.get("bonsai_idle_timeout_sec",    300.0))
        self.startup_timeout = float(startup_timeout if startup_timeout is not None else cfg.get("bonsai_startup_timeout_sec", 90.0))
        self.call_timeout    = float(call_timeout    if call_timeout    is not None else cfg.get("bonsai_call_timeout_sec",    45.0))
        self.max_tokens      = int(  max_tokens      if max_tokens      is not None else cfg.get("bonsai_max_tokens",          120))
        self.temperature     = float(temperature     if temperature     is not None else cfg.get("bonsai_temperature",         0.0))
        # Fix 3: Speculative Decoding — đưỜng dẫn draft model (VD: llama3.2:1b.gguf) và số token đoán trước
        self.draft_model_path: str = cfg.get("bonsai_draft_model_path", "")
        self.draft_n: int          = int(cfg.get("bonsai_draft_n", 5))

        self._proc: Optional[subprocess.Popen] = None
        self._lock  = threading.Lock()
        self._idle_timer: Optional[threading.Timer] = None
        self._keepalive: bool = False
        self._sleep_notify_cb = None

        atexit.register(self.shutdown)

    # ── Port checks ───────────────────────────────────────────────────────────

    def _check_port(self, timeout: float = 2.0) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=timeout)
            return r.status_code in (200, 503)
        except Exception:
            return False

    def _check_port_ready(self, timeout: float = 2.0) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    # ── Process management ────────────────────────────────────────────────────

    def _start_server(self) -> bool:
        if not self.auto_start:
            log.info("[Bonsai] auto_start=false, bỏ qua wake")
            return False
        if not os.path.isfile(self.server_bin):
            log.warning(f"[Bonsai] Binary không tìm thấy: {self.server_bin}")
            return False
        if not os.path.isfile(self.model_path):
            log.warning(f"[Bonsai] Model không tìm thấy: {self.model_path}")
            return False

        log.info(f"[Bonsai] Đang thức dậy (port {self.port})...")
        try:
            _cmd = [
                self.server_bin,
                "-m", self.model_path,
                "--host", self.host,
                "--port", str(self.port),
                "-ngl", str(self.n_gpu_layers),
            ]
            # Fix 3: Speculative Decoding — thêm draft model nếu được cấu hình và file tồn tại
            if self.draft_model_path and os.path.isfile(self.draft_model_path):
                _cmd += ["--draft-model", self.draft_model_path, "--draft-n", str(self.draft_n)]
                log.info(f"[Bonsai] Speculative decoding ON: draft_n={self.draft_n}, draft={self.draft_model_path}")
            self._proc = subprocess.Popen(
                _cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.error(f"[Bonsai] Không thể khởi động server: {e}")
            return False

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._check_port_ready(timeout=2.0):
                log.info(f"[Bonsai] Server sẵn sàng tại {self.base_url}")
                return True
            if self._proc.poll() is not None:
                log.warning("[Bonsai] Process đã thoát sớm")
                self._proc = None
                return False
            time.sleep(2.0)

        log.warning(f"[Bonsai] Timeout {self.startup_timeout}s, server chưa ready")
        return False

    def _stop_server(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            log.info("[Bonsai] Server đã vào sleep mode")

    # ── Idle timer ────────────────────────────────────────────────────────────

    def _reset_idle_timer(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self._keepalive or self.idle_timeout <= 0:
            return
        self._idle_timer = threading.Timer(self.idle_timeout, self._on_idle_timeout)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle_timeout(self):
        with self._lock:
            if self._keepalive:
                self._reset_idle_timer()
                return
            log.info(f"[Bonsai] Idle {self.idle_timeout:.0f}s → sleep mode")
            self._stop_server()
            if callable(self._sleep_notify_cb):
                try:
                    self._sleep_notify_cb(
                        "Bonsai-8B đã vào chế độ ngủ. Nếu nhắn tiếp em sẽ tự thức dậy nhé!"
                    )
                except Exception:
                    pass

    def set_keepalive(self, active: bool) -> None:
        self._keepalive = active
        if active:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            log.info("[Bonsai] Keepalive ON")
        else:
            self._reset_idle_timer()
            log.info("[Bonsai] Keepalive OFF — idle timer khởi lại")

    def set_sleep_notify(self, cb) -> None:
        self._sleep_notify_cb = cb

    # ── Wake-on-demand ────────────────────────────────────────────────────────

    def _ensure_awake(self) -> bool:
        if self._check_port_ready(timeout=1.5):
            return True
        with self._lock:
            if self._check_port_ready(timeout=1.5):
                return True
            if self._check_port(timeout=1.5):
                log.info("[Bonsai] Server alive nhưng đang load model (503) — đang chờ...")
                deadline = time.monotonic() + self.startup_timeout
                while time.monotonic() < deadline:
                    if self._check_port_ready(timeout=2.0):
                        return True
                    time.sleep(2.0)
                log.warning("[Bonsai] Server load timed out")
                return False
            return self._start_server()

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Blocking call — tương thích với code cũ.
        Trả về full string hoặc None.

        ⚠️  Dùng chat_stream() nếu muốn perceived latency thấp (~300ms).
        """
        if not self._ensure_awake():
            log.warning("[Bonsai] Không thể wake server")
            return None

        self._reset_idle_timer()

        try:
            r = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model":       "bonsai",
                    "messages":    list(messages),
                    "temperature": self.temperature,
                    "max_tokens":  int(max_tokens or self.max_tokens),
                    "stream":      False,
                },
                timeout=self.call_timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning(f"[Bonsai] chat() error: {e}")
            return None

    def chat_stream(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """
        STREAMING call — yield từng token ngay khi model generate ra.

        Perceived latency ~300ms (first token) thay vì 5-8s.

        Cách dùng:
            for token in bonsai.chat_stream(messages):
                print(token, end="", flush=True)

        Với iOS / WebSocket — gửi mỗi token ngay lập tức:
            for token in bonsai.chat_stream(messages):
                ws.send(json.dumps({"type": "token", "text": token}))
            ws.send(json.dumps({"type": "done"}))
        """
        if not self._ensure_awake():
            log.warning("[Bonsai] Không thể wake server")
            return

        self._reset_idle_timer()

        try:
            with requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model":       "bonsai",
                    "messages":    list(messages),
                    "temperature": self.temperature,
                    "max_tokens":  int(max_tokens or self.max_tokens),
                    "stream":      True,   # ← KEY DIFFERENCE
                },
                timeout=self.call_timeout,
                stream=True,              # requests không buffer response
            ) as r:
                r.raise_for_status()
                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    # SSE format: "data: {...}"
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
            log.warning(f"[Bonsai] chat_stream() error: {e}")
            return

    def chat_stream_full(
        self,
        messages: List[Dict],
        on_token,           # callback(token: str) — gọi mỗi khi có token mới
        on_done=None,       # callback(full_text: str) — gọi khi xong
        max_tokens: Optional[int] = None,
    ) -> None:
        """
        Streaming với callbacks — tiện hơn khi dùng với websocket/queue.

        Ví dụ với PentaMi iOS WebSocket:
            def send_token(t):
                ws.send(json.dumps({"type":"token","text":t}))
            def send_done(full):
                ws.send(json.dumps({"type":"done","text":full}))
            bonsai.chat_stream_full(messages, on_token=send_token, on_done=send_done)
        """
        full_text = []
        for token in self.chat_stream(messages, max_tokens=max_tokens):
            full_text.append(token)
            try:
                on_token(token)
            except Exception as e:
                log.debug(f"[Bonsai] on_token callback error: {e}")

        if on_done:
            try:
                on_done("".join(full_text))
            except Exception as e:
                log.debug(f"[Bonsai] on_done callback error: {e}")

    def is_available(self) -> bool:
        return self._check_port(timeout=1.5)

    def shutdown(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        self._stop_server()


# ── Singleton ─────────────────────────────────────────────────────────────────

_default_bonsai: Optional[BonsaiClient] = None
_bonsai_lock = threading.Lock()


def get_bonsai_client() -> BonsaiClient:
    global _default_bonsai
    if _default_bonsai is None:
        with _bonsai_lock:
            if _default_bonsai is None:
                _default_bonsai = BonsaiClient()
    return _default_bonsai