import hashlib
import json
import os
import uuid
from datetime import datetime

from supabase import Client, create_client


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class UserService:
    """用户服务（Supabase 持久化）

    Streamlit Cloud 使用临时文件系统，SQLite 数据库在容器回收后会丢失。
    因此将所有用户数据迁移到 Supabase PostgreSQL 实现持久化存储。
    """

    def __init__(self, db_path: str | None = None):
        # db_path 参数保留用于向后兼容，实际已不再使用
        _ = db_path
        url, key = self._get_credentials()
        self.supabase: Client = create_client(url, key)

    @staticmethod
    def _get_credentials() -> tuple[str, str]:
        """获取 Supabase 连接凭据。

        优先从 Streamlit secrets 读取（Streamlit Cloud 部署环境），
        其次从环境变量读取（本地开发环境）。
        """
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

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
        """PBKDF2-SHA256 密码哈希。"""
        if salt is None:
            salt = os.urandom(32).hex()
        hash_bytes = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
        )
        return hash_bytes.hex(), salt

    def register(self, username: str, password: str) -> tuple[bool, str]:
        """注册新用户。"""
        username = username.strip()
        if not username or not password:
            return False, "用户名和密码不能为空"
        if len(username) < 2:
            return False, "用户名至少需要2个字符"
        if len(password) < 4:
            return False, "密码至少需要4个字符"

        # 检查用户名是否已存在
        existing = (
            self.supabase.table("users")
            .select("id")
            .eq("username", username)
            .execute()
        )
        if existing.data:
            return False, "用户名已存在，请换一个"

        password_hash, salt = self._hash_password(password)
        user_id = uuid.uuid4().hex

        self.supabase.table("users").insert(
            {
                "id": user_id,
                "username": username,
                "password_hash": password_hash,
                "salt": salt,
                "created_at": _now_iso(),
                "profile": "{}",
            }
        ).execute()

        return True, user_id

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """用户登录验证。"""
        username = username.strip()
        if not username or not password:
            return False, "请输入用户名和密码"

        result = (
            self.supabase.table("users")
            .select("*")
            .eq("username", username)
            .execute()
        )

        if not result.data:
            return False, "用户名不存在"

        user = result.data[0]
        password_hash, _ = self._hash_password(password, user["salt"])

        if password_hash != user["password_hash"]:
            return False, "密码错误"

        return True, user["id"]

    def save_profile(self, user_id: str, profile: dict) -> bool:
        """保存用户档案。"""
        self.supabase.table("users").update(
            {"profile": json.dumps(profile, ensure_ascii=False)}
        ).eq("id", user_id).execute()
        return True

    def get_profile(self, user_id: str) -> dict:
        """获取用户档案。"""
        result = (
            self.supabase.table("users")
            .select("profile")
            .eq("id", user_id)
            .execute()
        )
        if result.data and result.data[0].get("profile"):
            return json.loads(result.data[0]["profile"])
        return {}

    def get_user(self, user_id: str) -> dict | None:
        """根据 user_id 获取用户信息。"""
        result = (
            self.supabase.table("users")
            .select("id, username, created_at")
            .eq("id", user_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
