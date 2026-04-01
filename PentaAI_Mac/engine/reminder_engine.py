# engine/reminder_engine.py
"""
ReminderEngine — Nhắc nhở chủ động (proactive messaging).

Hệ thống gốc hoàn toàn reactive: chỉ trả lời khi user gửi tin.
Module này thêm khả năng AI gửi tin trước theo lịch.

─────────────────────────────────────────────────────────
Cách dùng:

  # Trong main loop:
  engine = ReminderEngine(store=knowledge_store)
  engine.start()  # chạy background thread

  # Dạy AI nhắc:
  engine.add("nhắc em học bài lúc 8 giờ tối")
  engine.add("remind me to call mom tomorrow at 9am")

  # Lấy tin nhắn cần gửi ngay bây giờ:
  due = engine.get_due()
  for msg in due:
      print(f"[NHẮC] {msg}")

  engine.stop()

─────────────────────────────────────────────────────────
Lưu ý quan trọng:
  - Reminder được persist vào KnowledgeStore (key "reminders")
  - Sau khi gửi, reminder được đánh dấu sent=True
  - Repeat reminder (daily/weekly) được tái tạo sau khi gửi
  - Thread-safe: dùng threading.Lock
─────────────────────────────────────────────────────────
"""

import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Callable
from dataclasses import dataclass, field, asdict


# ── Từ khóa phát hiện lệnh nhắc nhở ─────────────────────────────
_REMIND_TRIGGERS = {
    "vi": [
        r"nhắc\s+(?:mình|tôi|em|anh|chị|tớ)?",
        r"báo\s+(?:mình|tôi|em)?",
        r"remind\s+me",
        r"đặt\s+nhắc",
        r"hẹn\s+giờ",
    ],
    "en": [
        r"remind\s+me",
        r"set\s+(?:a\s+)?reminder",
        r"remind\s+(?:me\s+)?(?:to|about)",
        r"alert\s+me",
    ],
}

# ── Regex nhận diện thời gian ─────────────────────────────────────
_TIME_PATTERNS = [
    # "lúc 8 giờ tối" / "lúc 20:30"
    (r"lúc\s+(\d{1,2})(?::(\d{2}))?\s*(giờ\s*)?(sáng|trưa|chiều|tối)?",   "vi_time"),
    # "at 8pm" / "at 20:30"
    (r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",                             "en_time"),
    # "sau X phút/giờ"
    (r"sau\s+(\d+)\s*(phút|giờ|tiếng)",                                      "vi_relative"),
    # "in X minutes/hours"
    (r"in\s+(\d+)\s*(minute|minutes|hour|hours|min|mins)",                   "en_relative"),
    # "ngày mai" / "tomorrow"
    (r"(?:ngày mai|hôm sau)",                                                 "vi_tomorrow"),
    (r"tomorrow",                                                              "en_tomorrow"),
    # Thứ trong tuần
    (r"(?:thứ\s*(?:hai|ba|tư|năm|sáu|bảy)|chủ\s*nhật)",                     "vi_weekday"),
    (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)",         "en_weekday"),
]

# ── Repeat patterns ───────────────────────────────────────────────
_REPEAT_PATTERNS = [
    (r"mỗi\s*ngày|hằng\s*ngày|daily",  "daily"),
    (r"mỗi\s*tuần|weekly",              "weekly"),
    (r"mỗi\s*giờ|hourly",              "hourly"),
]


@dataclass
class Reminder:
    id:          str
    message:     str          # Nội dung nhắc
    trigger_dt:  str          # ISO datetime khi nhắc
    repeat:      str = ""     # "" | "daily" | "weekly" | "hourly"
    lang:        str = "vi"
    sent:        bool = False
    created:     str = field(default_factory=lambda: datetime.now().isoformat())

    def trigger_datetime(self) -> datetime:
        return datetime.fromisoformat(self.trigger_dt)


class ReminderEngine:

    def __init__(self, store=None, on_reminder: Optional[Callable] = None):
        """
        store:       KnowledgeStore (để persist reminders)
        on_reminder: callback(message: str) — gọi khi đến giờ nhắc
                     Nếu None, dùng print()
        """
        self._store       = store
        self._callback    = on_reminder or (lambda msg: print(f"\n⏰ [NHẮC] {msg}\n"))
        self._reminders:  List[Reminder] = []
        self._lock        = threading.Lock()
        self._thread:     Optional[threading.Thread] = None
        self._running     = False
        self._poll_sec    = 30   # kiểm tra mỗi 30 giây

        self._load_from_store()

    # ── PUBLIC ────────────────────────────────────────────────────

    def start(self):
        """Bắt đầu background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Dừng polling thread."""
        self._running = False

    def parse_and_add(self, text: str, lang: str = "vi") -> Optional[str]:
        """
        Phân tích câu user → tạo reminder nếu phát hiện lệnh nhắc.
        Trả về xác nhận (string) hoặc None nếu không phải lệnh nhắc.

        Ví dụ:
          "nhắc mình học bài lúc 8 giờ tối" → Reminder + "OK, mình sẽ nhắc..."
          "remind me to call mom in 30 minutes" → Reminder + "Got it, I'll remind..."
        """
        if not self._is_remind_command(text, lang):
            return None

        trigger_dt, repeat = self._parse_time(text, lang)
        if trigger_dt is None:
            # Không parse được thời gian → nhắc sau 1 tiếng
            trigger_dt = datetime.now() + timedelta(hours=1)

        message = self._extract_message(text, lang)
        reminder = self._create_reminder(message, trigger_dt, repeat, lang)

        self.add(reminder)

        return self._build_confirm(reminder, lang)

    def add(self, reminder: Reminder):
        """Thêm reminder trực tiếp (dùng nội bộ hoặc khi tạo từ ngoài)."""
        with self._lock:
            self._reminders.append(reminder)
        self._save_to_store()

    def get_due(self) -> List[str]:
        """
        Trả về danh sách tin nhắn nhắc đã đến giờ.
        Gọi từ main loop nếu không dùng background thread.
        """
        due_messages = []
        now = datetime.now()
        with self._lock:
            for r in self._reminders:
                if not r.sent and r.trigger_datetime() <= now:
                    due_messages.append(r.message)
                    r.sent = True
                    self._reschedule_if_repeat(r, now)
        if due_messages:
            self._save_to_store()
        return due_messages

    def list_reminders(self, lang: str = "vi") -> str:
        """Liệt kê các reminder đang chờ."""
        with self._lock:
            pending = [r for r in self._reminders if not r.sent]

        if not pending:
            return {
                "vi": "Không có lịch nhắc nào đang chờ.",
                "en": "No pending reminders.",
            }.get(lang, "Không có lịch nhắc nào.")

        lines = []
        for r in sorted(pending, key=lambda x: x.trigger_dt):
            dt = r.trigger_datetime()
            time_str = dt.strftime("%H:%M %d/%m/%Y")
            repeat_str = f" (lặp: {r.repeat})" if r.repeat else ""
            lines.append(f"• {time_str}{repeat_str} — {r.message}")

        return "\n".join(lines)

    def cancel(self, keyword: str) -> bool:
        """Hủy reminder chứa từ khóa. Trả về True nếu đã hủy được."""
        with self._lock:
            before = len([r for r in self._reminders if not r.sent])
            self._reminders = [
                r for r in self._reminders
                if r.sent or keyword.lower() not in r.message.lower()
            ]
            after = len([r for r in self._reminders if not r.sent])
        if before != after:
            self._save_to_store()
            return True
        return False

    # ── PRIVATE: PARSING ──────────────────────────────────────────

    def _is_remind_command(self, text: str, lang: str) -> bool:
        text_lower = text.lower()
        patterns = _REMIND_TRIGGERS.get(lang, []) + _REMIND_TRIGGERS.get("en", [])
        return any(re.search(p, text_lower) for p in patterns)

    def _parse_time(self, text: str, lang: str):
        """
        Trả về (datetime, repeat_str) từ text.
        Nếu không tìm thấy → (None, "")
        """
        text_lower = text.lower()
        now = datetime.now()

        # Repeat
        repeat = ""
        for pattern, rtype in _REPEAT_PATTERNS:
            if re.search(pattern, text_lower):
                repeat = rtype
                break

        # Relative time: "sau X phút/giờ" / "in X minutes/hours"
        m = re.search(r"sau\s+(\d+)\s*(phút|giờ|tiếng)", text_lower)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = timedelta(minutes=n) if "phút" in unit else timedelta(hours=n)
            return now + delta, repeat

        m = re.search(r"in\s+(\d+)\s*(minute|minutes|hour|hours|min|mins)", text_lower)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = timedelta(minutes=n) if "min" in unit else timedelta(hours=n)
            return now + delta, repeat

        # Absolute time: "lúc 8 giờ tối" / "at 8pm"
        m = re.search(r"lúc\s+(\d{1,2})(?::(\d{2}))?\s*(?:giờ\s*)?(sáng|trưa|chiều|tối)?", text_lower)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            period = m.group(3) or ""
            if period in ("chiều", "tối") and h < 12:
                h += 12
            elif period == "trưa":
                h = 12
            target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            # "ngày mai" → +1 day
            if re.search(r"ngày mai|hôm sau", text_lower):
                target += timedelta(days=1)
            return target, repeat

        m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            period = m.group(3) or ""
            if period == "pm" and h < 12:
                h += 12
            elif period == "am" and h == 12:
                h = 0
            target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            if re.search(r"tomorrow", text_lower):
                target += timedelta(days=1)
            return target, repeat

        # "ngày mai" không có giờ → 9h sáng ngày mai
        if re.search(r"ngày mai|tomorrow", text_lower):
            return now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1), repeat

        return None, repeat

    def _extract_message(self, text: str, lang: str) -> str:
        """Trích xuất nội dung cần nhắc từ câu lệnh."""
        # Bỏ phần trigger
        result = text
        for triggers in _REMIND_TRIGGERS.values():
            for pat in triggers:
                result = re.sub(pat, "", result, flags=re.IGNORECASE)

        # Bỏ phần thời gian
        time_removals = [
            r"lúc\s+\d{1,2}(?::\d{2})?\s*(?:giờ\s*)?(?:sáng|trưa|chiều|tối)?",
            r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?",
            r"sau\s+\d+\s*(?:phút|giờ|tiếng)",
            r"in\s+\d+\s*(?:minute|minutes|hour|hours|min|mins)",
            r"ngày mai|hôm sau|tomorrow",
            r"mỗi\s*ngày|hằng\s*ngày|daily|mỗi\s*tuần|weekly|mỗi\s*giờ|hourly",
        ]
        for pat in time_removals:
            result = re.sub(pat, "", result, flags=re.IGNORECASE)

        # Dọn dẹp
        result = re.sub(r"\s+", " ", result).strip().strip(".,!? ")
        return result if result else text.strip()

    def _create_reminder(self, message: str, trigger_dt: datetime,
                         repeat: str, lang: str) -> Reminder:
        rid = f"r_{int(trigger_dt.timestamp())}_{hash(message) & 0xFFFF:04x}"
        return Reminder(
            id=rid,
            message=message,
            trigger_dt=trigger_dt.isoformat(),
            repeat=repeat,
            lang=lang,
        )

    def _reschedule_if_repeat(self, r: Reminder, now: datetime):
        """Tạo reminder mới cho lần lặp tiếp theo."""
        if not r.repeat:
            return
        deltas = {"hourly": timedelta(hours=1), "daily": timedelta(days=1),
                  "weekly": timedelta(weeks=1)}
        delta = deltas.get(r.repeat)
        if not delta:
            return
        next_dt = r.trigger_datetime() + delta
        new_r = Reminder(
            id=f"r_{int(next_dt.timestamp())}_{hash(r.message) & 0xFFFF:04x}",
            message=r.message,
            trigger_dt=next_dt.isoformat(),
            repeat=r.repeat,
            lang=r.lang,
        )
        self._reminders.append(new_r)

    def _build_confirm(self, r: Reminder, lang: str) -> str:
        dt = r.trigger_datetime()
        time_str = dt.strftime("%H:%M ngày %d/%m/%Y") if lang == "vi" else dt.strftime("%H:%M on %d/%m/%Y")
        repeat_info = ""
        if r.repeat:
            repeat_map = {
                "vi": {"daily": " (mỗi ngày)", "weekly": " (mỗi tuần)", "hourly": " (mỗi giờ)"},
                "en": {"daily": " (daily)", "weekly": " (weekly)", "hourly": " (every hour)"},
            }
            repeat_info = repeat_map.get(lang, repeat_map["vi"]).get(r.repeat, "")

        templates = {
            "vi": f"OK! Mình sẽ nhắc bạn '{r.message}' lúc {time_str}{repeat_info}. ⏰",
            "en": f"Got it! I'll remind you to '{r.message}' at {time_str}{repeat_info}. ⏰",
        }
        return templates.get(lang, templates["vi"])

    # ── PRIVATE: BACKGROUND LOOP ──────────────────────────────────

    def _poll_loop(self):
        """Background thread: kiểm tra reminder mỗi _poll_sec giây."""
        while self._running:
            due_messages = self.get_due()
            for msg in due_messages:
                try:
                    self._callback(msg)
                except Exception:
                    pass
            time.sleep(self._poll_sec)

    # ── PRIVATE: PERSIST ──────────────────────────────────────────

    def _save_to_store(self):
        if not self._store:
            return
        try:
            data = [asdict(r) for r in self._reminders]
            # Lưu vào KnowledgeStore dưới dạng fact đặc biệt
            self._store._data.setdefault("reminders", [])
            self._store._data["reminders"] = data
            self._store._mark_dirty()
        except Exception:
            pass

    def _load_from_store(self):
        if not self._store:
            return
        try:
            data = self._store._data.get("reminders", [])
            now = datetime.now()
            for d in data:
                r = Reminder(**d)
                # Bỏ qua reminder đã sent + không repeat
                if r.sent and not r.repeat:
                    continue
                # Nếu đã qua giờ và repeat → cập nhật trigger_dt
                if r.trigger_datetime() < now and r.repeat:
                    deltas = {"hourly": timedelta(hours=1), "daily": timedelta(days=1),
                              "weekly": timedelta(weeks=1)}
                    delta = deltas.get(r.repeat, timedelta(days=1))
                    while r.trigger_datetime() < now:
                        r.trigger_dt = (r.trigger_datetime() + delta).isoformat()
                    r.sent = False
                self._reminders.append(r)
        except Exception:
            pass
