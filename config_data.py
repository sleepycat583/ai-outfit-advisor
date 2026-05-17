md5_path = "./md5.text"

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

session_config = {
    "configurable": {
        "session_id": "user_001",
    }
}