-- Private queue and delivery state for asynchronous ordinary-memory extraction.
-- Payloads are opaque JSON and never exposed through the Data API.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgmq;

CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
REVOKE ALL ON SCHEMA app_private FROM anon;
REVOKE ALL ON SCHEMA app_private FROM authenticated;

CREATE TABLE IF NOT EXISTS app_private.memory_job_receipts (
    job_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    msg_id BIGINT,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'retrying', 'succeeded', 'dead_letter')),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS memory_job_receipts_status_idx
    ON app_private.memory_job_receipts (status, updated_at);

CREATE TABLE IF NOT EXISTS app_private.memory_dead_letters (
    job_id TEXT PRIMARY KEY REFERENCES app_private.memory_job_receipts(job_id),
    msg_id BIGINT NOT NULL,
    error TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Queue messages without a trustworthy receipt cannot reference the receipt
-- backed dead-letter table. Keep them separately for operational diagnosis.
CREATE TABLE IF NOT EXISTS app_private.memory_poison_dead_letters (
    msg_id BIGINT PRIMARY KEY,
    error TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

REVOKE ALL ON app_private.memory_job_receipts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON app_private.memory_dead_letters FROM PUBLIC, anon, authenticated;
REVOKE ALL ON app_private.memory_poison_dead_letters FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
    PERFORM pgmq.create('memory-extraction');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

REVOKE USAGE ON SCHEMA pgmq FROM PUBLIC, anon, authenticated;

INSERT INTO app_private.memory_migrations (migration_key, completed_at, status, details)
VALUES (
    'memory_extraction_queue',
    now(),
    'completed',
    jsonb_build_object('queue', 'memory-extraction', 'version', '20260912100000')
)
ON CONFLICT (migration_key) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    status = EXCLUDED.status,
    details = EXCLUDED.details;

COMMIT;
