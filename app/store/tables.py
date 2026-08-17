from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("platform", "repo", "pr_number", "head_sha", "task", name="uq_job"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    repo: Mapped[str]
    pr_number: Mapped[int]
    head_sha: Mapped[str]
    task: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class PostedComment(Base):
    __tablename__ = "posted_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int]
    external_comment_id: Mapped[str]
    marker: Mapped[str]


class DeadLetter(Base):
    __tablename__ = "dead_letter"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int]
    last_error: Mapped[str]
    failed_at: Mapped[datetime] = mapped_column(default=_utcnow)
