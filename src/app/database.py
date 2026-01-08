"""
投资机会雷达 - 数据库连接管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from .config import get_settings


def get_engine():
    """获取数据库引擎"""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,  # 生产环境关闭 SQL 日志
    )


def get_session_factory():
    """获取会话工厂"""
    engine = get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


SessionLocal = get_session_factory()


@contextmanager
def get_db_session() -> Session:
    """获取数据库会话（上下文管理器）"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI 依赖注入用"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
