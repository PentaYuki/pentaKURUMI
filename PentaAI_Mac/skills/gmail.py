#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Skill: GmailReader v3.0
================================
Đọc Gmail qua IMAP + App Password — không cần OAuth, không bao giờ hết hạn token.

Thiết kế phù hợp kiến trúc PentaKURUMI:
  ┌─────────────────────────────────────────────────────┐
  │  SkillManager.dispatch(text, context)               │
  │       ↓ check_intent()                              │
  │  GmailSkill.run(text, context)                      │
  │       ↓                                             │
  │  [Intent Router] ──► read    → fetch + filter       │
  │                  ──► urgent  → filter khẩn cấp      │
  │                  ──► from    → filter theo sender    │
  │                  ──► task    → detect + route AI     │
  │                  ──► count   → đếm nhanh            │
  └─────────────────────────────────────────────────────┘

Tính năng:
  - IMAP + App Password (không OAuth, không hết hạn, tự động hoàn toàn)
  - 3 tầng lọc spam: Whitelist → Blacklist domain → Blacklist subject
  - Nhận diện email có công việc → trả về meta.needs_action = True
    để ai_server hoặc AI router dispatch sang skill xử lý tiếp
  - Kết nối IMAP được cache + keepalive thread (không reconnect mỗi request)
  - Config đọc từ data/gmail_config.json (theo pattern PentaAI)
  - Output format thân thiện với TTS (câu ngắn, không markdown)
  - Báo thống kê: "Em lọc 5 email rác, còn 3 email quan trọng"
  - Decode RFC 2047 subject/sender chuẩn (không hiện ký tự rác)
  - Hỗ trợ VI / EN / JA

Thiết lập (chỉ 1 lần):
  1. Gmail → Settings → See all settings → Forwarding/POP/IMAP → Enable IMAP
  2. Google Account → Security → 2-Step Verification → App Passwords
  3. Tạo App Password → copy vào data/gmail_config.json

Cấu trúc data/gmail_config.json:
  {
    "email":    "yourname@gmail.com",
    "password": "xxxx xxxx xxxx xxxx",
    "max_emails": 5,
    "whitelist": ["boss@company.com", "bank@vcb.vn"],
    "blacklist_domains": ["mailchimp", "sendgrid", "newsletter"],
    "blacklist_subjects": ["khuyến mãi", "unsubscribe", "click here"],
    "task_detection": true
  }

Không cần pip install gì — dùng imaplib / email có sẵn trong Python stdlib.
"""

import os
import re
import json
import imaplib
import email
import logging
import threading
import time
from datetime import datetime
from email.header import decode_header as _rfc2047_decode
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Dict, Any, Optional, List, Tuple

log = logging.getLogger("Skill.Gmail")

# ── Skill meta (bắt buộc cho SkillManager) ───────────────────────────────────
SKILL_META: Dict[str, Any] = {
    "name":        "GmailReader",
    "version":     "3.0",
    "description": "Đọc Gmail qua IMAP, lọc spam 3 tầng, nhận diện email có công việc",
    "author":      "PentaAI",
    "requires":    [],   # stdlib only — không cần pip install gì thêm
    "enabled":     True,
}

# ── Paths (theo pattern PentaAI) ──────────────────────────────────────────────
_DATA_DIR    = os.path.join(os.path.dirname(__file__), "..", "data")
_CONFIG_FILE = os.path.join(_DATA_DIR, "gmail_config.json")
_MAIN_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.json")

# ── IMAP settings ─────────────────────────────────────────────────────────────
_IMAP_HOST      = "imap.gmail.com"
_IMAP_PORT      = 993
_KEEPALIVE_SEC  = 60    # gửi NOOP mỗi 60s để giữ kết nối
_CONNECT_TIMEOUT = 10
_SNIPPET_LEN    = 80

# ── Default config ────────────────────────────────────────────────────────────
_DEFAULT_CONFIG: Dict[str, Any] = {
    "email":    "",
    "password": "",
    "max_emails": 5,
    "whitelist": [],
    "blacklist_domains": [
        "mailchimp", "sendgrid", "klaviyo", "hubspot", "constantcontact",
        "mailjet", "drip", "convertkit", "activecampaign", "sendinblue",
        "newsletter", "noreply", "no-reply", "donotreply", "mailer-daemon",
        "bounce", "unsubscribe", "notification", "promotions", "marketing",
        "amazonses", "postmaster", "automailer",
    ],
    "blacklist_subjects": [
        "khuyến mãi", "giảm giá", "miễn phí", "trúng thưởng", "ưu đãi đặc biệt",
        "click ngay", "đăng ký ngay", "mua ngay", "hết hạn hôm nay",
        "unsubscribe", "click here", "limited offer", "you've won",
        "free gift", "act now", "verify your account", "confirm your email",
        "congratulations you", "you have been selected",
    ],
    "task_detection": True,
}

# ── Task keywords — nhận diện email có công việc ─────────────────────────────
_TASK_KEYWORDS = {
    "vi": [
        "họp", "meeting", "lịch", "deadline", "khẩn", "gấp", "quan trọng",
        "cần xử lý", "nhờ", "yêu cầu", "báo cáo", "hóa đơn", "thanh toán",
        "hợp đồng", "ký", "duyệt", "phê duyệt", "phản hồi",
        "theo dõi", "follow up", "reminder", "nhắc nhở",
    ],
    "en": [
        "meeting", "urgent", "asap", "deadline", "action required",
        "please review", "please confirm", "invoice", "payment due",
        "contract", "sign", "approval", "follow up", "reminder",
        "time sensitive", "important", "respond by",
    ],
}

# ── Intent patterns ───────────────────────────────────────────────────────────
_RE_READ = re.compile(
    r"\b("
    r"đọc\s*(email|mail|gmail|thư)|"
    r"kiểm\s*tra\s*(email|mail|gmail|thư)|"
    r"xem\s*(email|mail|gmail|hộp\s*thư|hòm\s*thư|thư\s*đến)|"
    r"có\s*(email|mail|thư)\s*(mới|gì|không|chưa)|"
    r"(email|mail|gmail|thư)\s*(hôm\s*nay|mới|đến|chưa\s*đọc)|"
    r"hộp\s*thư(\s*đến)?|hòm\s*thư|inbox|"
    r"(mail|thư)\s*chưa\s*đọc|"
    r"read\s*(email|mail|gmail)|check\s*(email|mail|gmail)|"
    r"any\s*(new\s*)?(email|mail)s?"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_URGENT = re.compile(
    r"\b(email|mail|thư)\s*(khẩn|gấp|quan\s*trọng|urgent|important)\b"
    r"|\b(khẩn|urgent)\s*(email|mail|thư)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_FROM = re.compile(
    r"\b(email|mail|thư)\s*(từ|from|của)\s+(.+)",
    re.IGNORECASE | re.UNICODE,
)
_RE_TASK = re.compile(
    r"\b(email\s*(có\s*)?công\s*việc|mail\s*cần\s*làm|task\s*từ\s*mail"
    r"|email\s*cần\s*xử\s*lý|email\s*yêu\s*cầu)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_COUNT = re.compile(
    r"\b(bao\s*nhiêu|mấy)\s*(email|mail|thư)\b"
    r"|\bhow\s*many\s*(email|mail)s?\b",
    re.IGNORECASE | re.UNICODE,
)


# ── IMAP connection pool ──────────────────────────────────────────────────────

class _IMAPPool:
    """
    Giữ một kết nối IMAP sống lâu dài.
    Tự động reconnect khi mất kết nối.
    Gửi NOOP mỗi 60s để giữ session.
    """
    def __init__(self):
        self._conn: Optional[imaplib.IMAP4_SSL] = None
        self._lock  = threading.Lock()
        self._ka_thread: Optional[threading.Thread] = None
        self._running   = False
        self._cfg: Dict = {}

    def connect(self, cfg: Dict[str, Any]) -> bool:
        with self._lock:
            self._cfg = cfg
            return self._do_connect()

    def _do_connect(self) -> bool:
        try:
            if self._conn:
                try:
                    self._conn.logout()
                except Exception:
                    pass
            conn = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
            conn.socket().settimeout(_CONNECT_TIMEOUT)
            conn.login(self._cfg["email"], self._cfg["password"])
            self._conn = conn
            log.info("[Gmail] ✅ IMAP kết nối thành công")
            self._start_keepalive()
            return True
        except imaplib.IMAP4.error as e:
            log.error(f"[Gmail] ❌ IMAP login thất bại: {e}")
            self._conn = None
            return False
        except Exception as e:
            log.error(f"[Gmail] ❌ IMAP lỗi: {e}")
            self._conn = None
            return False

    def get(self) -> Optional[imaplib.IMAP4_SSL]:
        with self._lock:
            if self._conn is None and self._cfg:
                self._do_connect()
            return self._conn

    def invalidate(self):
        """Đánh dấu kết nối đã chết — sẽ reconnect lần sau."""
        with self._lock:
            self._conn = None
            log.info("[Gmail] Kết nối IMAP bị invalidate, sẽ reconnect lần sau")

    def _start_keepalive(self):
        if self._ka_thread and self._ka_thread.is_alive():
            return
        self._running = True
        self._ka_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="GmailKeepalive"
        )
        self._ka_thread.start()

    def _keepalive_loop(self):
        while self._running:
            time.sleep(_KEEPALIVE_SEC)
            with self._lock:
                if self._conn:
                    try:
                        self._conn.noop()
                    except Exception:
                        log.warning("[Gmail] Keepalive NOOP thất bại → sẽ reconnect")
                        self._conn = None


_imap_pool = _IMAPPool()   # singleton dùng chung toàn bộ skill


# ── Config ────────────────────────────────────────────────────────────────────

def _load_config() -> Dict[str, Any]:
    """Ưu tiên config hệ thống (`config.json`), fallback file cũ gmail_config.json.

    Quy tắc:
    1) default
    2) legacy data/gmail_config.json (nếu có)
    3) main config.json ghi đè cuối cùng (ưu tiên cao nhất)
    """
    cfg = dict(_DEFAULT_CONFIG)

    # Backward compatibility: cấu hình cũ của skill.
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception as e:
        log.warning(f"[Gmail] Không đọc được legacy config gmail_config.json: {e}")

    # Single source of truth: config hệ thống.
    try:
        if os.path.exists(_MAIN_CONFIG_FILE):
            with open(_MAIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                main_cfg = json.load(f)

            # Các key dùng chung trực tiếp.
            for k in ("email", "password", "max_emails", "task_detection"):
                if k in main_cfg and main_cfg[k] is not None:
                    cfg[k] = main_cfg[k]

            # Nếu whitelist riêng của gmail.py chưa có, dùng whitelist notification để đồng bộ một nguồn.
            if not cfg.get("whitelist") and isinstance(main_cfg.get("gmail_notification_whitelist"), list):
                merged = []
                for item in main_cfg.get("gmail_notification_whitelist", []):
                    if isinstance(item, dict):
                        em = str(item.get("email", "")).strip()
                        if em:
                            merged.append(em)
                if merged:
                    cfg["whitelist"] = merged

    except Exception as e:
        log.warning(f"[Gmail] Không đọc được main config config.json: {e}")

    return cfg


# ── Public interface (bắt buộc cho SkillManager) ─────────────────────────────

def check_intent(text: str) -> bool:
    """Trả về True nếu người dùng muốn làm gì đó liên quan Gmail."""
    return bool(
        _RE_READ.search(text)
        or _RE_URGENT.search(text)
        or _RE_FROM.search(text)
        or _RE_TASK.search(text)
        or _RE_COUNT.search(text)
    )


def run(text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Entry point cho SkillManager.dispatch().

    Intent Router:
      count   → đếm nhanh (không fetch body)
      urgent  → lọc email khẩn cấp
      from X  → lọc email từ sender cụ thể
      task    → tìm email có công việc
      (mặc định) → đọc email chưa đọc + lọc spam

    Return:
      {
        "response": str,          # câu trả lời TTS-ready
        "pipeline": str,          # skill_gmail | skill_gmail_urgent | ...
        "meta": {
          "total_unread": int,
          "shown": int,
          "filtered": int,
          "tasks_found": list,
          "needs_action": bool,   # True → ai_server có thể dispatch AI tiếp
          "email_list": list,     # raw data cho skill khác dùng
        }
      }
    """
    ctx       = context or {}
    ai_prn    = ctx.get("ai_pronoun", "em")
    user_call = ctx.get("user_call", "anh")
    lang      = ctx.get("lang", "vi")

    cfg = _load_config()

    if not cfg.get("email") or not cfg.get("password"):
        return {
            "response": (
                f"Chưa cấu hình Gmail {user_call} ơi. "
                f"Anh điền email và app_password trong file config.json giúp em nhé. "
                f"(Legacy vẫn hỗ trợ: data/gmail_config.json)"
            ),
            "pipeline": "skill_gmail_no_config",
            "meta": {"error": "no_config"},
        }

    # Kết nối IMAP (pool tự reconnect nếu cần)
    conn = _imap_pool.get()
    if conn is None:
        ok = _imap_pool.connect(cfg)
        if not ok:
            return {
                "response": _t(lang,
                    vi=f"{ai_prn.capitalize()} không kết nối được Gmail {user_call} ơi. "
                       f"Kiểm tra email, app_password và IMAP đã bật chưa nhé.",
                    en=f"Couldn't connect to Gmail, {user_call}. "
                       f"Please check your email, app_password and that IMAP is enabled.",
                    ja=f"Gmailに接続できませんでした。メールアドレスとアプリパスワードを確認してください。",
                ),
                "pipeline": "skill_gmail_connect_fail",
                "meta": {"error": "connect_fail"},
            }
        conn = _imap_pool.get()

    # ── Intent Router ──────────────────────────────────────────────────────────
    if _RE_COUNT.search(text):
        return _handle_count(conn, lang, ai_prn, user_call)

    if _RE_URGENT.search(text):
        return _handle_urgent(conn, cfg, lang, ai_prn, user_call)

    m_from = _RE_FROM.search(text)
    if m_from:
        return _handle_from(conn, cfg, lang, ai_prn, user_call,
                            sender_query=m_from.group(3).strip())

    if _RE_TASK.search(text):
        return _handle_task_emails(conn, cfg, lang, ai_prn, user_call)

    return _handle_read(conn, cfg, lang, ai_prn, user_call)


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_read(conn, cfg, lang, ai_prn, user_call) -> Dict[str, Any]:
    """Đọc email chưa đọc + 3 tầng lọc spam + báo thống kê."""
    try:
        raw = _fetch_unread(conn, limit=cfg.get("max_emails", 5) * 3)
    except Exception as e:
        _imap_pool.invalidate()
        log.error(f"[Gmail] Fetch lỗi: {e}")
        return _fetch_error(lang, ai_prn, user_call)

    if not raw:
        return {
            "response": _t(lang,
                vi=f"Hộp thư của {user_call} không có email chưa đọc nào {ai_prn} ạ. 📭",
                en=f"No unread emails right now, {user_call}! 📭",
                ja=f"{user_call}さん、未読メールはありません。📭",
            ),
            "pipeline": "skill_gmail",
            "meta": {"total_unread": 0},
        }

    whitelisted, normal, filtered = _apply_filters(raw, cfg)
    max_n    = cfg.get("max_emails", 5)
    selected = (whitelisted + normal)[:max_n]
    n_filter = len(filtered)

    if not selected:
        return {
            "response": _t(lang,
                vi=f"{ai_prn.capitalize()} tìm thấy {len(raw)} email "
                   f"nhưng tất cả là quảng cáo hoặc spam, "
                   f"{ai_prn} đã lọc hết cho {user_call} rồi nhé. 🗑️",
                en=f"Found {len(raw)} emails but all appear to be spam or promotions — "
                   f"filtered them all out for you, {user_call}.",
                ja=f"{len(raw)}件ありますが、すべてスパムのようです。除外しました。",
            ),
            "pipeline": "skill_gmail",
            "meta": {"total_unread": len(raw), "filtered": n_filter},
        }

    n_shown = len(selected)
    n_star  = len(whitelisted)
    items   = "\n".join(f"  {i+1}. {_fmt_line(e)}" for i, e in enumerate(selected))

    filter_note = (_t(lang,
        vi=f" ({ai_prn} đã lọc {n_filter} email rác)",
        en=f" ({n_filter} spam filtered out)",
        ja=f"（{n_filter}件除外）",
    ) if n_filter > 0 else "")

    star_note = (_t(lang,
        vi=f" Có {n_star} email từ người quan trọng ⭐",
        en=f" {n_star} from priority senders ⭐",
        ja=f" 重要な送信者から{n_star}件 ⭐",
    ) if n_star > 0 else "")

    header = _t(lang,
        vi=f"{ai_prn.capitalize()} thấy {n_shown} email chưa đọc "
           f"của {user_call}{filter_note}:{star_note}",
        en=f"You have {n_shown} unread email{'s' if n_shown > 1 else ''}, "
           f"{user_call}{filter_note}:{star_note}",
        ja=f"{user_call}さん、未読メールが{n_shown}件あります{filter_note}：{star_note}",
    )

    # Nhận diện task nếu config bật
    tasks_found = []
    if cfg.get("task_detection", True):
        for e in selected:
            kws = _detect_tasks(e, lang)
            if kws:
                tasks_found.append({"subject": e["subject"], "keywords": kws})

    task_note = ""
    if tasks_found:
        task_note = "\n" + _t(lang,
            vi=f"  ⚡ {ai_prn.capitalize()} thấy {len(tasks_found)} email có vẻ cần xử lý, "
               f"{user_call} muốn {ai_prn} đọc chi tiết không?",
            en=f"  ⚡ {len(tasks_found)} email(s) may require action. "
               f"Want me to read them in detail?",
            ja=f"  ⚡ {len(tasks_found)}件のメールに対応が必要なようです。詳細を確認しますか？",
        )

    return {
        "response": f"{header}\n{items}{task_note}",
        "pipeline": "skill_gmail",
        "meta": {
            "total_unread":  len(raw),
            "shown":         n_shown,
            "filtered":      n_filter,
            "whitelisted":   n_star,
            "tasks_found":   tasks_found,
            "needs_action":  len(tasks_found) > 0,
            "email_list":    selected,
        },
    }


def _handle_count(conn, lang, ai_prn, user_call) -> Dict[str, Any]:
    """Đếm nhanh — không fetch body."""
    try:
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        count = len(data[0].split())
    except Exception:
        _imap_pool.invalidate()
        return _fetch_error(lang, ai_prn, user_call)

    return {
        "response": _t(lang,
            vi=(f"Hộp thư của {user_call} có {count} email chưa đọc {ai_prn} ạ."
                if count else
                f"Hộp thư của {user_call} sạch bóng, không có email chưa đọc nào {ai_prn} ạ. 📭"),
            en=(f"You have {count} unread email{'s' if count != 1 else ''}, {user_call}."
                if count else
                f"Inbox zero! No unread emails, {user_call}. 📭"),
            ja=(f"{user_call}さん、未読メールが{count}件あります。"
                if count else
                f"{user_call}さん、未読メールはありません。📭"),
        ),
        "pipeline": "skill_gmail_count",
        "meta": {"total_unread": count},
    }


def _handle_urgent(conn, cfg, lang, ai_prn, user_call) -> Dict[str, Any]:
    """Lọc riêng email khẩn cấp."""
    try:
        raw = _fetch_unread(conn, limit=30)
    except Exception:
        _imap_pool.invalidate()
        return _fetch_error(lang, ai_prn, user_call)

    urgent_kw = ["khẩn", "gấp", "urgent", "asap", "important", "action required"]
    urgent = [
        e for e in raw
        if any(kw in (e.get("subject", "") + " " + e.get("snippet", "")).lower()
               for kw in urgent_kw)
    ]

    if not urgent:
        return {
            "response": _t(lang,
                vi=f"Không có email khẩn cấp nào trong hộp thư của {user_call} {ai_prn} ạ. ✅",
                en=f"No urgent emails found in your inbox, {user_call}. ✅",
                ja=f"緊急メールはありません、{user_call}さん。✅",
            ),
            "pipeline": "skill_gmail_urgent",
            "meta": {"urgent_count": 0},
        }

    items  = "\n".join(f"  {i+1}. {_fmt_line(e)}" for i, e in enumerate(urgent[:5]))
    header = _t(lang,
        vi=f"{ai_prn.capitalize()} thấy {len(urgent)} email có vẻ khẩn cấp "
           f"trong hộp thư của {user_call}:",
        en=f"Found {len(urgent)} urgent email{'s' if len(urgent) > 1 else ''}, {user_call}:",
        ja=f"{user_call}さん、緊急メールが{len(urgent)}件あります：",
    )
    return {
        "response": f"{header}\n{items}",
        "pipeline": "skill_gmail_urgent",
        "meta": {"urgent_count": len(urgent), "needs_action": True, "email_list": urgent},
    }


def _handle_from(conn, cfg, lang, ai_prn, user_call, sender_query: str) -> Dict[str, Any]:
    """Lọc email từ sender cụ thể."""
    try:
        raw = _fetch_unread(conn, limit=30)
    except Exception:
        _imap_pool.invalidate()
        return _fetch_error(lang, ai_prn, user_call)

    q = sender_query.lower().strip()
    matched = [
        e for e in raw
        if q in e.get("sender_raw", "").lower() or q in e.get("sender", "").lower()
    ]

    if not matched:
        return {
            "response": _t(lang,
                vi=f"Không có email chưa đọc nào từ '{sender_query}' "
                   f"trong hộp thư của {user_call} {ai_prn} ạ.",
                en=f"No unread emails from '{sender_query}', {user_call}.",
                ja=f"'{sender_query}'からの未読メールはありません。",
            ),
            "pipeline": "skill_gmail_from",
            "meta": {"from_query": sender_query, "count": 0},
        }

    items  = "\n".join(f"  {i+1}. {_fmt_line(e)}" for i, e in enumerate(matched[:5]))
    header = _t(lang,
        vi=f"{ai_prn.capitalize()} thấy {len(matched)} email từ '{sender_query}' "
           f"chưa đọc của {user_call}:",
        en=f"Found {len(matched)} unread email{'s' if len(matched) > 1 else ''} "
           f"from '{sender_query}', {user_call}:",
        ja=f"'{sender_query}'からの未読メールが{len(matched)}件：",
    )
    return {
        "response": f"{header}\n{items}",
        "pipeline": "skill_gmail_from",
        "meta": {"from_query": sender_query, "count": len(matched), "email_list": matched},
    }


def _handle_task_emails(conn, cfg, lang, ai_prn, user_call) -> Dict[str, Any]:
    """Tìm email có công việc — trả meta.needs_action để AI router xử lý tiếp."""
    try:
        raw = _fetch_unread(conn, limit=30)
    except Exception:
        _imap_pool.invalidate()
        return _fetch_error(lang, ai_prn, user_call)

    task_emails = []
    for e in raw:
        kws = _detect_tasks(e, lang)
        if kws:
            task_emails.append({**e, "_detected_tasks": kws})

    if not task_emails:
        return {
            "response": _t(lang,
                vi=f"Không có email nào cần xử lý công việc "
                   f"trong hộp thư của {user_call} {ai_prn} ạ. ✅",
                en=f"No action-required emails found, {user_call}. ✅",
                ja=f"対応が必要なメールはありません。✅",
            ),
            "pipeline": "skill_gmail_tasks",
            "meta": {"task_count": 0, "needs_action": False},
        }

    lines = []
    for e in task_emails[:5]:
        kws_str = ", ".join(e["_detected_tasks"][:3])
        lines.append(
            f"[{_fmt_date(e['date'])}] {e['sender'][:35]}: "
            f"{e['subject'][:55]} → {kws_str}"
        )
    items  = "\n".join(f"  {i+1}. {l}" for i, l in enumerate(lines))
    header = _t(lang,
        vi=f"{ai_prn.capitalize()} tìm thấy {len(task_emails)} email "
           f"có vẻ cần xử lý công việc của {user_call}:",
        en=f"Found {len(task_emails)} email{'s' if len(task_emails) > 1 else ''} "
           f"that may require action, {user_call}:",
        ja=f"対応が必要なメールが{len(task_emails)}件あります：",
    )
    return {
        "response": f"{header}\n{items}",
        "pipeline": "skill_gmail_tasks",
        "meta": {
            "task_count":   len(task_emails),
            "needs_action": True,
            "email_list":   task_emails,
            # ai_server hoặc AI router pick up key này
            # dispatch sang skill tiếp theo (calendar, reminder, v.v.)
        },
    }


# ── IMAP fetch ────────────────────────────────────────────────────────────────

def _fetch_unread(conn: imaplib.IMAP4_SSL, limit: int = 15) -> List[Dict]:
    """Fetch N email UNSEEN mới nhất từ INBOX."""
    # Health check để tránh dùng connection zombie (timeout/ngắt ngầm).
    conn.noop()
    conn.select("INBOX")
    _, data = conn.search(None, "UNSEEN")
    ids = data[0].split()
    if not ids:
        return []

    ids = ids[-limit:]
    ids.reverse()   # mới nhất trước

    results = []
    for uid in ids:
        try:
            # Fetch header + 512 bytes body (đủ cho snippet)
            _, msg_data = conn.fetch(uid, "(RFC822.HEADER BODY.PEEK[TEXT]<0.512>)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            sender_raw = _decode_hdr(msg.get("From", ""))
            subject    = _decode_hdr(msg.get("Subject", "(Không có tiêu đề)"))
            date_str   = msg.get("Date", "")

            results.append({
                "uid":        uid,
                "sender_raw": sender_raw,
                "sender":     _clean_sender(sender_raw),
                "subject":    subject[:100],
                "date":       _parse_date(date_str),
                "snippet":    _extract_snippet(msg),
            })
        except Exception as e:
            log.warning(f"[Gmail] Bỏ qua uid {uid}: {e}")
            continue

    return results


# ── 3-tier spam filter ────────────────────────────────────────────────────────

def _apply_filters(
    emails: List[Dict], cfg: Dict
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Tầng 1 — Whitelist: sender trong danh sách ưu tiên → ⭐ whitelisted
    Tầng 2 — Blacklist domain: sender chứa domain rác → filtered
    Tầng 3 — Blacklist subject: subject chứa từ rác → filtered
    Trả về: (whitelisted, normal, filtered_out)
    """
    whitelist   = [w.lower() for w in cfg.get("whitelist", [])]
    bl_domains  = [d.lower() for d in cfg.get("blacklist_domains",
                                               _DEFAULT_CONFIG["blacklist_domains"])]
    bl_subjects = [s.lower() for s in cfg.get("blacklist_subjects",
                                               _DEFAULT_CONFIG["blacklist_subjects"])]

    whitelisted, normal, filtered = [], [], []
    for e in emails:
        sender_l  = e.get("sender_raw", "").lower()
        subject_l = e.get("subject", "").lower()

        if whitelist and any(w in sender_l for w in whitelist):
            whitelisted.append(e)
        elif any(bd in sender_l for bd in bl_domains):
            filtered.append(e)
        elif any(bs in subject_l for bs in bl_subjects):
            filtered.append(e)
        else:
            normal.append(e)

    return whitelisted, normal, filtered


# ── Task detector ─────────────────────────────────────────────────────────────

def _detect_tasks(e: Dict, lang: str) -> List[str]:
    """Tìm từ khóa công việc trong subject + snippet."""
    text = (e.get("subject", "") + " " + e.get("snippet", "")).lower()
    kws  = _TASK_KEYWORDS.get(lang, []) + _TASK_KEYWORDS.get("en", [])
    return list(dict.fromkeys(kw for kw in kws if kw in text))[:5]


# ── Text helpers ──────────────────────────────────────────────────────────────

def _decode_hdr(raw: str) -> str:
    """Decode RFC 2047 encoded header."""
    if not raw:
        return ""
    try:
        parts  = _rfc2047_decode(raw)
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return raw.strip()


def _clean_sender(raw: str) -> str:
    """Rút tên hiển thị từ 'Tên <email@...>'."""
    m = re.match(r'^"?([^"<]{2,})"?\s*<', raw)
    if m:
        return m.group(1).strip()[:50]
    m2 = re.match(r'^([^@\s<]+)', raw)
    return m2.group(1)[:50] if m2 else raw[:50]


def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str).astimezone(tz=None).replace(tzinfo=None)
    except Exception:
        return None


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    delta = (datetime.now().date() - dt.date()).days
    if delta == 0:
        return dt.strftime("%H:%M")
    if delta == 1:
        return f"Hôm qua {dt.strftime('%H:%M')}"
    if delta < 7:
        return ["T2","T3","T4","T5","T6","T7","CN"][dt.weekday()] + dt.strftime(" %H:%M")
    return dt.strftime("%d/%m")


def _extract_snippet(msg: Message) -> str:
    """Lấy text thuần từ email body, làm sạch."""
    snippet = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        snippet = payload.decode(charset, errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                snippet = payload.decode(charset, errors="replace")
    except Exception:
        pass

    snippet = re.sub(r'<[^>]+>', ' ', snippet)
    snippet = snippet.replace("&nbsp;", " ").replace("&amp;", "&")
    snippet = re.sub(r'\s+', ' ', snippet).strip()
    if len(snippet) > _SNIPPET_LEN:
        snippet = snippet[:_SNIPPET_LEN].rsplit(" ", 1)[0] + "…"
    return snippet


def _fmt_line(e: Dict) -> str:
    """Format một email thành dòng TTS-ready."""
    line = f"[{_fmt_date(e.get('date'))}] {e.get('sender','?')[:40]}: {e.get('subject','?')[:65]}"
    if e.get("snippet"):
        line += f" — {e['snippet']}"
    return line


def _t(lang: str, vi: str = "", en: str = "", ja: str = "") -> str:
    return {"vi": vi, "en": en, "ja": ja}.get(lang, vi)


def _fetch_error(lang: str, ai_prn: str, user_call: str) -> Dict[str, Any]:
    return {
        "response": _t(lang,
            vi=f"Ôi {user_call} ơi, {ai_prn} đọc email bị lỗi rồi, thử lại sau nhé.",
            en=f"Sorry {user_call}, couldn't fetch emails right now. Please try again.",
            ja=f"メールの取得に失敗しました。後でもう一度お試しください。",
        ),
        "pipeline": "skill_gmail_error",
        "meta": {"error": "fetch_error"},
    }


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _setup_config() -> None:
    """Tạo file gmail_config.json mẫu (legacy compatibility)."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    if os.path.exists(_CONFIG_FILE):
        print(f"Config đã tồn tại: {_CONFIG_FILE}")
        return
    sample = {
        "email":    "yourname@gmail.com",
        "password": "xxxx xxxx xxxx xxxx",
        "max_emails": 5,
        "whitelist": ["boss@company.com"],
        "blacklist_domains": _DEFAULT_CONFIG["blacklist_domains"][:8],
        "blacklist_subjects": _DEFAULT_CONFIG["blacklist_subjects"][:6],
        "task_detection": True,
    }
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
    print(f"✅ Tạo config mẫu: {_CONFIG_FILE}")
    print("👉 Khuyến nghị mới: điền email/password trực tiếp trong config.json để dùng chung toàn hệ thống.")


def _test_connection() -> None:
    """Test kết nối IMAP từ CLI."""
    cfg = _load_config()
    if not cfg["email"] or not cfg["password"]:
        print("❌ Chưa điền email/password trong config.json (hoặc legacy gmail_config.json)")
        return
    print(f"Kết nối tới {_IMAP_HOST} với {cfg['email']}...")
    ok = _imap_pool.connect(cfg)
    if ok:
        conn = _imap_pool.get()
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        count = len(data[0].split())
        print(f"✅ Thành công! Có {count} email chưa đọc.")
        # Test filter
        if count > 0:
            raw = _fetch_unread(conn, limit=count * 2)
            wl, nm, fl = _apply_filters(raw, cfg)
            print(f"   ⭐ Whitelist: {len(wl)} | 📧 Bình thường: {len(nm)} | 🗑️ Lọc bỏ: {len(fl)}")
    else:
        print("❌ Kết nối thất bại.")
        print("Kiểm tra:")
        print("  1. IMAP đã bật chưa: Gmail → Settings → See all settings → Forwarding/POP/IMAP")
        print("  2. App Password đúng chưa: myaccount.google.com → Security → App Passwords")
        print("  3. 2-Step Verification đã bật chưa (bắt buộc để dùng App Password)")


if __name__ == "__main__":
    import sys
    if "--setup" in sys.argv:
        _setup_config()
    elif "--test" in sys.argv:
        _test_connection()
    else:
        print(
            "Dùng:\n"
            "  python3 gmail.py --setup   Tạo file config mẫu (legacy)\n"
            "  python3 gmail.py --test    Test kết nối + filter\n"
        )