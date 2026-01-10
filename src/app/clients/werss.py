"""
投资机会雷达 - WeRSS 客户端

WeRSS API 客户端，用于获取公众号文章列表和内容。
- Token 自动获取和刷新
- 文章列表和详情获取
- 同机访问使用 http://localhost:8001
"""
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class WeRSSClient:
    """WeRSS HTTP API 客户端"""
    
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.werss_base_url.rstrip('/')
        self.api_prefix = "/api/v1/wx"
        self.username = settings.werss_username
        self.password = settings.werss_password
        
        # Token 状态
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        
        # HTTP 客户端
        self._client = httpx.Client(timeout=30.0)
    
    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.api_prefix}"
    
    def _is_token_valid(self) -> bool:
        """检查 token 是否有效"""
        if not self._token or not self._token_expires_at:
            return False
        # 提前 5 分钟认为过期
        return datetime.now() < self._token_expires_at - timedelta(minutes=5)
    
    def _get_token(self) -> str:
        """获取或刷新 token"""
        if self._is_token_valid():
            return self._token
        
        # 尝试刷新
        if self._token:
            try:
                return self._refresh_token()
            except Exception as e:
                logger.warning(f"WeRSS token 刷新失败，重新登录: {e}")
        
        # 重新登录
        return self._login()
    
    def _login(self) -> str:
        """登录获取 token"""
        url = f"{self.api_url}/auth/token"
        data = {
            "username": self.username,
            "password": self.password,
        }
        
        logger.info(f"WeRSS 登录: {self.username}")
        response = self._client.post(url, data=data)
        response.raise_for_status()
        
        result = response.json()
        self._token = result.get("access_token")
        expires_in = result.get("expires_in", 259200)  # 默认 3 天
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        logger.info(f"WeRSS 登录成功，token 有效期 {expires_in} 秒")
        return self._token
    
    def _refresh_token(self) -> str:
        """刷新 token"""
        url = f"{self.api_url}/auth/refresh"
        headers = {"Authorization": f"Bearer {self._token}"}
        
        logger.info("WeRSS 刷新 token")
        response = self._client.post(url, headers=headers)
        response.raise_for_status()
        
        result = response.json()
        self._token = result.get("access_token")
        expires_in = result.get("expires_in", 259200)
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        logger.info("WeRSS token 刷新成功")
        return self._token
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """带认证的请求"""
        token = self._get_token()
        url = f"{self.api_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        
        response = self._client.request(method, url, headers=headers, **kwargs)
        
        # 处理 401，尝试重新登录后重试
        if response.status_code == 401:
            logger.warning("WeRSS 返回 401，重新登录")
            self._token = None
            token = self._get_token()
            headers["Authorization"] = f"Bearer {token}"
            response = self._client.request(method, url, headers=headers, **kwargs)
        
        response.raise_for_status()
        return response.json()
    
    def get_mps(self) -> List[Dict[str, Any]]:
        """获取公众号列表"""
        result = self._request("GET", "/mps")
        # WeRSS API 返回格式: {"code":0,"data":{"list":[...]}}
        return result.get("data", {}).get("list", [])
    
    def get_articles(
        self,
        mp_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        has_content: bool = False,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取文章列表
        
        Args:
            mp_id: 公众号 ID（可选）
            limit: 返回数量限制
            offset: 偏移量
            has_content: 是否返回完整内容
            search: 搜索关键词
        
        Returns:
            包含文章列表的字典
        """
        params = {
            "limit": limit,
            "offset": offset,
            "has_content": str(has_content).lower(),
        }
        if mp_id:
            params["mp_id"] = mp_id
        if search:
            params["search"] = search
        result = self._request("GET", "/articles", params=params)
        # WeRSS API 返回格式: {"code":0,"data":{"list":[...]}}
        return {"articles": result.get("data", {}).get("list", [])}
    
    def get_articles_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        mp_id: Optional[str] = None,
        has_content: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        获取时间范围内的文章（按 publish_time 过滤）
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
            mp_id: 公众号 ID（可选）
            has_content: 是否返回完整内容
        
        Returns:
            文章列表
        """
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        all_articles = []
        offset = 0
        limit = 100
        
        while True:
            result = self.get_articles(
                mp_id=mp_id,
                limit=limit,
                offset=offset,
                has_content=has_content,
            )
            
            articles = result.get("articles", [])
            if not articles:
                break
            
            for article in articles:
                publish_time = article.get("publish_time", 0)
                if start_ts <= publish_time <= end_ts:
                    all_articles.append(article)
                elif publish_time < start_ts:
                    # 已经超出时间范围（按时间降序）
                    break
            
            # 如果最后一篇文章的时间已经小于 start_ts，退出
            if articles[-1].get("publish_time", 0) < start_ts:
                break
            
            offset += limit
            
            # 防止无限循环
            if offset > 10000:
                logger.warning("文章查询超过 10000 条，停止")
                break
        
        logger.info(f"获取到 {len(all_articles)} 篇文章（时间范围）")
        return all_articles
    
    def get_article_detail(self, article_id: str) -> Dict[str, Any]:
        """
        获取文章详情（含完整 HTML content）
        
        Args:
            article_id: 文章 ID
        
        Returns:
            文章详情
        """
        result = self._request("GET", f"/articles/{article_id}")
        # WeRSS API 返回格式: {"code":0,"data":{...}}
        return result.get("data", {})
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 单例模式
_client: Optional[WeRSSClient] = None


def get_werss_client() -> WeRSSClient:
    """获取 WeRSS 客户端单例"""
    global _client
    if _client is None:
        _client = WeRSSClient()
    return _client
