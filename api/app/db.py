"""Database engine and session handling."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import DATABASE_URL


def _engine_url(url: str) -> str:
    """Use the psycopg 3 driver for Postgres URLs as hosts like Neon provide them."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def _make_engine(url: str):
    if url.startswith("sqlite"):
        # SQLite is used for local development and tests. An in-memory database
        # ("sqlite://") must share one connection or each session would see an
        # empty database.
        options = {"connect_args": {"check_same_thread": False}}
        if url == "sqlite://":
            options["poolclass"] = StaticPool
        return create_engine(url, **options)
    return create_engine(_engine_url(url), pool_pre_ping=True)


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
