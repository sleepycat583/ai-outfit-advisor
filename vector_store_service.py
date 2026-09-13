import os
import time
import hashlib
import json

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
import config_data as config
from pgvector_store import PgVectorStore, VectorDocument
from supabase_config import get_database_url


def _pgvector_connection():
    connection_string = (get_database_url() or "").strip()
    if not connection_string:
        raise RuntimeError("未配置 SUPABASE_DB_URL，无法访问 pgvector")
    import psycopg

    conn = psycopg.connect(connection_string, autocommit=False)
    with conn.cursor() as cursor:
        cursor.execute('SET search_path TO "app_private", extensions')
    return conn


class VectorStoreService(object):
    def __init__(self, embedding, user_id: str = ""):
        """初始化知识库向量服务，并打印 Chroma 连接初始化耗时。"""
        start_time = time.time()
        self.embedding = embedding
        self.user_id = user_id
        self._chroma_enabled = config.VECTOR_BACKEND != "pgvector" or config.VECTOR_DUAL_WRITE
        self.vector_store = None
        if self._chroma_enabled:
            self.vector_store = self._create_chroma()
        print(f"[PERF] VectorStoreService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _create_chroma(self):
        persist_dir = os.path.join(config.persist_directory, self.user_id, "kb") if self.user_id else os.path.join(config.persist_directory, "kb")
        collection_name = f"kb_{self.user_id}" if self.user_id else "kb_default"
        os.makedirs(persist_dir, exist_ok=True)
        return Chroma(collection_name=collection_name, embedding_function=self.embedding, persist_directory=persist_dir)

    def _get_chroma(self):
        if self.vector_store is None:
            self.vector_store = self._create_chroma()
        return self.vector_store

    def _get_pgvector_store(self) -> PgVectorStore:
        if not hasattr(self, "_pgvector_store") or self._pgvector_store is None:
            self._pgvector_store = PgVectorStore(_pgvector_connection, embedding=self.embedding, user_id=self.user_id)
        return self._pgvector_store

    def _embed_documents(self, texts):
        method = getattr(self.embedding, "embed_documents", None)
        if not callable(method):
            raise RuntimeError("当前 embedding 实现不支持 embed_documents")
        vectors = [list(vector) for vector in method(list(texts))]
        if len(vectors) != len(texts):
            raise RuntimeError("embedding 返回数量与待写入文档数量不一致")
        return vectors

    def add_texts(self, texts, *, metadatas=None, ids=None) -> list[str]:
        texts = list(texts)
        metadatas = list(metadatas or [{} for _ in texts])
        if len(metadatas) != len(texts):
            raise ValueError("metadatas 数量必须与 texts 一致")
        ids = list(ids or [hashlib.sha256(f"{self.user_id}\x1f{i}\x1f{text}".encode()).hexdigest() for i, text in enumerate(texts)])
        if len(ids) != len(texts):
            raise ValueError("ids 数量必须与 texts 一致")
        if self._chroma_enabled:
            self._get_chroma().add_texts(texts=texts, metadatas=metadatas, ids=ids)
        if config.VECTOR_BACKEND == "pgvector" or config.VECTOR_DUAL_WRITE:
            try:
                vectors = self._embed_documents(texts)
                docs = [VectorDocument(doc_id=doc_id, content=text, metadata=metadata, embedding=vector) for doc_id, text, metadata, vector in zip(ids, texts, metadatas, vectors)]
                self._get_pgvector_store().upsert(docs, source_kind="knowledge")
            except Exception as error:
                self._safe_record_failures("upsert", [(doc_id, text, metadata) for doc_id, text, metadata in zip(ids, texts, metadatas)], error)
                if config.VECTOR_BACKEND == "pgvector":
                    raise
                print(f"[WARN] knowledge pgvector dual-write failed: {error}", flush=True)
        return ids

    def delete(self, ids):
        ids = list(ids)
        if self._chroma_enabled:
            self._get_chroma().delete(ids=ids)
        if config.VECTOR_BACKEND == "pgvector" or config.VECTOR_DUAL_WRITE:
            try:
                self._get_pgvector_store().delete(ids, source_kind="knowledge")
            except Exception as error:
                self._safe_record_failures("delete", [(doc_id, "", {}) for doc_id in ids], error)
                if config.VECTOR_BACKEND == "pgvector":
                    raise

    def delete_by_metadata(self, key: str, value: str) -> None:
        if config.VECTOR_BACKEND == "pgvector" or config.VECTOR_DUAL_WRITE:
            self._get_pgvector_store().delete_by_metadata(source_kind="knowledge", key=key, value=value)

    def delete_all(self) -> None:
        if config.VECTOR_BACKEND == "pgvector" or config.VECTOR_DUAL_WRITE:
            self._get_pgvector_store().delete_all(source_kind="knowledge")

    def search(self, query: str, k: int = 4):
        start_time = time.time()
        embed_query = getattr(self.embedding, "embed_query", None)
        if config.VECTOR_BACKEND == "pgvector":
            if not callable(embed_query):
                raise RuntimeError("当前 embedding 实现不支持 embed_query")
            results = self._get_pgvector_store().search(embed_query(query), source_kind="knowledge", limit=k)
            print(json.dumps({"event": "pgvector_search", "source_kind": "knowledge", "count": len(results), "latency_ms": round((time.time() - start_time) * 1000, 2)}, ensure_ascii=False), flush=True)
            return [Document(page_content=result["content"], metadata=result["metadata"]) for result in results]
        chroma_docs = self._get_chroma().similarity_search(query, k=k)
        if config.VECTOR_SHADOW_QUERY and callable(embed_query):
            shadow_start = time.time()
            try:
                shadow = self._get_pgvector_store().search(embed_query(query), source_kind="knowledge", limit=k)
                primary = {doc.page_content for doc in chroma_docs}
                shadow_set = {item["content"] for item in shadow}
                overlap = len(primary & shadow_set) / max(1, len(primary | shadow_set))
                print(json.dumps({"event": "vector_shadow", "source_kind": "knowledge", "primary_count": len(primary), "shadow_count": len(shadow_set), "overlap": round(overlap, 4), "primary_latency_ms": round((shadow_start - start_time) * 1000, 2), "shadow_latency_ms": round((time.time() - shadow_start) * 1000, 2)}, ensure_ascii=False), flush=True)
            except Exception as error:
                print(json.dumps({"event": "vector_shadow_error", "source_kind": "knowledge", "error": str(error)[:500]}, ensure_ascii=False), flush=True)
        return chroma_docs

    def _safe_record_failures(self, operation, items, error) -> None:
        try:
            store = self._get_pgvector_store()
            for doc_id, text, metadata in items:
                store.record_sync_failure(
                    source_kind="knowledge",
                    operation=operation,
                    doc_id=doc_id,
                    payload={"content": text, "metadata": metadata},
                    error=error,
                )
        except Exception as outbox_error:
            print(f"[ERROR] failed to record knowledge pgvector outbox: {outbox_error}", flush=True)

    def backfill_from_chroma(self, *, batch_size: int = 64) -> int:
        """Idempotently copy the current Chroma collection into pgvector."""
        if not self._chroma_enabled:
            return 0
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        result = self._get_chroma().get(include=["documents", "metadatas"])
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        total = 0
        for offset in range(0, len(ids), batch_size):
            end = offset + batch_size
            self.add_texts(documents[offset:end], metadatas=metadatas[offset:end], ids=ids[offset:end])
            total += len(ids[offset:end])
        return total

    def get_retriever(self):
        """返回向量库检索器，方便加入 Chain"""
        return RunnableLambda(lambda query: self.search(query, k=int(self._limit())))

    def _limit(self):
        return int(config.similarity_threshold)


class VectorWardrobeService:
    """管理衣橱单品的向量索引（独立 Chroma Collection），用于语义检索 Top-K 单品。"""

    def __init__(self, embedding, user_id: str = ""):
        """初始化衣橱向量服务，并打印 Chroma 连接初始化耗时。"""
        start_time = time.time()
        self.embedding = embedding
        self.user_id = user_id
        self._pgvector_store = None
        self._pgvector_enabled = (
            config.VECTOR_BACKEND == "pgvector"
            or config.VECTOR_DUAL_WRITE
        )
        persist_directory = os.path.join(config.persist_directory, user_id, "wardrobe") if user_id else os.path.join(config.persist_directory, "wardrobe")
        self._chroma_config = {
            "collection_name": "wardrobe_items",
            "embedding_function": self.embedding,
            "persist_directory": persist_directory,
        }
        self.vector_store = None
        if config.VECTOR_BACKEND != "pgvector" or config.VECTOR_DUAL_WRITE:
            self.vector_store = self._create_chroma()
        print(f"[PERF] VectorWardrobeService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _create_chroma(self):
        os.makedirs(self._chroma_config["persist_directory"], exist_ok=True)
        return Chroma(**self._chroma_config)

    def _get_chroma(self):
        if self.vector_store is None:
            self.vector_store = self._create_chroma()
        return self.vector_store

    def _get_pgvector_store(self) -> PgVectorStore:
        if self._pgvector_store is None:
            self._pgvector_store = PgVectorStore(
                _pgvector_connection,
                embedding=self.embedding,
                user_id=self.user_id,
            )
        return self._pgvector_store

    def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        embed_documents = getattr(self.embedding, "embed_documents", None)
        if not callable(embed_documents):
            raise RuntimeError("当前 embedding 实现不支持 embed_documents")
        embeddings = [list(vector) for vector in embed_documents(texts)]
        if len(embeddings) != len(texts):
            raise RuntimeError("embedding 返回数量与待写入文档数量不一致")
        return embeddings

    def _pgvector_write(self, items: list[tuple[str, str]]) -> None:
        if not items or not self._pgvector_enabled:
            return
        documents = [
            VectorDocument(
                doc_id=item_id,
                content=text,
                metadata={"item_id": item_id},
                embedding=embedding,
            )
            for (item_id, text), embedding in zip(items, self._embed_documents([text for _, text in items]))
        ]
        self._get_pgvector_store().upsert(documents, source_kind="wardrobe")

    def _handle_pgvector_error(self, error: Exception) -> None:
        if config.VECTOR_BACKEND == "pgvector":
            raise error
        print(f"[WARN] pgvector shadow/dual-write failed; Chroma remains primary: {error}", flush=True)

    def _record_pgvector_failure(self, operation: str, items: list[tuple[str, str]], error: Exception) -> None:
        if not self._pgvector_enabled:
            return
        try:
            store = self._get_pgvector_store()
            for item_id, text in items:
                store.record_sync_failure(
                    source_kind="wardrobe",
                    operation=operation,
                    doc_id=item_id,
                    payload={"content": text, "item_id": item_id},
                    error=error,
                )
        except Exception as outbox_error:
            print(f"[ERROR] failed to record pgvector sync outbox: {outbox_error}", flush=True)

    def add_items(self, items: list[tuple[str, str]]) -> None:
        """批量添加单品文本到向量库。items 为 [(item_id, text), ...] 列表。"""
        if not items:
            return
        ids, texts = zip(*items)
        if config.VECTOR_BACKEND != "pgvector" or config.VECTOR_DUAL_WRITE:
            self._get_chroma().add_texts(
                texts=list(texts),
                metadatas=[{"item_id": iid} for iid in ids],
                ids=list(ids),
            )
        try:
            self._pgvector_write(items)
        except Exception as error:
            self._record_pgvector_failure("upsert", items, error)
            self._handle_pgvector_error(error)

    def update_items(self, items: list[tuple[str, str]]) -> None:
        """批量更新单品文本。先删后加，避免 Chroma update 的 upsert 行为不一致。"""
        if not items:
            return
        if config.VECTOR_BACKEND != "pgvector" or config.VECTOR_DUAL_WRITE:
            ids_to_del = [iid for iid, _ in items]
            existing = self._get_chroma().get(ids=ids_to_del)
            if existing and existing.get("ids"):
                self._get_chroma().delete(ids=existing["ids"])
        self.add_items(items)

    def delete_items(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        if config.VECTOR_BACKEND != "pgvector" or config.VECTOR_DUAL_WRITE:
            existing = self._get_chroma().get(ids=item_ids)
            if existing and existing.get("ids"):
                self._get_chroma().delete(ids=existing["ids"])
        if self._pgvector_enabled:
            try:
                self._get_pgvector_store().delete(item_ids, source_kind="wardrobe")
            except Exception as error:
                self._record_pgvector_failure("delete", [(item_id, "") for item_id in item_ids], error)
                self._handle_pgvector_error(error)

    def backfill_from_chroma(self, *, batch_size: int = 64) -> int:
        """Idempotently copy the current wardrobe Chroma collection into pgvector."""
        if self.vector_store is None:
            return 0
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        result = self._get_chroma().get(include=["documents", "metadatas"])
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        total = 0
        for offset in range(0, len(ids), batch_size):
            end = offset + batch_size
            batch = []
            for chroma_id, content, metadata in zip(ids[offset:end], documents[offset:end], metadatas[offset:end]):
                batch.append((str((metadata or {}).get("item_id") or chroma_id), content))
            self._pgvector_write(batch)
            total += len(batch)
        return total

    def search(self, query: str, k: int = 15) -> list[str]:
        """语义检索最相关的 Top-K 单品描述文本，并打印检索耗时。"""
        start_time = time.time()
        if config.VECTOR_BACKEND == "pgvector":
            embed_query = getattr(self.embedding, "embed_query", None)
            if not callable(embed_query):
                raise RuntimeError("当前 embedding 实现不支持 embed_query")
            try:
                results = self._get_pgvector_store().search(
                    embed_query(query), source_kind="wardrobe", limit=k
                )
                print(json.dumps({"event": "pgvector_search", "source_kind": "wardrobe", "count": len(results), "latency_ms": round((time.time() - start_time) * 1000, 2)}, ensure_ascii=False), flush=True)
                return [result["content"] for result in results]
            except Exception as error:
                self._handle_pgvector_error(error)
        docs = self._get_chroma().similarity_search(query, k=k)
        if config.VECTOR_SHADOW_QUERY:
            embed_query = getattr(self.embedding, "embed_query", None)
            if callable(embed_query):
                shadow_start = time.time()
                try:
                    shadow = self._get_pgvector_store().search(
                        embed_query(query), source_kind="wardrobe", limit=k
                    )
                    primary = {doc.page_content for doc in docs}
                    shadow_set = {item["content"] for item in shadow}
                    overlap = len(primary & shadow_set) / max(1, len(primary | shadow_set))
                    print(json.dumps({"event": "vector_shadow", "source_kind": "wardrobe", "primary_count": len(primary), "shadow_count": len(shadow_set), "overlap": round(overlap, 4), "primary_latency_ms": round((shadow_start - start_time) * 1000, 2), "shadow_latency_ms": round((time.time() - shadow_start) * 1000, 2)}, ensure_ascii=False), flush=True)
                except Exception as error:
                    print(json.dumps({"event": "vector_shadow_error", "source_kind": "wardrobe", "error": str(error)[:500]}, ensure_ascii=False), flush=True)
        print(f"[PERF] VectorWardrobeService.search took {time.time() - start_time:.3f}s", flush=True)
        return [doc.page_content for doc in docs]


if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    retriever = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4")).get_retriever()
    res = retriever.invoke("我的体重180斤，尺码推荐")
    print(res)
