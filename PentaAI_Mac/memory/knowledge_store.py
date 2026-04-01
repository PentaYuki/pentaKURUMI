# knowledge_store.py
# memory/knowledge_store.py
"""
KnowledgeStore — Tầng 3A (storage).
Lưu 2 loại dữ liệu:
  1. facts   → { subject: { predicate, relation, lang } }
  2. phrases → [ { trigger, trigger_tokens, responses: [...] } ]

Batch save: chỉ ghi file sau SAVE_THRESHOLD thao tác.
"""

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from config import GRAPH_PATH, SAVE_THRESHOLD


class KnowledgeStore:
    def __init__(self):
        self._data: Dict = self._load()
        self._dirty_count = 0

    # ── PUBLIC: FACTS ─────────────────────────────────────────────

    def add_fact(
        self,
        subject: str,
        predicate: str,
        relation: str = "is_a",
        lang: str = "vi",
        confidence: float = 1.0,
    ) -> bool:
        """Thêm sự kiện. Trả về True nếu mới."""
        facts = self._data["facts"]
        if subject not in facts:
            facts[subject] = []

        # Kiểm tra trùng
        for entry in facts[subject]:
            if entry["predicate"] == predicate and entry["relation"] == relation:
                return False

        facts[subject].append({
            "predicate":  predicate,
            "relation":   relation,
            "lang":       lang,
            "confidence": confidence,
            "created":    datetime.now().isoformat(),
        })
        self._mark_dirty()
        return True

    def get_facts(self, subject: str) -> List[Dict]:
        """Lấy tất cả sự kiện về subject."""
        return self._data["facts"].get(subject, [])

    def get_facts_by_relation(self, subject: str, relation: str) -> List[Dict]:
        return [f for f in self.get_facts(subject) if f["relation"] == relation]

    # ── PUBLIC: PHRASES ───────────────────────────────────────────

    def add_phrase(self, trigger: str, response: str) -> bool:
        """
        Thêm cặp (trigger → response).
        Nếu trigger đã có → thêm response vào pool (không trùng).
        """
        trigger_clean = trigger.lower().strip()
        phrases = self._data["phrases"]

        for entry in phrases:
            if entry["trigger"] == trigger_clean:
                if response not in entry["responses"]:
                    entry["responses"].append(response)
                    self._mark_dirty()
                    return True
                return False  # đã có rồi

        # Trigger mới
        phrases.append({
            "trigger":        trigger_clean,
            "trigger_tokens": trigger_clean.split(),
            "responses":      [response],
            "lang":           self._guess_lang(trigger_clean),
            "use_count":      0,
            "created":        datetime.now().isoformat(),
        })
        self._mark_dirty()
        return True

    def get_all_phrases(self) -> List[Dict]:
        return self._data["phrases"]

    def increment_use(self, trigger: str):
        """Tăng bộ đếm dùng cho một phrase."""
        for entry in self._data["phrases"]:
            if entry["trigger"] == trigger.lower().strip():
                entry["use_count"] = entry.get("use_count", 0) + 1
                self._mark_dirty()
                return

    # ── PUBLIC: SYNONYMS ──────────────────────────────────────────

    def add_synonym(self, word1: str, word2: str) -> bool:
        w1, w2 = word1.lower().strip(), word2.lower().strip()
        syns = self._data["synonyms"]

        # Tìm group đã có
        for group in syns:
            if w1 in group or w2 in group:
                added = False
                if w1 not in group:
                    group.append(w1); added = True
                if w2 not in group:
                    group.append(w2); added = True
                if added:
                    self._mark_dirty()
                return added

        # Group mới
        syns.append([w1, w2])
        self._mark_dirty()
        return True

    def get_synonyms(self, word: str) -> List[str]:
        w = word.lower().strip()
        for group in self._data["synonyms"]:
            if w in group:
                return [s for s in group if s != w]
        return []

    # ── PUBLIC: PATTERNS ──────────────────────────────────────────

    def save_pattern(self, pattern_dict: Dict) -> bool:
        patterns = self._data.setdefault("patterns", [])
        for p in patterns:
            if p["template"] == pattern_dict["template"]:
                for new_slot in pattern_dict.get("slots", []):
                    for ex_slot in p.get("slots", []):
                        if ex_slot["name"] == new_slot["name"]:
                            for ex in new_slot.get("examples", []):
                                if ex not in ex_slot["examples"]:
                                    ex_slot["examples"].append(ex)
                p["source_pairs"] = p.get("source_pairs", 1) + 1
                p["confidence"]   = min(0.97, p.get("confidence", 0.5) + 0.02)
                self._mark_dirty()
                return False
        patterns.append(pattern_dict)
        self._mark_dirty()
        return True

    def get_all_patterns(self) -> List[Dict]:
        return self._data.get("patterns", [])

    def get_patterns_by_lang(self, lang: str) -> List[Dict]:
        return [p for p in self.get_all_patterns() if p.get("lang") == lang]

    # ── PUBLIC: STATS ─────────────────────────────────────────────

    def stats(self) -> Dict:
        return {
            "facts":           sum(len(v) for v in self._data["facts"].values()),
            "phrases":         len(self._data["phrases"]),
            "synonyms_groups": len(self._data["synonyms"]),
            "patterns":        len(self._data.get("patterns", [])),
        }

    # ── SAVE / LOAD ───────────────────────────────────────────────

    def flush(self):
        """Ghi file ngay lập tức."""
        os.makedirs(os.path.dirname(GRAPH_PATH), exist_ok=True)
        with open(GRAPH_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        self._dirty_count = 0

    def _mark_dirty(self):
        self._dirty_count += 1
        if self._dirty_count >= SAVE_THRESHOLD:
            self.flush()

    def _load(self) -> Dict:
        if os.path.exists(GRAPH_PATH):
            with open(GRAPH_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Tương thích ngược: đảm bảo các key tồn tại
            data.setdefault("facts",    {})
            data.setdefault("phrases",  [])
            data.setdefault("synonyms", [])
            return data
        return {
            "facts":    {},
            "phrases":  [],
            "synonyms": [],
            "created":  datetime.now().isoformat(),
        }

    def __del__(self):
        try:
            if self._dirty_count > 0:
                self.flush()
        except Exception:
            pass

    # ── HELPERS ───────────────────────────────────────────────────

    @staticmethod
    def _guess_lang(text: str) -> str:
        import re
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text):
            return "jp"
        vi_chars = re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễ'
                              r'ìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', text)
        if vi_chars:
            return "vi"
        return "en"