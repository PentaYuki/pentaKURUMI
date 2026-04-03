# core/time_awareness.py
"""
TimeAwareness — AI biết thời gian thực và nhắc nhở.

Chức năng:
  1. Biết ngày/giờ hiện tại → nói chuyện hợp thời (buổi sáng, tối thứ 2...)
  2. Người dùng dạy nhắc nhở: "nhắc anh lúc 8h tối đọc sách"
  3. AI tự kiểm tra mỗi lần chat() → trả về reminder nếu đến giờ
  4. Lập kế hoạch: "tuần này anh có gì không" → AI biết lịch

Hỗ trợ VI / EN / JP đầy đủ.
Lưu: data/reminders.json
"""

import json
import os
import re
import time
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
_PENTA_MEMORY = None


def _get_penta_memory():
    global _PENTA_MEMORY
    if _PENTA_MEMORY is not None:
        return _PENTA_MEMORY
    try:
        from penta_memory import PentaMemory
        _PENTA_MEMORY = PentaMemory()
    except Exception as e:
        logger.debug("PentaMemory unavailable for reminder variation: %s", e)
        _PENTA_MEMORY = False
    return _PENTA_MEMORY if _PENTA_MEMORY is not False else None

# ── NGÀY THÁNG THEO NGÔN NGỮ ─────────────────────────────────────────

_WEEKDAYS = {
    "vi": ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
           "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"],
    "jp": ["月曜日", "火曜日", "水曜日", "木曜日",
           "金曜日", "土曜日", "日曜日"],
}

_MONTHS = {
    "vi": ["tháng 1", "tháng 2", "tháng 3", "tháng 4",
           "tháng 5", "tháng 6", "tháng 7", "tháng 8",
           "tháng 9", "tháng 10", "tháng 11", "tháng 12"],
    "en": ["January", "February", "March", "April",
           "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "jp": ["1月", "2月", "3月", "4月", "5月", "6月",
           "7月", "8月", "9月", "10月", "11月", "12月"],
}

# Buổi trong ngày
_TIME_OF_DAY = {
    "vi": {
        "early_morning": "sáng sớm",    # 5-7
        "morning":       "buổi sáng",   # 7-12
        "noon":          "buổi trưa",   # 12-13
        "afternoon":     "buổi chiều",  # 13-18
        "evening":       "buổi tối",    # 18-22
        "night":         "đêm khuya",   # 22-5
    },
    "en": {
        "early_morning": "early morning",
        "morning":       "morning",
        "noon":          "noon",
        "afternoon":     "afternoon",
        "evening":       "evening",
        "night":         "late night",
    },
    "jp": {
        "early_morning": "早朝",
        "morning":       "午前",
        "noon":          "お昼",
        "afternoon":     "午後",
        "evening":       "夕方",
        "night":         "夜",
    },
}

# Pattern nhận dạng lệnh đặt nhắc nhở
_REMIND_PATTERNS_VI = [
    # "nhắc anh mỗi thứ 2 họp team lúc 9h"
    re.compile(
        r'nhắc\s+(?:anh|em|mình|tôi|bạn|tớ)?\s*mỗi\s+(thứ\s+\w+|chủ\s+nhật)\s+(.+?)(?:\s+lúc\s+(\d{1,2})h?)?$',
        re.IGNORECASE
    ),
    # "nhắc anh/em/mình lúc 8h tối xem phim"
    re.compile(
        r'nhắc\s+(?:anh|em|mình|tôi|bạn|tớ)\s+lúc\s+(\d{1,2})(?::(\d{2}))?\s*'
        r'(giờ\s+sáng|giờ\s+trưa|giờ\s+chiều|giờ\s+tối|h\s+sáng|h\s+chiều|h\s+tối|giờ|h)?\s+'
        r'(.+)$', re.IGNORECASE
    ),
    # "mỗi thứ 2 họp team lúc 9h" (không cần từ 'nhắc')
    re.compile(
        r'mỗi\s+(thứ\s+\w+|chủ\s+nhật)\s+(?:nhắc\s+(?:anh|em|mình|tôi|bạn)?\s*)?(.+?)(?:\s+lúc\s+(\d{1,2})h?)?$',
        re.IGNORECASE
    ),
    # "nhắc anh ngày mai 7h sáng uống thuốc"
    re.compile(
        r'nhắc\s+(?:anh|em|mình|tôi|bạn)\s+(ngày\s+mai|hôm\s+nay|ngày\s+\d+)\s+'
        r'(\d{1,2})(?::(\d{2}))?\s*h?\s*(.+)$', re.IGNORECASE
    ),
    # [NEW] "nhắc anh [lệnh] sau 10 phút" hoặc "nhắc anh sau 10 phút [lệnh]"
    re.compile(
        r'nhắc\s+(?:anh|em|mình|tôi|bạn|tớ)?\s*(.+?)\s+sau\s+(\d+)\s*(phút|giờ|tiếng)(?:\s+nữa)?(?:\s+(?:nhé|nha|nhen|đi|ạ|giùm|dùm|được\s+không))?$', 
        re.IGNORECASE
    ),
    re.compile(
        r'nhắc\s+(?:anh|em|mình|tôi|bạn|tớ)?\s*sau\s+(\d+)\s*(phút|giờ|tiếng)(?:\s+nữa)?\s+(.+?)(?:\s+(?:nhé|nha|nhen|đi|ạ|giùm|dùm|được\s+không))?$', 
        re.IGNORECASE
    ),
]

_REMIND_PATTERNS_EN = [
    # "remind me at 8pm to watch movie"
    re.compile(
        r'remind\s+(?:me|us)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(?:to\s+)?(.+)$',
        re.IGNORECASE
    ),
    # "every monday remind me to exercise"
    re.compile(
        r'every\s+(\w+day)\s+remind\s+(?:me|us)\s+(?:to\s+)?(.+)$',
        re.IGNORECASE
    ),
]

_REMIND_PATTERNS_JP = [
    # "毎朝8時に薬を飲むことを教えて"
    re.compile(
        r'毎日?(\d{1,2})時に?(.+?)(?:ことを|を)?(?:教えて|リマインド|提醒)',
        re.IGNORECASE
    ),
]

# Pattern hỏi lịch / kế hoạch
_SCHEDULE_ASK_VI = [
    r'hôm\s+nay\s+(?:là\s+)?(?:thứ\s+mấy|ngày\s+mấy|mấy\s+giờ)',
    r'(?:bây giờ|hiện tại)\s+mấy\s+giờ',
    r'ngày\s+mai\s+(?:là\s+)?thứ\s+mấy',
    r'tuần\s+này\s+(?:anh|em|mình|tôi)\s+có\s+(?:gì|lịch)',
    r'(?:nhắc|lịch|kế hoạch)',
    r'thứ\s+(?:hai|ba|tư|năm|sáu|bảy)',
]
_SCHEDULE_ASK_EN = [
    r'what\s+(?:day|time)\s+is\s+it',
    r'what\'?s\s+(?:today|the\s+date)',
    r'what\s+do\s+i\s+have\s+(?:today|this\s+week)',
    r'(?:schedule|reminder|remind)',
]
_SCHEDULE_ASK_JP = [
    r'今日は何曜日',
    r'今何時',
    r'スケジュール',
    r'リマインド',
]


class TimeAwareness:
    """
    Module nhận thức thời gian cho AI.
    Stateful: lưu reminders xuống file.
    """

    def __init__(self, save_path: str = "data/reminders.json"):
        self.save_path = save_path
        self._reminders: List[Dict] = []
        self._load()
        logger.info("TimeAwareness ready (%d reminders)", len(self._reminders))

    # ── THÔNG TIN THỜI GIAN ────────────────────────────────────────────

    def now(self) -> datetime:
        return datetime.now()

    def get_time_context(self, lang: str = "vi") -> Dict:
        """
        Trả về context thời gian đầy đủ.
        Dùng trong lời chào và response generation.
        """
        now      = self.now()
        weekday  = now.weekday()           # 0=Mon, 6=Sun
        hour     = now.hour
        minute   = now.minute

        # Buổi trong ngày
        if 5 <= hour < 7:
            period_key = "early_morning"
        elif 7 <= hour < 12:
            period_key = "morning"
        elif 12 <= hour < 13:
            period_key = "noon"
        elif 13 <= hour < 18:
            period_key = "afternoon"
        elif 18 <= hour < 22:
            period_key = "evening"
        else:
            period_key = "night"

        tod_map  = _TIME_OF_DAY.get(lang, _TIME_OF_DAY["vi"])
        wd_map   = _WEEKDAYS.get(lang, _WEEKDAYS["vi"])
        mo_map   = _MONTHS.get(lang, _MONTHS["vi"])

        # Ngày mai
        tomorrow     = now + timedelta(days=1)
        tm_weekday   = tomorrow.weekday()

        return {
            "datetime":      now,
            "weekday_idx":   weekday,
            "weekday_name":  wd_map[weekday],
            "tomorrow_name": wd_map[tm_weekday],
            "month_name":    mo_map[now.month - 1],
            "day":           now.day,
            "month":         now.month,
            "year":          now.year,
            "hour":          hour,
            "minute":        minute,
            "time_str":      f"{hour:02d}:{minute:02d}",
            "period":        period_key,
            "period_name":   tod_map[period_key],
            "is_weekend":    weekday >= 5,
            "is_monday":     weekday == 0,
        }

    def format_time_response(
        self, query: str, lang: str, user_name: str = "bạn"
    ) -> Optional[str]:
        """
        Tạo câu trả lời về thời gian tự nhiên.
        Trả về None nếu query không liên quan đến thời gian.
        """
        ctx    = self.get_time_context(lang)
        q_low  = query.lower()

        if lang == "vi":
            return self._format_vi(q_low, ctx, user_name)
        elif lang == "en":
            return self._format_en(q_low, ctx, user_name)
        elif lang == "jp":
            return self._format_jp(q_low, ctx, user_name)
        return None

    def is_time_query(self, text: str, lang: str) -> bool:
        """Kiểm tra câu có hỏi về thời gian không."""
        t = text.lower()
        patterns = {
            "vi": _SCHEDULE_ASK_VI,
            "en": _SCHEDULE_ASK_EN,
            "jp": _SCHEDULE_ASK_JP,
        }.get(lang, _SCHEDULE_ASK_VI)

        return any(re.search(p, t) for p in patterns)

    # ── REMINDERS ─────────────────────────────────────────────────────

    def parse_remind_command(
        self, text: str, lang: str
    ) -> Optional[Dict]:
        """
        Parse lệnh đặt nhắc nhở từ text.
        Trả về reminder dict hoặc None.
        """
        t = text.lower().strip()

        if lang == "vi":
            return self._parse_remind_vi(text, t)
        elif lang == "en":
            return self._parse_remind_en(text, t)
        return None

    def add_reminder(self, reminder: Dict) -> bool:
        """Thêm nhắc nhở mới."""
        self._reminders.append(reminder)
        self._save()
        logger.info("Reminder added: %s", reminder)
        return True

    def check_due_reminders(self) -> List[Dict]:
        """
        Kiểm tra xem có nhắc nhở đến hạn không.
        Gọi mỗi khi chat() được gọi.
        Returns danh sách reminders đến hạn.
        """
        now  = self.now()
        due  = []
        keep = []

        for r in self._reminders:
            if self._is_due(r, now):
                due.append(r)
                # Nếu là nhắc nhở lặp lại → giữ lại
                if r.get("repeat"):
                    keep.append(r)
                # Một lần → xóa sau khi nhắc
            else:
                keep.append(r)

        if len(keep) != len(self._reminders):
            self._reminders = keep
            self._save()

        return due

    def format_reminder_message(self, reminder: Dict, lang: str) -> str:
        """Tạo câu nhắc nhở tự nhiên."""
        msg  = reminder.get("message", "")

        templates = {
            "vi": [
                f"⏰ Nhắc {reminder.get('user_pronoun', 'bạn')} nhé: {msg}",
                f"🔔 Đến giờ rồi! {msg.capitalize()}",
                f"Hey! {msg.capitalize()} đó nhé.",
                f"Nè nè, tới giờ {msg} rồi đó {reminder.get('user_pronoun', 'bạn')} ơi.",
                f"Đồ ngốc đáng yêu ơi, tới giờ {msg} rồi nè.",
                f"Em ping nhẹ: mình {msg} nha, đừng quên đó.",
                f"Chuông báo từ em đây: {msg} liền cho ngoan nè.",
                f"Nhắc yêu một cái nè, {msg} đi {reminder.get('user_pronoun', 'bạn')} ơi.",
            ],
            "en": [
                f"⏰ Reminder: {msg}",
                f"🔔 Time to {msg}!",
                f"Hey, don't forget: {msg}",
            ],
            "jp": [
                f"⏰ リマインド：{msg}",
                f"🔔 時間です！{msg}",
            ],
        }
        pool = templates.get(lang, templates["vi"])
        default_text = random.choice(pool)

        mem = _get_penta_memory()
        if mem:
            try:
                intent = f"reminder_{lang}: {msg}"
                varied = mem.get_varied_phrase(intent=intent, default_text=default_text)
                if isinstance(varied, str) and varied.strip():
                    if "{msg}" in varied:
                        return varied.format(msg=msg)
                    return varied
            except Exception as e:
                logger.debug("Reminder variation fallback: %s", e)

        return default_text

    def get_upcoming_reminders(self, lang: str, hours_ahead: int = 24) -> List[str]:
        """Lấy danh sách nhắc nhở sắp tới."""
        now       = self.now()
        upcoming  = []
        wd_map    = _WEEKDAYS.get(lang, _WEEKDAYS["vi"])

        for r in self._reminders:
            r_time = r.get("time")
            r_day  = r.get("weekday")   # 0-6

            if r_day is not None:
                # Tính số ngày đến thứ đó
                days_ahead = (r_day - now.weekday()) % 7
                if days_ahead == 0 and r_time:
                    # Hôm nay
                    hour, minute = map(int, r_time.split(":"))
                    reminder_dt  = now.replace(hour=hour, minute=minute, second=0)
                    if reminder_dt > now:
                        upcoming.append(
                            f"{wd_map[r_day]} {r_time}: {r['message']}"
                        )
                elif days_ahead <= hours_ahead // 24:
                    upcoming.append(
                        f"{wd_map[r_day]}: {r['message']}"
                    )

        return upcoming

    # ── GREETING ENHANCEMENT ──────────────────────────────────────────

    def enhance_greeting(
        self, base_greeting: str, lang: str, user_name: str
    ) -> str:
        """
        Thêm context thời gian vào lời chào.
        "Chào Minh!" → "Chào Minh! Buổi tối thứ Hai rồi nhỉ."
        """
        ctx         = self.get_time_context(lang)
        period      = ctx["period_name"]
        weekday     = ctx["weekday_name"]
        is_monday   = ctx["is_monday"]
        is_weekend  = ctx["is_weekend"]

        import random

        additions = {
            "vi": {
                "early_morning": [
                    f"Dậy sớm thế {user_name}!",
                    f"Sáng sớm rồi nhỉ.",
                ],
                "morning": [
                    f"Buổi sáng {weekday} vui vẻ nhé!",
                    f"Chào {period}!",
                ],
                "noon": [
                    f"Trưa rồi, {user_name} ăn cơm chưa?",
                    f"Giờ này đói chưa?",
                ],
                "afternoon": [
                    f"Buổi chiều rồi đó.",
                    f"{period} {weekday} nhen.",
                ],
                "evening": [
                    f"Tối rồi! {user_name} làm việc cả ngày chắc mệt lắm.",
                    f"Buổi tối rồi nhỉ.",
                    f"Tối {weekday} rồi nè.",
                ],
                "night": [
                    f"Khuya rồi nha {user_name}, nhớ nghỉ ngơi đó.",
                    f"Thức khuya vậy?",
                ],
            },
            "en": {
                "early_morning": [f"Up early, {user_name}!", ""],
                "morning":       [f"Good morning! Happy {weekday}.", ""],
                "noon":          [f"Lunchtime! Have you eaten?", ""],
                "afternoon":     [f"Good afternoon!", ""],
                "evening":       [f"Good evening, {user_name}!", ""],
                "night":         [f"It's late, {user_name}. Don't forget to rest!", ""],
            },
            "jp": {
                "early_morning": [f"早起きですね、{user_name}さん！", ""],
                "morning":       [f"おはようございます！", ""],
                "noon":          [f"お昼ですね。ご飯食べましたか？", ""],
                "afternoon":     [f"こんにちは！", ""],
                "evening":       [f"お疲れ様です、{user_name}さん。", ""],
                "night":         [f"夜遅いですね。ゆっくり休んでください。", ""],
            },
        }

        lang_adds = additions.get(lang, additions["vi"])
        period_adds = lang_adds.get(ctx["period"], [""])
        addition = random.choice(period_adds)

        # Thứ Hai đặc biệt (đầu tuần)
        if is_monday and lang == "vi":
            addition = f"Thứ Hai rồi, tuần mới bắt đầu {user_name} nhé! " + addition

        if addition:
            return f"{base_greeting} {addition}"
        return base_greeting

    # ── PRIVATE ───────────────────────────────────────────────────────

    def _format_vi(self, q: str, ctx: Dict, user_name: str) -> Optional[str]:
        """Trả lời câu hỏi thời gian tiếng Việt."""
        import random

        # Hỏi ngày mai (phải check TRƯỚC generic "thứ mấy")
        if 'ngày mai' in q:
            if re.search(r'thứ\s+mấy|thứ\s+gì|ngày\s+mấy', q):
                return f"Ngày mai là {ctx['tomorrow_name']} {user_name} ơi."
            return f"Ngày mai là {ctx['tomorrow_name']} nhé {user_name}."

        # Hỏi thứ mấy / ngày mấy hôm nay
        if re.search(r'hôm\s+nay\s+(?:là\s+)?thứ', q) or re.search(r'thứ\s+mấy', q):
            return (f"Hôm nay là {ctx['weekday_name']}, "
                    f"ngày {ctx['day']} {ctx['month_name']} {ctx['year']} {user_name} ơi.")

        # Hỏi mấy giờ
        if re.search(r'(?:bây giờ|hiện tại)\s+mấy\s+giờ|mấy\s+giờ\s+rồi', q):
            return f"Bây giờ là {ctx['time_str']} {ctx['period_name']} rồi {user_name} ơi."

        # Hỏi lịch / kế hoạch
        if re.search(r'(?:tuần\s+này|hôm\s+nay)\s+(?:anh|em|mình|tôi|bạn)?\s*(?:có\s+)?(?:gì|lịch)', q):
            upcoming = self.get_upcoming_reminders("vi", hours_ahead=168)
            if upcoming:
                list_str = "\n  ".join(upcoming)
                return f"Lịch sắp tới của {user_name}:\n  {list_str}"
            return f"Tuần này {user_name} chưa có lịch gì cả. Muốn mình nhắc gì không?"

        # Hỏi thông tin ngày
        if re.search(r'hôm\s+nay\s+ngày\s+mấy', q):
            return (f"Hôm nay ngày {ctx['day']} {ctx['month_name']}, "
                    f"{ctx['weekday_name']} {user_name} ơi.")

        return None

    def _format_en(self, q: str, ctx: Dict, user_name: str) -> Optional[str]:
        """Answer time questions in English."""
        if re.search(r'what\s+day\s+is\s+it|what\'?s\s+today', q):
            return (f"Today is {ctx['weekday_name']}, "
                    f"{ctx['month_name']} {ctx['day']}, {ctx['year']}.")

        if re.search(r'what\s+time\s+is\s+it|what\'?s\s+the\s+time', q):
            return f"It's {ctx['time_str']} — {ctx['period_name']}."

        if re.search(r'what\'?s\s+tomorrow', q):
            return f"Tomorrow is {ctx['tomorrow_name']}."

        if re.search(r'(?:my\s+)?schedule|what\s+do\s+i\s+have', q):
            upcoming = self.get_upcoming_reminders("en", hours_ahead=168)
            if upcoming:
                return "Upcoming: " + "; ".join(upcoming)
            return "You have nothing scheduled. Want me to remind you of something?"

        return None

    def _format_jp(self, q: str, ctx: Dict, user_name: str) -> Optional[str]:
        """時間に関する質問に答える。"""
        if re.search(r'今日は何曜日|今日の曜日', q):
            return (f"今日は{ctx['weekday_name']}です。"
                    f"{ctx['month_name']}{ctx['day']}日ですよ。")

        if re.search(r'今何時|今の時刻', q):
            return f"今は{ctx['time_str']}、{ctx['period_name']}です。"

        if re.search(r'明日は何曜日', q):
            return f"明日は{ctx['tomorrow_name']}です。"

        return None

    def _parse_remind_vi(self, original: str, t: str) -> Optional[Dict]:
        """Parse lệnh nhắc nhở tiếng Việt."""
        now = self.now()
        weekday_map = {
            '2': 0, 'hai': 0, 'thứ 2': 0, 'thứ hai': 0,
            '3': 1, 'ba': 1,  'thứ 3': 1, 'thứ ba': 1,
            '4': 2, 'tư': 2,  'thứ 4': 2, 'thứ tư': 2,
            '5': 3, 'năm': 3, 'thứ 5': 3, 'thứ năm': 3,
            '6': 4, 'sáu': 4, 'thứ 6': 4, 'thứ sáu': 4,
            '7': 5, 'bảy': 5, 'thứ 7': 5, 'thứ bảy': 5,
            'chủ nhật': 6, 'cn': 6,
        }

        for pattern in _REMIND_PATTERNS_VI:
            m = pattern.match(t)
            if m:
                groups = m.groups()
                reminder = {
                    "message": "",
                    "time": None,
                    "weekday": None,
                    "date": None,
                    "repeat": False,
                    "created": now.isoformat(),
                    "lang": "vi",
                    "user_pronoun": "bạn",
                }

                # Parse groups theo pattern
                if len(groups) >= 4 and groups[0] and groups[0].isdigit():
                    # Pattern 1: lúc Xh [buổi] [message]
                    hour    = int(groups[0])
                    period  = groups[2] or ""
                    if "tối" in period or "chiều" in period:
                        if hour < 12:
                            hour += 12
                    elif "sáng" in period and hour == 12:
                        hour = 0
                    reminder["time"]    = f"{hour:02d}:{(int(groups[1]) if groups[1] else 0):02d}"
                    reminder["message"] = groups[3].strip()
                    reminder["weekday"] = now.weekday()

                elif len(groups) >= 2 and groups[0] and "thứ" in groups[0]:
                    # Pattern mỗi thứ X
                    day_str = groups[0].replace("thứ ", "").strip()
                    reminder["weekday"] = weekday_map.get(day_str,
                                           weekday_map.get(groups[0].strip(), now.weekday()))
                    msg = groups[1].strip() if groups[1] else ''
                    # Bỏ từ 'nhắc anh/em' nếu còn trong message
                    import re as _re
                    msg = _re.sub(r'^nhắc\s+(?:anh|em|mình|tôi|bạn|tớ)?\s*', '', msg).strip()
                    reminder["message"] = msg
                    reminder["repeat"]  = True
                    if groups[2]:
                        reminder["time"] = f"{int(groups[2]):02d}:00"

                elif len(groups) >= 3 and groups[1] and groups[1].isdigit() and any(u in (groups[2] or "").lower() for u in ["phút", "giờ", "tiếng"]):
                    # [NEW] Pattern relative time: "nhắc anh [lệnh] sau [X] phút"
                    offset = int(groups[1])
                    unit = groups[2].lower()
                    target_dt = now
                    if "phút" in unit:
                        target_dt = now + timedelta(minutes=offset)
                    else:
                        target_dt = now + timedelta(hours=offset)
                    
                    reminder["time"] = target_dt.strftime("%H:%M")
                    reminder["message"] = groups[0].strip()
                    reminder["weekday"] = target_dt.weekday()

                elif len(groups) >= 3 and groups[0] and groups[0].isdigit() and any(u in (groups[1] or "").lower() for u in ["phút", "giờ", "tiếng"]):
                    # [NEW] Pattern relative time: "nhắc anh sau [X] phút [lệnh]"
                    offset = int(groups[0])
                    unit = groups[1].lower()
                    target_dt = now
                    if "phút" in unit:
                        target_dt = now + timedelta(minutes=offset)
                    else:
                        target_dt = now + timedelta(hours=offset)
                    
                    reminder["time"] = target_dt.strftime("%H:%M")
                    reminder["message"] = groups[2].strip()
                    reminder["weekday"] = target_dt.weekday()

                if reminder["message"]:
                    return reminder

        return None

    def _parse_remind_en(self, original: str, t: str) -> Optional[Dict]:
        """Parse remind command in English."""
        now = self.now()
        for pattern in _REMIND_PATTERNS_EN:
            m = pattern.match(t)
            if m:
                groups = m.groups()
                reminder = {
                    "message": "",
                    "time": None,
                    "weekday": None,
                    "repeat": False,
                    "created": now.isoformat(),
                    "lang": "en",
                }
                if len(groups) >= 3 and groups[0] and groups[0].isdigit():
                    hour = int(groups[0])
                    am_pm = groups[2] or ""
                    if "pm" in am_pm and hour < 12:
                        hour += 12
                    elif "am" in am_pm and hour == 12:
                        hour = 0
                    reminder["time"]    = f"{hour:02d}:{(int(groups[1]) if groups[1] else 0):02d}"
                    reminder["message"] = groups[3].strip()
                    reminder["weekday"] = now.weekday()

                elif groups[0] and "day" in groups[0]:
                    weekday_map = {
                        "monday": 0, "tuesday": 1, "wednesday": 2,
                        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
                    }
                    reminder["weekday"] = weekday_map.get(groups[0], 0)
                    reminder["message"] = groups[1].strip()
                    reminder["repeat"]  = True

                if reminder["message"]:
                    return reminder
        return None

    def _is_due(self, reminder: Dict, now: datetime) -> bool:
        """Kiểm tra reminder có đến hạn không."""
        r_time    = reminder.get("time")
        r_weekday = reminder.get("weekday")

        if r_weekday is not None and r_weekday != now.weekday():
            return False

        if r_time:
            try:
                hour, minute = map(int, r_time.split(":"))
                # Chỉ nhắc nếu bây giờ đã đến hoặc qua giờ hẹn, và trong vòng 60 giây
                reminder_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                diff = (now - reminder_dt).total_seconds()
                return 0 <= diff <= 60  # Đã đến giờ và trong vòng 1 phút
            except Exception:
                return False

        return False

    def _load(self):
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as f:
                    self._reminders = json.load(f)
            except Exception:
                self._reminders = []

    def _save(self):
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(self._reminders, f, ensure_ascii=False, indent=2)