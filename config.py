"""配置模块统一导出接口

提供项目所有配置项的统一访问入口，整合基础配置和 Supabase 配置。
"""

from config.base import *
from config.supabase import get_supabase_client, WARDROBE_BUCKET

__all__ = [
    # base config
    'persist_directory',
    'chunk_size',
    'chunk_overlap',
    'embedding_model_name',
    'chat_model_name',
    'chat_history_max_rounds',
    'WARDROBE_CATEGORIES',
    # supabase
    'get_supabase_client',
    'WARDROBE_BUCKET',
]
