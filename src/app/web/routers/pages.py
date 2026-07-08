"""
投资机会雷达 - 页面路由（Aurora 重构版）

页面：
- /          今日工作台（机会处理工作台）
- /tracking  跟踪台（看板 + 复盘）
- /history   历史与搜索（时间线）
- /system    系统设置（数据源健康/批次/阈值/Prompt）
- /analysis/{id}, /daily/{date} 保留（钉钉推送落地页）

工作台 API：
- POST /api/workbench/{analysis_id}/action    执行/观望/跳过
- POST /api/workbench/track/{track_id}/review 复盘记录
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, Integer, cast, case
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...domain.models import (
    ContentItem,
    AnalysisResult,
    DailyReport,
    SlotRun,
    Opportunity,
    OpportunityTrack,
    Settings,
    PromptVersion,
    AppUser,
)
from ...core.security import verify_session_token
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


def build_card(analysis: AnalysisResult) -> dict:
    """把一条分析结果组装成工作台卡片数据"""
    item = analysis.content_item
    opps = sorted(analysis.opportunities, key=lambda o: o.idx)

    headline = opps[0].title if opps else item.title
    type_key, type_label = classify_type(opps[0].type if opps else "")

    # 最近的时间窗口截止
    deadlines = [as_naive(o.time_window_end) for o in opps if o.time_window_end]
    deadline = min(deadlines) if deadlines else None

    steps = []
    if opps and opps[0].how_to:
        steps = [str(s) for s in opps[0].how_to[:2]]

    return {
        "analysis_id": analysis.id,
        "score": analysis.score,
        "headline": headline,
        "title": item.title,
        "mp_name": item.mp_name or "未知来源",
        "type_key": type_key,
        "type_label": type_label,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_dt": deadline,
        "steps": steps,
        "summary": (analysis.summary_md or "")[:600],
        "opportunities": [
            {
                "title": o.title,
                "how_to": o.how_to or [],
                "constraints": o.constraints or [],
                "numbers": o.numbers or {},
            }
            for o in opps
        ],
    }


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
# 今日工作台
# ============================================================
@router.get("/", response_class=HTMLResponse)
async def workbench(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    urgent_hours = int(get_setting_value(db, "urgent_hours", 48))
    analyses = pending_query(db).all()
    cards = [build_card(a) for a in analyses]

    # 排序: 临期优先(有截止且未过期,越近越前) → 分数降序
    now = naive_now()
    far_future = now + timedelta(days=3650)

    def sort_key(c):
        dl = c["deadline_dt"]
        urgency = dl if (dl and dl > now) else far_future
        return (urgency, -c["score"])

    cards.sort(key=sort_key)

    urgent_count = sum(
        1 for c in cards
        if c["deadline_dt"] and now < c["deadline_dt"] < now + timedelta(hours=urgent_hours)
    )

    today = date.today()
    day_start = datetime.combine(today, datetime.min.time())
    analyzed_today = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.analyzed_at >= day_start)
        .scalar()
        or 0
    )
    source_count = db.query(func.count(func.distinct(ContentItem.mp_id))).scalar() or 0

    today_label = f"{today.year} 年 {today.month} 月 {today.day} 日 · {WEEKDAYS[today.weekday()]}"

    return templates.TemplateResponse(request, "pages/dashboard.html", {
        "request": request,
        "user": user,
        "today_label": today_label,
        "cards": cards,
        "pending_count": len(cards),
        "urgent_count": urgent_count,
        "urgent_hours": urgent_hours,
        "analyzed_today": analyzed_today,
        "source_count": source_count,
    })


# ===== 工作台操作 API =====
class ActionPayload(BaseModel):
    action: str  # executed / watching / skipped


@router.post("/api/workbench/{analysis_id}/action")
async def workbench_action(
    analysis_id: int,
    payload: ActionPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    if payload.action not in ("executed", "watching", "skipped"):
        raise HTTPException(status_code=400, detail="无效操作")

    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果不存在")

    analysis.action_status = payload.action
    track = OpportunityTrack(analysis_id=analysis_id, action=payload.action)
    db.add(track)
    db.commit()

    logger.info(f"工作台操作: analysis={analysis_id} action={payload.action}")
    return {"ok": True, "action": payload.action, "track_id": track.id}


class ReviewPayload(BaseModel):
    amount: Optional[float] = None
    pnl: Optional[float] = None
    note: Optional[str] = None
    close: bool = False


@router.post("/api/workbench/track/{track_id}/review")
async def track_review(
    track_id: int,
    payload: ReviewPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    track = db.query(OpportunityTrack).filter(OpportunityTrack.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="跟踪记录不存在")

    if payload.amount is not None:
        track.amount = Decimal(str(payload.amount))
    if payload.pnl is not None:
        track.pnl = Decimal(str(payload.pnl))
    if payload.note is not None:
        track.note = payload.note
    if payload.close:
        track.closed_at = naive_now()
    db.commit()

    return {"ok": True}


# ============================================================
# 跟踪台
# ============================================================
@router.get("/tracking", response_class=HTMLResponse)
async def tracking(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/tracking", status_code=303)

    # 每个 analysis 取最新一条跟踪记录
    latest_ids = (
        db.query(func.max(OpportunityTrack.id))
        .group_by(OpportunityTrack.analysis_id)
    ).subquery()
    tracks = (
        db.query(OpportunityTrack)
        .filter(OpportunityTrack.id.in_(latest_ids.select()))
        .order_by(desc(OpportunityTrack.created_at))
        .all()
    )

    def pack(t: OpportunityTrack) -> dict:
        a = t.analysis_result
        item = a.content_item
        opps = sorted(a.opportunities, key=lambda o: o.idx)
        return {
            "track_id": t.id,
            "analysis_id": a.id,
            "headline": (opps[0].title if opps else item.title)[:60],
            "mp_name": item.mp_name or "未知来源",
            "score": a.score,
            "amount": t.amount,
            "pnl": t.pnl,
            "note": t.note,
            "created_label": humanize_ago(t.created_at),
            "closed_label": humanize_ago(t.closed_at),
        }

    watching = [pack(t) for t in tracks if t.action == "watching"]
    executing = [pack(t) for t in tracks if t.action == "executed" and t.closed_at is None and t.pnl is None]
    reviewed_tracks = [t for t in tracks if t.action == "executed" and (t.closed_at is not None or t.pnl is not None)]
    reviewed = []
    for t in reviewed_tracks:
        r = pack(t)
        r["pnl"] = float(r["pnl"] or 0)
        reviewed.append(r)

    # 月度统计
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    month_tracks = [
        t for t in tracks
        if t.action == "executed" and as_naive(t.created_at) and as_naive(t.created_at) >= month_start
    ]
    month_executed = len(month_tracks)
    month_pnls = [float(t.pnl) for t in month_tracks if t.pnl is not None]
    month_pnl = sum(month_pnls)
    month_reviewed = len(month_pnls)

    all_pnls = [(float(t.pnl), t.analysis_result.score) for t in reviewed_tracks if t.pnl is not None]
    hit_rate = round(100 * len([p for p, s in all_pnls if p > 0]) / len(all_pnls)) if all_pnls else 0
    high = [(p, s) for p, s in all_pnls if s >= 80]
    high_score_rate = round(100 * len([p for p, s in high if p > 0]) / len(high)) if high else 0

    return templates.TemplateResponse(request, "pages/tracking.html", {
        "request": request,
        "user": user,
        "pending_count": get_pending_count(db),
        "watching": watching,
        "executing": executing,
        "reviewed": reviewed,
        "month_label": f"{today.year} 年 {today.month} 月",
        "month_executed": month_executed,
        "month_pnl": month_pnl,
        "month_reviewed": month_reviewed,
        "hit_rate": hit_rate,
        "high_score_rate": high_score_rate,
    })


# ============================================================
# 历史与搜索
# ============================================================
@router.get("/history", response_class=HTMLResponse)
async def history(
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
        return RedirectResponse(url="/login?next=/history", status_code=303)

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
        )
        .group_by(ContentItem.mp_name)
        .all()
    )
    sources = []
    for name, latest, week_count in rows:
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


# ============================================================
# 保留: 分析详情页（钉钉链接落地页,访客可看）
# ============================================================
@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
async def analysis_detail(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)

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


# ============================================================
# 保留: 当日日报页（钉钉链接落地页,访客可看）
# ============================================================
@router.get("/daily", response_class=HTMLResponse)
@router.get("/daily/", response_class=HTMLResponse)
async def daily_redirect_route(request: Request):
    return RedirectResponse(url=f"/daily/{date.today().isoformat()}", status_code=303)


@router.get("/daily/{report_date}", response_class=HTMLResponse)
async def daily_report(request: Request, report_date: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)

    try:
        parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    report = db.query(DailyReport).filter(DailyReport.report_date == parsed_date).first()
    slots = db.query(SlotRun).filter(SlotRun.run_date == parsed_date).all()

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

    return templates.TemplateResponse(request, "pages/daily.html", {
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
