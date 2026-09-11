"""LangGraph 原生 checkpoint 运行时。

该模块只在服务端配置 ``SUPABASE_DB_URL`` 且启用 native backend 时创建
PostgreSQL 连接。连接的 ``search_path`` 固定到私有 schema，避免 checkpoint
表被 Supabase Data API 暴露。调用方持有运行时对象的生命周期，并在进程
退出时调用 :meth:`close`。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

import config_data as config
from supabase_config import get_database_url

if False:  # pragma: no cover - only for static type checkers
    from langgraph.checkpoint.postgres import PostgresSaver


_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _validate_schema(schema: str) -> str:
    schema = (schema or "").strip().lower()
    if not _SCHEMA_RE.fullmatch(schema):
        raise ValueError("MEMORY_PRIVATE_SCHEMA 必须是合法的 PostgreSQL 标识符")
    return schema


@dataclass
class NativeMemoryRuntime:
    """持有一个 PostgresSaver 及其底层连接。"""

    connection: object
    checkpointer: object
    user_id: str = ""

    @classmethod
    def connect(cls, user_id: str = "") -> "NativeMemoryRuntime":
        conn_string = (get_database_url() or "").strip()
        if not conn_string:
            raise RuntimeError("未配置 SUPABASE_DB_URL，无法启用原生 PostgreSQL memory")

        # psycopg is an optional runtime dependency for legacy deployments.
        import psycopg
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres import PostgresSaver

        schema = _validate_schema(config.MEMORY_PRIVATE_SCHEMA)
        connection = psycopg.connect(
            conn_string,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}", public')
            checkpointer = PostgresSaver(connection)
            # setup() is idempotent and applies the upstream saver migrations.
            # It must run once per database before the graph starts serving traffic.
            checkpointer.setup()
            return cls(connection=connection, checkpointer=checkpointer, user_id=user_id)
        except Exception:
            connection.close()
            raise

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if close:
            close()

    def delete_thread(self, conversation_id: str) -> None:
        """显式删除一个会话的 checkpoint；不触碰长期记忆。"""
        self.checkpointer.delete_thread(conversation_id)


def native_memory_requested() -> bool:
    return config.MEMORY_BACKEND == "native" or config.MEMORY_DUAL_WRITE


def delete_native_thread(conversation_id: str) -> bool:
    """在没有已初始化 RagService 时显式删除 checkpoint。"""
    try:
        runtime = NativeMemoryRuntime.connect()
    except Exception as exc:
        print(f"[WARN] native checkpoint delete skipped: {exc}", flush=True)
        return False
    try:
        runtime.delete_thread(conversation_id)
        return True
    finally:
        runtime.close()


def load_native_thread_messages(conversation_id: str) -> Optional[list[object]]:
    """读取一个 native thread 的已恢复消息，供 UI 在进程重启后展示。

    ``None`` 表示 native 存储不可用，调用方应降级读取 legacy transcript；
    空列表表示 native 存储可用但该会话尚无 checkpoint。只返回对用户可见的
    Human/AI 消息，避免把动态系统提示和工具协议渲染到聊天界面。
    """
    try:
        runtime = NativeMemoryRuntime.connect()
    except Exception as exc:
        print(f"[WARN] native checkpoint history read skipped: {exc}", flush=True)
        return None
    try:
        checkpoint_tuple = runtime.checkpointer.get_tuple(
            {"configurable": {"thread_id": conversation_id}}
        )
        if checkpoint_tuple is None:
            return []
        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", [])
        from langchain_core.messages import AIMessage, HumanMessage

        return [message for message in messages if isinstance(message, (HumanMessage, AIMessage))]
    except Exception as exc:
        print(f"[WARN] native checkpoint history read failed: {exc}", flush=True)
        return None
    finally:
        runtime.close()
