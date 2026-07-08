"""
投资机会雷达 - 钉钉推送客户端

钉钉自定义机器人 API 客户端，用于发送机会提醒和日报。
- 支持加签安全设置
- 支持 Markdown 消息格式
- 幂等推送（msgUuid）
"""
import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class DingTalkClient:
    """钉钉机器人 API 客户端"""

    ENDPOINT = "https://oapi.dingtalk.com/robot/send"

    def __init__(self):
        settings = get_settings()
        self.webhook = settings.dingtalk_webhook
        self.secret = settings.dingtalk_secret

        # HTTP 客户端
        self._client = httpx.Client(timeout=30.0)

    def _sign(self, timestamp: int) -> str:
        """
        生成加签签名
        
        Args:
            timestamp: 当前时间戳（毫秒）
        
        Returns:
            签名字符串
        """
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(
            secret_enc,
            string_to_sign_enc,
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return sign

    def _get_signed_url(self) -> str:
        """获取带签名的 webhook URL"""
        if not self.secret:
            return self.webhook

        timestamp = int(round(time.time() * 1000))
        sign = self._sign(timestamp)

        # webhook 已经包含 access_token，需要追加 timestamp 和 sign
        separator = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{separator}timestamp={timestamp}&sign={sign}"

    def send_markdown(
        self,
        title: str,
        text: str,
        msg_uuid: Optional[str] = None,
        at_mobiles: Optional[list] = None,
        at_all: bool = False,
    ) -> Dict[str, Any]:
        """
        发送 Markdown 消息
        
        Args:
            title: 消息标题（会话列表显示）
            text: Markdown 内容
            msg_uuid: 幂等 key（同一个 key 不会重复发送）
            at_mobiles: @指定手机号的人
            at_all: 是否 @所有人
        
        Returns:
            钉钉 API 响应
        """
        url = self._get_signed_url()

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        }

        # 幂等 key
        if msg_uuid:
            payload["msgUuid"] = msg_uuid

        # @人
        at_config = {"isAtAll": at_all}
        if at_mobiles:
            at_config["atMobiles"] = at_mobiles
        payload["at"] = at_config

        logger.info(f"钉钉推送: title='{title}', uuid={msg_uuid}")

        response = self._client.post(url, json=payload)
        response.raise_for_status()

        result = response.json()

        if result.get("errcode") != 0:
            logger.error(f"钉钉推送失败: {result}")
        else:
            logger.info("钉钉推送成功")

        return result

    def send_text(
        self,
        content: str,
        msg_uuid: Optional[str] = None,
        at_mobiles: Optional[list] = None,
        at_all: bool = False,
    ) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            msg_uuid: 幂等 key
            at_mobiles: @指定手机号的人
            at_all: 是否 @所有人
        
        Returns:
            钉钉 API 响应
        """
        url = self._get_signed_url()

        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }

        if msg_uuid:
            payload["msgUuid"] = msg_uuid

        at_config = {"isAtAll": at_all}
        if at_mobiles:
            at_config["atMobiles"] = at_mobiles
        payload["at"] = at_config

        logger.info(f"钉钉推送文本: {content[:50]}...")

        response = self._client.post(url, json=payload)
        response.raise_for_status()

        result = response.json()

        if result.get("errcode") != 0:
            logger.error(f"钉钉推送失败: {result}")

        return result

    def send_opportunity_alert(
        self,
        mp_name: str,
        score: int,
        opportunity_type: str,
        key_points: List[str],
        article_url: str,
        msg_uuid: str,
    ) -> Dict[str, Any]:
        """
        发送机会简报：标题行 + 要点列表 + 仅一个原文链接

        Args:
            mp_name: 公众号名称
            score: 评分
            opportunity_type: 机会类型
            key_points: AI 输出的要点列表
            article_url: 公众号原文链接（为空时退化为无链接的纯文本）
            msg_uuid: 幂等 key

        Returns:
            钉钉 API 响应
        """
        heading = f"🎯 {opportunity_type} · {score}分 · {mp_name}"
        points_md = "\n".join(f"- {p}" for p in key_points) if key_points else "（无要点）"
        link_md = f"\n\n[查看原文]({article_url})" if article_url else ""

        text = f"""### {heading}

{points_md}{link_md}
"""

        return self.send_markdown(
            title=heading,
            text=text,
            msg_uuid=msg_uuid,
        )

    def send_daily_report(
        self,
        date: str,
        has_opportunity: bool,
        total_articles: int,
        total_opportunities: int,
        digest: str,
        msg_uuid: str,
    ) -> Dict[str, Any]:
        """
        发送每日日报（22:00 必推，纯钉钉消息，不链接系统内任何页面）

        Args:
            date: 日期 YYYY-MM-DD
            has_opportunity: 是否有机会
            total_articles: 文章总数
            total_opportunities: 机会总数
            digest: 按信源分组好的正文（已提醒的条目已被 digest 内容标注，不重复展开）
            msg_uuid: 幂等 key

        Returns:
            钉钉 API 响应
        """
        status_emoji = "✅" if has_opportunity else "📭"
        status_text = "发现机会" if has_opportunity else "暂无机会"

        text = f"""### 📊 {date} 日报

**状态**: {status_emoji} {status_text}

**统计**: 分析 {total_articles} 篇文章，发现 {total_opportunities} 个机会

---

{digest}
"""

        return self.send_markdown(
            title=f"📊 {date} 日报 - {status_text}",
            text=text,
            msg_uuid=msg_uuid,
        )

    def close(self):
        """关闭客户端"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 单例模式
_client: Optional[DingTalkClient] = None


def get_dingtalk_client() -> DingTalkClient:
    """获取钉钉客户端单例"""
    global _client
    if _client is None:
        _client = DingTalkClient()
    return _client
