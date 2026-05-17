"""drop unused columns and FK

Revision ID: d7f2a3b91c04
Revises: b6b95db8dd61
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7f2a3b91c04"
down_revision: Union[str, Sequence[str], None] = "b6b95db8dd61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: drop is_verified
    op.drop_column("users", "is_verified")

    # devices: drop phone and platform
    op.drop_column("devices", "phone")
    op.drop_column("devices", "platform")
    op.execute("DROP TYPE IF EXISTS platform_type")

    # scam_numbers: drop is_verified, is_ai_vetted, metadata_info
    op.drop_column("scam_numbers", "is_verified")
    op.drop_column("scam_numbers", "is_ai_vetted")
    op.drop_column("scam_numbers", "metadata_info")

    # scam_reports: drop FK + columns
    op.drop_index("ix_scam_reports_deviceId", table_name="scam_reports")
    with op.batch_alter_table("scam_reports") as batch_op:
        batch_op.drop_constraint("scam_reports_deviceId_fkey", type_="foreignkey")
    op.drop_column("scam_reports", "deviceId")
    op.drop_column("scam_reports", "reportType")
    op.drop_column("scam_reports", "description")
    op.drop_column("scam_reports", "evidence_urls")
    op.drop_column("scam_reports", "messages")


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    op.add_column(
        "scam_reports",
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "scam_reports",
        sa.Column("evidence_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("scam_reports", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("scam_reports", sa.Column("reportType", sa.String(), nullable=True))
    op.add_column("scam_reports", sa.Column("deviceId", sa.String(), nullable=True))
    op.create_index("ix_scam_reports_deviceId", "scam_reports", ["deviceId"], unique=False)
    with op.batch_alter_table("scam_reports") as batch_op:
        batch_op.create_foreign_key(
            "scam_reports_deviceId_fkey", "devices", ["deviceId"], ["deviceId"]
        )

    op.add_column(
        "scam_numbers",
        sa.Column("metadata_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("scam_numbers", sa.Column("is_ai_vetted", sa.Boolean(), nullable=True))
    op.add_column("scam_numbers", sa.Column("is_verified", sa.Boolean(), nullable=True))

    op.execute(
        "CREATE TYPE platform_type AS ENUM ('ANDROID', 'IOS', 'WEB', 'OTHER')"
    )
    op.add_column(
        "devices",
        sa.Column(
            "platform",
            sa.Enum("ANDROID", "IOS", "WEB", "OTHER", name="platform_type"),
            nullable=True,
        ),
    )
    op.add_column("devices", sa.Column("phone", sa.String(), nullable=True))

    op.add_column("users", sa.Column("is_verified", sa.Boolean(), nullable=True))
