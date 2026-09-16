"""Supabase 配置共享模块。

Streamlit Cloud 使用临时文件系统，所有数据必须持久化到外部服务。
本模块提供统一的 Supabase 客户端创建与凭据读取逻辑。
"""

import os
import time
from functools import lru_cache
from urllib.parse import urlsplit

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


def get_database_url() -> str | None:
    """读取仅供服务端使用的 PostgreSQL 连接串。

    不回退到 ``SUPABASE_URL``：PostgresSaver 必须使用数据库连接串，且该
    密钥不应出现在前端或匿名 Data API 请求中。
    """
    try:
        import streamlit as st

        value = st.secrets.get("SUPABASE_DB_URL")
        if value:
            normalized = _normalize_database_url(str(value))
            if normalized:
                return normalized
    except Exception:
        pass
    return _normalize_database_url(os.environ.get("SUPABASE_DB_URL"))


def _normalize_database_url(value: str | None) -> str | None:
    """过滤空值和文档示例连接串，避免把占位主机交给 psycopg。

    参数:
        value: 环境变量或 Streamlit secret 中的 PostgreSQL 连接串。
    返回值:
        可交给 psycopg 的连接串；未配置或明显为占位值时返回 ``None``。

    为什么需要这里校验：项目根目录的 ``.env`` 可能保留
    ``postgresql://...`` 示例值。psycopg 会把 ``...`` 当作真实主机名并
    触发 IDNA 编码异常，导致 legacy memory 也无法正常回退。
    """
    normalized = (value or "").strip()
    if not normalized:
        return None

    if normalized.startswith(("postgresql://", "postgres://")):
        try:
            parsed = urlsplit(normalized)
            hostname = parsed.hostname or ""
            if not hostname or "..." in hostname:
                return None
            # Accessing port validates malformed values such as ``:abc``.
            _ = parsed.port
        except ValueError:
            return None

    return normalized


# Storage bucket 名称
WARDROBE_BUCKET = "wardrobe-images"
