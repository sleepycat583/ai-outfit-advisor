# Memory extraction worker

The function is intended for private server-side invocation by the `pg_cron` job.
Configure these Supabase/Edge Function secrets before enabling the cron migration:

- `SUPABASE_DB_URL`
- `DASHSCOPE_API_KEY`
- `MEMORY_WORKER_SERVICE_KEY`
- `MEMORY_JOB_QUEUE_NAME` (optional, defaults to `memory-extraction`)
- `MEMORY_JOB_MAX_ATTEMPTS` (optional, defaults to `5`)

Store the function URL as Vault secret `memory_worker_url` and the same bearer key
as Vault secret `memory_worker_service_key`. The migration schedules one worker
request per minute; the worker claims at most ten messages per request.
