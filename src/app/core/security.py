"""
投资机会雷达 - 安全工具（密码哈希、认证等）
"""
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from jose import jwt, JWTError

from ..config import get_settings


# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对密码进行哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_session_token(user_id: int, remember_me: bool = False) -> str:
    """创建会话 token"""
    settings = get_settings()
    
    # 过期时间：记住我 30 天，否则 12 小时
    if remember_me:
        expire = datetime.utcnow() + timedelta(days=30)
    else:
        expire = datetime.utcnow() + timedelta(hours=12)
    
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "remember": remember_me,
    }
    
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token


def verify_session_token(token: str) -> Optional[int]:
    """验证会话 token，返回用户 ID"""
    settings = get_settings()
    
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
        return user_id
    except (JWTError, ValueError, TypeError):
        return None
