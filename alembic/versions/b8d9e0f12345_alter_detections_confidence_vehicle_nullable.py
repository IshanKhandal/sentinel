"""alter_detections_confidence_vehicle_nullable

Revision ID: b8d9e0f12345
Revises: a7c8e9d01234
Create Date: 2026-09-29 01:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d9e0f12345'
down_revision: Union[str, None] = 'a7c8e9d01234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.alter_column('confidence_vehicle',
                              existing_type=sa.Float(),
                              nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.alter_column('confidence_vehicle',
                              existing_type=sa.Float(),
                              nullable=False)
