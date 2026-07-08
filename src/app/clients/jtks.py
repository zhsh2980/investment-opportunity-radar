"""
今天看啥（jintiankansha.me）VIP RSS 客户端

每个已订阅专栏对应一条带个人 token 的 RSS 地址（配置在 JTKS_FEEDS）。
feed 的 content:encoded 含文章全文 HTML，guid 形如
http://www.jintiankansha.me/t/{external_id}，channel link 形如
http://www.jintiankansha.me/column/{column_id}。
"""
import re
import time
from datetime import datetime
from typing import Any, Dict, List

import feedparser
import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)

_CHANNEL_SUFFIX = " - 今天看啥"


class JTKSFeedError(Exception):
    """单个 feed 拉取/解析失败"""


class JTKSClient:
    """今天看啥 RSS 客户端"""

    def __init__(self, feeds: List[str] | None = None):
        settings = get_settings()
        self.feeds = feeds if feeds is not None else settings.jtks_feeds
        self.timeout = 30.0

    def fetch_feed(self, feed_url: str) -> List[Dict[str, Any]]:
        """
        拉取单个专栏 feed，返回统一结构的文章列表。

        Raises:
            JTKSFeedError: HTTP 失败或 feed 无法解析
        """
        try:
            resp = httpx.get(
                feed_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "investment-opportunity-radar/0.1"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise JTKSFeedError(f"feed 请求失败: {e}") from e

        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            raise JTKSFeedError(f"feed 解析失败: {parsed.bozo_exception}")

        channel_link = parsed.feed.get("link", "")
        m = re.search(r"/column/(\w+)", channel_link)
        column_id = m.group(1) if m else feed_url[-16:]
        column_name = (parsed.feed.get("title") or "").removesuffix(_CHANNEL_SUFFIX).strip() or column_id

        articles = []
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("guid", "")
            m = re.search(r"/t/(\w+)", guid)
            external_id = m.group(1) if m else guid
            if not external_id:
                logger.warning(f"feed 条目缺少 guid，跳过: {entry.get('title')}")
                continue

            # 全文优先取 content:encoded，退化到 summary/description
            html = ""
            if entry.get("content"):
                html = entry.content[0].get("value", "")
            if not html:
                html = entry.get("summary", "")

            published_at = None
            if entry.get("published_parsed"):
                published_at = datetime.fromtimestamp(time.mktime(entry.published_parsed))

            articles.append({
                "external_id": external_id,
                "title": entry.get("title", "无标题"),
                "url": entry.get("link", ""),
                "html": html,
                "published_at": published_at,
                "column_id": column_id,
                "column_name": column_name,
            })

        return articles

    def fetch_all(self) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        拉取全部专栏 feed。

        Returns:
            (文章列表, 失败的 feed 映射 {feed_url: 错误信息})
        """
        all_articles: List[Dict[str, Any]] = []
        failures: Dict[str, str] = {}
        for feed_url in self.feeds:
            try:
                articles = self.fetch_feed(feed_url)
                all_articles.extend(articles)
                name = articles[0]["column_name"] if articles else feed_url
                logger.info(f"拉取专栏 feed 成功: {name}, {len(articles)} 篇")
            except JTKSFeedError as e:
                logger.error(f"拉取专栏 feed 失败: {feed_url[:60]}..., {e}")
                failures[feed_url] = str(e)
        return all_articles, failures


_client: JTKSClient | None = None


def get_jtks_client() -> JTKSClient:
    """获取客户端单例"""
    global _client
    if _client is None:
        _client = JTKSClient()
    return _client
