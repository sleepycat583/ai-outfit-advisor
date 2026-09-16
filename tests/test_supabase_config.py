from __future__ import annotations

import supabase_config


def test_normalize_database_url_ignores_documentation_placeholder():
    assert supabase_config._normalize_database_url("postgresql://...") is None


def test_normalize_database_url_ignores_uri_without_host():
    assert supabase_config._normalize_database_url("postgresql:///postgres") is None


def test_normalize_database_url_preserves_valid_postgres_uri():
    value = "postgresql://postgres:secret@db.example.supabase.co:5432/postgres?sslmode=require"
    assert supabase_config._normalize_database_url(value) == value