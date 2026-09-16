"""配置模块统一导出接口

从 config 包中导入所有配置项，简化外部模块的导入路径。
"""
from config.base import (
    NO_PROXY,
    CHAT_HISTORY_DIR,
    EMBEDDING_MODEL_NAME,
    DEFAULT_OPERATOR,
    persist_directory,
    chunk_size,
    chunk_overlap,
    separators,
    max_split_char_number,
    similarity_threshold,
    embedding_model_name,
    chat_model_name,
    chat_history_max_rounds,
    chat_history_summary_batch_rounds,
    chat_history_summary_interval_rounds,
    chat_history_summary_target_chars,
    chat_history_summary_max_chars,
    constraint_keywords_negative,
    constraint_keywords_body,
    session_config,
    WARDROBE_FILE_PATH,
    WARDROBE_IMAGE_DIR,
    VISUAL_MODEL_NAME,
    WARDROBE_CATEGORIES,
)
from config.supabase import get_supabase_client, WARDROBE_BUCKET

__all__ = [
    # base config
    "NO_PROXY",
    "CHAT_HISTORY_DIR",
    "EMBEDDING_MODEL_NAME",
    "DEFAULT_OPERATOR",
    "persist_directory",
    "chunk_size",
    "chunk_overlap",
    "separators",
    "max_split_char_number",
    "similarity_threshold",
    "embedding_model_name",
    "chat_model_name",
    "chat_history_max_rounds",
    "chat_history_summary_batch_rounds",
    "chat_history_summary_interval_rounds",
    "chat_history_summary_target_chars",
    "chat_history_summary_max_chars",
    "constraint_keywords_negative",
    "constraint_keywords_body",
    "session_config",
    "WARDROBE_FILE_PATH",
    "WARDROBE_IMAGE_DIR",
    "VISUAL_MODEL_NAME",
    "WARDROBE_CATEGORIES",
    # supabase
    "get_supabase_client",
    "WARDROBE_BUCKET",
]
