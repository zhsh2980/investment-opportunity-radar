"""opportunity_track: 机会跟踪流水表

Revision ID: 002_opportunity_track
Revises: 001_initial
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_opportunity_track'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'opportunity_track',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('analysis_id', sa.BigInteger(), sa.ForeignKey('analysis_result.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('amount', sa.Numeric(16, 2), nullable=True),
        sa.Column('pnl', sa.Numeric(16, 2), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_track_analysis', 'opportunity_track', ['analysis_id'])
    op.create_index('idx_track_action_created', 'opportunity_track', ['action', 'created_at'])


def downgrade() -> None:
    op.drop_index('idx_track_action_created', table_name='opportunity_track')
    op.drop_index('idx_track_analysis', table_name='opportunity_track')
    op.drop_table('opportunity_track')
