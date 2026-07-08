"""content_item 增加 source_category（机会类/宽泛类），驱动推送策略

Revision ID: 004_content_item_source_category
Revises: 003_prompt_split_action_status
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_content_item_source_category"
down_revision: Union[str, None] = "003_prompt_split_action_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content_item",
        sa.Column("source_category", sa.String(16), nullable=False, server_default="opportunity"),
    )


def downgrade() -> None:
    op.drop_column("content_item", "source_category")
