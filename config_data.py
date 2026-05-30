import os


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

session_config = {
    "configurable": {
        "session_id": "user_001",
    }
}

WARDROBE_FILE_PATH = "./data/wardrobe.json"
WARDROBE_IMAGE_DIR = "./data/wardrobe_images"
VISUAL_MODEL_NAME = "qwen-vl-max"
WARDROBE_CATEGORIES = ["外套", "内搭", "下装", "鞋履", "配饰"]
