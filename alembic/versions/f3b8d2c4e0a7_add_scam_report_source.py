"""add source column to scam_reports

Revision ID: f3b8d2c4e0a7
Revises: e8a4c1f06b21
Create Date: 2026-05-17 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b8d2c4e0a7"
down_revision: Union[str, Sequence[str], None] = "e8a4c1f06b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


report_source_enum = sa.Enum(
    "USER_MANUAL", "SMS_INBOX",
    name="report_source",
)


def upgrade() -> None:
    bind = op.get_bind()
    report_source_enum.create(bind, checkfirst=True)
    op.add_column(
        "scam_reports",
        sa.Column(
            "source",
            report_source_enum,
            nullable=False,
            server_default="USER_MANUAL",
        ),
    )


def downgrade() -> None:
    op.drop_column("scam_reports", "source")
    report_source_enum.drop(op.get_bind(), checkfirst=True)
