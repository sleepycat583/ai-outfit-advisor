"""服务端 Supabase 长期记忆适配器。

实现 LangGraph 官方 BaseStore 协议，但通过私有 PostgreSQL schema 访问，
不依赖 anon Data API。namespace 的第一段绑定用户，阻断跨用户读写；本阶段
提供结构化 KV 与前缀/文本检索，语义向量索引留到阶段六。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Iterable

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    PutOp,
    SearchItem,
    SearchOp,
)

from native_memory import _validate_schema
from supabase_config import get_database_url


_USER_NAMESPACE_RE = re.compile(r"^user:([^:]+)$")


class MemoryNamespaceError(ValueError):
    """长期记忆 namespace 不符合用户隔离约束。"""


def user_namespace(user_id: str, category: str = "memory") -> tuple[str, ...]:
    if not user_id or ":" in user_id:
        raise MemoryNamespaceError("user_id 不能为空且不能包含 ':'")
    if not category or ":" in category:
        raise MemoryNamespaceError("memory category 非法")
    return (f"user:{user_id}", category)


class SupabaseMemoryStore(BaseStore):
    """基于 psycopg 的同步长期记忆 store。"""

    def __init__(self, *, user_id: str, schema: str = "app_private"):
        if not user_id or ":" in user_id:
            raise MemoryNamespaceError("user_id 不能为空且不能包含 ':'")
        self.user_id = user_id
        self.schema = _validate_schema(schema)

    def _connection(self):
        conn_string = (get_database_url() or "").strip()
        if not conn_string:
            raise RuntimeError("未配置 SUPABASE_DB_URL，无法访问长期记忆")
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(conn_string, autocommit=True, row_factory=dict_row)
        with conn.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{self.schema}"')
        return conn

    def _validate_namespace(self, namespace: tuple[str, ...]) -> None:
        if not namespace or not isinstance(namespace[0], str):
            raise MemoryNamespaceError("长期记忆必须绑定 user namespace")
        if not _USER_NAMESPACE_RE.fullmatch(namespace[0]):
            raise MemoryNamespaceError("namespace 第一段必须是 user:<user_id>")
        if namespace[0] != f"user:{self.user_id}":
            raise MemoryNamespaceError("namespace 不属于当前用户")

    @staticmethod
    def _to_item(row: dict[str, Any], result_type=Item):
        kwargs = {
            "namespace": tuple(row["namespace"]),
            "key": row["key"],
            "value": row["value"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if result_type is SearchItem:
            kwargs["score"] = row.get("score")
        return result_type(**kwargs)

    def batch(self, ops: Iterable[Any]) -> list[Any]:
        operations = list(ops)
        for op in operations:
            if isinstance(op, (GetOp, PutOp)):
                self._validate_namespace(op.namespace)
            elif isinstance(op, SearchOp):
                self._validate_namespace(op.namespace_prefix)
            elif isinstance(op, ListNamespacesOp):
                has_user_prefix = False
                for condition in op.match_conditions or ():
                    if condition.match_type == "prefix" and condition.path:
                        self._validate_namespace(tuple(condition.path))
                        has_user_prefix = True
                if not has_user_prefix:
                    raise MemoryNamespaceError("列举长期记忆必须提供 user:<user_id> 前缀")
        results: list[Any] = []
        conn = self._connection()
        try:
            # A LangGraph batch is an atomic unit: a failed later Put must not
            # leave earlier writes visible.  The connection otherwise uses
            # autocommit for cheap single-operation calls.
            with conn.transaction():
                with conn.cursor() as cursor:
                    for op in operations:
                        if isinstance(op, GetOp):
                            cursor.execute(
                                """SELECT namespace, key, value, created_at, updated_at
                                   FROM memory_items
                                   WHERE namespace = %s AND key = %s""",
                                (list(op.namespace), op.key),
                            )
                            row = cursor.fetchone()
                            results.append(self._to_item(row) if row else None)
                        elif isinstance(op, PutOp):
                            if op.value is None:
                                cursor.execute(
                                    "DELETE FROM memory_items WHERE namespace = %s AND key = %s",
                                    (list(op.namespace), op.key),
                                )
                            else:
                                cursor.execute(
                                    """INSERT INTO memory_items (namespace, key, value)
                                       VALUES (%s, %s, %s::jsonb)
                                       ON CONFLICT (namespace, key) DO UPDATE SET
                                         value = EXCLUDED.value, updated_at = now()""",
                                    (list(op.namespace), op.key, json.dumps(op.value, ensure_ascii=False)),
                                )
                            results.append(None)
                        elif isinstance(op, SearchOp):
                            prefix = list(op.namespace_prefix)
                            cursor.execute(
                                """SELECT namespace, key, value, created_at, updated_at
                                   FROM memory_items
                                   WHERE namespace[1:%s] = %s::text[]
                                   ORDER BY updated_at DESC""",
                                (len(prefix), prefix),
                            )
                            rows = cursor.fetchall()
                            if op.filter:
                                rows = [
                                    row for row in rows
                                    if isinstance(row["value"], dict)
                                    and all(row["value"].get(k) == v for k, v in op.filter.items())
                                ]
                            if op.query:
                                query = op.query.casefold()
                                rows = [
                                    row for row in rows
                                    if query in json.dumps(row["value"], ensure_ascii=False).casefold()
                                ]
                            results.append(
                                [
                                    self._to_item(row, SearchItem)
                                    for row in rows[op.offset : op.offset + op.limit]
                                ]
                            )
                        elif isinstance(op, ListNamespacesOp):
                            conditions = tuple(op.match_conditions or ())
                            prefix = next(
                                (tuple(condition.path) for condition in conditions if condition.match_type == "prefix"),
                                (),
                            )
                            cursor.execute(
                                """SELECT DISTINCT namespace FROM memory_items
                                   WHERE namespace[1:%s] = %s::text[]
                                   ORDER BY namespace""",
                                (len(prefix), list(prefix)),
                            )
                            namespaces = [tuple(row["namespace"]) for row in cursor.fetchall()]
                            if any(condition.match_type == "suffix" for condition in conditions):
                                suffixes = [tuple(condition.path) for condition in conditions if condition.match_type == "suffix"]
                                namespaces = [ns for ns in namespaces if any(ns[-len(suffix):] == suffix for suffix in suffixes)]
                            if op.max_depth is not None:
                                namespaces = [ns[: op.max_depth] for ns in namespaces]
                                namespaces = list(dict.fromkeys(namespaces))
                            results.append(namespaces[op.offset : op.offset + op.limit])
                        else:
                            raise TypeError(f"unsupported store operation: {type(op)!r}")
            return results
        finally:
            conn.close()

    async def abatch(self, ops: Iterable[Any]) -> list[Any]:
        return await asyncio.to_thread(self.batch, ops)

    def _assert_user(self, user_id: str) -> None:
        if user_id != self.user_id:
            raise MemoryNamespaceError("user_id 不属于当前 memory store")

    def remember(self, user_id: str, key: str, value: dict[str, Any], *, category: str = "memory") -> None:
        self._assert_user(user_id)
        self.put(user_namespace(user_id, category), key, value)

    def forget(self, user_id: str, key: str, *, category: str = "memory") -> None:
        self._assert_user(user_id)
        self.delete(user_namespace(user_id, category), key)

    def list_for_user(self, user_id: str, *, category: str = "memory", limit: int = 100) -> list[Item]:
        self._assert_user(user_id)
        return self.search(user_namespace(user_id, category), limit=limit)

    def recall(self, user_id: str, query: str, *, limit: int = 5) -> list[Item]:
        """跨会话读取当前用户的结构化档案和显式记忆。"""
        self._assert_user(user_id)
        profile = self.search(user_namespace(user_id, "profile"), limit=1)
        memories = self.search(user_namespace(user_id, "memory"), query=query, limit=limit)
        return (profile + memories)[:limit]
