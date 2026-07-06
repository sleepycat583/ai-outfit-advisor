import hashlib
import json
import os
import uuid
from datetime import datetime

from postgrest.exceptions import APIError

from supabase_config import get_supabase_client


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class UserService:
    """用户服务（Supabase PostgreSQL 持久化）

    Streamlit Cloud 使用临时文件系统，因此将用户数据存储在 Supabase。
    """

    def __init__(self, db_path: str | None = None):
        # db_path 参数保留用于向后兼容
        _ = db_path
        self.supabase = get_supabase_client()

    def _format_supabase_error(self, exc: Exception, action: str) -> str:
        """将 Supabase/PostgREST 异常转换为面向用户的可读提示。

        参数:
            exc: 原始异常对象，通常是 postgrest.exceptions.APIError。
            action: 当前执行的业务动作，例如“登录”“注册”“保存用户档案”。

        返回:
            适合在前端直接展示的中文错误说明。
        """
        if not isinstance(exc, APIError):
            return f"{action}失败，请稍后重试"

        message = str(getattr(exc, "message", "") or "")
        details = str(getattr(exc, "details", "") or "")
        hint = str(getattr(exc, "hint", "") or "")
        code = str(getattr(exc, "code", "") or "")
        raw_text = " ".join(part for part in [message, details, hint, code] if part).lower()

        # 业务规则：这里优先把部署期最常见的 Supabase 配置问题翻译成可执行提示，避免 Streamlit Cloud 直接展示脱敏异常。
        if "relation" in raw_text and "users" in raw_text:
            return "登录失败：Supabase 中不存在 users 表。请先在 SQL Editor 执行 README 里的建表语句。"
        if "password_hash" in raw_text or "salt" in raw_text or "profile" in raw_text:
            return "登录失败：users 表字段不完整。请检查是否已按 README 创建 username、password_hash、salt、profile 等字段。"
        if "permission denied" in raw_text or "row-level security" in raw_text or code == "42501":
            return "登录失败：Supabase 权限策略阻止了 users 表访问。请检查 RLS 策略，或确认当前使用的 SUPABASE_KEY 是否具备查询 users 表的权限。"
        if "invalid api key" in raw_text or "jwt" in raw_text or code in {"401", "403", "PGRST301"}:
            return "登录失败：Supabase 密钥无效或没有权限。请检查 Streamlit Secrets 中的 SUPABASE_KEY 是否填写正确。"

        return f"{action}失败：Supabase 接口返回异常，请检查表结构、RLS 策略和 Secrets 配置"

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
        try:
            existing = (
                self.supabase.table("users")
                .select("id")
                .eq("username", username)
                .execute()
            )
        except Exception as exc:
            return False, self._format_supabase_error(exc, "注册")
        if existing.data:
            return False, "用户名已存在，请换一个"

        password_hash, salt = self._hash_password(password)
        user_id = uuid.uuid4().hex

        try:
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
        except Exception as exc:
            return False, self._format_supabase_error(exc, "注册")

        return True, user_id

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """用户登录验证。

        参数:
            username: 用户输入的登录名。
            password: 用户输入的明文密码。

        返回:
            (是否成功, user_id 或错误提示)。
        """
        username = username.strip()
        if not username or not password:
            return False, "请输入用户名和密码"

        try:
            result = (
                self.supabase.table("users")
                .select("*")
                .eq("username", username)
                .execute()
            )
        except Exception as exc:
            return False, self._format_supabase_error(exc, "登录")

        if not result.data:
            return False, "用户名不存在"

        user = result.data[0]
        password_hash, _ = self._hash_password(password, user["salt"])

        if password_hash != user["password_hash"]:
            return False, "密码错误"

        return True, user["id"]

    def save_profile(self, user_id: str, profile: dict) -> bool:
        """保存用户档案。"""
        try:
            self.supabase.table("users").update(
                {"profile": json.dumps(profile, ensure_ascii=False)}
            ).eq("id", user_id).execute()
            return True
        except Exception:
            return False

    def get_profile(self, user_id: str) -> dict:
        """获取用户档案。"""
        try:
            result = (
                self.supabase.table("users")
                .select("profile")
                .eq("id", user_id)
                .execute()
            )
        except Exception:
            return {}
        if result.data and result.data[0].get("profile"):
            return json.loads(result.data[0]["profile"])
        return {}

    def get_user(self, user_id: str) -> dict | None:
        """根据 user_id 获取用户信息。"""
        try:
            result = (
                self.supabase.table("users")
                .select("id, username, created_at")
                .eq("id", user_id)
                .execute()
            )
        except Exception:
            return None
        if result.data:
            return result.data[0]
        return None
