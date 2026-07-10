"""聊天记录持久化（Supabase PostgreSQL）

替代原有的本地 JSON 文件存储，解决 Streamlit Cloud 临时文件系统
导致的聊天记录丢失问题。
"""

import json
import time
from datetime import datetime
from typing import Callable, Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, message_to_dict, messages_from_dict

import config_data as config
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

    def _fetch_row(self) -> dict | None:
        """读取当前会话的原始存储行。

        返回值:
            chat_messages 表中当前 session_id 对应的首行；不存在时返回 None。
        """
        result = (
            self.supabase.table("chat_messages")
            .select("messages, recent_messages, summary, summary_message_count")
            .eq("session_id", self.session_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None

    def _load_json_messages(self, raw_value: str | None) -> list[BaseMessage]:
        """把 JSON 字符串安全转换为 LangChain message 列表。"""
        if not raw_value:
            return []
        try:
            return messages_from_dict(json.loads(raw_value))
        except Exception:
            return []

    def _serialize_messages(self, messages: Sequence[BaseMessage]) -> str:
        """把 LangChain message 列表序列化成 JSON 字符串。"""
        return json.dumps([message_to_dict(msg) for msg in messages], ensure_ascii=False)

    def _build_agent_messages(self, summary: str, recent_messages: list[BaseMessage]) -> list[BaseMessage]:
        """组装给 Agent 使用的历史消息。

        为什么这样做：UI 需要恢复全量原始聊天记录，而 Agent 只需要“摘要 + 最近 N 轮”。
        两者拆开后，既能避免上下文无限增长，也能保留未来导出完整聊天记录的空间。
        """
        agent_messages: list[BaseMessage] = []
        if summary:
            # 说明：分批摘要尚未处理完全部 overflow 时，Agent 看到的是“当前摘要 + 最近 N 轮”。
            # 这是预期内的过渡状态，早期剩余历史会在后续轮次继续滚动吸收到 summary 里。
            agent_messages.append(SystemMessage(content=f"以下是更早历史对话的摘要：\n{summary}"))
        agent_messages.extend(recent_messages)
        return agent_messages

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

    def get_agent_messages(self) -> list[BaseMessage]:
        """返回给 Agent 使用的历史消息。

        返回值:
            由 summary 和 recent_messages 组装出的历史消息列表；字段不存在时降级到全量 messages。
        """
        try:
            row = self._fetch_row()
        except Exception:
            return self.messages
        if not row:
            return []

        summary = (row.get("summary") or "").strip()
        recent_messages = self._load_json_messages(row.get("recent_messages"))
        if recent_messages or summary:
            return self._build_agent_messages(summary, recent_messages)
        return self._load_json_messages(row.get("messages"))

    def add_messages(
        self,
        messages: Sequence[BaseMessage],
    ) -> None:
        """追加聊天记录，并快速维护 messages 与 recent_messages。

        参数:
            messages: 本轮新增消息，通常是 1 条 HumanMessage + 1 条 AIMessage。
        返回值:
            无返回值，直接更新 Supabase 中当前会话的历史记录。
        """
        start_time = time.time()
        row = None
        try:
            row = self._fetch_row()
        except Exception as exc:
            print(f"[WARN] 新记忆字段读取失败，已降级为旧版聊天历史写入：{exc}", flush=True)

        existing_messages = self._load_json_messages(row.get("messages")) if row else []
        summary = (row.get("summary") or "").strip() if row else ""
        summary_message_count = int(row.get("summary_message_count") or 0) if row else 0

        full_messages = [*existing_messages, *list(messages)]
        max_recent_messages = int(config.chat_history_max_rounds) * 2
        recent_messages = full_messages[-max_recent_messages:] if max_recent_messages > 0 else full_messages

        payload = {
            "messages": self._serialize_messages(full_messages),
            "recent_messages": self._serialize_messages(recent_messages),
            "summary": summary,
            "summary_message_count": summary_message_count,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        if row:
            self.supabase.table("chat_messages").update(payload).eq(
                "session_id", self.session_id
            ).execute()
        else:
            self.supabase.table("chat_messages").insert(
                {
                    "session_id": self.session_id,
                    **payload,
                }
            ).execute()
        print(f"[PERF] FileChatMessageHistory.add_messages took {time.time() - start_time:.3f}s", flush=True)

    def maybe_update_summary(
        self,
        summary_updater: Callable[[str, list[BaseMessage]], str],
    ) -> bool:
        """按低频策略检查并更新摘要。

        参数:
            summary_updater: 摘要生成函数，接收旧摘要和待吸收的旧消息批次。
        返回值:
            本次是否实际触发了摘要更新。
        """
        start_time = time.time()
        row = self._fetch_row()
        if not row:
            return False

        full_messages = self._load_json_messages(row.get("messages"))
        summary = (row.get("summary") or "").strip()
        summary_message_count = int(row.get("summary_message_count") or 0)
        max_recent_messages = int(config.chat_history_max_rounds) * 2
        recent_messages = self._load_json_messages(row.get("recent_messages"))
        if not recent_messages:
            recent_messages = full_messages[-max_recent_messages:] if max_recent_messages > 0 else full_messages

        overflow_end = max(0, len(full_messages) - len(recent_messages))
        remaining_overflow = full_messages[summary_message_count:overflow_end]
        interval_message_limit = int(config.chat_history_summary_interval_rounds) * 2
        if len(remaining_overflow) < interval_message_limit:
            return False

        try:
            summary = summary_updater(summary, remaining_overflow)
        except Exception as exc:
            print(f"[WARN] 聊天历史摘要生成失败，已保留旧摘要：{exc}", flush=True)
            return False

        summary_message_count += len(remaining_overflow)
        self.supabase.table("chat_messages").update(
            {
                "summary": summary,
                "summary_message_count": summary_message_count,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        ).eq("session_id", self.session_id).execute()
        print(f"[PERF] FileChatMessageHistory.maybe_update_summary took {time.time() - start_time:.3f}s", flush=True)
        return True

    def clear(self) -> None:
        self.supabase.table("chat_messages").delete().eq(
            "session_id", self.session_id
        ).execute()
