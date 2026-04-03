#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: core/web_actions.py
Thực hiện các hành động web: mở URL, tìm kiếm YouTube/Google/Bing/Wiki.

Không cần API key — dùng webbrowser để mở trình duyệt hệ thống.
Platform: macOS (dùng open / webbrowser)
"""

import webbrowser
import urllib.parse
import subprocess
import logging
import os
from typing import Dict, Any

log = logging.getLogger("WebActions")


class WebActions:
    """
    Thực thi các hành động web trực tiếp trên máy tính.
    Hỗ trợ: mở URL, tìm kiếm YouTube/Google/Bing/Wiki, mở app macOS.
    """

    # ── Search engines ───────────────────────────────────────────────────────
    SEARCH_ENGINES: Dict[str, str] = {
        "youtube":   "https://www.youtube.com/results?search_query={}",
        "yt":        "https://www.youtube.com/results?search_query={}",
        "google":    "https://www.google.com/search?q={}",
        "gg":        "https://www.google.com/search?q={}",
        "bing":      "https://www.bing.com/search?q={}",
        "wikipedia": "https://vi.wikipedia.org/wiki/Special:Search?search={}",
        "wiki":      "https://vi.wikipedia.org/wiki/Special:Search?search={}",
        "github":    "https://github.com/search?q={}",
        "npm":       "https://www.npmjs.com/search?q={}",
    }

    # ── URL helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Thêm https:// nếu URL không có scheme."""
        url = url.strip()
        if not url.startswith(("http://", "https://", "ftp://")):
            url = "https://" + url
        return url

    # ── Public API ───────────────────────────────────────────────────────────

    def open_url(self, url: str) -> Dict[str, Any]:
        """Mở URL bất kỳ trong trình duyệt mặc định."""
        if not url:
            return {"ok": False, "msg": "URL trống"}
        url = self._normalize_url(url)
        try:
            webbrowser.open(url)
            log.info(f"[WebActions] open_url → {url}")
            return {"ok": True, "msg": f"Đã mở {url}", "url": url}
        except Exception as e:
            log.error(f"[WebActions] open_url error: {e}")
            return {"ok": False, "msg": str(e)}

    def open_path(self, path: str) -> Dict[str, Any]:
        """Mở file/folder cục bộ bằng app mặc định của hệ điều hành."""
        if not path:
            return {"ok": False, "msg": "Đường dẫn trống"}
        expanded = os.path.expanduser(path.strip())
        if not os.path.exists(expanded):
            return {"ok": False, "msg": f"Không tìm thấy đường dẫn '{expanded}'"}
        try:
            if os.name == "nt":
                os.startfile(expanded)
            else:
                subprocess.run(["open", expanded], capture_output=True, text=True, timeout=5)
            log.info(f"[WebActions] open_path → {expanded}")
            return {"ok": True, "msg": f"Đã mở {expanded}", "path": expanded}
        except Exception as e:
            log.error(f"[WebActions] open_path error: {e}")
            return {"ok": False, "msg": str(e), "path": expanded}

    def search_youtube(self, query: str) -> Dict[str, Any]:
        """Tìm kiếm trên YouTube với từ khoá."""
        if not query:
            return self.open_url("https://www.youtube.com")
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        webbrowser.open(url)
        log.info(f"[WebActions] YouTube search → {query!r}")
        return {"ok": True, "msg": f"Đã tìm '{query}' trên YouTube", "url": url}

    def search_google(self, query: str) -> Dict[str, Any]:
        """Tìm kiếm trên Google."""
        if not query:
            return self.open_url("https://www.google.com")
        encoded = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded}"
        webbrowser.open(url)
        log.info(f"[WebActions] Google search → {query!r}")
        return {"ok": True, "msg": f"Đã tìm '{query}' trên Google", "url": url}

    def search_on(self, platform: str, query: str) -> Dict[str, Any]:
        """
        Tìm kiếm thông minh theo platform.
        Ví dụ: search_on("youtube", "nhạc lofi") → mở YouTube tìm kiếm
        """
        p = (platform or "").lower().strip()

        # Khớp engine trong danh sách
        for key, template in self.SEARCH_ENGINES.items():
            if key in p:
                if not query:
                    # Không có query → mở trang chủ engine
                    base = template.split("?")[0]
                    return self.open_url(base)
                encoded = urllib.parse.quote(query)
                url = template.format(encoded)
                webbrowser.open(url)
                log.info(f"[WebActions] search [{key}] → {query!r}")
                return {
                    "ok": True,
                    "msg": f"Đã tìm '{query}' trên {key.title()}",
                    "url": url,
                }

        # Fallback: tìm trên Google nếu không nhận ra platform
        log.info(f"[WebActions] Platform không rõ ({p!r}), fallback Google")
        return self.search_google(query or p)

    def open_app(self, app_name: str) -> Dict[str, Any]:
        """Mở ứng dụng macOS bằng `open -a <App>`."""
        if not app_name:
            return {"ok": False, "msg": "Tên app trống"}
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                log.info(f"[WebActions] open_app → {app_name}")
                return {"ok": True, "msg": f"Đã mở {app_name}"}
            return {"ok": False, "msg": f"Không tìm thấy app '{app_name}'"}
        except FileNotFoundError:
            return {"ok": False, "msg": "Lệnh `open` không khả dụng (chạy trên macOS?)"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def play_youtube(self, query: str) -> Dict[str, Any]:
        """Alias: phát nhạc/video → search YouTube."""
        return self.search_youtube(query)
