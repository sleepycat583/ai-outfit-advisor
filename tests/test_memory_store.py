from __future__ import annotations

import pytest

import memory_store
from memory_store import MemoryNamespaceError, SupabaseMemoryStore, user_namespace
from langgraph.store.base import ListNamespacesOp
from langgraph.store.base import Item
from datetime import datetime, timezone


def test_user_namespace_is_explicit_and_rejects_injection():
    assert user_namespace("u-1") == ("user:u-1", "memory")
    with pytest.raises(MemoryNamespaceError):
        user_namespace("u:other")
    with pytest.raises(MemoryNamespaceError):
        user_namespace("u-1", "bad:category")


def test_store_rejects_non_user_namespace_before_database_access(monkeypatch):
    store = SupabaseMemoryStore(user_id="u-1")
    monkeypatch.setattr(store, "_connection", lambda: pytest.fail("database must not be opened"))

    with pytest.raises(MemoryNamespaceError):
        store.get(("public", "memory"), "key")


def test_store_requires_server_database_secret(monkeypatch):
    monkeypatch.setattr(memory_store, "get_database_url", lambda: None)
    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        SupabaseMemoryStore(user_id="u-1").get(user_namespace("u-1"), "key")


def test_store_rejects_unscoped_namespace_listing_before_database_access(monkeypatch):
    store = SupabaseMemoryStore(user_id="u-1")
    monkeypatch.setattr(store, "_connection", lambda: pytest.fail("database must not be opened"))

    with pytest.raises(MemoryNamespaceError):
        store.batch([ListNamespacesOp()])


def test_recall_always_includes_profile_and_limits_explicit_memories():
    class Store(SupabaseMemoryStore):
        def __init__(self):
            super().__init__(user_id="u-1")

        def search(self, namespace_prefix, /, **kwargs):
            category = namespace_prefix[1]
            item = Item(
                namespace=namespace_prefix,
                key=category,
                value={"category": category, "query": kwargs.get("query")},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return [item]

    recalled = Store().recall("u-1", "不穿高跟鞋", limit=5)

    assert [(item.key, item.value["query"]) for item in recalled] == [
        ("profile", None),
        ("memory", "不穿高跟鞋"),
    ]


def test_store_requires_bound_user_before_database_access(monkeypatch):
    with pytest.raises(TypeError):
        SupabaseMemoryStore()


def test_store_connection_does_not_fall_back_to_public_schema(monkeypatch):
    import types
    class Cursor:
        def __init__(self):
            self.statements = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, statement, params=None):
            self.statements.append(statement)
    class Conn:
        def __init__(self):
            self.cursor_obj = Cursor()
        def cursor(self):
            return self.cursor_obj
    conn = Conn()
    psycopg_module = types.ModuleType("psycopg")
    psycopg_module.connect = lambda *args, **kwargs: conn
    rows_module = types.ModuleType("psycopg.rows")
    rows_module.dict_row = object()
    monkeypatch.setattr(memory_store, "get_database_url", lambda: "postgres://test")
    monkeypatch.setitem(__import__("sys").modules, "psycopg", psycopg_module)
    monkeypatch.setitem(__import__("sys").modules, "psycopg.rows", rows_module)
    store = SupabaseMemoryStore(user_id="u-1")
    result = store._connection()
    assert result is conn
    assert '"app_private"' in conn.cursor_obj.statements[0]
    assert ", public" not in conn.cursor_obj.statements[0]
