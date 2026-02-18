"""add endpoint_or_token field for notification subscriptions

Revision ID: 20260218_0003
Revises: 20260218_0002
Create Date: 2026-02-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260218_0003"
down_revision: Union[str, None] = "20260218_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    sub_cols = {col["name"] for col in inspector.get_columns("notification_subscriptions")}
    if "endpoint_or_token" not in sub_cols:
        op.add_column(
            "notification_subscriptions",
            sa.Column("endpoint_or_token", sa.String(length=500), nullable=True),
        )

    op.execute(
        "UPDATE notification_subscriptions "
        "SET endpoint_or_token = endpoint "
        "WHERE endpoint_or_token IS NULL OR endpoint_or_token = ''"
    )

    sub_indexes = {idx["name"] for idx in inspector.get_indexes("notification_subscriptions")}
    if "uq_subscription_unique_endpoint" in sub_indexes:
        op.drop_index("uq_subscription_unique_endpoint", table_name="notification_subscriptions")
    if "uq_subscription_unique_endpoint_or_token" not in sub_indexes:
        op.create_index(
            "uq_subscription_unique_endpoint_or_token",
            "notification_subscriptions",
            ["caregiver_id", "platform", "endpoint_or_token"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("uq_subscription_unique_endpoint_or_token", table_name="notification_subscriptions")
    op.drop_column("notification_subscriptions", "endpoint_or_token")
