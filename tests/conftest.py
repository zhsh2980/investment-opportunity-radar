"""
pytest 测试基础设施：内存 SQLite + 测试数据工厂。

注意：BigInteger 主键在 SQLite 方言下不会走 rowid 自增别名（不同于纯 INTEGER），
所以这里的所有测试数据工厂都手动分配自增 id，而不是依赖数据库自动生成。
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.domain.models import AnalysisResult, Base, ContentItem, PromptVersion


@pytest.fixture()
def db_session():
    # StaticPool + check_same_thread=False: FastAPI TestClient 在独立线程里跑同步
    # 路由处理函数，这里要保证所有线程复用同一个内存 sqlite 连接，而不是各开各的
    # （否则每个线程会看到一个空的、没建表的新内存库）。
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def next_id():
    counter = {"n": 0}

    def _next():
        counter["n"] += 1
        return counter["n"]

    return _next


@pytest.fixture()
def make_content_item(db_session, next_id):
    def _make(**overrides):
        item_id = overrides.pop("id", None) or next_id()
        published_at = overrides.pop("published_at", datetime.now())
        defaults = dict(
            id=item_id,
            source_type="jtks",
            source_id="test-column",
            external_id=f"ext-{item_id}",
            mp_id="test-column",
            mp_name="测试来源",
            title="测试标题",
            url="https://mp.weixin.qq.com/s/test",
            published_at=published_at,
            werss_publish_time=int(published_at.timestamp()),
            status=1,
            raw_html="<p>正文内容</p>",
            raw_text="正文内容",
            content_hash=f"hash-{item_id}",
            analyzed_status=0,
        )
        defaults.update(overrides)
        item = ContentItem(**defaults)
        db_session.add(item)
        db_session.flush()
        return item

    return _make


@pytest.fixture()
def make_analysis_result(db_session, next_id):
    def _make(content_item, **overrides):
        result_id = overrides.pop("id", None) or next_id()
        defaults = dict(
            id=result_id,
            content_item_id=content_item.id,
            model="deepseek-reasoner",
            score=70,
            has_opportunity=True,
            result_json={
                "score": 70,
                "has_opportunity": True,
                "key_points": ["测试要点一", "测试要点二"],
                "opportunity_types": ["other"],
                "no_opportunity_reason": "",
            },
            summary_md="1. 测试要点一 ｜ 2. 测试要点二",
        )
        defaults.update(overrides)
        analysis = AnalysisResult(**defaults)
        db_session.add(analysis)
        db_session.flush()
        return analysis

    return _make


@pytest.fixture()
def make_prompt_version(db_session, next_id):
    def _make(**overrides):
        pv_id = overrides.pop("id", None) or next_id()
        defaults = dict(
            id=pv_id,
            name="opportunity_analyzer",
            version=1,
            is_active=True,
            threshold=60,
            system_prompt="test system prompt",
            user_template="test user template",
        )
        defaults.update(overrides)
        pv = PromptVersion(**defaults)
        db_session.add(pv)
        db_session.flush()
        return pv

    return _make
