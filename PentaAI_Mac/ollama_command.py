#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: ollama_command.py
Mục đích: Phân tích câu lệnh tự nhiên thành cấu trúc action/target/parameters
Sử dụng Ollama để hiểu ý định người dùng.
Có thể mở rộng độc lập với phần còn lại của hệ thống.
"""

import json
import logging
import requests
import time
from typing import List, Dict, Any, Optional

log = logging.getLogger("OllamaCommand")

class OllamaCommandInterpreter:
    """
    Lớp trung tâm để giao tiếp với Ollama và chuyển đổi văn bản thành lệnh.
    Có thể tùy chỉnh model, URL, và prompt.
    """

    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "llama3.2:1b"):
        self.ollama_url = ollama_url
        self.model = model
        self._available = None
        self._last_check = 0

    def _check_ollama(self) -> bool:
        """Kiểm tra Ollama có sẵn sàng không, cache 60s."""
        now = time.monotonic()
        if self._available is not None and (now - self._last_check) < 60:
            return self._available
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            self._available = r.status_code == 200
        except Exception:
            self._available = False
        self._last_check = now
        return self._available

    def interpret(self, text: str, available_commands: List[str] = None) -> Dict[str, Any]:
        """
        Nhận câu lệnh tự nhiên, trả về dict với các khóa:
            - action:   hành động (open, close, toggle, run, search, ...)
            - target:   đối tượng tác động (notepad, đèn, ...)
            - parameters: tham số bổ sung (nếu có)
            - error:    thông báo lỗi (nếu Ollama không khả dụng hoặc parse sai)
            - raw:      nội dung thô trả về từ Ollama (khi lỗi)
        """
        if not self._check_ollama():
            return {"error": "Ollama không khả dụng"}

        # Tạo phần danh sách lệnh đã biết (nếu có)
        known_section = ""
        if available_commands:
            known_list = ", ".join(f'"{c}"' for c in available_commands[:20])
            known_section = (
                f"\nCác lệnh hiện có trong hệ thống: [{known_list}]. "
                "Hãy ưu tiên dùng tên lệnh trong danh sách này nếu phù hợp."
            )

        # Prompt hệ thống
        sys_prompt = (
            "You are a command parser. Respond with ONLY a valid JSON object, no other text, no markdown, no explanation. "
            "The JSON must have keys: action, target, parameters. "
            "Examples:\n"
            "- Input: 'mở google' -> Output: {\"action\":\"open\",\"target\":\"https://www.google.com\",\"parameters\":\"\"}\n"
            "- Input: 'mở notepad' -> Output: {\"action\":\"run\",\"target\":\"notepad.exe\",\"parameters\":\"\"}\n"
            "- Input: 'tìm mèo trên youtube' -> Output: {\"action\":\"search\",\"target\":\"mèo\",\"parameters\":\"youtube\"}\n"
            "Do not include any other text."
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": text},
        ]

        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=10,
            )
            response.raise_for_status()
            raw_content: str = response.json()["message"]["content"].strip()

            # Xóa code block markdown nếu có
            if raw_content.startswith("```"):
                # Bỏ dòng đầu (```json hoặc ```)
                lines = raw_content.split("\n")
                raw_content = "\n".join(lines[1:])
                if raw_content.endswith("```"):
                    raw_content = raw_content[:-3].strip()

            # Loại bỏ các ký tự không phải JSON trước và sau
            import re
            json_match = re.search(r'(\{.*\})', raw_content, re.DOTALL)
            if json_match:
                raw_content = json_match.group(1)

            parsed = json.loads(raw_content)

            return {
                "action":     str(parsed.get("action", "")).strip(),
                "target":     str(parsed.get("target", "")).strip(),
                "parameters": str(parsed.get("parameters", "")).strip(),
            }
        except json.JSONDecodeError as e:
            log.warning(f"JSON decode error: {e}\nRaw content: {raw_content}")
            return {"error": "Không thể hiểu lệnh", "raw": raw_content}


# Tiện ích: tạo instance mặc định
_default_interpreter = None

def get_default_interpreter() -> OllamaCommandInterpreter:
    global _default_interpreter
    if _default_interpreter is None:
        _default_interpreter = OllamaCommandInterpreter()
    return _default_interpreter
