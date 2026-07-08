"""
信息源分类配置解析与入库回填。
"""
from datetime import datetime
from unittest.mock import patch

from src.app.config import JTKSFeedConfig
from src.app.domain.models import ContentItem
from src.app.services.analyzer import fetch_and_save_articles


def test_jtks_feed_config_defaults_to_opportunity_category():
    feed = JTKSFeedConfig(url="http://rss.jintiankansha.me/rss/abc")
    assert feed.category == "opportunity"


def test_jtks_feed_config_accepts_explicit_broad_category():
    feed = JTKSFeedConfig(url="http://rss.jintiankansha.me/rss/abc", category="broad")
    assert feed.category == "broad"


def _fake_article(external_id, category, published_at):
    return {
        "external_id": external_id,
        "title": f"文章 {external_id}",
        "url": f"https://mp.weixin.qq.com/s/{external_id}",
        "html": "<p>正文</p>",
        "published_at": published_at,
        "column_id": "col-1",
        "column_name": "测试专栏",
        "category": category,
    }


def test_fetch_and_save_articles_backfills_source_category(db_session):
    now = datetime.now()
    articles = [
        _fake_article("a1", "opportunity", now),
        _fake_article("a2", "broad", now),
    ]

    with patch(
        "src.app.clients.jtks.JTKSClient.fetch_all",
        return_value=(articles, {}),
    ):
        fetch_and_save_articles(
            session=db_session,
            start_time=now.replace(hour=0, minute=0),
            end_time=now.replace(hour=23, minute=59),
        )

    item_a1 = db_session.query(ContentItem).filter(ContentItem.external_id == "a1").one()
    item_a2 = db_session.query(ContentItem).filter(ContentItem.external_id == "a2").one()
    assert item_a1.source_category == "opportunity"
    assert item_a2.source_category == "broad"
