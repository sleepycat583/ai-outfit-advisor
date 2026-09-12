-- Native LangGraph memory objects.
-- The application connects with search_path=app_private only. Keeping these
-- objects outside public prevents anon/authenticated Data API access.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
REVOKE ALL ON SCHEMA app_private FROM anon;
REVOKE ALL ON SCHEMA app_private FROM authenticated;

CREATE TABLE IF NOT EXISTS app_private.conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE app_private.conversations
    ADD COLUMN IF NOT EXISTS native_state TEXT NOT NULL DEFAULT 'active';
ALTER TABLE app_private.conversations
    ADD COLUMN IF NOT EXISTS native_error TEXT;

CREATE INDEX IF NOT EXISTS conversations_user_updated_idx
    ON app_private.conversations (user_id, updated_at DESC);

-- Legacy sessions were keyed as chat_session_<user_id>.  Keep a deterministic
-- mapping so the first native request can import the bounded legacy window and
-- rollback can still address the original transcript.
DO $$
BEGIN
    IF to_regclass('public.chat_messages') IS NOT NULL THEN
        INSERT INTO app_private.conversations (conversation_id, user_id, title, updated_at)
        SELECT
            'legacy:' || substring(c.session_id FROM 14),
            substring(c.session_id FROM 14),
            '历史会话',
            now()
        FROM public.chat_messages AS c
        WHERE c.session_id ~ '^chat_session_[^:]+$'
        ON CONFLICT (conversation_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS app_private.memory_migrations (
    migration_key TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending',
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- These names and columns match langgraph-checkpoint-postgres 3.1.2,
-- including checkpoint_writes.task_path. PostgresSaver still records its own
-- migration versions at startup, but serving requests never has to add this
-- current schema column implicitly.
CREATE TABLE IF NOT EXISTS app_private.checkpoint_migrations (v INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS app_private.checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS app_private.checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);
CREATE TABLE IF NOT EXISTS app_private.checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx
    ON app_private.checkpoints (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx
    ON app_private.checkpoint_blobs (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx
    ON app_private.checkpoint_writes (thread_id);

INSERT INTO app_private.memory_migrations (migration_key, completed_at, status, details)
VALUES (
    'native_memory_private_schema',
    now(),
    'completed',
    jsonb_build_object('schema', 'app_private', 'version', '20260911100000')
)
ON CONFLICT (migration_key) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    status = EXCLUDED.status,
    details = EXCLUDED.details;

COMMIT;
