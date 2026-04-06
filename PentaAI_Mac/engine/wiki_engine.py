#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaWiki Engine — Wikipedia REST API integration for PentaAI.
Hỗ trợ 3 ngôn ngữ: tiếng Việt (vi), tiếng Anh (en), tiếng Nhật (ja).
Không cần API key — dùng Wikipedia REST API (public).
"""

import re
import json
import logging
import unicodedata
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, List

log = logging.getLogger("PentaWiki")

# ── Wikipedia REST API endpoints ──────────────────────────────────────────────
_WIKI_SUMMARY_API: Dict[str, str] = {
    "vi": "https://vi.wikipedia.org/api/rest_v1/page/summary/{}",
    "en": "https://en.wikipedia.org/api/rest_v1/page/summary/{}",
    "ja": "https://ja.wikipedia.org/api/rest_v1/page/summary/{}",
}
_WIKI_SEARCH_API: Dict[str, str] = {
    "vi": "https://vi.wikipedia.org/w/api.php?action=query&list=search&srsearch={}&srlimit=3&format=json",
    "en": "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={}&srlimit=3&format=json",
    "ja": "https://ja.wikipedia.org/w/api.php?action=query&list=search&srsearch={}&srlimit=3&format=json",
}

# ── Intent patterns ───────────────────────────────────────────────────────────
_RE_WIKI_ON = re.compile(
    r"\b(bật|mở|khởi\s*động|start|on|enable)\s*"
    r"(penta\s*wiki|wiki\s*mode|pentawiki)\b",
    re.IGNORECASE,
)
_RE_WIKI_OFF = re.compile(
    r"\b(tắt|đóng|stop|off|disable)\s*"
    r"(penta\s*wiki|wiki\s*mode|pentawiki)\b",
    re.IGNORECASE,
)

# Language toggle — requires an action verb before the language
_RE_LANG_JA = re.compile(
    r"\b(nói|dùng|chuyển|đổi|sang|switch|bật|reply|trả\s*lời)\s+"
    r"(tiếng\s+)?(nhật|japan(ese)?|ja\b)",
    re.IGNORECASE,
)
_RE_LANG_EN = re.compile(
    r"\b(nói|dùng|chuyển|đổi|sang|switch|bật|reply|trả\s*lời)\s+"
    r"(tiếng\s+)?(anh|eng(lish)?|en\b)",
    re.IGNORECASE,
)
_RE_LANG_VI = re.compile(
    r"\b(nói|dùng|chuyển|đổi|sang|về|quay\s*về|switch|bật|reply|trả\s*lời)\s+"
    r"(tiếng\s+)?(việt(nam)?|vietnamese|vi\b)",
    re.IGNORECASE,
)


def check_wiki_toggle(text: str) -> Optional[str]:
    """Return 'on', 'off', or None."""
    if _RE_WIKI_ON.search(text):
        return "on"
    if _RE_WIKI_OFF.search(text):
        return "off"
    return None


def check_lang_toggle(text: str) -> Optional[str]:
    """Return 'ja', 'en', 'vi', or None."""
    if _RE_LANG_JA.search(text):
        return "ja"
    if _RE_LANG_EN.search(text):
        return "en"
    if _RE_LANG_VI.search(text):
        return "vi"
    return None


# ── Conversational filter — tránh đưa câu trò chuyện vào wiki ────────────────
_RE_CONVERSATIONAL = re.compile(
    r"\b(đợi|chờ|nhé|nha|xin|giúp|cảm\s*ơn|ok|được\s*rồi|xong\s*rồi"
    r"|hiểu\s*rồi|phút|giây|tiếng|anh|em|mình|tôi|bạn|thêm|nữa|nhé\s*$)",
    re.IGNORECASE,
)
_RE_INFORMATIONAL = re.compile(
    r"\b(là\s*gì|là\s*ai|như\s*thế\s*nào|thế\s*nào|khi\s*nào|ở\s*đâu"
    r"|tại\s*sao|vì\s*sao|được\s*phát\s*hiện|được\s*tạo|được\s*hình\s*thành"
    r"|có\s*từ\s*khi\s*nào|ra\s*đời|lịch\s*sử|nguồn\s*gốc|ý\s*nghĩa"
    r"|what\s*is|who\s*is|when\s*was|how\s*is|where\s*is|tell\s*me\s*about"
    r"|cho\s*biết|giải\s*thích|nói\s*về|tra\s*cứu)\b",
    re.IGNORECASE,
)


def is_informational_query(text: str) -> bool:
    """
    Trả về True nếu câu có vẻ là câu hỏi thông tin (phù hợp Wikipedia).
    Trả về False nếu là câu trò chuyện thông thường.
    """
    # Có từ hỏi thông tin → luôn True
    if _RE_INFORMATIONAL.search(text):
        return True
    # Rõ ràng là hội thoại → False
    if _RE_CONVERSATIONAL.search(text):
        return False
    # Tên tính năng nội bộ (không phải câu hỏi bách khoa)
    _RE_INTERNAL = re.compile(
        r"^(penta\s*wiki|wiki\s*mode|pentawiki|penta\s*mi|pentami)$",
        re.IGNORECASE,
    )
    if _RE_INTERNAL.match(text.strip()):
        return False
    # Cụm từ ngắn 1-5 từ không có động từ hành động → coi là tìm kiếm chủ đề
    return len(text.strip().split()) <= 5


# ── Rule-based keyword extractor (không dùng Ollama) ─────────────────────────
# Xóa phần câu hỏi cuối câu tiếng Việt, giữ lại chủ đề
_VI_Q_SUFFIX = re.compile(
    r"\s+(?:"
    r"là\s+(?:gì|ai|sao|loại\s+gì|sinh\s+vật\s+(?:gì|như\s+thế\s+nào)?)"
    r"|như\s+thế\s+nào|thế\s+nào|ra\s+sao"
    r"|được\s+(?:phát\s+hiện|tìm\s+ra|tạo\s+ra|hình\s+thành)(?:\s+khi\s+nào|\s+thế\s+nào)?"
    r"|khi\s+nào|bao\s+giờ|ở\s+đâu|tại\s+sao|vì\s+sao|bao\s+nhiêu"
    r"|dùng\s+để\s+làm\s+gì|có\s+tác\s+dụng"
    r"|sống\s+ở\s+đâu|ăn\s+gì|làm\s+gì|có\s+từ\s+khi\s+nào"
    r"|là\s+sinh\s+vật(?:\s+như\s+thế\s+nào)?"
    r")(?:[\s,.]|$)",
    re.IGNORECASE,
)
# Xóa danh từ chỉ loại tiếng Việt đứng đầu câu
# Không xóa "bảng" vì có thể là một phần của tên (bảng cửu chương)
_VI_CLASSIFIER = re.compile(
    r"^(?:con|cái|cây|loài|loại|quả|quyển|cuốn|chiếc|tờ|cục|khối)\s+",
    re.IGNORECASE,
)


def _rule_extract_keyword(text: str, lang: str = "vi") -> str:
    """Rút từ khóa tra cứu bằng regex — nhanh và đáng tin hơn LLM nhỏ."""
    cleaned = text.strip()
    if lang == "vi":
        # Bước 1: xóa phần hỏi cuối câu
        cleaned = _VI_Q_SUFFIX.sub("", cleaned).strip()
        # Bước 2: xóa danh từ loại đầu câu
        cleaned = _VI_CLASSIFIER.sub("", cleaned).strip()
    elif lang == "en":
        cleaned = re.sub(
            r"\s+(?:is|are|was|were|means|meaning|about|what|who|when|where|how)\b.*$",
            "", cleaned, flags=re.IGNORECASE,
        ).strip()
    return cleaned if len(cleaned) >= 2 else text.strip()


# ── HTTP helper ───────────────────────────────────────────────────────────────
def _http_get(url: str, timeout: int = 6) -> Optional[bytes]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PentaAI/1.0 (+https://github.com/pentaai)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        log.warning(f"[Wiki HTTP] {url[:90]} → {exc}")
        return None


def _search_wiki_title(query: str, lang: str = "vi") -> Optional[str]:
    """Tìm tiêu đề bài viết Wikipedia khớp nhất với query."""
    titles = _search_wiki_all(query, lang, limit=1)
    return titles[0] if titles else None


def _search_wiki_all(query: str, lang: str = "vi", limit: int = 4) -> List[str]:
    """Tìm danh sách tiêu đề Wikipedia (tối đa limit kết quả)."""
    api_tmpl = _WIKI_SEARCH_API.get(lang, _WIKI_SEARCH_API["vi"])
    # Tăng srlimit nếu cần nhiều hơn 3 kết quả mặc định
    url = api_tmpl.replace("srlimit=3", f"srlimit={max(limit, 3)}").format(
        urllib.parse.quote_plus(query)
    )
    raw = _http_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
        results = data.get("query", {}).get("search", [])
        return [str(r["title"]) for r in results if r.get("title")][:limit]
    except Exception:
        return []


def _extract_query_with_ollama(
    user_text: str,
    lang: str = "vi",
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2:1b",
) -> str:
    """
    Bước 1: rule-based (nhanh, chính xác cho tiếng Việt).
    Bước 2: nếu rule chưa rút được (> 4 từ), thử Ollama.
    Bước 3: fallback nguyên văn.
    """
    # Bước 1 — rule-based
    rule_kw = _rule_extract_keyword(user_text, lang)
    if len(rule_kw.split()) <= 4:
        log.info(f"[Wiki Rule] '{user_text}' → '{rule_kw}'")
        return rule_kw

    # Bước 2 — Ollama (chỉ cần khi câu phức tạp > 4 từ và rule không rút gọn được)
    _prompts = {
        "vi": (
            f"Chỉ trả về 1-3 từ tiêu đề bài Wikipedia tiếng Việt. Không giải thích.\n"
            f"Câu: \"{user_text}\"\n"
            f"Ví dụ: 'bảng cửu chương là gì' → bảng cửu chương\n"
            f"Ví dụ: 'Bác Hồ là ai' → Hồ Chí Minh\n"
            f"Tiêu đề:"
        ),
        "en": (
            f"Return only 1-3 word Wikipedia article title. No explanation.\n"
            f"Query: \"{user_text}\"\n"
            f"Example: 'what is the water cycle' → water cycle\n"
            f"Title:"
        ),
        "ja": (
            f"Wikipedia記事タイトル（1～3語）のみ返答。説明不要。\n"
            f"質問: \"{user_text}\"\n"
            f"タイトル："
        ),
    }
    try:
        payload = json.dumps({
            "model": ollama_model,
            "prompt": _prompts.get(lang, _prompts["vi"]),
            "stream": False,
            "options": {"num_predict": 15, "temperature": 0.0},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ollama_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "PentaAI/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_kw = str(data.get("response", "")).strip()
            keyword = raw_kw.splitlines()[0].strip().strip('"').strip("'").strip()
            # Sánủn Ollama trả về phân tích/giải thích dài thay vì từ khóa
            if keyword and len(keyword.split()) <= 5 and len(keyword) < 60:
                log.info(f"[Wiki Ollama] '{user_text}' → '{keyword}'")
                return keyword
    except Exception as exc:
        log.warning(f"[Wiki Ollama] fallback: {exc}")

    return rule_kw  # fallback về rule result


def _nfc(s: str) -> str:
    """Chuẩn hóa Unicode NFC — bắt buộc để so sánh tiếng Việt chính xác."""
    return unicodedata.normalize("NFC", s)


def _word_set(text: str) -> set:
    """Tokenize + NFC + lowercase, bỏ stop-words, min 2 ký tự."""
    _STOP = {
        "là", "gì", "ai", "sao", "why", "the", "is", "an", "of", "in",
        "và", "có", "như", "thế", "nào", "qua", "khi", "ra", "đã",
        "các", "một", "cho", "bởi", "từ", "theo", "với", "hoặc",
    }
    return {
        _nfc(w.lower())
        for w in re.split(r"[\s\W]+", _nfc(text))
        if len(w) >= 2 and _nfc(w.lower()) not in _STOP
    }


def _is_relevant_result(query: str, result_title: str) -> bool:
    """
    Kiểm tra độ liên quan giữa query và kết quả Wikipedia.
    Dùng NFC normalization để tốt với tiếng Việt có dấu.
    """
    q_words = _word_set(query)
    t_words = _word_set(result_title)
    if not q_words:
        return True   # không có từ để kiểm tra → cho qua
    return bool(q_words & t_words)


def fetch_wiki(
    query: str,
    lang: str = "vi",
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2:1b",
) -> Dict[str, Any]:
    """
    Lấy tóm tắt bài Wikipedia cho câu hỏi query.
    Trả về: {ok, title, extract, url}
    extract được cắt tối đa 3 câu / 480 ký tự để phù hợp TTS.
    """
    # Bước 0: dùng Ollama rút từ khóa từ câu tự nhiên
    search_query = _extract_query_with_ollama(query, lang, ollama_url, ollama_model)

    # Bước 1: tìm tiêu đề chính xác + chủ đề liên quan
    all_titles = _search_wiki_all(search_query, lang, limit=4)
    title   = all_titles[0] if all_titles else search_query.strip()
    related = all_titles[1:3]  # tối đa 2 chủ đề liên quan

    # Bước 2: gọi API tóm tắt
    api_tmpl = _WIKI_SUMMARY_API.get(lang, _WIKI_SUMMARY_API["vi"])
    url = api_tmpl.format(urllib.parse.quote(title.replace(" ", "_"), safe=""))
    raw = _http_get(url, timeout=7)
    if not raw:
        return {"ok": False, "title": title, "extract": "", "url": ""}

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "title": title, "extract": "", "url": ""}

    extract = str(data.get("extract", "")).strip()
    result_title = data.get("title", title)
    if not extract:
        return {"ok": False, "title": result_title, "extract": "", "url": ""}

    # Kiểm tra độ liên quan: nếu tiêu đề kết quả hoàn toàn khác query → bỏ
    if not _is_relevant_result(search_query, result_title):
        log.warning(f"[Wiki] irrelevant result: query='{search_query}' title='{result_title}'")
        return {"ok": False, "title": result_title, "extract": "", "url": ""}

    # Cắt ngắn thân thiện với TTS (tối đa 3 câu/480 ký tự)
    # Phân tách câu theo dấu câu của cả 3 ngôn ngữ
    sentences = re.split(r'(?<=[.!?。！？])\s+', extract)
    short = " ".join(sentences[:3])
    if len(short) > 480:
        short = short[:480].rsplit(" ", 1)[0] + "…"

    page_url = (
        data.get("content_urls", {}).get("desktop", {}).get("page", "")
        or data.get("fullurl", "")
    )
    # Lọc loại bỏ related trùng với title chính
    related_clean = [r for r in related if r.lower() != result_title.lower()]
    return {
        "ok": True,
        "title": result_title,
        "extract": short,
        "url": page_url,
        "related": related_clean,
    }


def format_wiki_response(
    result: Dict[str, Any],
    lang: str,
    ai_prn: str = "em",
    user_call: str = "anh",
) -> str:
    """Định dạng kết quả Wikipedia thành câu trả lời dễ nghe qua TTS."""
    if not result.get("ok"):
        msgs = {
            "vi": f"{ai_prn.capitalize()} tìm trên Wikipedia nhưng không thấy thông tin về chủ đề này {user_call} ơi.",
            "en": f"Sorry {user_call}, I couldn't find anything about that on Wikipedia.",
            "ja": f"{user_call}さん、Wikipediaではそのトピックが見つかりませんでした。",
        }
        return msgs.get(lang, msgs["vi"])

    title   = result["title"]
    extract = result["extract"]

    intros = {
        "vi": f"Theo Wikipedia, {title}: {extract}",
        "en": f"According to Wikipedia — {title}: {extract}",
        "ja": f"Wikipediaによると、{title}：{extract}",
    }
    return intros.get(lang, intros["vi"])
