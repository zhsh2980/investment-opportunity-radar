"""
投资机会雷达 - 配置管理
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    
    # 数据库
    database_url: str = "postgresql://radar:radar@localhost:5432/radar"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # WeRSS
    werss_base_url: str = "http://localhost:8001"
    werss_username: str = "admin"
    werss_password: str = ""
    
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-reasoner"
    
    # 钉钉
    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""
    
    # Web 应用
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


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
