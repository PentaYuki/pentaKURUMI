#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import re
from typing import Any, Dict, Optional, Tuple

DAY_ORDER = [
    ("monday", "Thứ 2"),
    ("tuesday", "Thứ 3"),
    ("wednesday", "Thứ 4"),
    ("thursday", "Thứ 5"),
    ("friday", "Thứ 6"),
    ("saturday", "Thứ 7"),
    ("sunday", "Chủ nhật"),
]

DAY_ALIASES = {
    "thu 2": "monday", "thứ 2": "monday", "thu hai": "monday", "thứ hai": "monday", "monday": "monday", "mon": "monday",
    "thu 3": "tuesday", "thứ 3": "tuesday", "thu ba": "tuesday", "thứ ba": "tuesday", "tuesday": "tuesday", "tue": "tuesday",
    "thu 4": "wednesday", "thứ 4": "wednesday", "thu tu": "wednesday", "thứ tư": "wednesday", "wednesday": "wednesday", "wed": "wednesday",
    "thu 5": "thursday", "thứ 5": "thursday", "thu nam": "thursday", "thứ năm": "thursday", "thursday": "thursday", "thu": "thursday",
    "thu 6": "friday", "thứ 6": "friday", "thu sau": "friday", "thứ sáu": "friday", "friday": "friday", "fri": "friday",
    "thu 7": "saturday", "thứ 7": "saturday", "thu bay": "saturday", "thứ bảy": "saturday", "saturday": "saturday", "sat": "saturday",
    "chu nhat": "sunday", "chủ nhật": "sunday", "cn": "sunday", "sunday": "sunday", "sun": "sunday",
}

_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_parser_rules.json")


def _load_schedule_rules() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "extra_day_aliases": {
            "t2": "monday", "t3": "tuesday", "t4": "wednesday", "t5": "thursday", "t6": "friday", "t7": "saturday", "cnhat": "sunday"
        },
        "setup_trigger_phrases": ["sắp lịch", "xếp lịch", "lên lịch", "tạo lịch", "tao lich", "lịch trình", "schedule", "kế hoạch tuần"],
        "query_phrases": ["xem lịch", "lịch tuần", "lịch trình", "show schedule", "thời khóa biểu", "thời biểu"],
        "done_phrases": ["được rồi em", "duoc roi em", "xong rồi", "xong nha", "thế thôi", "the thoi", "done", "ok em", "đủ rồi"],
        "empty_phrases": ["không", "khong", "để trống", "de trong", "tạm để trống", "skip", "bo qua"],
        "day_query_markers": ["làm gì", "có gì", "rảnh không", "như thế nào", "lịch", "lich", "schedule"],
        "connectors": [",", ";", "|", "\n", " và ", " va ", " rồi ", " sau đó ", " tiếp theo "],
    }
    try:
        if os.path.exists(_RULES_PATH):
            with open(_RULES_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                defaults.update(loaded)
    except Exception:
        pass
    return defaults


_RULES = _load_schedule_rules()
DAY_ALIASES.update(_RULES.get("extra_day_aliases", {}))

_SCHEDULE_FLOW_PROMPTS = {
    "guard": {
        "vi": [
            "Em vẫn đang lên lịch cho anh nè... mình tiếp tục hay dừng tạm vậy anh?",
            "Ơ kìa, lịch mình chưa xong mà anh đổi chủ đề rồi. Anh muốn làm tiếp hay tạm dừng nha?",
            "Em hơi dỗi xíu vì lịch còn dang dở đó. Mình tiếp tục lịch luôn hay dừng lại anh?",
        ],
        "en": [
            "I'm still setting up your schedule, hehe. Do we continue or pause for now?",
            "Aww, we haven't finished the schedule yet. Want to keep going or stop here?",
            "Tiny sulky mode on because the schedule is unfinished. Continue or pause, boss?",
        ],
        "jp": [
            "まだ予定を作成中だよ。続ける？それともいったん止める？",
            "えへへ、まだスケジュール終わってないの。続きやる？それとも休憩する？",
            "ちょっとだけ拗ねちゃうよ、予定が未完了なんだもん。続ける？止める？",
        ],
    },
    "pause_auto": {
        "vi": [
            "Em đoán anh đang muốn nói chuyện khác nên em tạm dừng lịch nha. Khi nào cần, anh nói 'tiếp tục lịch' là em làm tiếp liền.",
            "Thôi được rồi, em tạm cất bản nháp lịch trước nè. Anh gọi 'tiếp tục lịch' là em quay lại ngay.",
            "Em giữ nguyên lịch dang dở cho anh rồi nhé. Lát anh nói 'tiếp tục lịch' là mình làm tiếp luôn.",
        ],
        "en": [
            "Looks like you're switching topics, so I'll pause scheduling and keep your draft safe. Say 'resume schedule' anytime.",
            "Okay, I'll park the schedule draft for now. Just say 'resume schedule' and we'll continue.",
            "No worries, I saved the unfinished schedule draft. Say 'resume schedule' when you're ready.",
        ],
        "jp": [
            "話題が変わったみたいだから、予定作成は一旦止めて下書きを保存しておくね。『スケジュール再開』で続けられるよ。",
            "いったん予定は保留にして、下書きはちゃんと残しておくね。再開したい時に言ってね。",
            "大丈夫、未完了の予定は保存してあるよ。『再開』って言ってくれたらすぐ続けるね。",
        ],
    },
}


def pick_schedule_flow_prompt(kind: str, lang: str = "vi") -> str:
    custom = _RULES.get("flow_prompts", {}) if isinstance(_RULES.get("flow_prompts", {}), dict) else {}
    bucket = custom.get(kind) if isinstance(custom.get(kind), dict) else _SCHEDULE_FLOW_PROMPTS.get(kind, {})
    if not isinstance(bucket, dict):
        bucket = _SCHEDULE_FLOW_PROMPTS.get(kind, {})

    pool = bucket.get(lang) or bucket.get("vi") or []
    if not isinstance(pool, list) or not pool:
        fallback = _SCHEDULE_FLOW_PROMPTS.get(kind, {}).get("vi", ["Mình tiếp tục hay dừng lịch nè anh?"])
        return random.choice(fallback)
    return random.choice(pool)

SCHEDULE_TRIGGER_RE = re.compile(
    r"(sắp\s*lịch|xếp\s*lịch|lên\s*lịch|tạo\s+lịch|tao\s+lich|lịch\s+trình|lich\s+trinh|schedule|kế\s*hoạch\s*tuần|ke\s*hoach\s*tuan)",
    re.IGNORECASE,
)

SCHEDULE_QUERY_RE = re.compile(
    r"(xem\s*lịch|lịch\s*tuần|lịch\s*trình\s*(tuần|hôm\s*nay)?|show\s*schedule|thời\s*khóa\s*biểu|thời\s*biểu)",
    re.IGNORECASE,
)

SCHEDULE_EMPTY_RE = re.compile(
    r"^(không|khong|để\s*trống|de\s*trong|tạm\s*để\s*trống|skip|bo\s*qua)",
    re.IGNORECASE,
)

SCHEDULE_DONE_RE = re.compile(
    r"(được\s*rồi\s*em|duoc\s*roi\s*em|xong\s*rồi|xong\s*nha|thế\s*thôi|the\s*thoi|done|ok\s*em|đủ\s*rồi)",
    re.IGNORECASE,
)

SCHEDULE_EXIT_RE = re.compile(
    r"(thoát\s*lịch|tam\s*dung\s*lich|tạm\s*dừng\s*lịch|dừng\s*lịch|hủy\s*lịch|huy\s*lich|cancel\s*schedule)",
    re.IGNORECASE,
)

SCHEDULE_RESUME_RE = re.compile(
    r"(tiếp\s*tục\s*lịch|tiep\s*tuc\s*lich|quay\s*lại\s*lịch|resume\s*schedule|xếp\s*lịch\s*tiếp)",
    re.IGNORECASE,
)

# Tìm vị trí nhắc tới ngày trong câu để trích đoạn task theo từng ngày.
DAY_SEGMENT_RE = re.compile(
    r"\b(thu\s*2|thứ\s*2|thu\s*hai|thứ\s*hai|monday|mon|"
    r"thu\s*3|thứ\s*3|thu\s*ba|thứ\s*ba|tuesday|tue|"
    r"thu\s*4|thứ\s*4|thu\s*tu|thứ\s*tư|wednesday|wed|"
    r"thu\s*5|thứ\s*5|thu\s*nam|thứ\s*năm|thursday|thu|"
    r"thu\s*6|thứ\s*6|thu\s*sau|thứ\s*sáu|friday|fri|"
    r"thu\s*7|thứ\s*7|thu\s*bay|thứ\s*bảy|saturday|sat|"
    r"chu\s*nhat|chủ\s*nhật|cn|sunday|sun)\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _contains_any_phrase(text: str, phrases) -> bool:
    txt = _norm(text)
    for phrase in (phrases or []):
        if _norm(str(phrase)) and _norm(str(phrase)) in txt:
            return True
    return False


def _normalize_connectors(text: str) -> str:
    txt = text or ""
    for connector in _RULES.get("connectors", []):
        c = str(connector)
        if c == "\\n":
            txt = txt.replace("\n", " ; ")
        else:
            txt = txt.replace(c, " ; ")
    return re.sub(r"\s+", " ", txt).strip()


def empty_week_schedule() -> Dict[str, str]:
    return {
        "monday": "",
        "tuesday": "",
        "wednesday": "",
        "thursday": "",
        "friday": "",
        "saturday": "",
        "sunday": "",
    }


def normalize_schedule_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    out = empty_week_schedule()
    for k, v in (payload or {}).items():
        mapped = DAY_ALIASES.get(_norm(str(k or "")))
        if mapped:
            out[mapped] = str(v or "").strip()
    return out


def is_schedule_setup_trigger(text: str) -> bool:
    txt = text or ""
    # Nếu đã là query lịch thì không ép vào mode setup.
    if is_schedule_query(txt) or detect_day_query(txt):
        return False
    return bool(SCHEDULE_TRIGGER_RE.search(txt)) or _contains_any_phrase(txt, _RULES.get("setup_trigger_phrases", []))


def is_schedule_done(text: str) -> bool:
    return bool(SCHEDULE_DONE_RE.search(text or "")) or _contains_any_phrase(text or "", _RULES.get("done_phrases", []))


def is_schedule_empty(text: str) -> bool:
    txt = (text or "").strip()
    return bool(SCHEDULE_EMPTY_RE.search(txt)) or _contains_any_phrase(txt, _RULES.get("empty_phrases", []))


def is_schedule_query(text: str) -> bool:
    return bool(SCHEDULE_QUERY_RE.search(text or "")) or _contains_any_phrase(text or "", _RULES.get("query_phrases", []))


def is_schedule_exit(text: str) -> bool:
    return bool(SCHEDULE_EXIT_RE.search(text or "")) or _contains_any_phrase(text or "", _RULES.get("exit_phrases", []))


def is_schedule_resume(text: str) -> bool:
    return bool(SCHEDULE_RESUME_RE.search(text or "")) or _contains_any_phrase(text or "", _RULES.get("resume_phrases", []))


def detect_day_query(text: str) -> Optional[str]:
    txt = _norm(text)
    ask_markers = _RULES.get("day_query_markers", ["làm gì", "có gì", "rảnh không", "như thế nào", "lich", "lịch", "schedule"])
    if not any(m in txt for m in ask_markers):
        return None

    found = DAY_SEGMENT_RE.search(txt)
    if not found:
        return None
    return DAY_ALIASES.get(_norm(found.group(1)))


def is_likely_offtopic_for_schedule(text: str) -> bool:
    """
    Đánh dấu off-topic khi đang trong flow xếp lịch để tránh trap người dùng.
    """
    txt = _norm(text)
    if not txt:
        return False
    if is_schedule_setup_trigger(txt) or is_schedule_query(txt) or is_schedule_done(txt) or is_schedule_empty(txt) or is_schedule_exit(txt) or is_schedule_resume(txt):
        return False
    if detect_day_query(txt):
        return False
    # Nếu không chứa bất kỳ alias ngày nào thì nhiều khả năng là câu chuyện ngoài luồng.
    if not DAY_SEGMENT_RE.search(txt):
        return True
    return False


def _cleanup_task_text(raw: str) -> str:
    t = (raw or "").strip(" .,:;|-")
    t = re.sub(r"^(anh\s+|em\s+|mình\s+|toi\s+|tôi\s+)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(co\s+|có\s+)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(làm\s+gì\s+|lam\s+gi\s+)", "", t, flags=re.IGNORECASE)
    # Gộp từ bị lặp liên tiếp do speech-to-text (vd: "học bài học bài")
    t = re.sub(r"\b(\w+)\s+\1\b", r"\1", t, flags=re.IGNORECASE)
    return t.strip()


def _strip_tail_day_reference(text: str, day_key: str) -> str:
    aliases = [k for k, v in DAY_ALIASES.items() if v == day_key]
    if not aliases:
        return text
    alias_regex = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    # Xoá đuôi kiểu "vào thứ 2" hoặc "ngày monday" trong cùng segment
    out = re.sub(rf"\s+(?:vao|vào|ngay|ngày|luc|lúc)\s+(?:{alias_regex})\b\s*$", "", text, flags=re.IGNORECASE)
    return out.strip()


def extract_schedule_updates(text: str) -> Dict[str, str]:
    txt = _normalize_connectors((text or "").strip())
    if not txt:
        return {}

    matches = list(DAY_SEGMENT_RE.finditer(txt))
    if not matches:
        return {}

    out: Dict[str, str] = {}
    for i, m in enumerate(matches):
        day_alias = _norm(m.group(1))
        day_key = DAY_ALIASES.get(day_alias)
        if not day_key:
            continue

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(txt)
        segment = txt[start:end]
        segment = re.sub(r"^[\s,:;\-]*", "", segment)
        segment = re.sub(r"^(anh|em|mình|toi|tôi)\b", "", segment, flags=re.IGNORECASE).strip(" ,:;-")

        if not segment:
            continue

        if is_schedule_empty(segment):
            out[day_key] = ""
        else:
            cleaned = _cleanup_task_text(segment)
            cleaned = _strip_tail_day_reference(cleaned, day_key)
            out[day_key] = cleaned

    return out


def merge_schedule(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, str]:
    merged = normalize_schedule_payload(base or {})
    for k, v in (updates or {}).items():
        if k in merged:
            merged[k] = str(v or "").strip()
    return merged


def schedule_brief(schedule_data: Dict[str, str]) -> str:
    filled = [f"{vn}: {schedule_data.get(en, '')}" for en, vn in DAY_ORDER if schedule_data.get(en, "").strip()]
    return " | ".join(filled) if filled else "Hiện tại các ngày đều để trống."


def schedule_day_answer(schedule_data: Dict[str, str], day_key: str) -> str:
    vi_name = dict(DAY_ORDER).get(day_key, day_key)
    value = str((schedule_data or {}).get(day_key, "")).strip()
    if value:
        return f"{vi_name} anh có: {value}."
    return f"{vi_name} hiện đang để trống."


def schedule_week_answer(schedule_data: Dict[str, str]) -> str:
    return f"Lịch tuần hiện tại: {schedule_brief(schedule_data)}"


def day_task_count(value: str) -> int:
    txt = str(value or "").strip()
    if not txt:
        return 0
    parts = [p for p in re.split(r"[;|,]|\s+và\s+|\s+va\s+", txt, flags=re.IGNORECASE) if p.strip()]
    return max(1, len(parts))


def build_weekly_detail_summary(cur: Dict[str, Any], prev: Dict[str, Any]) -> str:
    cur_norm = {k: str((cur or {}).get(k, "")).strip() for k, _ in DAY_ORDER}
    prev_norm = {k: str((prev or {}).get(k, "")).strip() for k, _ in DAY_ORDER}

    cur_count = sum(1 for v in cur_norm.values() if v)
    prev_count = sum(1 for v in prev_norm.values() if v)
    delta = cur_count - prev_count
    trend = "tích cực hơn tuần trước" if delta > 0 else ("chậm hơn tuần trước" if delta < 0 else "ổn định như tuần trước")

    empty_days = [vn for k, vn in DAY_ORDER if not cur_norm[k]]
    overload_days = [vn for k, vn in DAY_ORDER if day_task_count(cur_norm[k]) >= 3]

    tips = []
    if overload_days:
        tips.append(f"Ngày quá tải: {', '.join(overload_days[:3])}.")
        tips.append("Nên tách 1-2 việc nặng sang ngày trống để đỡ áp lực.")
    if empty_days:
        tips.append(f"Ngày trống: {', '.join(empty_days[:3])}.")
        tips.append("Có thể thêm việc nhẹ như ôn tập 30 phút hoặc tổng kết ngày.")
    if not tips:
        tips.append("Lịch tuần cân bằng tốt, giữ nhịp hiện tại là ổn.")

    return f"Tổng kết tuần: {cur_count} ngày có lịch, {trend}. " + " ".join(tips)


def parse_schedule_with_ollama(text: str, parser_func) -> Dict[str, str]:
    parsed = parser_func(text)
    if not isinstance(parsed, dict):
        return empty_week_schedule()
    return normalize_schedule_payload(parsed)


def summarize_updates(updates: Dict[str, str]) -> str:
    if not updates:
        return ""
    vi = dict(DAY_ORDER)
    parts = []
    for day_key, value in updates.items():
        day_name = vi.get(day_key, day_key)
        if value:
            parts.append(f"{day_name}: {value}")
        else:
            parts.append(f"{day_name}: để trống")
    return " | ".join(parts)


def parse_show_schedule_token(text: str) -> Tuple[str, bool]:
    if not text:
        return "", False
    cleaned = re.sub(r"<URL>\s*SHOW_SCHEDULE\s*</URL>", "", text, flags=re.IGNORECASE)
    had_token = cleaned != text or ("SHOW_SCHEDULE" in text.upper())
    cleaned = cleaned.replace("SHOW_SCHEDULE", "").strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned, had_token
