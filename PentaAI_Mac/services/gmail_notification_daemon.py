#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Gmail Notification Daemon v1.0
======================================
Chạy background, monitor email từ danh sách whitelist, phát thông báo qua TTS.

Kiến trúc:
  - IMAP monitor: Lắng nghe email từ danh sách user config
  - Queue system: Xếp hàng thông báo, retry 15 phút nếu user không trả lời
  - TTS broadcast: Phát "Bạn có tin nhắn từ [nickname]" qua WebSocket
  - Interactive: Hỏi "Bạn có muốn đọc nội dung không?", wait for voice response
  - Đánh dấu: Mark as read khi user đọc xong

Queue state diagram:
  PENDING → ASK_USER → REPLIED (yes/no) → DONE
                    ↓ timeout (15 min)
                   REQUEUE
"""

import os
import json
import time
import logging
import threading
import imaplib
import email
import html as html_lib
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

log = logging.getLogger("GmailNotifDaemon")

# ── Status States ──────────────────────────────────────────────────────────────
class NotifState(str, Enum):
    PENDING = "pending"         # Mới nhận, chưa phát thông báo
    ASK_USER = "ask_user"       # Đã phát thông báo, chờ trả lời
    REPLIED_YES = "replied_yes" # User nói "có", đang đọc nội dung
    REPLIED_NO = "replied_no"   # User nói "không"
    READ = "read"               # Đọc xong, đánh dấu mail
    REQUEUE = "requeue"         # Timeout 15 phút, sắp phát lại

# ── Data Models ────────────────────────────────────────────────────────────────
@dataclass
class GmailWhitelist:
    """Một entry trong gmail_notification_whitelist."""
    email: str           # "test.gmail"
    nickname: str        # "test"
    
    def key(self) -> str:
        return self.email.lower()

@dataclass
class PendingNotif:
    """Một email đang chờ xử lý."""
    uid: str
    email_from: str           # "test.gmail"
    nickname: str             # "test"
    subject: str
    sender_display: str       # "Tên người gửi"
    received_at: datetime     # Thời điểm nhận
    state: NotifState = field(default=NotifState.PENDING)
    asked_at: Optional[datetime] = field(default=None)
    user_response: Optional[str] = None  # "yes", "no", None
    read_at_imap: bool = field(default=False)
    snippet: str = field(default="")
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = d["state"].value
        d["received_at"] = d["received_at"].isoformat() if d["received_at"] else None
        d["asked_at"] = d["asked_at"].isoformat() if d["asked_at"] else None
        return d

# ── Main Daemon ────────────────────────────────────────────────────────────────
class GmailNotificationDaemon:
    """
    Monitor email và phát thông báo.
    Chạy background thread, async safe.
    """
    def __init__(self, config_fn: Callable[[], dict], broadcast_fn: Callable[[str], None]):
        """
        Args:
            config_fn: callable() → dict config (gọi mỗi loop để refresh)
            broadcast_fn: callable(text: str) → None (broadcast via WebSocket)
        """
        self._config_fn = config_fn
        self._broadcast_fn = broadcast_fn
        
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.RLock()
        
        # Queue state
        self._queue: List[PendingNotif] = []     # Email chờ xử lý
        self._notified: Dict[str, datetime] = {} # {uid: thời điểm phát thông báo lần cuối}
        
        # IMAP
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._last_uids: List[bytes] = []
        self._bootstrapped_unseen = False
        
        log.info("[GmailNotifDaemon] Khởi tạo thành công")
    
    # ── Lifecycle ──────────────────────────────────────────────────────────────
    
    def start(self) -> None:
        """Khởi động background thread."""
        with self._lock:
            if self._running:
                log.warning("[GmailNotifDaemon] Đã chạy rồi")
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="GmailNotifDaemon")
            self._thread.start()
            log.info("[GmailNotifDaemon] ✅ Daemon đã khởi động")
    
    def stop(self) -> None:
        """Dừng daemon."""
        with self._lock:
            self._running = False
            self._disconnect_imap()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("[GmailNotifDaemon] ✅ Daemon đã dừng")
    
    # ── Main Loop ──────────────────────────────────────────────────────────────
    
    def _loop(self) -> None:
        """Background loop - 15 giây/lần check."""
        while self._running:
            try:
                cfg = self._config_fn()
                enabled = cfg.get("gmail_notification_enabled", False)
                
                if not enabled:
                    time.sleep(30)
                    continue
                
                # Kết nối / kiểm tra sống IMAP trước khi fetch để tránh zombie connection.
                if not self._ensure_imap_alive(cfg):
                    time.sleep(5)
                    continue
                
                # (1) Fetch email mới từ INBOX
                self._fetch_new_emails(cfg)
                
                # (2) Xử lý queue: phát thông báo, requeue timeout
                self._process_queue(cfg)
                
                time.sleep(15)  # Check lại mỗi 15 giây
            except Exception as e:
                log.error(f"[GmailNotifDaemon] Loop error: {e}", exc_info=True)
                self._disconnect_imap()
                time.sleep(30)

    def _ensure_imap_alive(self, cfg: dict) -> bool:
        """Đảm bảo kết nối IMAP còn sống; nếu chết thì reconnect."""
        if not self._imap:
            return self._connect_imap(cfg)
        try:
            self._imap.noop()
            return True
        except Exception as e:
            log.warning(f"[GmailNotifDaemon] IMAP NOOP fail, reconnecting: {e}")
            self._disconnect_imap()
            return self._connect_imap(cfg)
    
    # ── IMAP Connection ────────────────────────────────────────────────────────
    
    def _connect_imap(self, cfg: dict) -> bool:
        """Kết nối IMAP."""
        try:
            email_addr = cfg.get("email")
            password = cfg.get("password")
            
            if not email_addr or not password:
                log.warning("[GmailNotifDaemon] Email/password chưa cấu hình")
                return False
            
            self._imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            self._imap.login(email_addr, password)
            log.info("[GmailNotifDaemon] ✅ IMAP connected")
            return True
        except Exception as e:
            log.error(f"[GmailNotifDaemon] IMAP connect error: {e}")
            self._imap = None
            return False
    
    def _disconnect_imap(self) -> None:
        """Ngắt kết nối IMAP."""
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
        self._last_uids = []
    
    # ── Fetch New Emails ──────────────────────────────────────────────────────
    
    def _fetch_new_emails(self, cfg: dict) -> None:
        """Fetch email mới từ INBOX, so sánh với last_uids."""
        if not self._imap:
            return
        
        try:
            self._imap.select("INBOX")
            
            # Tìm UID mới (chỉ nhận email UNSEEN)
            _, unseen_data = self._imap.search(None, "UNSEEN")
            unseen_uids = unseen_data[0].split()

            # Lần đầu chạy: snapshot unseen hiện tại để tránh đẩy backlog cũ.
            ignore_existing = bool(cfg.get("gmail_notification_ignore_existing_unseen_on_start", True))
            if not self._bootstrapped_unseen:
                self._bootstrapped_unseen = True
                if ignore_existing:
                    self._last_uids = list(unseen_uids)
                    log.info(
                        f"[GmailNotifDaemon] Bootstrap unseen snapshot ({len(unseen_uids)} mail), "
                        "chỉ thông báo mail mới phát sinh sau thời điểm này"
                    )
                    return

            # Chỉ quét nhóm unseen mới nhất để giảm nhiễu/độ trễ.
            scan_limit = int(cfg.get("gmail_notification_unseen_scan_limit", 30) or 30)
            candidate_uids = unseen_uids[-scan_limit:]
            max_age_hours = float(cfg.get("gmail_notification_max_age_hours", 24) or 24)
            cutoff = datetime.now() - timedelta(hours=max_age_hours) if max_age_hours > 0 else None
            
            # Filter theo whitelist
            whitelist = self._parse_whitelist(cfg)
            wl_emails = {e.email.lower() for e in whitelist}
            if not wl_emails:
                log.warning("[GmailNotifDaemon] Whitelist đang rỗng, bỏ qua thông báo email mới")
            
            # Duyệt mới nhất trước.
            for uid in reversed(candidate_uids):
                if uid in [u for u in self._last_uids]:
                    continue  # Đã xử lý rồi
                
                # Fetch header
                _, msg_data = self._imap.fetch(uid, "(RFC822.HEADER BODY.PEEK[TEXT]<0.256>)")
                if not msg_data:
                    continue
                
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                # Lọc mail quá cũ (ví dụ backlog UNSEEN lâu ngày).
                if cutoff is not None:
                    msg_date = self._parse_msg_date(msg.get("Date", ""))
                    if msg_date and msg_date < cutoff:
                        continue
                
                from_raw = msg.get("From", "")
                sender = self._extract_email(from_raw)
                
                # Kiểm tra trong whitelist
                if sender.lower() not in wl_emails:
                    log.debug(f"[GmailNotifDaemon] Skip sender not in whitelist: {sender}")
                    continue
                
                subject = self._decode_hdr(msg.get("Subject", ""))
                if not subject.strip():
                    subject = "(Không có tiêu đề)"
                nickname = next((e.nickname for e in whitelist if e.email.lower() == sender.lower()), sender)
                sender_display = self._clean_sender(self._decode_hdr(from_raw))
                
                notif = PendingNotif(
                    uid=uid.decode() if isinstance(uid, bytes) else uid,
                    email_from=sender,
                    nickname=nickname,
                    subject=subject,
                    sender_display=sender_display,
                    received_at=datetime.now(),
                    snippet=self._extract_snippet(msg),
                )

                self._enqueue_with_limit(notif, cfg)
            
            self._last_uids = unseen_uids
        
        except Exception as e:
            log.error(f"[GmailNotifDaemon] Fetch error: {e}")
            self._imap = None
    
    # ── Process Queue ──────────────────────────────────────────────────────────
    
    def _process_queue(self, cfg: dict) -> None:
        """Xử lý queue: phát thông báo, check timeout."""
        if not self._queue:
            return
        
        retry_interval_sec = cfg.get("gmail_notification_retry_interval_sec", 900)  # 15 min default
        max_announcements = int(cfg.get("gmail_notification_max_announcements_per_cycle", 1) or 1)
        announcements = 0
        
        with self._lock:
            for notif in self._queue[:]:
                # Dọn item đã hoàn tất
                if notif.state in {NotifState.REPLIED_YES, NotifState.READ}:
                    self._queue.remove(notif)
                    continue

                # Trạng thái: PENDING → phát thông báo
                if notif.state == NotifState.PENDING and announcements < max_announcements:
                    self._queue.remove(notif)
                    notif.state = NotifState.ASK_USER
                    notif.asked_at = datetime.now()
                    
                    msg = f"Bạn có tin nhắn từ {notif.nickname} - {notif.subject}. Bạn có muốn đọc nội dung không?"
                    try:
                        self._broadcast_fn(msg)
                        self._notified[notif.uid] = datetime.now()
                    except Exception as e:
                        log.error(f"[GmailNotifDaemon] Broadcast error: {e}")
                    
                    self._queue.append(notif)
                    announcements += 1
                
                # Trạng thái: ASK_USER + timeout → REQUEUE
                elif notif.state == NotifState.ASK_USER:
                    if notif.asked_at and (datetime.now() - notif.asked_at).total_seconds() > retry_interval_sec:
                        if notif.user_response is None:
                            log.info(f"[GmailNotifDaemon] Timeout, requeue: {notif.nickname}")
                            notif.state = NotifState.REQUEUE
                            notif.asked_at = datetime.now()
                
                # Trạng thái: REQUEUE → chờ interval rồi phát lại
                elif notif.state == NotifState.REQUEUE and announcements < max_announcements:
                    if not notif.asked_at:
                        notif.asked_at = datetime.now()
                        continue
                    if (datetime.now() - notif.asked_at).total_seconds() <= retry_interval_sec:
                        continue

                    self._queue.remove(notif)
                    notif.state = NotifState.ASK_USER
                    notif.asked_at = datetime.now()
                    notif.user_response = None
                    
                    msg = f"Nhắc nhở: Bạn có tin nhắn từ {notif.nickname} - {notif.subject}. Bạn có muốn đọc không?"
                    try:
                        self._broadcast_fn(msg)
                    except Exception as e:
                        log.error(f"[GmailNotifDaemon] Requeue broadcast error: {e}")
                    
                    self._queue.append(notif)
                    announcements += 1

                # REPLIED_NO: người dùng đã từ chối, chuyển về REQUEUE có delay
                elif notif.state == NotifState.REPLIED_NO:
                    notif.state = NotifState.REQUEUE
                    notif.asked_at = datetime.now()

    def _enqueue_with_limit(self, notif: PendingNotif, cfg: dict) -> None:
        """Thêm email mới vào queue, chống jam bằng queue limit + dedupe UID."""
        queue_limit = int(cfg.get("gmail_notification_queue_limit", 5) or 5)
        with self._lock:
            if any(n.uid == notif.uid for n in self._queue):
                return
            self._queue.append(notif)
            # Giữ queue không vượt ngưỡng để tránh dồn thông báo khi vắng lâu.
            if len(self._queue) > queue_limit:
                self._queue.sort(key=lambda n: n.received_at)
                removed = self._queue[:-queue_limit]
                self._queue = self._queue[-queue_limit:]
                if removed:
                    log.warning(f"[GmailNotifDaemon] Queue cap reached, dropped {len(removed)} old items")
                    try:
                        self._broadcast_fn(
                            f"Hàng đợi Gmail đang nhiều, em chỉ giữ {queue_limit} email mới nhất để tránh dồn thông báo."
                        )
                    except Exception:
                        pass
            log.info(f"[GmailNotifDaemon] Thêm vào queue: {notif.nickname} - {notif.subject[:50]}")
    
    # ── Helpers ────────────────────────────────────────────────────────────────
    
    def _parse_whitelist(self, cfg: dict) -> List[GmailWhitelist]:
        """Parse whitelist từ file data ưu tiên, fallback config key."""
        wl_raw: Any = None

        wl_path = str(cfg.get("gmail_notification_whitelist_file", "data/gmail_notify_whitelist.json") or "").strip()
        if not wl_path:
            wl_path = "data/gmail_notify_whitelist.json"
        if not os.path.isabs(wl_path):
            base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            wl_path = os.path.join(base, wl_path)

        if os.path.exists(wl_path):
            try:
                with open(wl_path, "r", encoding="utf-8") as f:
                    wl_raw = json.load(f)
            except Exception as e:
                log.warning(f"[GmailNotifDaemon] Không đọc được whitelist file {wl_path}: {e}")

        if wl_raw is None:
            wl_raw = cfg.get("gmail_notification_whitelist", [])

        if not isinstance(wl_raw, list):
            return []

        out: List[GmailWhitelist] = []
        for e in wl_raw:
            if isinstance(e, dict):
                em = str(e.get("email", "")).strip().lower()
                nick = str(e.get("nickname", "")).strip()
            elif isinstance(e, str):
                em = e.strip().lower()
                nick = ""
            else:
                continue
            if not em:
                continue
            out.append(GmailWhitelist(email=em, nickname=nick or em.split("@")[0]))

        # Deduplicate
        uniq: Dict[str, GmailWhitelist] = {}
        for item in out:
            if item.email not in uniq:
                uniq[item.email] = item
        return list(uniq.values())
    
    def _extract_email(self, raw: str) -> str:
        """Extract email từ 'Name <email@...>'."""
        import re
        m = re.search(r'<([^>]+)>', raw)
        return m.group(1).lower() if m else raw.lower()
    
    def _clean_sender(self, raw: str) -> str:
        """Rút tên từ header."""
        import re
        m = re.match(r'^"?([^"<]{2,})"?\s*<', raw)
        return m.group(1).strip()[:50] if m else self._extract_email(raw)[:50]
    
    def _decode_hdr(self, raw: str) -> str:
        """Decode RFC 2047 header."""
        if not raw:
            return ""
        try:
            from email.header import decode_header
            parts = decode_header(raw)
            result = []
            for part, charset in parts:
                if isinstance(part, bytes):
                    result.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    result.append(str(part))
            return "".join(result).strip()
        except Exception:
            return raw.strip()

    def _extract_snippet(self, msg_obj: Any, max_len: int = 220) -> str:
        """Lấy preview nội dung text từ email message (plain ưu tiên, fallback HTML)."""
        snippet = ""
        html_body = ""
        try:
            if msg_obj.is_multipart():
                for part in msg_obj.walk():
                    ctype = (part.get_content_type() or "").lower()
                    if ctype == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            snippet = payload.decode(charset, errors="replace")
                            break
                    elif ctype == "text/html" and not html_body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            html_body = payload.decode(charset, errors="replace")
            else:
                payload = msg_obj.get_payload(decode=True)
                if payload:
                    charset = msg_obj.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    ctype = (msg_obj.get_content_type() or "").lower()
                    if ctype == "text/html":
                        html_body = decoded
                    else:
                        snippet = decoded
        except Exception:
            snippet = ""

        # HTML fallback khi không có text/plain rõ ràng.
        if not snippet.strip() and html_body:
            # Bỏ script/style và chuyển block tags thành xuống dòng trước khi strip.
            cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_body)
            cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
            cleaned = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", cleaned)
            cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
            cleaned = html_lib.unescape(cleaned)
            snippet = cleaned

        snippet = (snippet or "").replace("\r", " ").replace("\n", " ")
        snippet = " ".join(snippet.split()).strip()
        if len(snippet) > max_len:
            snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
        return snippet

    def _fetch_preview_by_uid(self, uid: str) -> Dict[str, str]:
        """Fetch subject/sender/snippet theo UID để đọc nội dung khi user nói YES."""
        out = {"subject": "", "sender_display": "", "snippet": ""}
        if not self._imap:
            return out
        try:
            self._imap.select("INBOX")
            # Ưu tiên lấy full message để parse body ổn định (text/plain + html fallback).
            _, msg_data = self._imap.fetch(uid, "(RFC822)")
            if not msg_data:
                return out

            raw_chunks: List[bytes] = []
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                    raw_chunks.append(bytes(item[1]))
            raw = b"".join(raw_chunks)

            # Một số server có thể trả về format khác, fallback lấy TEXT range lớn hơn.
            if not raw:
                _, msg_data = self._imap.fetch(uid, "(RFC822.HEADER BODY.PEEK[TEXT]<0.8192>)")
                raw_chunks = []
                for item in (msg_data or []):
                    if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                        raw_chunks.append(bytes(item[1]))
                raw = b"".join(raw_chunks)

            if not raw:
                return out

            msg_obj = email.message_from_bytes(raw)
            out["subject"] = self._decode_hdr(msg_obj.get("Subject", "")).strip()
            out["sender_display"] = self._clean_sender(self._decode_hdr(msg_obj.get("From", "")).strip())
            out["snippet"] = self._extract_snippet(msg_obj)
        except Exception as e:
            log.warning(f"[GmailNotifDaemon] Fetch preview fail uid={uid}: {e}")
        return out

    def _parse_msg_date(self, raw: str) -> Optional[datetime]:
        if not raw:
            return None
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            return None
    
    # ── Public Interface ──────────────────────────────────────────────────────
    
    def get_queue(self) -> List[dict]:
        """Lấy queue hiện tại."""
        with self._lock:
            return [notif.to_dict() for notif in self._queue]

    def get_oldest_waiting_uid(self) -> Optional[str]:
        """Lấy UID mail đang chờ xác nhận lâu nhất (ASK_USER/REQUEUE/PENDING)."""
        with self._lock:
            waiting = [n for n in self._queue if n.state in {NotifState.ASK_USER, NotifState.REQUEUE, NotifState.PENDING}]
            if not waiting:
                return None
            waiting.sort(key=lambda n: n.received_at)
            return waiting[0].uid
    
    def set_user_response(self, uid: str, response: str) -> bool:
        """
        User trả lời: "yes" hoặc "no".
        """
        normalized = (response or "").strip().lower()
        if not uid:
            uid = self.get_oldest_waiting_uid() or ""
        if not uid:
            return False

        with self._lock:
            for notif in self._queue:
                if notif.uid == uid:
                    if normalized in ("yes", "có", "1", "true"):
                        notif.state = NotifState.REPLIED_YES
                        notif.user_response = "yes"
                        log.info(f"[GmailNotifDaemon] User said YES: {notif.nickname}")

                        # Lấy preview nội dung theo UID để đọc sát nội dung thật.
                        preview = self._fetch_preview_by_uid(notif.uid)
                        _subject = (preview.get("subject") or notif.subject or "").strip()
                        if not _subject:
                            _subject = "(Không có tiêu đề)"

                        _sender = (preview.get("sender_display") or notif.sender_display or "").strip()
                        if not _sender:
                            _sender = notif.nickname or "người gửi"

                        _snippet = (preview.get("snippet") or notif.snippet or "").strip()
                        if _snippet:
                            summary = f"Email từ {_sender}. Tiêu đề: {_subject}. Nội dung tóm tắt: {_snippet}"
                        else:
                            summary = f"Email từ {_sender}. Tiêu đề: {_subject}. Hiện chưa lấy được nội dung chi tiết."
                        self._broadcast_fn(f"Nội dung: {summary}")
                        
                        # Mark as read sau 2 giây
                        def mark_read():
                            time.sleep(2)
                            try:
                                if self._imap:
                                    self._imap.store(notif.uid, "+FLAGS", "\\Seen")
                                notif.read_at_imap = True
                                notif.state = NotifState.READ
                            except Exception as e:
                                log.error(f"Mark read error: {e}")
                        threading.Thread(target=mark_read, daemon=True).start()
                        
                        return True
                    else:
                        notif.state = NotifState.REPLIED_NO
                        notif.user_response = "no"
                        log.info(f"[GmailNotifDaemon] User said NO: {notif.nickname}")
                        return True
        return False

    def clear_queue(self) -> int:
        """Xóa toàn bộ queue chờ thông báo."""
        with self._lock:
            n = len(self._queue)
            self._queue.clear()
            self._notified.clear()
            return n

# ── Module-level singleton ────────────────────────────────────────────────────

_daemon: Optional[GmailNotificationDaemon] = None

def init_daemon(config_fn: Callable[[], dict], broadcast_fn: Callable[[str], None]) -> GmailNotificationDaemon:
    """Tạo singleton daemon."""
    global _daemon
    if _daemon is None:
        _daemon = GmailNotificationDaemon(config_fn, broadcast_fn)
    return _daemon

def get_daemon() -> Optional[GmailNotificationDaemon]:
    """Lấy daemon hiện tại."""
    return _daemon
