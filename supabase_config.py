"""Supabase 配置共享模块。

Streamlit Cloud 使用临时文件系统，所有数据必须持久化到外部服务。
本模块提供统一的 Supabase 客户端创建与凭据读取逻辑。
"""

import os

from supabase import Client, create_client


def get_supabase_client() -> Client:
    """创建 Supabase 客户端。

    优先从 Streamlit secrets 读取凭据（Streamlit Cloud），
    其次从环境变量读取（本地开发）。
    """
    url, key = _get_credentials()
    return create_client(url, key)


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
