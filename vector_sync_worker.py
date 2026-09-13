"""Server-side retry worker for pgvector dual-write outbox events."""

from __future__ import annotations

from typing import Any, Callable

from pgvector_store import PgVectorStore, VectorDocument


def process_event(store: PgVectorStore, event: dict[str, Any], *, max_attempts: int = 5) -> bool:
    """Apply one leased event and acknowledge it only after the target write succeeds."""
    event_id = int(event["id"])
    lease_token = str(event["lease_token"])
    source_kind = str(event["source_kind"])
    try:
        if event["operation"] == "delete":
            store.delete([str(event["doc_id"])], source_kind=source_kind)
        elif event["operation"] == "upsert":
            payload = event.get("payload") or {}
            content = str(payload.get("content", ""))
            metadata = payload.get("metadata") or {}
            embedding = payload.get("embedding")
            if embedding is None:
                embedding = store.embedding.embed_query(content)
            store.upsert(
                [VectorDocument(str(event["doc_id"]), content, metadata, embedding)],
                source_kind=source_kind,
            )
        else:
            raise ValueError(f"unknown outbox operation: {event['operation']}")
        return store.complete_sync_event(event_id, lease_token)
    except Exception as error:
        store.fail_sync_event(event_id, lease_token, error, max_attempts=max_attempts)
        return False


def run_once(store: PgVectorStore, *, limit: int = 50, lease_seconds: int = 120, max_attempts: int = 5) -> dict[str, int]:
    events = store.claim_sync_events(limit=limit, lease_seconds=lease_seconds)
    succeeded = sum(process_event(store, event, max_attempts=max_attempts) for event in events)
    return {"claimed": len(events), "succeeded": succeeded, "failed": len(events) - succeeded}
