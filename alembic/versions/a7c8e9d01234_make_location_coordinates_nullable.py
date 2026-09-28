"""make_location_coordinates_nullable_for_unmapped_sites

Revision ID: a7c8e9d01234
Revises: f1a891746c72
Create Date: 2026-09-29 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c8e9d01234'
down_revision: Union[str, None] = 'f1a891746c72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.alter_column('latitude',
                              existing_type=sa.Numeric(precision=10, scale=7),
                              nullable=True)
        batch_op.alter_column('longitude',
                              existing_type=sa.Numeric(precision=10, scale=7),
                              nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.alter_column('longitude',
                              existing_type=sa.Numeric(precision=10, scale=7),
                              nullable=False)
        batch_op.alter_column('latitude',
                              existing_type=sa.Numeric(precision=10, scale=7),
                              nullable=False)
