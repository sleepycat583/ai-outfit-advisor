"""聊天记录持久化（Supabase PostgreSQL）

替代原有的本地 JSON 文件存储，解决 Streamlit Cloud 临时文件系统
导致的聊天记录丢失问题。
"""

import json
import time
from datetime import datetime
from typing import Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

from supabase_config import get_supabase_client


def get_history(session_id):
    """获取聊天历史实例（向后兼容的函数签名）。"""
    return FileChatMessageHistory(session_id)


class FileChatMessageHistory(BaseChatMessageHistory):
    """基于 Supabase 的聊天记录持久化。

    类名保留 "File" 以保持向后兼容，实际存储已迁移到 Supabase PostgreSQL。
    storage_path 参数保留用于向后兼容，不再使用。
    """

    def __init__(self, session_id: str, storage_path: str = ""):
        start_time = time.time()
        self.session_id = session_id
        self.supabase = get_supabase_client()
        # storage_path 保留用于向后兼容
        print(f"[PERF] FileChatMessageHistory.__init__ took {time.time() - start_time:.3f}s", flush=True)

    @property
    def messages(self) -> list[BaseMessage]:
        start_time = time.time()
        result = (
            self.supabase.table("chat_messages")
            .select("messages")
            .eq("session_id", self.session_id)
            .execute()
        )
        print(f"[PERF] FileChatMessageHistory.messages took {time.time() - start_time:.3f}s", flush=True)
        if result.data:
            return messages_from_dict(json.loads(result.data[0]["messages"]))
        return []

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """追加聊天记录，并打印读取与写入总耗时。"""
        start_time = time.time()
        new_dicts = [message_to_dict(msg) for msg in messages]

        # 读取现有消息
        result = (
            self.supabase.table("chat_messages")
            .select("messages")
            .eq("session_id", self.session_id)
            .execute()
        )

        if result.data:
            existing = json.loads(result.data[0]["messages"])
            existing.extend(new_dicts)
            self.supabase.table("chat_messages").update(
                {
                    "messages": json.dumps(existing, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            ).eq("session_id", self.session_id).execute()
        else:
            self.supabase.table("chat_messages").insert(
                {
                    "session_id": self.session_id,
                    "messages": json.dumps(new_dicts, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            ).execute()
        print(f"[PERF] FileChatMessageHistory.add_messages took {time.time() - start_time:.3f}s", flush=True)

    def clear(self) -> None:
        self.supabase.table("chat_messages").delete().eq(
            "session_id", self.session_id
        ).execute()
