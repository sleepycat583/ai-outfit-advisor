from __future__ import annotations

import pytest

from pgvector_store import VECTOR_DIMENSION, PgVectorStore, VectorDocument

import config_data as config


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.rows = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else (0,)

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
        [VectorDocument(doc_id="item-1", content="黑色外套", metadata={"item_id": "item-1"}, embedding=[0.1] * VECTOR_DIMENSION)],
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

    results = store.search([0.1] * VECTOR_DIMENSION, source_kind="knowledge", limit=3)

    assert results == [{"id": "doc-a", "content": "用户A内容", "metadata": {"owner": "a"}, "distance": 0.12}]
    query, params = conn.cursor_obj.calls[-1]
    assert "user_id = %s" in query
    assert params[1:3] == ("knowledge", "user-a")
    assert params[-1] == 3


def test_upsert_rolls_back_when_database_write_fails():
    conn = FakeConnection()
    original_execute = conn.cursor_obj.execute

    def fail_execute(query, params=None):
        original_execute(query, params)
        raise RuntimeError("db unavailable")

    conn.cursor_obj.execute = fail_execute
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    with pytest.raises(RuntimeError, match="db unavailable"):
        store.upsert([VectorDocument("doc", "x", {}, [0.1] * VECTOR_DIMENSION)], source_kind="knowledge")

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
    assert "WITH SCHEMA extensions" in migration
    assert "extensions.vector(1024)" in migration
    assert "app_private.vector_documents" in migration
    assert "extensions.vector(1024)" in migration
    assert "REVOKE ALL ON app_private.vector_documents" in migration
    assert "ON CONFLICT (source_kind, user_id, doc_id)" in migration or "PRIMARY KEY (source_kind, user_id, doc_id)" in migration


def test_vector_dimension_mismatch_is_rejected_before_database_write():
    conn = FakeConnection()
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    with pytest.raises(ValueError, match="1024"):
        store.upsert([VectorDocument("doc", "x", {}, [0.1])], source_kind="knowledge")

    assert conn.cursor_obj.calls == []
    assert conn.rollbacks == 1


def test_pgvector_failure_is_persisted_in_private_sync_outbox():
    conn = FakeConnection()
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    store.record_sync_failure(
        source_kind="wardrobe",
        operation="upsert",
        doc_id="item-1",
        payload={"content": "黑色外套"},
        error=RuntimeError("pg unavailable"),
    )

    query, params = conn.cursor_obj.calls[-1]
    assert "app_private.vector_sync_outbox" in query
    assert params[:4] == ("wardrobe", "user-a", "upsert", "item-1")
    assert conn.commits == 1


def test_list_documents_is_user_scoped():
    conn = FakeConnection()
    conn.cursor_obj.rows = [("doc-a", "内容", {"source": "a"})]
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")
    assert store.list_documents(source_kind="knowledge") == [{"id": "doc-a", "content": "内容", "metadata": {"source": "a"}}]
    assert conn.cursor_obj.calls[-1][1] == ("knowledge", "user-a")


def test_outbox_event_state_machine_uses_lease_and_latest_operation():
    conn = FakeConnection()
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")

    store.claim_sync_events(limit=2, lease_seconds=30)
    claim_query, claim_params = conn.cursor_obj.calls[-1]
    assert "FOR UPDATE SKIP LOCKED" in claim_query
    assert claim_params == (2, 30)

    store.complete_sync_event(7, "lease-token")
    complete_query, complete_params = conn.cursor_obj.calls[-1]
    assert "status = 'succeeded'" in complete_query
    assert complete_params == (7, "lease-token")

    store.fail_sync_event(7, "lease-token", RuntimeError("temporary"), max_attempts=3)
    fail_query, fail_params = conn.cursor_obj.calls[-1]
    assert "status = CASE" in fail_query
    assert fail_params == (3, "temporary", 7, "lease-token")


def test_count_is_user_scoped():
    conn = FakeConnection()
    conn.cursor_obj.rows = [(4,)]
    store = PgVectorStore(lambda: conn, embedding=object(), user_id="user-a")
    assert store.count(source_kind="knowledge") == 4
    assert conn.cursor_obj.calls[-1][1] == ("knowledge", "user-a")


def test_outbox_worker_acknowledges_only_after_target_write():
    from vector_sync_worker import process_event

    class Store:
        embedding = object()

        def upsert(self, documents, *, source_kind):
            assert documents[0].content == "内容"
            assert source_kind == "knowledge"

        def complete_sync_event(self, event_id, lease_token):
            assert (event_id, lease_token) == (7, "lease")
            return True

        def fail_sync_event(self, *args, **kwargs):
            raise AssertionError("success path must not fail")

    event = {"id": 7, "lease_token": "lease", "source_kind": "knowledge", "operation": "upsert", "doc_id": "doc", "payload": {"content": "内容", "metadata": {}, "embedding": [0.1] * VECTOR_DIMENSION}}
    assert process_event(Store(), event) is True


def test_wardrobe_dual_write_keeps_chroma_primary(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def add_texts(self, texts, metadatas, ids):
            self.added.append((texts, metadatas, ids))

    class Embedding:
        def embed_documents(self, texts):
            return [[0.1] * VECTOR_DIMENSION for _ in texts]

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


def test_shadow_query_does_not_enable_pgvector_dual_write(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def add_texts(self, texts, metadatas, ids):
            self.added.append(ids)

    class Embedding:
        def embed_documents(self, texts):
            raise AssertionError("shadow-only mode must not embed writes")

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", False)
    monkeypatch.setattr(module.config, "VECTOR_SHADOW_QUERY", True)
    service = module.VectorWardrobeService(Embedding(), user_id="user-a")

    service.add_items([("item-1", "黑色外套")])
    assert service.vector_store.added == [["item-1"]]
    assert service._pgvector_store is None


def test_pgvector_backend_with_dual_write_keeps_chroma_rollback_copy(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def add_texts(self, texts, metadatas, ids):
            self.added.append(ids)

    class Embedding:
        def embed_documents(self, texts):
            return [[0.1] * VECTOR_DIMENSION for _ in texts]

    class PgStore:
        def upsert(self, documents, *, source_kind):
            assert source_kind == "wardrobe"

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", True)
    monkeypatch.setattr(module.config, "VECTOR_SHADOW_QUERY", False)
    service = module.VectorWardrobeService(Embedding(), user_id="user-a")
    service._pgvector_store = PgStore()

    service.add_items([("item-1", "黑色外套")])
    assert service.vector_store.added == [["item-1"]]


def test_wardrobe_dual_write_failure_is_recorded_for_retry(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            self.added = []

        def add_texts(self, texts, metadatas, ids):
            self.added.append(ids)

    class Embedding:
        def embed_documents(self, texts):
            return [[0.1] * VECTOR_DIMENSION for _ in texts]

    class PgStore:
        def upsert(self, documents, *, source_kind):
            raise RuntimeError("pg unavailable")

        def record_sync_failure(self, **kwargs):
            self.failure = kwargs

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", True)
    monkeypatch.setattr(module.config, "VECTOR_SHADOW_QUERY", False)
    service = module.VectorWardrobeService(Embedding(), user_id="user-a")
    pg_store = PgStore()
    service._pgvector_store = pg_store

    service.add_items([("item-1", "黑色外套")])
    assert pg_store.failure["operation"] == "upsert"
    assert pg_store.failure["doc_id"] == "item-1"


def test_knowledge_service_supports_pgvector_read_path_without_chroma(monkeypatch, tmp_path):
    import vector_store_service as module

    class FakeChroma:
        def __init__(self, **kwargs):
            raise AssertionError("pgvector-only mode must lazily avoid Chroma")

    class Embedding:
        def embed_query(self, query):
            return [0.1] * VECTOR_DIMENSION

    class PgStore:
        def search(self, embedding, *, source_kind, limit):
            assert source_kind == "knowledge"
            return [{"id": "doc-1", "content": "洗涤知识", "metadata": {"source": "seed"}, "distance": 0.1}]

    monkeypatch.setattr(module, "Chroma", FakeChroma)
    monkeypatch.setattr(module.config, "persist_directory", str(tmp_path))
    monkeypatch.setattr(module.config, "VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr(module.config, "VECTOR_DUAL_WRITE", False)
    service = module.VectorStoreService(Embedding(), user_id="user-a")
    service._pgvector_store = PgStore()

    docs = service.search("洗涤", k=2)
    assert docs[0].page_content == "洗涤知识"
