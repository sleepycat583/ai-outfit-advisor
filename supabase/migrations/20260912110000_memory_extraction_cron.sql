-- Invoke the private Edge Function every minute.  The URL and bearer key are
-- read from Supabase Vault at execution time and never stored in git.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

DO $$
DECLARE
    existing_job_id BIGINT;
    worker_url TEXT;
    worker_service_key TEXT;
BEGIN
    SELECT decrypted_secret INTO worker_url
    FROM vault.decrypted_secrets
    WHERE name = 'memory_worker_url';
    SELECT decrypted_secret INTO worker_service_key
    FROM vault.decrypted_secrets
    WHERE name = 'memory_worker_service_key';

    IF NULLIF(BTRIM(worker_url), '') IS NULL
       OR NULLIF(BTRIM(worker_service_key), '') IS NULL THEN
        RAISE EXCEPTION 'memory worker Vault secrets are required before enabling cron';
    END IF;

    SELECT jobid INTO existing_job_id
    FROM cron.job
    WHERE jobname = 'memory-extraction-worker';

    IF existing_job_id IS NOT NULL THEN
        PERFORM cron.unschedule(existing_job_id);
    END IF;

    PERFORM cron.schedule(
        'memory-extraction-worker',
        '* * * * *',
        $job$
        SELECT net.http_post(
            url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'memory_worker_url'),
            headers := jsonb_build_object(
                'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'memory_worker_service_key'),
                'Content-Type', 'application/json'
            ),
            body := '{}'::jsonb
        );
        $job$
    );
END $$;

INSERT INTO app_private.memory_migrations (migration_key, completed_at, status, details)
VALUES (
    'memory_extraction_cron',
    now(),
    'completed',
    jsonb_build_object('job_name', 'memory-extraction-worker', 'schedule', '* * * * *')
)
ON CONFLICT (migration_key) DO UPDATE SET
    completed_at = EXCLUDED.completed_at,
    status = EXCLUDED.status,
    details = EXCLUDED.details;

COMMIT;
