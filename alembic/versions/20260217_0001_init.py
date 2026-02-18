"""initial tables

Revision ID: 20260217_0001
Revises:
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260217_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "caregivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_caregivers_email"), "caregivers", ["email"], unique=True)
    op.create_index(op.f("ix_caregivers_id"), "caregivers", ["id"], unique=False)

    op.create_table(
        "children",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("caregiver_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["caregivers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_children_caregiver_id"), "children", ["caregiver_id"], unique=False)
    op.create_index(op.f("ix_children_id"), "children", ["id"], unique=False)

    op.create_table(
        "diary_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("submitted", sa.Boolean(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("responses", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("child_id", "entry_date", name="uq_diary_child_date"),
    )
    op.create_index(op.f("ix_diary_entries_child_id"), "diary_entries", ["child_id"], unique=False)
    op.create_index(op.f("ix_diary_entries_entry_date"), "diary_entries", ["entry_date"], unique=False)
    op.create_index(op.f("ix_diary_entries_id"), "diary_entries", ["id"], unique=False)

    op.create_table(
        "reminder_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("caregiver_id", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("reminder_times", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["caregivers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("caregiver_id"),
    )
    op.create_index(op.f("ix_reminder_settings_caregiver_id"), "reminder_settings", ["caregiver_id"], unique=True)
    op.create_index(op.f("ix_reminder_settings_id"), "reminder_settings", ["id"], unique=False)

    op.create_table(
        "notification_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("caregiver_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("keys", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["caregivers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_subscriptions_caregiver_id"), "notification_subscriptions", ["caregiver_id"], unique=False)
    op.create_index(op.f("ix_notification_subscriptions_id"), "notification_subscriptions", ["id"], unique=False)

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("caregiver_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("slot_time", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["caregivers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("caregiver_id", "child_id", "local_date", "slot_time", name="uq_notification_daily_slot"),
    )
    op.create_index(op.f("ix_notification_logs_caregiver_id"), "notification_logs", ["caregiver_id"], unique=False)
    op.create_index(op.f("ix_notification_logs_child_id"), "notification_logs", ["child_id"], unique=False)
    op.create_index(op.f("ix_notification_logs_id"), "notification_logs", ["id"], unique=False)
    op.create_index(op.f("ix_notification_logs_local_date"), "notification_logs", ["local_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_logs_local_date"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_id"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_child_id"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_caregiver_id"), table_name="notification_logs")
    op.drop_table("notification_logs")

    op.drop_index(op.f("ix_notification_subscriptions_id"), table_name="notification_subscriptions")
    op.drop_index(op.f("ix_notification_subscriptions_caregiver_id"), table_name="notification_subscriptions")
    op.drop_table("notification_subscriptions")

    op.drop_index(op.f("ix_reminder_settings_id"), table_name="reminder_settings")
    op.drop_index(op.f("ix_reminder_settings_caregiver_id"), table_name="reminder_settings")
    op.drop_table("reminder_settings")

    op.drop_index(op.f("ix_diary_entries_id"), table_name="diary_entries")
    op.drop_index(op.f("ix_diary_entries_entry_date"), table_name="diary_entries")
    op.drop_index(op.f("ix_diary_entries_child_id"), table_name="diary_entries")
    op.drop_table("diary_entries")

    op.drop_index(op.f("ix_children_id"), table_name="children")
    op.drop_index(op.f("ix_children_caregiver_id"), table_name="children")
    op.drop_table("children")

    op.drop_index(op.f("ix_caregivers_id"), table_name="caregivers")
    op.drop_index(op.f("ix_caregivers_email"), table_name="caregivers")
    op.drop_table("caregivers")
