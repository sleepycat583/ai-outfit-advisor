from __future__ import annotations

import json

import pytest

from memory_jobs import (
    MemoryExtractionJob,
    MemoryJobRepository,
    RetryPolicy,
    build_dedupe_key,
    extract_candidate_messages,
    sanitize_job_payload,
)


def test_dedupe_key_is_stable_for_same_conversation_turn():
    assert build_dedupe_key("user-a", "conversation-a", "turn-7") == build_dedupe_key(
        "user-a", "conversation-a", "turn-7"
    )
    assert build_dedupe_key("user-a", "conversation-a", "turn-7") != build_dedupe_key(
        "user-a", "conversation-a", "turn-8"
    )


def test_candidate_messages_drop_system_and_tool_protocol_content():
    messages = [
        {"role": "system", "content": "hidden prompt"},
        {"role": "user", "content": "我不穿高跟鞋"},
        {"role": "tool", "content": "internal result"},
        {"role": "assistant", "content": "记住了"},
    ]

    assert extract_candidate_messages(messages) == [
        {"role": "user", "content": "我不穿高跟鞋"},
        {"role": "assistant", "content": "记住了"},
    ]


def test_job_payload_never_contains_service_secrets():
    job = MemoryExtractionJob(
        job_id="job-1",
        dedupe_key="dedupe-1",
        user_id="user-a",
        conversation_id="conversation-a",
        messages=[{"role": "user", "content": "偏好黑色"}],
    )

    payload = sanitize_job_payload(job)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["job_id"] == "job-1"
    assert "SUPABASE_DB_URL" not in serialized
    assert "DASHSCOPE_API_KEY" not in serialized
    assert "service_role" not in serialized


def test_retry_policy_exponential_backoff_and_dead_letter_threshold():
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=10, max_delay_seconds=90)

    assert [policy.delay_seconds(attempt) for attempt in (1, 2, 3)] == [10, 20, 40]
    assert policy.should_dead_letter(3) is True
    assert policy.should_dead_letter(2) is False


def test_retry_policy_rejects_invalid_attempts():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=3, base_delay_seconds=-1)


def test_queue_repository_uses_private_search_path(monkeypatch):
    import memory_jobs
    import types

    class Cursor:
        def __init__(self):
            self.statements = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, statement, params=None):
            self.statements.append(statement)
    class Conn:
        def __init__(self):
            self.cursor_obj = Cursor()
        def cursor(self):
            return self.cursor_obj
    conn = Conn()
    psycopg_module = types.ModuleType("psycopg")
    psycopg_module.connect = lambda *args, **kwargs: conn
    rows_module = types.ModuleType("psycopg.rows")
    rows_module.dict_row = object()
    monkeypatch.setattr(memory_jobs, "get_database_url", lambda: "postgres://test")
    monkeypatch.setitem(__import__("sys").modules, "psycopg", psycopg_module)
    monkeypatch.setitem(__import__("sys").modules, "psycopg.rows", rows_module)

    MemoryJobRepository()._connection()
    assert '"app_private"' in conn.cursor_obj.statements[0]
    assert ", public" not in conn.cursor_obj.statements[0]


def test_queue_repository_reads_configured_max_attempts(monkeypatch):
    import config_data
    monkeypatch.setattr(config_data, "MEMORY_JOB_MAX_ATTEMPTS", 2)
    repository = MemoryJobRepository()
    assert repository.retry_policy.max_attempts == 2


def test_queue_repository_rejects_unmanaged_schema_or_queue():
    with pytest.raises(ValueError, match="app_private"):
        MemoryJobRepository(schema="another_private_schema")
    with pytest.raises(ValueError, match="memory-extraction"):
        MemoryJobRepository(queue_name="another-queue")


def test_retry_policy_exposes_delay_for_queue_visibility_timeout():
    assert RetryPolicy(base_delay_seconds=7).delay_seconds(3) == 28


def test_queue_migration_creates_private_receipts_queue_and_dead_letters():
    migration = (
        __import__("pathlib").Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260912100000_memory_extraction_queue.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS pgmq" in migration
    assert "memory_job_receipts" in migration
    assert "memory_dead_letters" in migration
    assert "memory_poison_dead_letters" in migration
    assert "pgmq.create('memory-extraction')" in migration
    assert "REVOKE USAGE ON SCHEMA pgmq" in migration
    assert "REVOKE ALL ON app_private.memory_job_receipts" in migration


def test_worker_and_cron_are_server_side_only():
    worker = (
        __import__("pathlib").Path(__file__).parents[1]
        / "supabase"
        / "functions"
        / "memory-worker"
        / "index.ts"
    ).read_text(encoding="utf-8")
    cron = (
        __import__("pathlib").Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260912110000_memory_extraction_cron.sql"
    ).read_text(encoding="utf-8")
    assert "MEMORY_WORKER_SERVICE_KEY" in worker
    assert "DASHSCOPE_API_KEY" in worker
    assert "memory_job_receipts" in worker
    assert "archivePoisonMessage" in worker
    assert "claimed.length === 0" in worker
    assert "MEMORY_JOB_QUEUE_NAME must be memory-extraction" in worker
    assert "vault.decrypted_secrets" in cron
    assert "cron.schedule" in cron
