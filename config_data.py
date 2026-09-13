import os


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()

NO_PROXY = os.getenv("NO_PROXY")

CHAT_HISTORY_DIR = "./chat_history"
EMBEDDING_MODEL_NAME = "text-embedding-v4"
DEFAULT_OPERATOR = "小曹"

# Chroma 向量库配置
persist_directory = "./data/chroma"

# 文本切分配置
chunk_size = 800
chunk_overlap = 0
separators = ["\n\n", "\n", " ", ""]

# 超过该字符数才进行切分（避免短文本不必要的切分）
max_split_char_number = 1000

similarity_threshold = 2  # 检索返回匹配的文档数量

embedding_model_name = EMBEDDING_MODEL_NAME
chat_model_name = "qwen3-max"

# 聊天记忆配置
chat_history_max_rounds = 10
chat_history_summary_batch_rounds = 10
chat_history_summary_interval_rounds = 3
chat_history_summary_target_chars = 600
chat_history_summary_max_chars = 1200

# Memory migration feature flags. Keep the legacy path as the production default
# until the native Postgres-backed implementation has passed its rollout checks.
MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "legacy").strip().lower()
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "chroma").strip().lower()
if VECTOR_BACKEND not in {"chroma", "pgvector"}:
    raise ValueError("VECTOR_BACKEND 仅支持 chroma 或 pgvector")
VECTOR_DUAL_WRITE = _env_bool("VECTOR_DUAL_WRITE", default=False)
VECTOR_SHADOW_QUERY = _env_bool("VECTOR_SHADOW_QUERY", default=False)
# Native checkpoint rollouts keep the legacy transcript in sync so that a
# failed Postgres connection can be rolled back without losing the UI history.
# The default is intentionally conservative for the existing legacy backend.
MEMORY_DUAL_WRITE = _env_bool("MEMORY_DUAL_WRITE", default=MEMORY_BACKEND == "native")
MEMORY_NATIVE_FALLBACK = _env_bool("MEMORY_NATIVE_FALLBACK", default=True)
# Memory objects are deployed in one private schema.  Keeping this fixed avoids
# the Python producer and the Edge worker silently targeting different schemas.
_configured_memory_schema = os.getenv("MEMORY_PRIVATE_SCHEMA", "app_private").strip() or "app_private"
if _configured_memory_schema != "app_private":
    raise ValueError("MEMORY_PRIVATE_SCHEMA 仅支持 app_private")
MEMORY_PRIVATE_SCHEMA = "app_private"
LONG_TERM_MEMORY_ENABLED = _env_bool("LONG_TERM_MEMORY_ENABLED", default=False)
MEMORY_ASYNC_EXTRACTION_ENABLED = _env_bool("MEMORY_ASYNC_EXTRACTION_ENABLED", default=False)
MEMORY_JOB_QUEUE_NAME = os.getenv("MEMORY_JOB_QUEUE_NAME", "memory-extraction").strip().lower()
if MEMORY_JOB_QUEUE_NAME != "memory-extraction":
    raise ValueError("MEMORY_JOB_QUEUE_NAME 仅支持 memory-extraction")
MEMORY_JOB_MAX_ATTEMPTS = int(os.getenv("MEMORY_JOB_MAX_ATTEMPTS", "5"))
if MEMORY_JOB_MAX_ATTEMPTS < 1:
    raise ValueError("MEMORY_JOB_MAX_ATTEMPTS 必须大于 0")

# 摘要约束检测关键词配置
# 用于识别用户消息中的明确约束,确保这些约束在摘要压缩时不被丢弃
constraint_keywords_negative = [
    "不穿", "不喜欢", "不要", "避免", "禁忌", "讨厌", "不适合",
    "不能", "别", "拒绝", "排斥", "反感", "不接受"
]
constraint_keywords_body = [
    "腿粗", "显胖", "显矮", "肩宽", "驼背", "小个子", "梨形身材",
    "苹果型", "腿短", "胯宽", "手臂粗", "脖子短"
]

session_config = {
    "configurable": {
        "session_id": "user_001",
    }
}

WARDROBE_FILE_PATH = "./data/wardrobe.json"
WARDROBE_IMAGE_DIR = "./data/wardrobe_images"
VISUAL_MODEL_NAME = "qwen-vl-max"
WARDROBE_CATEGORIES = ["外套", "内搭", "下装", "鞋履", "配饰"]
