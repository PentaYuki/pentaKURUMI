#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI SkillManager
=====================
Cổng giao tiếp trung gian giữa ai_server và các skill module.

Thiết kế:
  - ai_server chỉ cần import SkillManager và gọi dispatch().
  - Để thêm skill mới: tạo file trong skills/, không sửa ai_server.
  - Để tắt/bật skill: chỉnh enabled=False trong SKILL_META hoặc xóa file.

Mỗi skill phải export (bắt buộc):
  SKILL_META: dict  — {"name", "version", "description", "enabled"(opt)}
  check_intent(text: str) -> bool
  run(text: str, context: dict) -> dict  — {"response": str, "pipeline": str}
"""

import os
import importlib
import importlib.util
import logging
import inspect
from typing import Optional, Dict, Any, List

log = logging.getLogger("SkillManager")

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


class SkillManager:
    """
    Tự động nạp toàn bộ skill từ thư mục skills/.
    Cung cấp dispatch() để ai_server gọi khi xử lý tin nhắn.
    """

    def __init__(self, skills_dir: str = None):
        self._dir: str    = skills_dir or _SKILLS_DIR
        self._skills: List[Dict[str, Any]] = []
        self.load_all()

    # ── Load ─────────────────────────────────────────────────────────────────

    def load_all(self) -> None:
        """Quét và nạp tất cả skill trong thư mục skills/."""
        self._skills = []
        if not os.path.isdir(self._dir):
            log.warning(f"[SkillManager] Thư mục skills không tồn tại: {self._dir}")
            return

        for fname in sorted(os.listdir(self._dir)):
            if fname.startswith("_") or not fname.endswith(".py"):
                continue
            self._load_skill_file(os.path.join(self._dir, fname), fname[:-3])

        log.info(f"[SkillManager] Đã nạp {len(self._skills)} skill: "
                 f"{[s['meta']['name'] for s in self._skills]}")

    def _load_skill_file(self, path: str, module_name: str) -> None:
        """Nạp một file skill, kiểm tra interface bắt buộc."""
        try:
            spec   = importlib.util.spec_from_file_location(
                f"penta_skills.{module_name}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            meta = getattr(module, "SKILL_META", None)
            if not isinstance(meta, dict) or not meta.get("name"):
                log.warning(f"[SkillManager] {module_name}: thiếu SKILL_META — bỏ qua")
                return
            if not callable(getattr(module, "check_intent", None)):
                log.warning(f"[SkillManager] {module_name}: thiếu check_intent() — bỏ qua")
                return
            if not callable(getattr(module, "run", None)):
                log.warning(f"[SkillManager] {module_name}: thiếu run() — bỏ qua")
                return

            # enabled mặc định True trừ khi skill tự khai báo False
            if not meta.get("enabled", True):
                log.info(f"[SkillManager] {meta['name']} đã tắt (enabled=False)")
                return

            self._skills.append({
                "meta":   meta,
                "module": module,
            })
            log.info(f"[SkillManager] ✅ Nạp skill: {meta['name']} v{meta.get('version', '?')}")

        except Exception as e:
            log.error(f"[SkillManager] Lỗi khi nạp {module_name}: {e}")

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def dispatch(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Thử từng skill theo thứ tự.
        Trả về dict kết quả nếu skill nào đó nhận xử lý, ngược lại None.

        Kết quả: {"response": str, "pipeline": str, "skill": str}
        """
        ctx = context or {}
        for entry in self._skills:
            mod  = entry["module"]
            name = entry["meta"]["name"]
            try:
                check_intent = getattr(mod, "check_intent")
                try:
                    params = inspect.signature(check_intent).parameters
                    matched = bool(check_intent(text, ctx)) if len(params) >= 2 else bool(check_intent(text))
                except (TypeError, ValueError):
                    matched = bool(check_intent(text))

                if matched:
                    log.info(f"[SkillManager] '{text[:40]}' → skill: {name}")
                    result = mod.run(text, ctx)
                    if isinstance(result, dict) and result.get("response"):
                        result["skill"] = name
                        return result
            except Exception as e:
                log.error(f"[SkillManager] Lỗi khi chạy skill {name}: {e}")
        return None

    # ── Info ─────────────────────────────────────────────────────────────────

    def list_skills(self) -> List[Dict[str, Any]]:
        """Trả về danh sách meta của các skill đã nạp."""
        return [s["meta"] for s in self._skills]

    def reload(self) -> None:
        """Nạp lại toàn bộ skill (dùng khi có skill update lúc runtime)."""
        log.info("[SkillManager] Reload skill...")
        self.load_all()


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: Optional[SkillManager] = None


def get_skill_manager() -> Optional[SkillManager]:
    """
    Trả về singleton SkillManager.
    Trả về None nếu thư mục skills/ chưa tồn tại hoặc lỗi init.
    """
    global _manager
    if _manager is None:
        try:
            _manager = SkillManager()
        except Exception as e:
            log.error(f"[SkillManager] Không khởi tạo được: {e}")
            _manager = None
    return _manager
