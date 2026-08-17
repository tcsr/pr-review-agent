"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("repo", sa.String, nullable=False),
        sa.Column("pr_number", sa.Integer, nullable=False),
        sa.Column("head_sha", sa.String, nullable=False),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("platform", "repo", "pr_number", "head_sha", "task",
                            name="uq_job"),
    )
    op.create_table(
        "posted_comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, nullable=False),
        sa.Column("external_comment_id", sa.String, nullable=False),
        sa.Column("marker", sa.String, nullable=False),
    )
    op.create_table(
        "dead_letter",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, nullable=False),
        sa.Column("last_error", sa.String, nullable=False),
        sa.Column("failed_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dead_letter")
    op.drop_table("posted_comments")
    op.drop_table("jobs")
