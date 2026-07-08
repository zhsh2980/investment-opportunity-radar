"""prompt_version 拆分 system_prompt/user_template; analysis_result 增加 action_status

Revision ID: 003_prompt_split_action_status
Revises: 002_opportunity_track
Create Date: 2026-07-08

模型早已把 prompt_version.prompt_text 拆成 system_prompt + user_template，
并给 analysis_result 加了 action_status（工作台操作状态），但一直缺少对应迁移。
本迁移补齐 schema，system_prompt 从旧 prompt_text 回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_prompt_split_action_status"
down_revision: Union[str, None] = "002_opportunity_track"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === prompt_version: prompt_text -> system_prompt + user_template ===
    op.add_column("prompt_version", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("prompt_version", sa.Column("user_template", sa.Text(), nullable=True))
    op.execute(
        "UPDATE prompt_version SET system_prompt = COALESCE(prompt_text, ''), "
        "user_template = '' WHERE system_prompt IS NULL"
    )
    op.alter_column("prompt_version", "system_prompt", nullable=False)
    op.alter_column("prompt_version", "user_template", nullable=False)
    op.drop_column("prompt_version", "prompt_text")
    # response_schema 在模型中已是可空
    op.alter_column("prompt_version", "response_schema", nullable=True)

    # === analysis_result: 工作台操作状态 ===
    op.add_column(
        "analysis_result",
        sa.Column("action_status", sa.String(32), nullable=True, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_column("analysis_result", "action_status")
    op.add_column("prompt_version", sa.Column("prompt_text", sa.Text(), nullable=True))
    op.execute("UPDATE prompt_version SET prompt_text = system_prompt")
    op.alter_column("prompt_version", "prompt_text", nullable=False)
    op.alter_column("prompt_version", "response_schema", nullable=False)
    op.drop_column("prompt_version", "user_template")
    op.drop_column("prompt_version", "system_prompt")
