"""analysis_result.prompt_version_id 放开 NOT NULL，对齐 ORM 模型

迁移 001 建表时该列是 NOT NULL，后来 ORM 模型改成 nullable=True（未配置
活跃 Prompt 时用内置默认模板分析，prompt_version_id 为空）但一直没有写
对应迁移。本地测试用 ORM create_all 建表所以从未暴露；生产 prompt_version
表为空时，分析结果入库直接违反 NOT NULL 约束，且毒化 session 导致整个
批次卡死、日报停发。

Revision ID: 005_prompt_version_nullable
Revises: 004_content_item_source_category
Create Date: 2026-07-09

注意：revision 字符串必须 ≤32 字符（alembic_version.version_num 是
varchar(32)，004 恰好 32 字符压线通过，更长会在 UPDATE 版本号时截断报错）。

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "005_prompt_version_nullable"
down_revision: Union[str, None] = "004_content_item_source_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "analysis_result",
        "prompt_version_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    # 注意：降级前需保证表里没有 prompt_version_id 为 NULL 的行
    op.alter_column(
        "analysis_result",
        "prompt_version_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
