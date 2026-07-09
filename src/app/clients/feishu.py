"""
投资机会雷达 - 飞书（Lark）推送客户端

飞书自建应用机器人 API 客户端，与 DingTalkClient 并行、独立运行——
两个推送渠道互不依赖，一个平台的 API 变化或故障不影响另一个。

- 用 tenant_access_token 鉴权（app_id + app_secret 换取，内存内缓存到过期）
- 消息用 interactive 卡片 + markdown 元素承载（飞书没有钉钉那种
  msgtype=markdown 的简单格式，卡片是官方推荐的等价方案）
- 幂等推送用请求体的 uuid 字段（同一个 uuid 短时间内不会重复发送）
"""
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class FeishuClient:
    """飞书自建应用机器人 API 客户端"""

    TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MESSAGE_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self):
        settings = get_settings()
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.chat_id = settings.feishu_chat_id

        self._client = httpx.Client(timeout=30.0)
        self._token: Optional[str] = None
        self._token_expire_at: float = 0

    def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token，内存缓存到快过期前 60 秒"""
        now = time.time()
        if self._token and now < self._token_expire_at - 60:
            return self._token

        response = self._client.post(
            self.TOKEN_ENDPOINT,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 tenant_access_token 失败: {data}")

        self._token = data["tenant_access_token"]
        self._token_expire_at = now + data.get("expire", 7200)
        return self._token

    def send_markdown(
        self,
        title: str,
        text: str,
        msg_uuid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发送 Markdown 消息（用 interactive 卡片承载）

        Args:
            title: 卡片标题
            text: Markdown 内容
            msg_uuid: 幂等 key（同一个 key 短时间内不会重复发送）

        Returns:
            飞书 API 响应
        """
        token = self._get_tenant_access_token()

        card = {
            "header": {"title": {"content": title, "tag": "plain_text"}},
            "elements": [{"tag": "markdown", "content": text}],
        }
        payload: Dict[str, Any] = {
            "receive_id": self.chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        if msg_uuid:
            payload["uuid"] = msg_uuid

        logger.info(f"飞书推送: title='{title}', uuid={msg_uuid}")

        response = self._client.post(
            self.MESSAGE_ENDPOINT,
            params={"receive_id_type": "chat_id"},
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

        result = response.json()
        if result.get("code") != 0:
            logger.error(f"飞书推送失败: {result}")
        else:
            logger.info("飞书推送成功")

        return result

    def send_opportunity_alert(
        self,
        mp_name: str,
        score: int,
        opportunity_type: str,
        key_points: List[str],
        article_url: str,
        msg_uuid: str,
        publish_label: str = "",
    ) -> Dict[str, Any]:
        """发送机会简报：标题行 + 要点列表 + 仅一个原文链接（与 DingTalkClient 同构）"""
        heading = f"🎯 {opportunity_type} · {score}分 · {mp_name}"
        meta_md = f"🕐 发布于 {publish_label}\n\n" if publish_label else ""
        points_md = "\n".join(f"- {p}" for p in key_points) if key_points else "（无要点）"
        link_md = f"\n\n[查看原文]({article_url})" if article_url else ""

        text = f"{meta_md}{points_md}{link_md}"

        return self.send_markdown(title=heading, text=text, msg_uuid=msg_uuid)

    def send_daily_report(
        self,
        date: str,
        has_opportunity: bool,
        total_articles: int,
        total_opportunities: int,
        digest: str,
        msg_uuid: str,
    ) -> Dict[str, Any]:
        """发送每日日报（与 DingTalkClient 同构）"""
        status_emoji = "✅" if has_opportunity else "📭"
        status_text = "发现机会" if has_opportunity else "暂无机会"

        text = (
            f"**状态**: {status_emoji} {status_text}\n\n"
            f"**统计**: 分析 {total_articles} 篇文章，发现 {total_opportunities} 个机会\n\n"
            "---\n\n"
            f"{digest}"
        )

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
_client: Optional[FeishuClient] = None


def get_feishu_client() -> FeishuClient:
    """获取飞书客户端单例"""
    global _client
    if _client is None:
        _client = FeishuClient()
    return _client


def is_feishu_configured() -> bool:
    """飞书推送是否已配置（app_id + chat_id 均非空）"""
    settings = get_settings()
    return bool(settings.feishu_app_id and settings.feishu_chat_id)
