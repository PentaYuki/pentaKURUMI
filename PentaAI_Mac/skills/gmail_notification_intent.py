#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Skill: Gmail Notification Intent Handler v1.0
========================================================
Xử lý các lệnh liên quan Gmail notification:
- "bật PentaGmail" - Enable Gmail notification
- "tắt PentaGmail" - Disable Gmail notification
- "có tin nhắn nào không?" - Check queue
- "được rồi" / "không cần" - User response
"""

import re
import logging
from typing import Dict, Any

log = logging.getLogger("Skill.GmailNotif")

SKILL_META: Dict[str, Any] = {
    "name": "GmailNotificationIntent",
    "version": "1.3",
    "description": "Xử lý lệnh Gmail notification như bật/tắt, kiểm tra tin nhắn",
    "author": "PentaAI",
    "enabled": True,
}

# ── Intent Patterns ────────────────────────────────────────────────────────────
_PENTAGMAIL_ALIAS = r"(?:pentagmail|penta\s*gmail|pentgmail)"

_RE_ENABLE = re.compile(
    rf"\b(bật|kích hoạt|bật lên|start)\s+({_PENTAGMAIL_ALIAS}|gmail\s*notif|thông\s*báo\s*gmail|gmail)"
    r"|\bgmail\s+(notification|notif|thông\s*báo)\s+(bật|on|start|enable)\b"
    rf"|\bthực\s*hiện\s*{_PENTAGMAIL_ALIAS}\b"
    r"|\bgmail\s*em\s*xin\s*bật",
    re.IGNORECASE | re.UNICODE,
)

_RE_DISABLE = re.compile(
    rf"\b(tắt|vô hiệu hóa|tắt đi|stop)\s+({_PENTAGMAIL_ALIAS}|gmail\s*notif|thông\s*báo\s*gmail|gmail)"
    r"|\bgmail\s+(notification|notif|thông\s*báo)\s+(tắt|off|stop|disable)\b"
    rf"|\btắt\s*{_PENTAGMAIL_ALIAS}\b"
    rf"|\bkhông\s*cần\s*{_PENTAGMAIL_ALIAS}",
    re.IGNORECASE | re.UNICODE,
)

_RE_CHECK = re.compile(
    r"\b(có|kiểm\s*tra|xem)\s+(tin\s*nhắn|email|mail|gmail).*(nào|không|gì|chưa)"
    r"|\b(kiểm\s*tra|xem|check)\s*(gmail|mail|email)\b"
    r"|\b(gmail|mail|email)\s*(check|kiểm\s*tra)\b"
    r"|\btin\s*nhắn\s*nào\s*mới\b"
    r"|\bemail\s*nào\s*chưa\s*đọc\b"
    r"|\bqueue\s*gmail\b"
    r"|\bcheck\s*mail(s)?",
    re.IGNORECASE | re.UNICODE,
)

_RE_CLEAR = re.compile(
    r"\b(xóa|xoá|clear|dọn|don|hủy|huy)\s*(hết|het|toàn\s*bộ|tat\s*ca|all)?\s*"
    r"(hàng\s*đợi|queue|thông\s*báo|tin\s*nhắn|email)?\s*(gmail|mail)?\b"
    r"|\bclear\s*(gmail\s*)?queue\b"
    r"|\bxóa\s*(hết\s*)?(queue\s*)?gmail\b",
    re.IGNORECASE | re.UNICODE,
)

_RE_YES = re.compile(
    r"\b(được|được rồi|được thôi|ok|okela|okee|vâng|được bạn|được em|được mà|được à|chắc rồi|xong rồi)\b"
    r"|\b(yes|yeah|yep|yup|1|true|sure|fine)\b"
    r"|\bĐ\b",
    re.IGNORECASE | re.UNICODE,
)

_RE_NO = re.compile(
    r"\b(không|không cần|không muốn|thôi|thôi được|không được|không được bạn|bỏ qua|bỏ)\b"
    r"|\b(no|nope|nah|0|false|skip|never)\b"
    r"|\bK\b",
    re.IGNORECASE | re.UNICODE,
)

_YES_EXACT = {
    "co", "có", "yes", "yeah", "yep", "yup", "ok", "oke", "okela",
    "okee", "vâng", "vang", "được", "duoc", "đ", "1", "true", "sure", "fine",
}
_NO_EXACT = {
    "khong", "không", "no", "nope", "nah", "k", "0", "false", "skip",
    "thoi", "thôi", "bo", "bỏ",
}

# ── Public Interface ───────────────────────────────────────────────────────────

def check_intent(text: str, context: Dict[str, Any] = None) -> bool:
    """Check if text is a Gmail notification command.

    Yes/No chỉ được coi là Gmail intent khi thực sự đang có email chờ xác nhận,
    tránh cướp mất các câu trả lời ngắn của ngữ cảnh hội thoại khác.
    """
    if _RE_ENABLE.search(text) or _RE_DISABLE.search(text) or _RE_CHECK.search(text) or _RE_CLEAR.search(text):
        return True

    if _is_short_confirmation(text, positive=True) or _is_short_confirmation(text, positive=False):
        return _has_pending_gmail_confirmation()

    return False


def run(text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Handle Gmail notification intents.
    
    Returns:
      {
        "response": str,
        "pipeline": str,
        "meta": {
          "action": "enable" | "disable" | "check" | "response",
          "action_detail": dict,
        }
      }
    """
    ctx = context or {}
    ai_prn = ctx.get("ai_pronoun", "em")
    user_call = ctx.get("user_call", "anh")
    lang = ctx.get("lang", "vi")
    
    # Check intents in order of priority
    if _RE_ENABLE.search(text):
        return _handle_enable(lang, ai_prn, user_call)
    
    if _RE_DISABLE.search(text):
        return _handle_disable(lang, ai_prn, user_call)
    
    if _RE_CHECK.search(text):
        return _handle_check(lang, ai_prn, user_call)

    if _RE_CLEAR.search(text):
        return _handle_clear(lang, ai_prn, user_call)
    
    if _is_short_confirmation(text, positive=True) and _has_pending_gmail_confirmation():
        return _handle_yes(lang, ai_prn, user_call)
    
    if _is_short_confirmation(text, positive=False) and _has_pending_gmail_confirmation():
        return _handle_no(lang, ai_prn, user_call)
    
    return {
        "response": f"Xin lỗi {user_call}, {ai_prn} không hiểu yêu cầu.",
        "pipeline": "skill_gmail_notif_unknown",
        "meta": {"action": None},
    }


# ── Handlers ───────────────────────────────────────────────────────────────────

def _handle_enable(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle enable Gmail notification."""
    resp = _t(lang,
        vi=f"{ai_prn.capitalize()} sẽ bật Gmail Notification cho {user_call} rồi ạ. "
           f"Khi có email từ danh sách {user_call} cấu hình, "
           f"{ai_prn} sẽ phát thông báo: 'Bạn có tin nhắn từ [tên người gửi]' nhé.",
        en=f"I'll enable Gmail Notification for you, {user_call}. "
           f"When emails arrive from your whitelist, I'll announce them. ",
        ja=f"メール通知を有効にします。設定したメールアドレスからのメールが届くと通知します。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_enable",
        "meta": {
            "action": "enable",
            "action_detail": {},
        },
    }


def _handle_disable(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle disable Gmail notification."""
    resp = _t(lang,
        vi=f"{ai_prn.capitalize()} đã tắt Gmail Notification của {user_call} rồi ạ.",
        en=f"Gmail Notification is now disabled, {user_call}.",
        ja=f"メール通知を無効にしました。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_disable",
        "meta": {
            "action": "disable",
            "action_detail": {},
        },
    }


def _handle_check(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle check Gmail queue."""
    resp = _t(lang,
        vi=f"{ai_prn.capitalize()} sẽ kiểm tra hàng đợi email của {user_call}.",
        en=f"Let me check your email queue, {user_call}.",
        ja=f"メールキューを確認します。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_check",
        "meta": {
            "action": "check",
            "action_detail": {},
        },
    }


def _handle_yes(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle user's 'yes' response to email notification."""
    resp = _t(lang,
        vi=f"Vâng, {ai_prn} sẽ đọc nội dung email cho {user_call} ngay ạ.",
        en=f"Sure, {user_call}, I'll read it for you.",
        ja=f"了解です。メールの内容をお読みします。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_yes",
        "meta": {
            "action": "response",
            "action_detail": {"user_response": "yes"},
        },
    }


def _handle_clear(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle clear all Gmail notification queue."""
    resp = _t(lang,
        vi=f"Được rồi {user_call}, {ai_prn} sẽ xóa toàn bộ hàng đợi thông báo Gmail.",
        en=f"Got it, {user_call}. I'll clear all Gmail notification queue.",
        ja=f"了解です。Gmail通知キューをすべてクリアします。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_clear",
        "meta": {
            "action": "clear",
            "action_detail": {},
        },
    }


def _handle_no(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    """Handle user's 'no' response to email notification."""
    resp = _t(lang,
        vi=f"Được rồi {user_call}, {ai_prn} sẽ nhắc lại sau 15 phút nếu {user_call} chưa đọc.",
        en=f"Understood, {user_call}. I'll remind you again in 15 minutes.",
        ja=f"了解しました。15分後にもう一度お知らせします。",
    )
    return {
        "response": resp,
        "pipeline": "skill_gmail_notif_no",
        "meta": {
            "action": "response",
            "action_detail": {"user_response": "no"},
        },
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _t(lang: str, vi: str = "", en: str = "", ja: str = "") -> str:
    """Translate by language."""
    return {"vi": vi, "en": en, "ja": ja}.get(lang, vi)


def _has_pending_gmail_confirmation() -> bool:
    """Chỉ cho yes/no đi vào Gmail flow khi daemon đang có mail chờ trả lời."""
    try:
        from services.gmail_notification_daemon import get_daemon

        daemon = get_daemon()
        return daemon is not None and daemon.get_oldest_waiting_uid() is not None
    except Exception:
        return False


def _is_short_confirmation(text: str, positive: bool) -> bool:
    """Chỉ nhận yes/no khi là câu xác nhận ngắn để tránh cướp intent câu hỏi khác.

    Ví dụ hợp lệ: "có", "được", "ok", "không", "thôi".
    Ví dụ không hợp lệ: "mai anh có lịch gì không".
    """
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False

    # Giữ logic cũ cho các cụm rõ nghĩa nhưng vẫn giới hạn độ dài.
    has_pattern = bool(_RE_YES.search(cleaned) if positive else _RE_NO.search(cleaned))
    tokenized = re.sub(r"[\.,!?;:\-\(\)\[\]\{\}\"'`]+", " ", cleaned)
    words = [w for w in tokenized.split() if w]
    if len(words) > 3:
        return False

    compact = " ".join(words)
    exact_set = _YES_EXACT if positive else _NO_EXACT
    if compact in exact_set:
        return True

    # Cho phép các cụm ngắn đã có trong regex (vd: "được rồi", "không cần").
    return has_pattern and len(words) <= 3
