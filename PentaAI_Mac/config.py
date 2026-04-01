# config.py
import os

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "data")
GRAPH_PATH = os.path.join(MEMORY_DIR, "knowledge.json")

# ── Batch save ────────────────────────────────────────────────
# Flush sau N thao tác
SAVE_THRESHOLD = 8

# ── Fuzzy match ───────────────────────────────────────────────
FUZZY_MIN_SCORE = 0.52

# ── Synonym ───────────────────────────────────────────────────
SYNONYM_SWAP_PROB = 0.35

# ── Embedding model ───────────────────────────────────────────
# Chọn model phù hợp với máy:
#
#   "auto"    → Tự động chọn: nếu đã cài sentence-transformers thì dùng
#               MULTILINGUAL_SMALL, nếu không thì TF-IDF fallback
#
#   "tfidf"   → Luôn dùng TF-IDF (nhanh nhất, không cần cài thêm)
#               Phù hợp máy yếu hoặc chỉ dùng tiếng Việt đơn giản
#
#   "small"   → paraphrase-MiniLM-L3-v2 (~17MB)
#               Tiếng Anh tốt, tiếng Việt trung bình
#               Load ~1s, inference ~3ms
#
#   "multilingual" → paraphrase-multilingual-MiniLM-L12-v2 (~118MB)
#               VI/EN/JP đều tốt — ĐỀ XUẤT nếu máy đủ RAM
#               Load ~2s, inference ~8ms
#
#   "best"    → paraphrase-multilingual-mpnet-base-v2 (~280MB)
#               Chất lượng cao nhất, cần ~1GB RAM
#               Load ~4s, inference ~15ms
#
EMBEDDING_MODE = "tfidf"

# Model name tương ứng với từng mode
EMBEDDING_MODELS = {
    "small":         "paraphrase-MiniLM-L3-v2",
    "multilingual":  "paraphrase-multilingual-MiniLM-L12-v2",
    "best":          "paraphrase-multilingual-mpnet-base-v2",
}

# Model cache directory
MODEL_CACHE_DIR = os.path.join(MEMORY_DIR, "model_cache")