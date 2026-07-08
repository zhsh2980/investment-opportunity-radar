"""
投资机会雷达 - 页面路由（运维后台）

页面：
- /          历史与搜索（时间线，应用首页）
- /system    系统设置（数据源健康/批次/阈值/Prompt）
- /analysis/{id} 保留（钉钉简报里的原文核对入口，需登录）

钉钉简报现在只链接公众号原文，不再链接本应用的任何页面。
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from ...core.security import verify_session_token
from ...database import SessionLocal
from ...domain.models import (
    AnalysisResult,
    AppUser,
    ContentItem,
    DailyReport,
    Opportunity,
    PromptVersion,
    Settings,
    SlotRun,
)
from ...logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="src/app/web/templates")

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

ACTION_LABELS = {
    "executed": "已执行",
    "watching": "观望中",
    "skipped": "已跳过",
    "pending": "待处理",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[dict]:
    token = request.cookies.get("session_token")
    if not token:
        return None
    user_id = verify_session_token(token)
    if not user_id:
        return None
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if user:
        return {"id": user.id, "username": user.username}
    return None


def get_setting_value(db: Session, key: str, default=None):
    setting = db.query(Settings).filter(Settings.key == key).first()
    if setting is not None:
        return setting.value_json
    return default


# ===== 机会类型归一化 =====
TYPE_RULES = [
    ("cb", "可转债", ("convertible", "转债", "cb_")),
    ("arb", "套利", ("arbitrage", "套利", "discount", "折价", "premium")),
    ("ipo", "新股", ("ipo", "new_stock", "新股", "打新")),
    ("cash", "现金管理", ("cash", "reverse_repo", "逆回购", "货基", "money_fund", "国债")),
]


def classify_type(raw: str) -> tuple:
    low = (raw or "").lower()
    for key, label, needles in TYPE_RULES:
        for n in needles:
            if n in low:
                return key, label
    return "other", "其他"


def naive_now() -> datetime:
    return datetime.now()


def as_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def humanize_ago(dt: Optional[datetime]) -> str:
    if not dt:
        return "无记录"
    delta = naive_now() - as_naive(dt)
    if delta.days > 0:
        return f"{delta.days} 天前"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours} 小时前"
    return f"{max(delta.seconds // 60, 1)} 分钟前"


def pending_query(db: Session):
    threshold = get_setting_value(db, "push_score_threshold", 60)
    since = naive_now() - timedelta(days=14)
    return (
        db.query(AnalysisResult)
        .join(ContentItem)
        .filter(
            AnalysisResult.has_opportunity.is_(True),
            AnalysisResult.score >= threshold,
            (AnalysisResult.action_status == "pending") | (AnalysisResult.action_status.is_(None)),
            ContentItem.published_at >= since,
        )
    )


def get_pending_count(db: Session) -> int:
    return pending_query(db).count()


# ============================================================
# 历史与搜索（应用首页）
# ============================================================
@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    min_score: int = Query(0),
    only_opp: int = Query(0),
    keyword: Optional[str] = Query(None),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/", status_code=303)

    end_parsed = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    start_parsed = (
        datetime.strptime(start_date, "%Y-%m-%d").date()
        if start_date else end_parsed - timedelta(days=14)
    )

    query = (
        db.query(AnalysisResult)
        .join(ContentItem)
        .filter(
            AnalysisResult.score >= min_score,
            ContentItem.published_at >= datetime.combine(start_parsed, datetime.min.time()),
            ContentItem.published_at < datetime.combine(end_parsed + timedelta(days=1), datetime.min.time()),
        )
    )
    if only_opp:
        query = query.filter(AnalysisResult.has_opportunity.is_(True))
    if keyword:
        query = query.filter(
            ContentItem.title.ilike(f"%{keyword}%") | ContentItem.mp_name.ilike(f"%{keyword}%")
        )

    analyses = query.order_by(desc(ContentItem.published_at)).limit(200).all()

    report_dates = {
        r[0] for r in db.query(DailyReport.report_date).filter(
            DailyReport.report_date >= start_parsed,
            DailyReport.report_date <= end_parsed,
        ).all()
    }

    days_map = {}
    for a in analyses:
        item = a.content_item
        pub = as_naive(item.published_at)
        d = pub.date()
        opp_types = (a.result_json or {}).get("opportunity_types") or []
        _, type_label = classify_type(opp_types[0] if opp_types else "")
        days_map.setdefault(d, []).append({
            "id": a.id,
            "score": a.score,
            "title": item.title,
            "mp_name": item.mp_name or "未知来源",
            "time_label": pub.strftime("%H:%M"),
            "has_opp": a.has_opportunity,
            "type_label": type_label,
            "action_status": a.action_status,
            "action_label": ACTION_LABELS.get(a.action_status or "pending", ""),
        })

    days = [
        {
            "date": d.isoformat(),
            "label": f"{d.month} 月 {d.day} 日 · {WEEKDAYS[d.weekday()]}",
            "report": d in report_dates,
            "entries": items,
        }
        for d, items in sorted(days_map.items(), reverse=True)
    ]

    return templates.TemplateResponse(request, "pages/history.html", {
        "request": request,
        "user": user,
        "pending_count": get_pending_count(db),
        "days": days,
        "total": len(analyses),
        "start_date": start_parsed.isoformat(),
        "end_date": end_parsed.isoformat(),
        "min_score": min_score,
        "only_opp": only_opp,
        "keyword": keyword or "",
    })


# ============================================================
# 系统设置
# ============================================================
@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/system", status_code=303)

    # 数据源健康: 按公众号统计最新文章与近7天数量
    now = naive_now()
    week_ago = now - timedelta(days=7)
    rows = (
        db.query(
            ContentItem.mp_name,
            func.max(ContentItem.published_at).label("latest"),
            func.sum(case((ContentItem.published_at >= week_ago, 1), else_=0)).label("week_count"),
            func.max(ContentItem.source_category).label("category"),
        )
        .group_by(ContentItem.mp_name)
        .all()
    )
    sources = []
    for name, latest, week_count, category in rows:
        latest_naive = as_naive(latest)
        if latest_naive and latest_naive > now - timedelta(hours=48):
            health = "ok"
        elif latest_naive and latest_naive > now - timedelta(days=7):
            health = "warn"
        else:
            health = "bad"
        sources.append({
            "name": name or "未知来源",
            "latest_label": humanize_ago(latest),
            "week_count": int(week_count or 0),
            "health": health,
            "category": category or "opportunity",
        })
    sources.sort(key=lambda s: s["name"])

    # 今日批次
    today = date.today()
    schedule_slots = get_setting_value(db, "schedule_slots", ["07:00", "12:00", "14:00", "18:00", "22:00"])
    slots_status = {s: {"status": "pending"} for s in schedule_slots}
    for run in db.query(SlotRun).filter(SlotRun.run_date == today).all():
        st = {0: "running", 1: "success", 2: "failed"}.get(run.status, "pending")
        slots_status[run.slot] = {"status": st}

    settings_dict = {
        "push_score_threshold": get_setting_value(db, "push_score_threshold", 60),
        "window_days": get_setting_value(db, "window_days", 3),
        "schedule_slots": schedule_slots,
        "urgent_hours": get_setting_value(db, "urgent_hours", 48),
        "broad_category_override_score": get_setting_value(db, "broad_category_override_score", 80),
    }

    prompts = db.query(PromptVersion).order_by(PromptVersion.name, desc(PromptVersion.version)).all()

    return templates.TemplateResponse(request, "pages/system.html", {
        "request": request,
        "user": user,
        "pending_count": get_pending_count(db),
        "sources": sources,
        "slots_status": slots_status,
        "settings": settings_dict,
        "prompts": prompts,
    })


# ===== 旧路径重定向 =====
@router.get("/prompts")
@router.get("/settings")
@router.get("/health")
async def legacy_redirect():
    return RedirectResponse(url="/system", status_code=301)


@router.get("/history")
async def history_redirect():
    """/history 的内容已迁移到应用首页 /"""
    return RedirectResponse(url="/", status_code=301)


# ============================================================
# 保留: 分析详情页（钉钉简报里的原文核对入口，需登录）
# ============================================================
@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
async def analysis_detail(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果不存在")

    content_item = analysis.content_item
    opportunities = db.query(Opportunity).filter(
        Opportunity.analysis_id == analysis_id
    ).order_by(Opportunity.idx).all()

    return templates.TemplateResponse(request, "pages/analysis.html", {
        "request": request,
        "user": user,
        "analysis": analysis,
        "content_item": content_item,
        "opportunities": opportunities,
        "result": analysis.result_json or {},
    })
