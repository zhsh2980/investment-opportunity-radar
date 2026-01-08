"""Initial tables: app_user, settings, prompt_version, slot_run, content_item, analysis_result, opportunity, daily_report, notification_log

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === app_user ===
    op.create_table(
        'app_user',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('username', sa.String(64), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )

    # === settings ===
    op.create_table(
        'settings',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # === prompt_version ===
    op.create_table(
        'prompt_version',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('threshold', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('response_schema', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('name', 'version', name='uq_prompt_name_version'),
    )
    op.create_index('idx_prompt_name_active', 'prompt_version', ['name', 'is_active'])

    # === slot_run ===
    op.create_table(
        'slot_run',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(5), nullable=False),
        sa.Column('window_start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('stats', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.UniqueConstraint('run_date', 'slot', name='uq_slot_run_date_slot'),
    )

    # === content_item ===
    op.create_table(
        'content_item',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='werss'),
        sa.Column('source_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('external_id', sa.String(255), unique=True, nullable=False),
        sa.Column('mp_id', sa.String(255), nullable=True),
        sa.Column('mp_name', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('pic_url', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('werss_publish_time', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('raw_html', sa.Text(), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('analyzed_status', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.create_index('idx_content_published_at', 'content_item', ['published_at'])
    op.create_index('idx_content_mp_published', 'content_item', ['mp_id', 'published_at'])
    op.create_index('idx_content_analyzed_status', 'content_item', ['analyzed_status', 'published_at'])

    # === analysis_result ===
    op.create_table(
        'analysis_result',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('content_item_id', sa.BigInteger(), sa.ForeignKey('content_item.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.BigInteger(), sa.ForeignKey('slot_run.id', ondelete='SET NULL'), nullable=True),
        sa.Column('prompt_version_id', sa.BigInteger(), sa.ForeignKey('prompt_version.id'), nullable=False),
        sa.Column('model', sa.String(64), nullable=False, server_default='deepseek-reasoner'),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('has_opportunity', sa.Boolean(), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('summary_md', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('content_item_id', name='uq_analysis_content_item'),
    )
    op.create_index('idx_analysis_score', 'analysis_result', ['score'])
    op.create_index('idx_analysis_has_opp', 'analysis_result', ['has_opportunity', 'score'])
    op.create_index('idx_analysis_created_at', 'analysis_result', ['created_at'])

    # === opportunity ===
    op.create_table(
        'opportunity',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('analysis_id', sa.BigInteger(), sa.ForeignKey('analysis_result.id', ondelete='CASCADE'), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(64), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('score_hint', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=True),
        sa.Column('time_window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('time_window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('how_to', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('constraints', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('need_search_queries', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('numbers', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('analysis_id', 'idx', name='uq_opportunity_analysis_idx'),
    )
    op.create_index('idx_opp_type_created', 'opportunity', ['type', 'created_at'])

    # === daily_report ===
    op.create_table(
        'daily_report',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('report_date', sa.Date(), unique=True, nullable=False),
        sa.Column('digest_md', sa.Text(), nullable=False),
        sa.Column('digest_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('slots_done', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('stats', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_report_date', 'daily_report', ['report_date'])

    # === notification_log ===
    op.create_table(
        'notification_log',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(5), nullable=False),
        sa.Column('push_type', sa.String(16), nullable=False),
        sa.Column('msg_uuid', sa.String(64), unique=True, nullable=False),
        sa.Column('target_url', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.SmallInteger(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_notify_date_slot', 'notification_log', ['report_date', 'slot'])
    op.create_index('idx_notify_status_sent', 'notification_log', ['status', 'sent_at'])


def downgrade() -> None:
    op.drop_table('notification_log')
    op.drop_table('daily_report')
    op.drop_table('opportunity')
    op.drop_table('analysis_result')
    op.drop_table('content_item')
    op.drop_table('slot_run')
    op.drop_table('prompt_version')
    op.drop_table('settings')
    op.drop_table('app_user')
