from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config.settings import get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str, *, serverless: bool = False):
    url = make_url(database_url)
    supabase_pooler = (url.host or "").endswith(".pooler.supabase.com")
    options = {"pool_pre_ping": True}
    if serverless or supabase_pooler:
        # Supavisor owns pooling. Warm serverless instances must not retain
        # session-mode connections and multiply the database's connection usage.
        options["poolclass"] = NullPool
    else:
        options.update(pool_size=3, max_overflow=2, pool_recycle=300)
    if url.drivername == "postgresql+psycopg":
        options["connect_args"] = {"connect_timeout": 10}
        if supabase_pooler or serverless:
            # Named prepared statements cannot be reused across Supavisor
            # transaction-mode backend connections.
            options["connect_args"]["prepare_threshold"] = None
    return create_engine(url, **options)


engine = create_database_engine(get_settings().database_url, serverless=os.getenv("VERCEL") == "1")
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
