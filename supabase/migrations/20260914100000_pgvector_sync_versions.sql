-- Incremental upgrade for pgvector sync ordering.
-- This file must remain separate from the original migration because Supabase
-- applies migrations by filename and does not re-run edited historical files.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_private;
CREATE SEQUENCE IF NOT EXISTS app_private.vector_sync_version_seq;

ALTER TABLE app_private.vector_documents
    ADD COLUMN IF NOT EXISTS sync_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE app_private.vector_sync_outbox
    ADD COLUMN IF NOT EXISTS operation_version BIGINT NOT NULL DEFAULT 0;

REVOKE ALL ON SEQUENCE app_private.vector_sync_version_seq FROM PUBLIC, anon, authenticated;
REVOKE ALL ON app_private.vector_documents FROM PUBLIC, anon, authenticated;
REVOKE ALL ON app_private.vector_sync_outbox FROM PUBLIC, anon, authenticated;

INSERT INTO app_private.memory_migrations (migration_key, completed_at, status, details)
VALUES (
    'pgvector_sync_versions', now(), 'completed',
    jsonb_build_object('schema', 'app_private', 'version', '20260914100000')
)
ON CONFLICT (migration_key) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    status = EXCLUDED.status,
    details = EXCLUDED.details;

COMMIT;
