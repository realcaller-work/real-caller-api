"""add user_id to scam_reports for consensus path

Revision ID: b4d9e7a52f18
Revises: f3b8d2c4e0a7
Create Date: 2026-05-17 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4d9e7a52f18"
down_revision: Union[str, Sequence[str], None] = "f3b8d2c4e0a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scam_reports",
        sa.Column("user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "scam_reports_user_id_fkey",
        "scam_reports",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_scam_reports_phone_user",
        "scam_reports",
        ["phone", "user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scam_reports_phone_user", table_name="scam_reports")
    op.drop_constraint("scam_reports_user_id_fkey", "scam_reports", type_="foreignkey")
    op.drop_column("scam_reports", "user_id")
