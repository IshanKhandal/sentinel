"""add_raw_text_and_detection_metadata_to_detections

Revision ID: f1a891746c72
Revises: c1a5639ce6ba
Create Date: 2026-09-28 23:40:46.181924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a891746c72'
down_revision: Union[str, None] = 'c1a5639ce6ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('raw_text', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('detection_metadata', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.drop_column('detection_metadata')
        batch_op.drop_column('raw_text')
