"""
投资机会雷达 - 数据库模型 (SQLAlchemy ORM)
"""
from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Integer, SmallInteger, String, Text, Boolean, 
    Date, DateTime, Numeric, ForeignKey, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


class AppUser(Base):
    """登录账号"""
    __tablename__ = "app_user"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Settings(Base):
    """系统配置（阈值等）"""
    __tablename__ = "settings"
    
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PromptVersion(Base):
    """Prompt 版本管理"""
    __tablename__ = "prompt_version"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_name_version"),
        Index("idx_prompt_name_active", "name", "is_active"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # opportunity_analyzer / daily_digest
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    threshold: Mapped[Optional[int]] = mapped_column(Integer, default=60, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    response_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # 关联
    analysis_results: Mapped[List["AnalysisResult"]] = relationship(back_populates="prompt_version")


class SlotRun(Base):
    """批次运行记录（每天 5 次）"""
    __tablename__ = "slot_run"
    __table_args__ = (
        UniqueConstraint("run_date", "slot", name="uq_slot_run_date_slot"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(5), nullable=False)  # 07:00 / 12:00 / 14:00 / 18:00 / 22:00
    window_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)  # 0=running, 1=success, 2=failed
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)
    
    # 关联
    analysis_results: Mapped[List["AnalysisResult"]] = relationship(back_populates="slot_run")


class ContentItem(Base):
    """文章快照（来自 WeRSS）"""
    __tablename__ = "content_item"
    __table_args__ = (
        Index("idx_content_published_at", "published_at", postgresql_using="btree"),
        Index("idx_content_mp_published", "mp_id", "published_at"),
        Index("idx_content_analyzed_status", "analyzed_status", "published_at"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), default="werss", nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # WeRSS article_id
    mp_id: Mapped[Optional[str]] = mapped_column(String(255))
    mp_name: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    pic_url: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    werss_publish_time: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix 时间戳（秒）
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # WeRSS status
    raw_html: Mapped[Optional[str]] = mapped_column(Text)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    analyzed_status: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)  # 0=未分析, 1=已分析, 2=跳过, 3=失败
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    
    # 关联
    analysis_result: Mapped[Optional["AnalysisResult"]] = relationship(back_populates="content_item", uselist=False)


class AnalysisResult(Base):
    """单篇文章分析结果"""
    __tablename__ = "analysis_result"
    __table_args__ = (
        UniqueConstraint("content_item_id", name="uq_analysis_content_item"),
        Index("idx_analysis_score", "score"),
        Index("idx_analysis_has_opp", "has_opportunity", "score"),
        Index("idx_analysis_created_at", "created_at"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("content_item.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("slot_run.id", ondelete="SET NULL"))
    prompt_version_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("prompt_version.id"), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="deepseek-reasoner", nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    has_opportunity: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    action_status: Mapped[Optional[str]] = mapped_column(String(32), default="pending", nullable=True)  # pending/executed/skipped/watching
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # 关联
    content_item: Mapped["ContentItem"] = relationship(back_populates="analysis_result")
    slot_run: Mapped[Optional["SlotRun"]] = relationship(back_populates="analysis_results")
    prompt_version: Mapped["PromptVersion"] = relationship(back_populates="analysis_results")
    opportunities: Mapped[List["Opportunity"]] = relationship(back_populates="analysis_result", cascade="all, delete-orphan")


class Opportunity(Base):
    """机会点规范化表（从 JSON 抽取）"""
    __tablename__ = "opportunity"
    __table_args__ = (
        UniqueConstraint("analysis_id", "idx", name="uq_opportunity_analysis_idx"),
        Index("idx_opp_type_created", "type", "created_at"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("analysis_result.id", ondelete="CASCADE"), nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)  # JSON 中机会点序号
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # convertible_bond_ipo / fund_arbitrage 等
    title: Mapped[str] = mapped_column(Text, nullable=False)
    score_hint: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3))  # 0~1
    time_window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    time_window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    how_to: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    constraints: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    need_search_queries: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    numbers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # 关联
    analysis_result: Mapped["AnalysisResult"] = relationship(back_populates="opportunities")


class DailyReport(Base):
    """当日日报（22:00 必推）"""
    __tablename__ = "daily_report"
    __table_args__ = (
        Index("idx_report_date", "report_date"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    digest_md: Mapped[str] = mapped_column(Text, nullable=False)
    digest_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    slots_done: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # ["07:00", "12:00"...]
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class NotificationLog(Base):
    """推送记录（幂等与审计）"""
    __tablename__ = "notification_log"
    __table_args__ = (
        Index("idx_notify_date_slot", "report_date", "slot"),
        Index("idx_notify_status_sent", "status", "sent_at"),
    )
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(5), nullable=False)
    push_type: Mapped[str] = mapped_column(String(16), nullable=False)  # opportunity / daily
    msg_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 幂等键
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=失败, 1=成功
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
