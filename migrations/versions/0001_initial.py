"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS = sa.Enum(
    "draft", "new", "in_progress", "done", "rejected",
    name="applicationstatus", native_enum=False, length=20,
)
_DIRECTION = sa.Enum(
    "job", "psy", "law", "other", name="direction", native_enum=False, length=10
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_blocked", sa.Boolean(), server_default="0"),
        sa.UniqueConstraint("max_user_id"),
    )
    op.create_index("ix_users_max_user_id", "users", ["max_user_id"], unique=True)

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fio", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("phone_verified", sa.Boolean(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("is_svo_participant", sa.Boolean(), nullable=True),
        sa.Column("status", _STATUS, server_default="new", nullable=False),
        sa.Column("is_repeat", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticket"),
    )
    op.create_index("ix_applications_ticket", "applications", ["ticket"], unique=True)
    op.create_index("ix_applications_user_id", "applications", ["user_id"])

    op.create_table(
        "consultations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("direction", _DIRECTION, nullable=False),
        sa.Column("fio", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("phone_verified", sa.Boolean(), nullable=True),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column("status", _STATUS, server_default="new", nullable=False),
        sa.Column("is_repeat", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticket"),
    )
    op.create_index("ix_consultations_ticket", "consultations", ["ticket"], unique=True)
    op.create_index("ix_consultations_user_id", "consultations", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_events_user_id", "events", ["user_id"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("consultations")
    op.drop_table("applications")
    op.drop_table("users")
