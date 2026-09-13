"""Private PostgreSQL/pgvector storage used by the staged vector migration.

The class deliberately accepts a connection factory so production code can use
the server-side ``SUPABASE_DB_URL`` while tests can exercise transaction and
query behavior without replacing the database API with a mock client.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


_SOURCE_KINDS = {"knowledge", "wardrobe"}
VECTOR_DIMENSION = 1024


@dataclass(frozen=True)
class VectorDocument:
    doc_id: str
    content: str
    metadata: dict[str, Any]
    embedding: Sequence[float]


def _vector_literal(values: Iterable[float]) -> str:
    numbers = [float(value) for value in values]
    if not numbers:
        raise ValueError("embedding 不能为空")
    if len(numbers) != VECTOR_DIMENSION:
        raise ValueError(f"embedding 维度必须为 {VECTOR_DIMENSION}")
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError("embedding 必须是有限数字")
    return "[" + ",".join(format(value, ".12g") for value in numbers) + "]"


class PgVectorStore:
    """User-scoped pgvector repository with idempotent upsert semantics."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        embedding: Any,
        user_id: str,
    ) -> None:
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")
        self._connection_factory = connection_factory
        self.embedding = embedding
        self.user_id = user_id

    @staticmethod
    def _validate_source_kind(source_kind: str) -> str:
        if source_kind not in _SOURCE_KINDS:
            raise ValueError("source_kind 必须是 knowledge 或 wardrobe")
        return source_kind

    def upsert(self, documents: Iterable[VectorDocument], *, source_kind: str) -> int:
        source_kind = self._validate_source_kind(source_kind)
        documents = list(documents)
        if not documents:
            return 0
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                for document in documents:
                    if not document.doc_id or not document.content.strip():
                        raise ValueError("doc_id 和 content 不能为空")
                    cursor.execute(
                        """INSERT INTO app_private.vector_documents
                           (source_kind, user_id, doc_id, content, metadata, embedding)
                           VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)
                           ON CONFLICT (source_kind, user_id, doc_id) DO UPDATE SET
                             content = EXCLUDED.content,
                             metadata = EXCLUDED.metadata,
                             embedding = EXCLUDED.embedding,
                             updated_at = now()""",
                        (
                            source_kind,
                            self.user_id,
                            document.doc_id,
                            document.content,
                            json.dumps(document.metadata, ensure_ascii=False),
                            _vector_literal(document.embedding),
                        ),
                    )
            conn.commit()
            return len(documents)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def search(
        self,
        embedding: Sequence[float],
        *,
        source_kind: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        source_kind = self._validate_source_kind(source_kind)
        if limit < 1 or limit > 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        vector = _vector_literal(embedding)
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT doc_id, content, metadata, embedding <=> %s::vector AS distance
                       FROM app_private.vector_documents
                       WHERE source_kind = %s AND user_id = %s
                       ORDER BY embedding <=> %s::vector
                       LIMIT %s""",
                    (vector, source_kind, self.user_id, vector, limit),
                )
                rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "content": row[1],
                    "metadata": row[2] or {},
                    "distance": float(row[3]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def delete(self, doc_ids: Iterable[str], *, source_kind: str) -> int:
        source_kind = self._validate_source_kind(source_kind)
        ids = [doc_id for doc_id in doc_ids if doc_id]
        if not ids:
            return 0
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """DELETE FROM app_private.vector_documents
                       WHERE source_kind = %s AND user_id = %s AND doc_id = ANY(%s)
                       RETURNING doc_id""",
                    (source_kind, self.user_id, ids),
                )
                deleted = len(cursor.fetchall())
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_documents(self, *, source_kind: str) -> list[dict[str, Any]]:
        source_kind = self._validate_source_kind(source_kind)
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT doc_id, content, metadata
                       FROM app_private.vector_documents
                       WHERE source_kind = %s AND user_id = %s
                       ORDER BY updated_at DESC""",
                    (source_kind, self.user_id),
                )
                rows = cursor.fetchall()
            return [
                {"id": row[0], "content": row[1], "metadata": row[2] or {}}
                for row in rows
            ]
        finally:
            conn.close()

    def record_sync_failure(
        self,
        *,
        source_kind: str,
        operation: str,
        doc_id: str,
        payload: dict[str, Any],
        error: Exception,
    ) -> None:
        source_kind = self._validate_source_kind(source_kind)
        if operation not in {"upsert", "delete"}:
            raise ValueError("operation 必须是 upsert 或 delete")
        if not doc_id:
            raise ValueError("doc_id 不能为空")
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO app_private.vector_sync_outbox
                       (source_kind, user_id, operation, doc_id, payload, last_error)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (source_kind, user_id, operation, doc_id) DO UPDATE SET
                         payload = EXCLUDED.payload,
                         last_error = EXCLUDED.last_error,
                         attempts = app_private.vector_sync_outbox.attempts + 1,
                         available_at = now(),
                         updated_at = now()""",
                    (
                        source_kind,
                        self.user_id,
                        operation,
                        doc_id,
                        json.dumps(payload, ensure_ascii=False),
                        str(error)[:2000],
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
