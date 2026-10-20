from unittest.mock import patch

from sqlalchemy.pool import NullPool

from app.db.session import create_database_engine


def test_supabase_transaction_pool_does_not_keep_connections():
    with patch("app.db.session.create_engine") as factory:
        create_database_engine("postgresql+psycopg://test:test@aws-0-ap-south-1.pooler.supabase.com:6543/postgres")
    kwargs = factory.call_args.kwargs
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"] == {"connect_timeout": 10, "prepare_threshold": None}
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs


def test_session_pool_also_releases_connections():
    with patch("app.db.session.create_engine") as factory:
        create_database_engine("postgresql+psycopg://test:test@aws-0-ap-south-1.pooler.supabase.com:5432/postgres")
    assert factory.call_args.kwargs["poolclass"] is NullPool


def test_serverless_direct_connection_uses_no_local_pool():
    with patch("app.db.session.create_engine") as factory:
        create_database_engine("postgresql+psycopg://test:test@db.example.com/postgres", serverless=True)
    assert factory.call_args.kwargs["poolclass"] is NullPool


def test_local_persistent_server_retains_bounded_pool():
    with patch("app.db.session.create_engine") as factory:
        create_database_engine("postgresql+psycopg://test:test@localhost/postgres")
    kwargs = factory.call_args.kwargs
    assert "poolclass" not in kwargs
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 2
    assert "prepare_threshold" not in kwargs["connect_args"]
