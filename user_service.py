import hashlib
import json
import os
import time
import uuid
from datetime import datetime

from supabase_config import get_supabase_client


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class UserService:
    """用户服务（Supabase PostgreSQL 持久化）

    Streamlit Cloud 使用临时文件系统，因此将用户数据存储在 Supabase。
    """

    def __init__(self, db_path: str | None = None):
        # db_path 参数保留用于向后兼容
        start_time = time.time()
        _ = db_path
        self.supabase = get_supabase_client()
        print(f"[PERF] UserService.__init__ took {time.time() - start_time:.3f}s", flush=True)

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
        """获取用户档案，并打印 Supabase 查询耗时。"""
        start_time = time.time()
        result = (
            self.supabase.table("users")
            .select("profile")
            .eq("id", user_id)
            .execute()
        )
        print(f"[PERF] UserService.get_profile took {time.time() - start_time:.3f}s", flush=True)
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
