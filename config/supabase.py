"""Supabase 配置共享模块。

Streamlit Cloud 使用临时文件系统，所有数据必须持久化到外部服务。
本模块提供统一的 Supabase 客户端创建与凭据读取逻辑。
"""

import os
import time
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """创建 Supabase 客户端，并打印初始化耗时。

    优先从 Streamlit secrets 读取凭据（Streamlit Cloud），
    其次从环境变量读取（本地开发）。

    为什么要缓存：Supabase client 可以理解为“数据库网站的会话对象”。
    这个对象本身可复用，如果每次页面 rerun、每次服务初始化都重新创建，
    会重复产生连接和握手成本，直接拖慢页面加载与问答前准备阶段。
    """
    start_time = time.time()
    url, key = _get_credentials()
    client = create_client(url, key)
    print(f"[PERF] get_supabase_client took {time.time() - start_time:.3f}s", flush=True)
    return client


def _get_credentials() -> tuple[str, str]:
    try:
        import streamlit as st

        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
        if url and key:
            return url, key
    except Exception:
        pass

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        return url, key

    raise RuntimeError(
        "未找到 Supabase 连接凭据。请执行以下操作之一：\n"
        "  1. Streamlit Cloud：在 App Settings → Secrets 中添加 SUPABASE_URL 和 SUPABASE_KEY\n"
        "  2. 本地开发：创建 .streamlit/secrets.toml 文件，或设置环境变量"
    )


# Storage bucket 名称
WARDROBE_BUCKET = "wardrobe-images"
