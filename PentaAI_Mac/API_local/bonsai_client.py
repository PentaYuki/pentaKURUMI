#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: bonsai_client.py  [DEPRECATED — Compatibility Shim]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  File này chỉ còn là shim tương thích ngược.
    Logic thực tế đã chuyển sang: API_local/mlx_client.py

Tất cả import cũ vẫn hoạt động không đổi:
    from API_local.bonsai_client import BonsaiClient, get_bonsai_client

Chuỗi fallback mới (từ mlx_client.py):
  Ollama 1B  →  MLX-vLLM Qwen2.5-7B-Instruct-4bit (tier 2)  →  Cloud (tier 3)

Lý do giữ file này:
  - ai_server.py, pentami_chat.py, ollama_command.py đều import từ đây
  - Giữ backward compat không cần sửa toàn bộ codebase ngay
  - Trong tương lai có thể xóa hoàn toàn sau khi tất cả đã dùng mlx_client
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging

log = logging.getLogger("BonsaiClient")
log.info(
    "[BonsaiClient] ⚠️ bonsai_client.py là shim — "
    "dùng mlx_client.py (MLX-vLLM Qwen2.5-7B)"
)

# Re-export toàn bộ từ mlx_client
from .mlx_client import (
    MLXClient as BonsaiClient,      # BonsaiClient → MLXClient
    MLXClient,
    AsyncMLXClient,
    get_mlx_client as get_bonsai_client,  # get_bonsai_client() → get_mlx_client()
    get_mlx_client,
    get_async_mlx_client,
    _load_config,
)

__all__ = [
    "BonsaiClient",
    "MLXClient",
    "AsyncMLXClient",
    "get_bonsai_client",
    "get_mlx_client",
    "get_async_mlx_client",
]