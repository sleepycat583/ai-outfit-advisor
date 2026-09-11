BEGIN;

CREATE TABLE IF NOT EXISTS app_private.memory_items (
    namespace TEXT[] NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, key),
    CONSTRAINT memory_items_user_namespace CHECK (
        array_length(namespace, 1) >= 2
        AND namespace[1] ~ '^user:[^:]+$'
    )
);

CREATE INDEX IF NOT EXISTS memory_items_namespace_idx
    ON app_private.memory_items USING GIN (namespace);
CREATE INDEX IF NOT EXISTS memory_items_updated_idx
    ON app_private.memory_items (updated_at DESC);

REVOKE ALL ON app_private.memory_items FROM PUBLIC, anon, authenticated;

COMMIT;
