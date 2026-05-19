md5_path = "./md5.text"
chat_history_path = "./chat_history"
metrics_path = "./data/metrics.jsonl"
feedback_path = "./data/feedback.jsonl"
favorites_path = "./data/favorites.jsonl"

# Chroma 向量库配置
persist_directory = "./data/chroma"
collection_name = "knowledge_base"

# 文本切分配置
chunk_size = 800
chunk_overlap = 0
separators = ["\n\n", "\n", " ", ""]

# 超过该字符数才进行切分（避免短文本不必要的切分）
max_split_char_number = 1000

similarity_threshold = 2  # 检索返回匹配的文档数量

embedding_model_name = "text-embedding-v4"
chat_model_name = "qwen3-max"

# 推理稳定与工程兜底配置
request_window_seconds = 60
max_requests_per_window = 6

# 规则层权重（简单可解释加权）
scene_weight = 3
style_weight = 2
budget_weight = 2
body_weight = 1
assistant_signature = "怎么样，这套搭配还合你的心意吗？还有什么场景需要我帮你参谋参谋？👗✨"
max_failure_reason_length = 300

session_config = {
    "configurable": {
        "session_id": "user_001",
    }
}
