"""
投资机会雷达 - 管理 API

实现：
- 设置管理 API
- Prompt 管理 API
"""
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...domain.models import Settings, PromptVersion
from ...core.security import verify_session_token
from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["admin"])


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """获取当前登录用户"""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    
    user_id = verify_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期")
    
    from ...domain.models import AppUser
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


# ===== 设置 API =====
class SettingsUpdate(BaseModel):
    push_score_threshold: Optional[int] = None
    remember_me_days: Optional[int] = None
    window_days: Optional[int] = None


@router.post("/settings")
async def update_settings(
    settings_data: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    """更新系统设置"""
    user = get_current_user(request, db)
    
    updates = settings_data.dict(exclude_none=True)
    
    for key, value in updates.items():
        # 查找或创建设置
        setting = db.query(Settings).filter(Settings.key == key).first()
        if setting:
            setting.value_json = value
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(key=key, value_json=value)
            db.add(setting)
    
    db.commit()
    logger.info(f"用户 {user.username} 更新了设置: {updates}")
    
    return {"status": "success", "updated": list(updates.keys())}


@router.get("/settings")
async def get_settings(request: Request, db: Session = Depends(get_db)):
    """获取系统设置"""
    user = get_current_user(request, db)
    
    all_settings = db.query(Settings).all()
    settings_dict = {s.key: s.value_json for s in all_settings}
    
    # 设置默认值
    default_settings = {
        "push_score_threshold": 60,
        "remember_me_days": 30,
        "window_days": 3,
    }
    
    for key, default in default_settings.items():
        if key not in settings_dict:
            settings_dict[key] = default
    
    return settings_dict


# ===== Prompt API =====
class PromptCreate(BaseModel):
    name: str
    system_prompt: str
    user_template: str
    threshold: Optional[int] = 60


@router.post("/prompts")
async def create_prompt(
    prompt_data: PromptCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """创建新的 Prompt 版本"""
    user = get_current_user(request, db)
    
    # 获取当前最大版本号
    latest = db.query(PromptVersion).filter(
        PromptVersion.name == prompt_data.name
    ).order_by(PromptVersion.version.desc()).first()
    
    new_version = (latest.version + 1) if latest else 1
    
    # 创建新版本
    new_prompt = PromptVersion(
        name=prompt_data.name,
        version=new_version,
        system_prompt=prompt_data.system_prompt,
        user_template=prompt_data.user_template,
        threshold=prompt_data.threshold,
        is_active=True,
    )
    
    # 停用其他版本
    db.query(PromptVersion).filter(
        PromptVersion.name == prompt_data.name,
        PromptVersion.is_active == True
    ).update({"is_active": False})
    
    db.add(new_prompt)
    db.commit()
    
    logger.info(f"用户 {user.username} 创建了 Prompt: {prompt_data.name} v{new_version}")
    
    return RedirectResponse(url="/prompts", status_code=303)


@router.post("/prompts/{prompt_id}/activate")
async def activate_prompt(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """激活指定的 Prompt 版本"""
    user = get_current_user(request, db)
    
    prompt = db.query(PromptVersion).filter(PromptVersion.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    
    # 停用同名的其他版本
    db.query(PromptVersion).filter(
        PromptVersion.name == prompt.name,
        PromptVersion.is_active == True
    ).update({"is_active": False})
    
    # 激活当前版本
    prompt.is_active = True
    db.commit()
    
    logger.info(f"用户 {user.username} 激活了 Prompt: {prompt.name} v{prompt.version}")
    
    return RedirectResponse(url="/prompts", status_code=303)


@router.get("/prompts/{prompt_id}")
async def get_prompt(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """获取指定的 Prompt 详情"""
    user = get_current_user(request, db)
    
    prompt = db.query(PromptVersion).filter(PromptVersion.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    
    return {
        "id": prompt.id,
        "name": prompt.name,
        "version": prompt.version,
        "system_prompt": prompt.system_prompt,
        "user_template": prompt.user_template,
        "threshold": prompt.threshold,
        "is_active": prompt.is_active,
        "created_at": prompt.created_at.isoformat(),
    }
