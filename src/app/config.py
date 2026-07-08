"""
投资机会雷达 - 配置管理
"""
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class JTKSFeedConfig(BaseModel):
    """单个「今天看啥」专栏 feed 的配置：地址 + 推送分类"""

    url: str
    # opportunity=机会类，命中阈值即推；broad=宽泛类，只进日报，除非分数很高
    category: Literal["opportunity", "broad"] = "opportunity"


class Settings(BaseSettings):
    """应用配置"""

    # 数据库
    database_url: str = "postgresql://radar:radar@localhost:5432/radar"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # 今天看啥 VIP RSS（JSON 数组，每个专栏一条带个人 token 的 feed 地址 + 分类）
    jtks_feeds: list[JTKSFeedConfig] = []

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-reasoner"

    # 钉钉
    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""

    # Web 应用
    public_base_url: str = "https://radar.codexcc.cc"  # 钉钉推送链接使用的公网地址
    secret_key: str = "change-me-in-production"
    radar_admin_username: str = "admin"
    radar_admin_password: str = ""

    # 时区
    tz: str = "Asia/Shanghai"

    # 推送阈值
    push_score_threshold: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 允许 .env 中存在未声明的键(如 docker-compose 用的 POSTGRES_*)


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
