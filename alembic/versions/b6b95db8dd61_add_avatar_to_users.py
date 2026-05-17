"""add avatar to users

Revision ID: b6b95db8dd61
Revises: 05abfb0254b3
Create Date: 2026-05-04 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6b95db8dd61"
down_revision: Union[str, Sequence[str], None] = "05abfb0254b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar")

