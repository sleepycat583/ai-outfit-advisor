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
# 默认知识库索引版本。旧 kb_default 保留作为回滚副本，不再被新代码读取。
knowledge_collection_name = "kb_default_r006"

# 文本切分配置
chunk_size = 800
chunk_overlap = 100  # R-006: 增加重叠以保持跨 chunk 上下文连续性
# 以字符级切分保证每个相邻 chunk 都实际保留 overlap；章节归属由 metadata 单独记录。
separators = [""]

# 超过该字符数才进行切分（避免短文本不必要的切分）
max_split_char_number = 1000

# 知识库检索配置
knowledge_retrieval_k = 3  # 知识库默认返回数量（可动态调整，范围 2-6）
knowledge_min_similarity = 0.50  # 最低相似度阈值（基于当前真实知识库评测集标定）
knowledge_strong_similarity = 0.60  # 达到该分数且有多个来源时视为证据充分

# 功能开关
enable_knowledge_dynamic_k = True  # 是否启用动态 k 值（根据查询类型调整）
enable_knowledge_similarity_filter = True  # 是否启用相似度过滤

embedding_model_name = EMBEDDING_MODEL_NAME
chat_model_name = "qwen3-max"

# 聊天记忆配置
chat_history_max_rounds = 10
chat_history_summary_batch_rounds = 10
chat_history_summary_interval_rounds = 3
chat_history_summary_target_chars = 600
chat_history_summary_max_chars = 1200

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
