"""
投资机会雷达 - DeepSeek 客户端

DeepSeek API 客户端，用于调用 deepseek-reasoner 模型进行投资机会分析。
- 强制 JSON 输出
- 支持思考模型（reasoning_content）
- 自动重试和超时处理
"""
import json
from typing import Optional, Dict, Any, Tuple
import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class DeepSeekClient:
    """DeepSeek API 客户端"""
    
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.deepseek_base_url.rstrip('/')
        self.api_key = settings.deepseek_api_key
        self.model = settings.deepseek_model
        
        # HTTP 客户端（长超时，因为思考模型可能需要较长时间）
        self._client = httpx.Client(timeout=120.0)
    
    def chat_completion(
        self,
        messages: list,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        json_mode: bool = True,
    ) -> Tuple[str, Optional[str]]:
        """
        调用 Chat Completions API
        
        Args:
            messages: 消息列表 [{"role": "system/user", "content": "..."}]
            max_tokens: 最大输出 token 数
            temperature: 温度参数
            json_mode: 是否强制 JSON 输出
        
        Returns:
            (content, reasoning_content) - 回答内容和推理内容（仅 reasoner 模型有）
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # 强制 JSON 输出
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        logger.info(f"调用 DeepSeek: model={self.model}, json_mode={json_mode}")
        
        response = self._client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        
        content = message.get("content", "")
        reasoning_content = message.get("reasoning_content")
        
        # 记录 token 使用
        usage = result.get("usage", {})
        logger.info(
            f"DeepSeek 调用完成: "
            f"prompt_tokens={usage.get('prompt_tokens', 0)}, "
            f"completion_tokens={usage.get('completion_tokens', 0)}"
        )
        
        return content, reasoning_content
    
    def analyze_article(
        self,
        system_prompt: str,
        article_content: str,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        分析文章，返回结构化结果
        
        Args:
            system_prompt: 系统提示词
            article_content: 文章内容
            max_tokens: 最大输出 token 数
        
        Returns:
            解析后的 JSON 结果
        
        Raises:
            json.JSONDecodeError: 如果输出不是有效 JSON
            httpx.HTTPError: 如果 API 调用失败
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": article_content},
        ]
        
        content, reasoning_content = self.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            json_mode=True,
        )
        
        # 记录推理内容（用于调试）
        if reasoning_content:
            logger.debug(f"DeepSeek 推理内容: {reasoning_content[:500]}...")
        
        # 解析 JSON
        try:
            result = json.loads(content)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"DeepSeek 输出 JSON 解析失败: {e}")
            logger.error(f"原始输出: {content[:1000]}...")
            raise
    
    def close(self):
        """关闭客户端"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 单例模式
_client: Optional[DeepSeekClient] = None


def get_deepseek_client() -> DeepSeekClient:
    """获取 DeepSeek 客户端单例"""
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
