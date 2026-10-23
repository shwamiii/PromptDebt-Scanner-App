"""Database tables.

Scan tables (``scan``, ``artefact``) hold public repository data and are shared by
everyone. Per-client tables (``watchlist_item``, ``finding_triage``) belong to one
anonymous client and are deleted with it.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timestamp that always comes back as timezone-aware UTC.

    Postgres keeps the timezone, but SQLite (used locally and in tests) drops it;
    this makes both behave the same.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Client(Base):
    __tablename__ = "client"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # SHA-256 of the client's key. The key itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)

    watchlist: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    triage: Mapped[list["FindingTriage"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Scan(Base):
    __tablename__ = "scan"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repo_full_name: Mapped[str] = mapped_column(String(140), index=True)
    default_branch: Mapped[str] = mapped_column(String(255))
    head_sha: Mapped[str] = mapped_column(String(40))
    last_commit_at: Mapped[datetime] = mapped_column(UTCDateTime)
    stars: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean)
    scanned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)

    artefacts: Mapped[list["Artefact"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="Artefact.path"
    )
    review: Mapped["AiReview | None"] = relationship(cascade="all, delete-orphan")


class Artefact(Base):
    __tablename__ = "artefact"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(60))
    last_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    days_behind: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    documented: Mapped[bool] = mapped_column(Boolean)
    commits_since_update: Mapped[int | None] = mapped_column(Integer)
    change_count: Mapped[int] = mapped_column(Integer)
    line_count: Mapped[int] = mapped_column(Integer)
    approx_tokens: Mapped[int] = mapped_column(Integer)
    # Paths mentioned in the artefact that don't exist, each with its line and reason
    # ({"path", "line", "reason", "found_at"}); NULL if they couldn't be checked.
    broken_refs: Mapped[list[dict] | None] = mapped_column(JSON)
    # [{"text": rule line, "other_path": artefact it also appears in}]
    duplicate_rules: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # Other artefact paths that are symlinks to this one, e.g. ["CLAUDE.md"].
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)

    scan: Mapped[Scan] = relationship(back_populates="artefacts")


class WatchlistItem(Base):
    __tablename__ = "watchlist_item"
    __table_args__ = (UniqueConstraint("client_id", "repo_full_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("client.id", ondelete="CASCADE"), index=True)
    repo_full_name: Mapped[str] = mapped_column(String(140))
    label: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    last_scan_id: Mapped[str | None] = mapped_column(ForeignKey("scan.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)

    client: Mapped[Client] = relationship(back_populates="watchlist")
    last_scan: Mapped[Scan | None] = relationship()


class FindingTriage(Base):
    __tablename__ = "finding_triage"
    __table_args__ = (UniqueConstraint("client_id", "repo_full_name", "finding_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("client.id", ondelete="CASCADE"), index=True)
    repo_full_name: Mapped[str] = mapped_column(String(140), index=True)
    finding_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(15), default="open")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)

    client: Mapped[Client] = relationship(back_populates="triage")


class AiReview(Base):
    """The advisory AI review of one scan (see review.py). At most one per scan."""

    __tablename__ = "ai_review"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(
        ForeignKey("scan.id", ondelete="CASCADE"), unique=True, index=True
    )
    # 1-3 sentences on what is most wrong, most important first.
    overview: Mapped[list[str]] = mapped_column(JSON)
    # [{"path_a", "quote_a", "path_b", "quote_b", "explanation"}], quotes verified.
    conflicts: Mapped[list[dict]] = mapped_column(JSON)
    # What produced it, so results can be reproduced and reported honestly.
    model: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
