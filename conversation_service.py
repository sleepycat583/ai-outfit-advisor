"""多会话注册与归属校验。

会话元数据位于 ``app_private.conversations``，通过服务端 PostgreSQL 连接
访问；匿名/前端 Supabase client 永远不会直接读取该表。没有配置数据库连接
串时，服务继续使用稳定的 legacy 会话 id，便于灰度回滚。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from supabase_config import get_database_url


class ConversationOwnershipError(PermissionError):
    """会话不属于当前用户。"""


class ConversationRepository:
    def __init__(self, *, schema: str = "app_private"):
        if not schema or not schema.replace("_", "").isalnum() or not schema[0].isalpha():
            raise ValueError("invalid private schema")
        self.schema = schema

    @staticmethod
    def legacy_id(user_id: str) -> str:
        return f"legacy:{user_id}"

    @staticmethod
    def legacy_session_id(conversation_id: str) -> str:
        """返回旧 ``chat_messages.session_id``，供迁移双写/回滚使用。"""
        if conversation_id.startswith("legacy:"):
            legacy_value = conversation_id[len("legacy:") :]
            if legacy_value.startswith("chat_session_"):
                return legacy_value
            return f"chat_session_{legacy_value}"
        return conversation_id

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    @contextmanager
    def _connection(self) -> Iterator[object]:
        conn_string = get_database_url()
        if not conn_string:
            yield None
            return
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(conn_string, autocommit=True, row_factory=dict_row)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{self.schema}", public')
            yield conn
        finally:
            conn.close()

    def ensure(self, user_id: str, conversation_id: str | None = None) -> str:
        """创建或验证会话，并返回可直接用作 thread_id 的值。"""
        if not user_id:
            raise ValueError("user_id 不能为空")
        conversation_id = conversation_id or self.legacy_id(user_id)
        with self._connection() as conn:
            if conn is None:
                # Legacy mode has no server DB connection.  The deterministic id
                # still prevents one user's default thread from being reused by
                # another user in the UI session state.
                return conversation_id
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (conversation_id, user_id, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (conversation_id) DO UPDATE SET updated_at = now()
                    WHERE conversations.user_id = EXCLUDED.user_id
                    RETURNING user_id
                    """,
                    (conversation_id, user_id),
                )
                row = cursor.fetchone()
                if not row or row["user_id"] != user_id:
                    raise ConversationOwnershipError("conversation_id 不属于当前用户")
        return conversation_id

    def list_for_user(self, user_id: str) -> list[dict]:
        with self._connection() as conn:
            if conn is None:
                return [{"conversation_id": self.legacy_id(user_id), "user_id": user_id}]
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT conversation_id, user_id, title, created_at, updated_at
                       FROM conversations WHERE user_id = %s
                       ORDER BY updated_at DESC""",
                    (user_id,),
                )
                return list(cursor.fetchall())

    def delete_for_user(self, user_id: str, conversation_id: str) -> bool:
        """删除会话元数据；长期记忆由独立服务管理，不在此处级联删除。"""
        with self._connection() as conn:
            if conn is None:
                return False
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM conversations WHERE conversation_id = %s AND user_id = %s",
                    (conversation_id, user_id),
                )
                return cursor.rowcount > 0
