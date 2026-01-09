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


# ===== 导出 API =====
import csv
import io
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from sqlalchemy import desc

from ...domain.models import AnalysisResult, ContentItem


@router.get("/export/analyses")
async def export_analyses(
    request: Request,
    db: Session = Depends(get_db),
    format: str = "json",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_score: int = 0,
):
    """导出分析结果（JSON 或 CSV）"""
    user = get_current_user(request, db)
    
    # 解析日期
    if end_date:
        end_date_parsed = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        end_date_parsed = date.today()
    
    if start_date:
        start_date_parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start_date_parsed = end_date_parsed - timedelta(days=7)
    
    # 查询数据
    analyses = db.query(AnalysisResult).join(ContentItem).filter(
        AnalysisResult.score >= min_score,
        ContentItem.published_at >= datetime.combine(start_date_parsed, datetime.min.time()),
        ContentItem.published_at < datetime.combine(end_date_parsed + timedelta(days=1), datetime.min.time()),
    ).order_by(desc(AnalysisResult.score)).all()
    
    # 构建导出数据
    export_data = []
    for a in analyses:
        export_data.append({
            "id": a.id,
            "score": a.score,
            "has_opportunity": a.has_opportunity,
            "summary": a.summary_md,
            "title": a.content_item.title if a.content_item else "",
            "mp_name": a.content_item.mp_name if a.content_item else "",
            "published_at": a.content_item.published_at.isoformat() if a.content_item else "",
            "url": a.content_item.url if a.content_item else "",
            "action_status": a.action_status or "pending",
            "created_at": a.created_at.isoformat() if a.created_at else "",
        })
    
    if format == "csv":
        # CSV 导出
        output = io.StringIO()
        if export_data:
            writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
            writer.writeheader()
            writer.writerows(export_data)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=analyses_{start_date_parsed}_{end_date_parsed}.csv"}
        )
    else:
        # JSON 导出
        return {
            "start_date": start_date_parsed.isoformat(),
            "end_date": end_date_parsed.isoformat(),
            "count": len(export_data),
            "analyses": export_data,
        }


# ===== JSON API（分析列表）=====
@router.get("/analyses")
async def list_analyses(
    request: Request,
    db: Session = Depends(get_db),
    page: int = 1,
    per_page: int = 20,
    min_score: int = 0,
    only_opportunities: bool = False,
):
    """获取分析列表 (JSON API)"""
    user = get_current_user(request, db)
    
    query = db.query(AnalysisResult).join(ContentItem).filter(
        AnalysisResult.score >= min_score
    )
    
    if only_opportunities:
        query = query.filter(AnalysisResult.has_opportunity == True)
    
    total = query.count()
    analyses = query.order_by(desc(AnalysisResult.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "analyses": [
            {
                "id": a.id,
                "score": a.score,
                "has_opportunity": a.has_opportunity,
                "summary": a.summary_md,
                "title": a.content_item.title if a.content_item else "",
                "mp_name": a.content_item.mp_name if a.content_item else "",
                "published_at": a.content_item.published_at.isoformat() if a.content_item else "",
                "action_status": a.action_status or "pending",
            }
            for a in analyses
        ],
    }


@router.get("/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """获取单个分析详情 (JSON API)"""
    user = get_current_user(request, db)
    
    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    return {
        "id": analysis.id,
        "score": analysis.score,
        "has_opportunity": analysis.has_opportunity,
        "summary": analysis.summary_md,
        "result_json": analysis.result_json,
        "action_status": analysis.action_status or "pending",
        "content_item": {
            "id": analysis.content_item.id,
            "title": analysis.content_item.title,
            "mp_name": analysis.content_item.mp_name,
            "url": analysis.content_item.url,
            "published_at": analysis.content_item.published_at.isoformat(),
        } if analysis.content_item else None,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


# ===== 执行标记 API =====
class ActionStatusUpdate(BaseModel):
    action_status: str  # pending, executed, skipped, watching


@router.put("/analyses/{analysis_id}/status")
async def update_analysis_status(
    analysis_id: int,
    status_data: ActionStatusUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    """更新分析的执行状态"""
    user = get_current_user(request, db)
    
    valid_statuses = ["pending", "executed", "skipped", "watching"]
    if status_data.action_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态，可选: {valid_statuses}")
    
    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    analysis.action_status = status_data.action_status
    db.commit()
    
    logger.info(f"用户 {user.username} 更新分析 {analysis_id} 状态为: {status_data.action_status}")
    
    return {"status": "success", "analysis_id": analysis_id, "action_status": status_data.action_status}
