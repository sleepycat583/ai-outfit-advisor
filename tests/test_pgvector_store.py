from __future__ import annotations

import pytest

from pgvector_store import PgVectorStore, VectorDocument

import config_data as config


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.rows = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_upsert_scopes_documents_by_user_and_source_kind():
    conn = FakeConnection()
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    store.upsert(
        [VectorDocument(doc_id="item-1", content="黑色外套", metadata={"item_id": "item-1"}, embedding=[0.1, 0.2])],
        source_kind="wardrobe",
    )

    query, params = conn.cursor_obj.calls[-1]
    assert "app_private.vector_documents" in query
    assert "source_kind" in query
    assert params[0:3] == ("wardrobe", "user-a", "item-1")
    assert conn.commits == 1


def test_search_rejects_cross_user_rows_and_returns_ranked_content():
    conn = FakeConnection()
    conn.cursor_obj.rows = [("doc-a", "用户A内容", {"owner": "a"}, 0.12)]
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    results = store.search([0.1, 0.2], source_kind="knowledge", limit=3)

    assert results == [{"id": "doc-a", "content": "用户A内容", "metadata": {"owner": "a"}, "distance": 0.12}]
    query, params = conn.cursor_obj.calls[-1]
    assert "user_id = %s" in query
    assert params == ("[0.1,0.2]", "knowledge", "user-a", "[0.1,0.2]", 3)


def test_upsert_rolls_back_when_database_write_fails():
    conn = FakeConnection()
    original_execute = conn.cursor_obj.execute

    def fail_execute(query, params=None):
        original_execute(query, params)
        raise RuntimeError("db unavailable")

    conn.cursor_obj.execute = fail_execute
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    with pytest.raises(RuntimeError, match="db unavailable"):
        store.upsert([VectorDocument("doc", "x", {}, [0.1])], source_kind="knowledge")

    assert conn.rollbacks == 1
    assert conn.commits == 0


def test_vector_rollout_flags_are_conservative_by_default(monkeypatch):
    monkeypatch.setattr(config, "VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(config, "VECTOR_DUAL_WRITE", False)
    monkeypatch.setattr(config, "VECTOR_SHADOW_QUERY", False)
    assert config.VECTOR_BACKEND == "chroma"
    assert config.VECTOR_DUAL_WRITE is False
    assert config.VECTOR_SHADOW_QUERY is False


def test_pgvector_migration_is_private_and_has_reversible_target():
    from pathlib import Path

    migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260913120000_pgvector_private.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "app_private.vector_documents" in migration
    assert "VECTOR(1024)" in migration
    assert "REVOKE ALL ON app_private.vector_documents" in migration
    assert "ON CONFLICT (source_kind, user_id, doc_id)" in migration or "PRIMARY KEY (source_kind, user_id, doc_id)" in migration


def test_wardrobe_dual_write_keeps_chroma_primary(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def add_texts(self, texts, metadatas, ids):
            self.added.append((texts, metadatas, ids))

    class Embedding:
        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class PgStore:
        def __init__(self):
            self.upserts = []

        def upsert(self, documents, *, source_kind):
            self.upserts.append((documents, source_kind))

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", True)
    monkeypatch.setattr(module.config, "VECTOR_SHADOW_QUERY", False)

    service = module.VectorWardrobeService(Embedding(), user_id="user-a")
    pg_store = PgStore()
    service._pgvector_store = pg_store
    service.add_items([("item-1", "黑色外套")])

    assert service.vector_store.added[0][2] == ["item-1"]
    assert pg_store.upserts[0][1] == "wardrobe"
    assert pg_store.upserts[0][0][0].doc_id == "item-1"


def test_wardrobe_pgvector_backend_reads_target_without_chroma(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def similarity_search(self, query, k):
            raise AssertionError("pgvector backend must not read Chroma")

    class Embedding:
        def embed_query(self, query):
            return [0.1, 0.2]

    class PgStore:
        def search(self, embedding, *, source_kind, limit):
            assert source_kind == "wardrobe"
            assert limit == 2
            return [{"id": "item-1", "content": "黑色外套", "metadata": {}, "distance": 0.1}]

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", False)
    monkeypatch.setattr(module.config, "VECTOR_SHADOW_QUERY", False)

    service = module.VectorWardrobeService(Embedding(), user_id="user-a")
    service._pgvector_store = PgStore()
    assert service.search("黑色", k=2) == ["黑色外套"]
