# core/user_profile.py
"""
UserProfile — Lưu thông tin người dùng để AI gọi tên tự nhiên.

Lưu:
  name       : tên người dùng  ("Minh", "anh Tuấn", "Mi")
  ai_name    : tên người dùng đặt cho AI  ("Penta", "bé", "em")
  pronoun    : cách người dùng xưng với AI ("anh/em", "bạn/mình", "tớ/cậu")
  lang       : ngôn ngữ chính ("vi", "en", "jp")
  created_at : lần đầu gặp
  last_seen  : lần cuối nói chuyện

File: data/user_profile.json
"""

import json
import os
import time
from typing import Optional, Dict
from datetime import datetime


_DEFAULT_PROFILE = {
    "name":       None,   # Chưa biết
    "ai_name":    None,   # Người dùng chưa đặt tên cho AI
    "pronoun":    "bạn",  # Default gọi người dùng là "bạn"
    "ai_pronoun": "mình", # AI tự xưng là "mình"
    "lang":       "vi",
    "created_at": None,
    "last_seen":  None,
    "session_count": 0,
}

# Cách xưng hô theo cặp (người dùng → AI)
_PRONOUN_PAIRS = {
    "vi": [
        ("anh",  "em"),    # anh gọi AI là em
        ("chị",  "em"),
        ("em",   "anh"),   # em gọi AI là anh
        ("bạn",  "mình"),  # bạn gọi AI là mình
        ("tớ",   "cậu"),
        ("mình", "bạn"),
    ],
    "en": [
        ("you",  "i"),
    ],
    "jp": [
        ("あなた", "私"),
        ("君",    "僕"),
    ],
}


class UserProfile:
    """Quản lý profile người dùng. Load/save JSON."""

    def __init__(self, save_path: str = "data/user_profile.json"):
        self.save_path = save_path
        self._data = dict(_DEFAULT_PROFILE)
        self._load()

    # ── PUBLIC ────────────────────────────────────────────────────

    @property
    def name(self) -> Optional[str]:
        return self._data.get("name")

    @property
    def ai_name(self) -> Optional[str]:
        return self._data.get("ai_name")

    @property
    def pronoun(self) -> str:
        return self._data.get("pronoun", "bạn")

    @property
    def ai_pronoun(self) -> str:
        return self._data.get("ai_pronoun", "mình")

    @property
    def lang(self) -> str:
        return self._data.get("lang", "vi")

    @property
    def is_new_user(self) -> bool:
        """Lần đầu gặp (chưa có profile)."""
        return self._data.get("name") is None

    @property
    def session_count(self) -> int:
        return self._data.get("session_count", 0)

    def set_name(self, name: str):
        """Lưu tên người dùng."""
        self._data["name"] = name.strip()
        self._save()

    def set_ai_name(self, ai_name: str):
        """Lưu tên AI do người dùng đặt."""
        self._data["ai_name"] = ai_name.strip()
        self._save()

    def set_pronoun_pair(self, user_pronoun: str, ai_pronoun: str):
        """Lưu cặp xưng hô."""
        self._data["pronoun"]    = user_pronoun.strip()
        self._data["ai_pronoun"] = ai_pronoun.strip()
        self._save()

    def set_lang(self, lang: str):
        self._data["lang"] = lang
        self._save()

    def start_session(self):
        """Gọi khi bắt đầu session mới."""
        self._data["last_seen"]     = datetime.now().isoformat()
        self._data["session_count"] = self._data.get("session_count", 0) + 1
        if not self._data.get("created_at"):
            self._data["created_at"] = datetime.now().isoformat()
        self._save()

    def get_greeting_context(self) -> Dict:
        """
        Trả về context để tạo lời chào cá nhân hóa.
        Dùng trong cli.py và gui.py.
        """
        name          = self.name
        ai_name       = self.ai_name or "Penta"
        sessions      = self.session_count
        last_seen_str = self._data.get("last_seen")

        # Tính thời gian từ lần cuối
        time_away = None
        if last_seen_str and sessions > 1:
            try:
                last = datetime.fromisoformat(last_seen_str)
                diff = datetime.now() - last
                hours = diff.total_seconds() / 3600
                if hours < 1:
                    time_away = "vừa nãy"
                elif hours < 24:
                    time_away = f"{int(hours)} tiếng trước"
                elif hours < 48:
                    time_away = "hôm qua"
                else:
                    days = int(hours / 24)
                    time_away = f"{days} ngày trước"
            except Exception:
                pass

        return {
            "name":       name,
            "ai_name":    ai_name,
            "pronoun":    self.pronoun,
            "ai_pronoun": self.ai_pronoun,
            "sessions":   sessions,
            "time_away":  time_away,
            "is_new":     sessions <= 1,
        }

    def personalize(self, text: str) -> str:
        """
        Thay thế placeholder trong text bằng tên thật.

        {USER}     → tên người dùng ("Minh")
        {AI}       → tên AI ("Penta")
        {PRONOUN}  → cách gọi người dùng ("anh", "bạn")
        {AI_PRN}   → AI tự xưng ("em", "mình")
        """
        name          = self.name or self.pronoun
        ai_name       = self.ai_name or "Penta"
        pronoun       = self.pronoun
        ai_pronoun    = self.ai_pronoun

        return (text
                .replace("{USER}",    name)
                .replace("{AI}",      ai_name)
                .replace("{PRONOUN}", pronoun)
                .replace("{AI_PRN}",  ai_pronoun))

    # ── PRIVATE ───────────────────────────────────────────────────

    def _save(self):
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data.update(saved)
            except Exception:
                pass  # Dùng default nếu file lỗi


# ── SETUP WIZARD ──────────────────────────────────────────────────────

def run_setup_wizard(profile: UserProfile) -> str:
    """
    Hỏi tên và cách xưng hô lần đầu.
    Trả về lời chào cá nhân hóa.

    Được gọi từ cli.py khi profile.is_new_user == True.
    """
    print()
    print("  ✨ Lần đầu gặp nhau! Để mình biết cách gọi bạn nhé.")
    print()

    # Hỏi tên
    while True:
        try:
            name = input("  Bạn tên gì? (Enter để bỏ qua): ").strip()
        except (EOFError, KeyboardInterrupt):
            name = ""
            break
        break  # Bất kỳ input nào cũng OK (kể cả rỗng)

    if not name:
        name = "bạn"
        display_name = "bạn"
    else:
        display_name = name
        profile.set_name(name)

    # Hỏi cách xưng hô
    print()
    print("  Bạn muốn xưng hô thế nào?")
    print("  1. anh/em  (bạn là anh, AI là em)")
    print("  2. bạn/mình  (thân thiện, ngang hàng)")
    print("  3. tớ/cậu  (thân mật)")
    print("  4. tự nhập")

    try:
        choice = input("  Chọn (1-4, mặc định=2): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "2"

    pronoun_map = {
        "1": ("anh",  "em"),
        "2": ("bạn",  "mình"),
        "3": ("tớ",   "cậu"),
    }

    if choice in pronoun_map:
        user_prn, ai_prn = pronoun_map[choice]
    elif choice == "4":
        try:
            user_prn = input("  Bạn xưng là: ").strip() or "bạn"
            ai_prn   = input("  AI xưng là:  ").strip() or "mình"
        except (EOFError, KeyboardInterrupt):
            user_prn, ai_prn = "bạn", "mình"
    else:
        user_prn, ai_prn = "bạn", "mình"

    profile.set_pronoun_pair(user_prn, ai_prn)

    # Hỏi tên AI
    print()
    try:
        ai_name = input(f"  {user_prn.capitalize()} muốn gọi tôi là gì? (Enter → Penta): ").strip()
    except (EOFError, KeyboardInterrupt):
        ai_name = ""

    if ai_name:
        profile.set_ai_name(ai_name)
    else:
        ai_name = "Penta"

    profile.start_session()

    # Lời chào đầu tiên
    greet_lines = {
        ("anh",  "em"):    f"Dạ, {ai_prn} là {ai_name}! Rất vui được gặp {user_prn} {display_name} ạ. {user_prn.capitalize()} cần {ai_prn} giúp gì không?",
        ("bạn",  "mình"):  f"Mình là {ai_name}! Vui được quen {display_name} nha. Bạn muốn dạy mình điều gì không?",
        ("tớ",   "cậu"):   f"Cậu là {ai_name} nè! Vui ghê khi gặp {display_name}. Tớ có thể dạy cậu gì không?",
    }
    greeting = greet_lines.get(
        (user_prn, ai_prn),
        f"{ai_prn.capitalize()} là {ai_name}! Vui được gặp {display_name}."
    )

    print()
    print(f"  AI: {greeting}")
    print()

    return greeting


def build_return_greeting(profile: UserProfile) -> str:
    """
    Lời chào khi người dùng quay lại (không phải lần đầu).
    """
    ctx       = profile.get_greeting_context()
    name      = ctx["name"] or ctx["pronoun"]
    ai_name   = ctx["ai_name"]
    time_away = ctx["time_away"]
    sessions  = ctx["sessions"]
    ai_prn    = profile.ai_pronoun
    user_prn  = profile.pronoun

    import random
    if time_away in ("vừa nãy", None):
        templates = [
            f"{ai_prn.capitalize()} đây {user_prn} ơi!",
            f"Chào {name}!",
            f"{name} quay lại rồi nè!",
        ]
    elif "tiếng" in str(time_away):
        templates = [
            f"Chào {name}! Vừa đi đâu về vậy?",
            f"{name} về rồi! {ai_prn.capitalize()} chờ mãi.",
            f"Ôi {name}! Lâu lắm mới gặp lại.",
        ]
    elif "hôm qua" in str(time_away):
        templates = [
            f"Chào {name}! Hôm qua {user_prn} đi đâu vậy?",
            f"{name} quay lại rồi! {ai_prn.capitalize()} nhớ {user_prn} ghê.",
        ]
    else:
        templates = [
            f"Ôi {name}! {time_away} mới thấy {user_prn}.",
            f"Chào {name}! Lâu rồi không gặp nhỉ.",
            f"{name}! {ai_prn.capitalize()} tưởng {user_prn} quên {ai_prn} rồi.",
        ]

    return random.choice(templates)