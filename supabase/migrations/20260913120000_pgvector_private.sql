-- Private pgvector target for the staged Chroma migration.
-- Reads remain on Chroma until VECTOR_BACKEND is explicitly switched.

BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS app_private.vector_documents (
    source_kind TEXT NOT NULL CHECK (source_kind IN ('knowledge', 'wardrobe')),
    user_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding extensions.vector(1024) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_kind, user_id, doc_id)
);

CREATE TABLE IF NOT EXISTS app_private.vector_sync_outbox (
    id BIGSERIAL PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('knowledge', 'wardrobe')),
    user_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    doc_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'succeeded', 'dead_letter')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_kind, user_id, doc_id)
);

CREATE INDEX IF NOT EXISTS vector_documents_user_source_idx
    ON app_private.vector_documents (user_id, source_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS vector_documents_embedding_hnsw_idx
    ON app_private.vector_documents USING hnsw (embedding extensions.vector_cosine_ops);

REVOKE ALL ON app_private.vector_documents FROM PUBLIC, anon, authenticated;
REVOKE ALL ON app_private.vector_sync_outbox FROM PUBLIC, anon, authenticated;
ALTER TABLE app_private.vector_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.vector_sync_outbox ENABLE ROW LEVEL SECURITY;

INSERT INTO app_private.memory_migrations (migration_key, completed_at, status, details)
VALUES (
    'pgvector_private_target', now(), 'completed',
    jsonb_build_object('schema', 'app_private', 'dimension', 1024, 'version', '20260913120000')
)
ON CONFLICT (migration_key) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    status = EXCLUDED.status,
    details = EXCLUDED.details;

COMMIT;
