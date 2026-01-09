"""
投资机会雷达 - 主要页面路由

实现：
- 首页 Dashboard
- 分析详情页
- 当日日报页
- 历史列表页
"""
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...domain.models import (
    ContentItem,
    AnalysisResult,
    DailyReport,
    SlotRun,
    Opportunity,
    Settings,
)
from ...core.security import verify_session_token
from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="src/app/web/templates")


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[dict]:
    """获取当前登录用户"""
    token = request.cookies.get("session_token")
    if not token:
        return None
    
    user_id = verify_session_token(token)
    if not user_id:
        return None
    
    from ...domain.models import AppUser
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if user:
        return {"id": user.id, "username": user.username}
    return None


def require_login(request: Request, db: Session = Depends(get_db)):
    """需要登录的依赖"""
    user = get_current_user(request, db)
    if not user:
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        raise HTTPException(status_code=303, headers={"Location": f"/login?next={next_url}"})
    return user


def get_setting_value(db: Session, key: str, default=None):
    """获取配置值"""
    setting = db.query(Settings).filter(Settings.key == key).first()
    if setting:
        return setting.value_json
    return default


# ===== 首页 Dashboard =====
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """首页 Dashboard"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    today = date.today()
    threshold = get_setting_value(db, "push_score_threshold", 60)
    
    # 今日 slot 运行状态
    today_slots = db.query(SlotRun).filter(
        SlotRun.run_date == today
    ).all()
    
    # 从数据库动态获取配置的 schedule_slots
    schedule_slots = get_setting_value(db, "schedule_slots", ["07:00", "12:00", "14:00", "18:00", "22:00"])
    
    # 初始化 slots 状态
    slots_status = {}
    for slot in schedule_slots:
        slots_status[slot] = {"status": "pending", "label": "未运行"}
    
    for slot in today_slots:
        if slot.status == 1:
            slots_status[slot.slot] = {"status": "success", "label": "成功"}
        elif slot.status == 0:
            slots_status[slot.slot] = {"status": "running", "label": "运行中"}
        elif slot.status == 2:
            slots_status[slot.slot] = {"status": "failed", "label": "失败"}
    
    # 今日分析结果（近3天的文章）
    window_start = datetime.combine(today - timedelta(days=3), datetime.min.time())
    today_analyses = db.query(AnalysisResult).join(ContentItem).filter(
        ContentItem.published_at >= window_start
    ).order_by(desc(AnalysisResult.score)).limit(20).all()
    
    # 统计
    total_analyzed = len(today_analyses)
    opportunities = [a for a in today_analyses if a.has_opportunity and a.score >= threshold]
    max_score = max([a.score for a in today_analyses], default=0)
    
    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "user": user,
        "today": today,
        "slots_status": slots_status,
        "total_analyzed": total_analyzed,
        "opportunities_count": len(opportunities),
        "max_score": max_score,
        "threshold": threshold,
        "recent_analyses": today_analyses[:10],
        "opportunities": opportunities[:5],
    })


# ===== 分析详情页 =====
@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
async def analysis_detail(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """分析详情页"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next=/analysis/{analysis_id}", status_code=303)
    
    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    content_item = analysis.content_item
    opportunities = db.query(Opportunity).filter(
        Opportunity.analysis_id == analysis_id
    ).order_by(Opportunity.idx).all()
    
    # 解析 result_json
    result = analysis.result_json or {}
    
    return templates.TemplateResponse("pages/analysis.html", {
        "request": request,
        "user": user,
        "analysis": analysis,
        "content_item": content_item,
        "opportunities": opportunities,
        "result": result,
    })


# ===== 日报页重定向 =====
@router.get("/daily", response_class=HTMLResponse)
@router.get("/daily/", response_class=HTMLResponse)
async def daily_redirect(request: Request, db: Session = Depends(get_db)):
    """重定向到今日日报"""
    today = date.today().isoformat()
    return RedirectResponse(url=f"/daily/{today}", status_code=303)


# ===== 当日日报页 =====
@router.get("/daily/{report_date}", response_class=HTMLResponse)
async def daily_report(
    request: Request,
    report_date: str,
    db: Session = Depends(get_db)
):
    """当日日报页"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next=/daily/{report_date}", status_code=303)
    
    try:
        parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")
    
    # 获取日报
    report = db.query(DailyReport).filter(DailyReport.report_date == parsed_date).first()
    
    # 获取当天的 slot 运行记录
    slots = db.query(SlotRun).filter(SlotRun.run_date == parsed_date).all()
    
    # 获取当天的分析结果
    day_start = datetime.combine(parsed_date, datetime.min.time())
    day_end = datetime.combine(parsed_date + timedelta(days=1), datetime.min.time())
    
    analyses = db.query(AnalysisResult).join(ContentItem).filter(
        and_(
            ContentItem.published_at >= day_start,
            ContentItem.published_at < day_end,
        )
    ).order_by(desc(AnalysisResult.score)).all()
    
    threshold = get_setting_value(db, "push_score_threshold", 60)
    opportunities = [a for a in analyses if a.has_opportunity and a.score >= threshold]
    
    return templates.TemplateResponse("pages/daily.html", {
        "request": request,
        "user": user,
        "report_date": parsed_date,
        "prev_date": (parsed_date - timedelta(days=1)).isoformat(),
        "next_date": (parsed_date + timedelta(days=1)).isoformat(),
        "report": report,
        "slots": slots,
        "analyses": analyses,
        "opportunities": opportunities,
        "threshold": threshold,
    })


# ===== 历史列表页 =====
@router.get("/history", response_class=HTMLResponse)
async def history(
    request: Request,
    db: Session = Depends(get_db),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    min_score: int = Query(0),
    type_filter: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
):
    """历史列表页"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/history", status_code=303)
    
    # 默认最近7天
    if not end_date:
        end_date_parsed = date.today()
    else:
        end_date_parsed = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    if not start_date:
        start_date_parsed = end_date_parsed - timedelta(days=7)
    else:
        start_date_parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
    
    # 构建查询
    query = db.query(AnalysisResult).join(ContentItem).filter(
        AnalysisResult.score >= min_score,
        ContentItem.published_at >= datetime.combine(start_date_parsed, datetime.min.time()),
        ContentItem.published_at < datetime.combine(end_date_parsed + timedelta(days=1), datetime.min.time()),
    )
    
    # 关键词过滤
    if keyword:
        query = query.filter(
            ContentItem.title.ilike(f"%{keyword}%") |
            ContentItem.mp_name.ilike(f"%{keyword}%")
        )
    
    analyses = query.order_by(desc(AnalysisResult.score)).limit(100).all()
    
    return templates.TemplateResponse("pages/history.html", {
        "request": request,
        "user": user,
        "analyses": analyses,
        "start_date": start_date_parsed.isoformat(),
        "end_date": end_date_parsed.isoformat(),
        "min_score": min_score,
        "type_filter": type_filter,
        "keyword": keyword or "",
    })


# ===== Prompt 管理页 =====
@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, db: Session = Depends(get_db)):
    """Prompt 管理页"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/prompts", status_code=303)
    
    from ...domain.models import PromptVersion
    
    # 获取所有 Prompt 版本
    prompts = db.query(PromptVersion).order_by(
        PromptVersion.name,
        desc(PromptVersion.version)
    ).all()
    
    # 按名称分组
    prompts_by_name = {}
    for p in prompts:
        if p.name not in prompts_by_name:
            prompts_by_name[p.name] = []
        prompts_by_name[p.name].append(p)
    
    # 获取当前活跃的 Prompt
    active_prompts = {p.name: p for p in prompts if p.is_active}
    
    return templates.TemplateResponse("pages/prompts.html", {
        "request": request,
        "user": user,
        "prompts_by_name": prompts_by_name,
        "active_prompts": active_prompts,
    })


# ===== 设置页 =====
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """系统设置页"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/settings", status_code=303)
    
    # 获取所有设置
    all_settings = db.query(Settings).all()
    settings_dict = {s.key: s.value_json for s in all_settings}
    
    # 设置默认值
    default_settings = {
        "push_score_threshold": 60,
        "remember_me_days": 30,
        "window_days": 3,
        "schedule_slots": ["07:00", "12:00", "14:00", "18:00", "22:00"],
    }
    
    for key, default in default_settings.items():
        if key not in settings_dict:
            settings_dict[key] = default
    
    return templates.TemplateResponse("pages/settings.html", {
        "request": request,
        "user": user,
        "settings": settings_dict,
    })
