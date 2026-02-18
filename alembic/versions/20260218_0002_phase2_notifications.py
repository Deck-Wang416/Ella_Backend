"""phase2 notification delivery and subscription fields

Revision ID: 20260218_0002
Revises: 20260217_0001
Create Date: 2026-02-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260218_0002"
down_revision: Union[str, None] = "20260217_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notification_subscriptions", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column(
        "notification_subscriptions",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_unique_constraint(
        "uq_subscription_unique_endpoint",
        "notification_subscriptions",
        ["caregiver_id", "platform", "endpoint"],
    )

    op.add_column("notification_logs", sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notification_logs", sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE notification_logs SET status = 'pending' WHERE status IS NULL")

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_log_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["notification_log_id"], ["notification_logs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["notification_subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_deliveries_id"), "notification_deliveries", ["id"], unique=False)
    op.create_index(
        op.f("ix_notification_deliveries_notification_log_id"),
        "notification_deliveries",
        ["notification_log_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_subscription_id"),
        "notification_deliveries",
        ["subscription_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_deliveries_subscription_id"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_notification_log_id"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_id"), table_name="notification_deliveries")
    op.drop_table("notification_deliveries")

    op.drop_column("notification_logs", "failed_count")
    op.drop_column("notification_logs", "delivered_count")

    op.drop_constraint("uq_subscription_unique_endpoint", "notification_subscriptions", type_="unique")
    op.drop_column("notification_subscriptions", "updated_at")
    op.drop_column("notification_subscriptions", "active")
