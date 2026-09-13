"""异步长期记忆提取任务。

任务消息只包含用户/助手文本和不可变去重键；数据库连接与模型密钥永远不
进入队列 payload。队列使用 Supabase pgmq，任务收据和死信记录位于私有
``app_private`` schema。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from native_memory import _validate_schema
from supabase_config import get_database_url


_QUEUE_RE = re.compile(r"^[a-z0-9_-]+$")
_PRIVATE_SCHEMA = "app_private"
_QUEUE_NAME = "memory-extraction"


@dataclass(frozen=True)
class MemoryExtractionJob:
    job_id: str
    dedupe_key: str
    user_id: str
    conversation_id: str
    messages: list[dict[str, str]]


def build_dedupe_key(user_id: str, conversation_id: str, turn_id: str) -> str:
    """生成跨重试稳定且不泄露原文的任务幂等键。"""
    raw = "\x1f".join((user_id, conversation_id, turn_id)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def extract_candidate_messages(messages: Iterable[Any]) -> list[dict[str, str]]:
    """过滤系统提示、工具协议和空文本，只保留可供模型提取的对话。"""
    candidates: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, dict):
            role = str(message.get("role", "")).lower()
            content = message.get("content", "")
        else:
            role = str(getattr(message, "type", "")).lower()
            content = getattr(message, "content", "")
            role = {"human": "user", "ai": "assistant"}.get(role, role)
        if role not in {"user", "assistant"}:
            continue
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        content = str(content).strip()
        if content:
            candidates.append({"role": role, "content": content[:4000]})
    return candidates[-20:]


def sanitize_job_payload(job: MemoryExtractionJob) -> dict[str, Any]:
    """返回可安全放入 pgmq 的 JSON payload。"""
    return {
        "job_id": str(job.job_id),
        "dedupe_key": str(job.dedupe_key),
        "user_id": str(job.user_id),
        "conversation_id": str(job.conversation_id),
        "messages": extract_candidate_messages(job.messages),
    }


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: int = 15
    max_delay_seconds: int = 900

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须大于 0")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("重试延迟不能为负数")

    def delay_seconds(self, attempt: int) -> int:
        if attempt < 1:
            raise ValueError("attempt 必须从 1 开始")
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))

    def should_dead_letter(self, attempt: int) -> bool:
        return attempt >= self.max_attempts


class MemoryJobRepository:
    """Supabase pgmq 任务仓储，连接和表均只在服务端使用。"""

    def __init__(
        self,
        *,
        schema: str = "app_private",
        queue_name: str = "memory-extraction",
        retry_policy: RetryPolicy | None = None,
    ):
        self.schema = _validate_schema(schema)
        if self.schema != _PRIVATE_SCHEMA:
            raise ValueError("异步记忆队列仅支持 app_private schema")
        if not _QUEUE_RE.fullmatch(queue_name):
            raise ValueError("queue_name 必须是小写 pgmq 标识符")
        if queue_name != _QUEUE_NAME:
            raise ValueError("异步记忆队列仅支持 memory-extraction")
        self.queue_name = queue_name
        if retry_policy is None:
            try:
                import config_data
                max_attempts = config_data.MEMORY_JOB_MAX_ATTEMPTS
            except (ImportError, AttributeError, ValueError):
                max_attempts = int(os.getenv("MEMORY_JOB_MAX_ATTEMPTS", "5"))
            retry_policy = RetryPolicy(max_attempts=max_attempts)
        self.retry_policy = retry_policy

    def _connection(self):
        url = (get_database_url() or "").strip()
        if not url:
            raise RuntimeError("未配置 SUPABASE_DB_URL，无法访问记忆队列")
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        with conn.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{self.schema}"')
        return conn

    def enqueue(self, job: MemoryExtractionJob) -> bool:
        payload = sanitize_job_payload(job)
        conn = self._connection()
        try:
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO memory_job_receipts
                           (job_id, dedupe_key, user_id, conversation_id, payload, status)
                           VALUES (%s, %s, %s, %s, %s::jsonb, 'queued')
                           ON CONFLICT (dedupe_key) DO NOTHING
                           RETURNING job_id""",
                        (
                            job.job_id,
                            job.dedupe_key,
                            job.user_id,
                            job.conversation_id,
                            json.dumps(payload, ensure_ascii=False),
                        ),
                    )
                    inserted = cursor.fetchone()
                    if not inserted:
                        return False
                    cursor.execute(
                        "SELECT pgmq.send(%s, %s::jsonb, 0) AS msg_id",
                        (self.queue_name, json.dumps(payload, ensure_ascii=False)),
                    )
                    msg_id = cursor.fetchone()["msg_id"]
                    cursor.execute(
                        "UPDATE memory_job_receipts SET msg_id = %s WHERE job_id = %s",
                        (msg_id, job.job_id),
                    )
            return True
        finally:
            conn.close()

    def claim(self, *, limit: int = 10, visibility_timeout: int = 120) -> list[dict[str, Any]]:
        if limit < 1 or visibility_timeout < 1:
            raise ValueError("limit 和 visibility_timeout 必须大于 0")
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM pgmq.read(%s, %s, %s)",
                    (self.queue_name, visibility_timeout, limit),
                )
                return list(cursor.fetchall())
        finally:
            conn.close()

    def ack(self, msg_id: int) -> bool:
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pgmq.delete(%s, %s) AS deleted", (self.queue_name, msg_id))
                return bool(cursor.fetchone()["deleted"])
        finally:
            conn.close()

    def fail(self, *, msg_id: int, job_id: str, error: str, attempt: int) -> bool:
        """记录失败；达到阈值后归档消息并写入死信表。"""
        conn = self._connection()
        try:
            with conn.transaction():
                with conn.cursor() as cursor:
                    dead = self.retry_policy.should_dead_letter(attempt)
                    cursor.execute(
                        """UPDATE memory_job_receipts
                           SET status = %s, attempts = %s, last_error = %s, updated_at = now()
                           WHERE job_id = %s""",
                        ("dead_letter" if dead else "retrying", attempt, str(error)[:2000], job_id),
                    )
                    if dead:
                        cursor.execute("SELECT pgmq.archive(%s, %s)", (self.queue_name, msg_id))
                        cursor.execute(
                            """INSERT INTO memory_dead_letters
                               (job_id, msg_id, error, attempts)
                               VALUES (%s, %s, %s, %s)
                               ON CONFLICT (job_id) DO UPDATE SET
                                 error = EXCLUDED.error, attempts = EXCLUDED.attempts""",
                            (job_id, msg_id, str(error)[:2000], attempt),
                        )
                    else:
                        cursor.execute(
                            "SELECT pgmq.set_vt(%s, %s, %s)",
                            (self.queue_name, msg_id, self.retry_policy.delay_seconds(attempt)),
                        )
            return dead
        finally:
            conn.close()


def make_turn_job(
    *, user_id: str, conversation_id: str, turn_id: str, messages: Iterable[Any]
) -> MemoryExtractionJob | None:
    candidates = extract_candidate_messages(messages)
    if not candidates:
        return None
    dedupe_key = build_dedupe_key(user_id, conversation_id, turn_id)
    return MemoryExtractionJob(
        job_id=dedupe_key,
        dedupe_key=dedupe_key,
        user_id=user_id,
        conversation_id=conversation_id,
        messages=candidates,
    )
