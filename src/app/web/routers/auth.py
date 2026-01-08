"""
投资机会雷达 - 用户认证路由
"""
from fastapi import APIRouter, Request, Form, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ...database import get_db
from ...domain.models import AppUser
from ...core.security import verify_password, create_session_token, verify_session_token
from ...logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login")
async def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: bool = Form(False),
    db: Session = Depends(get_db),
):
    """用户登录"""
    # 查找用户
    user = db.query(AppUser).filter(AppUser.username == username).first()
    
    if not user or not verify_password(password, user.password_hash):
        logger.warning(f"登录失败: {username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已禁用")
    
    # 创建会话 token
    token = create_session_token(user.id, remember_me)
    
    # 设置 cookie
    max_age = 30 * 24 * 3600 if remember_me else 12 * 3600
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )
    
    # 更新最后登录时间
    from datetime import datetime
    user.last_login_at = datetime.utcnow()
    db.commit()
    
    logger.info(f"用户登录成功: {username}")
    return response


@router.post("/logout")
async def logout(response: Response):
    """用户登出"""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    """获取当前登录用户（依赖注入）"""
    token = request.cookies.get("session_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    
    user_id = verify_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="会话已过期")
    
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> AppUser | None:
    """获取当前登录用户（可选，未登录返回 None）"""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None
