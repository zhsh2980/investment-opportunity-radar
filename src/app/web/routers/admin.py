"""
投资机会雷达 - 管理 API

实现：
- 设置管理 API
- Prompt 管理 API
"""
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
import redis
import socket
import http.client
import json
import os
from ...tasks.celery_app import app as celery_app

from ...database import SessionLocal
from ...domain.models import Settings, PromptVersion
from ...core.security import verify_session_token
from ...logging_config import get_logger
from ...tasks.slot import execute_slot  # 使用普通函数而非 Celery Task

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
    schedule_slots: Optional[List[str]] = None


@router.post("/settings")
async def update_settings(
    settings_data: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    """更新系统设置"""
    user = get_current_user(request, db)
    
    updates = settings_data.dict(exclude_none=True)
    schedule_slots_changed = "schedule_slots" in updates
    
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
    
    # 如果修改了 schedule_slots，自动重启 beat 容器使调度生效
    beat_restarted = False
    if schedule_slots_changed:
        try:
            import socket
            import http.client
            
            # 通过 Unix socket 连接 Docker API
            class UnixHTTPConnection(http.client.HTTPConnection):
                def __init__(self, socket_path):
                    super().__init__("localhost")
                    self.socket_path = socket_path
                    
                def connect(self):
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.sock.connect(self.socket_path)
            
            conn = UnixHTTPConnection("/var/run/docker.sock")
            conn.request("POST", "/containers/radar-beat/restart")
            response = conn.getresponse()
            
            if response.status == 204:
                beat_restarted = True
                logger.info("已自动重启 radar-beat 容器，调度配置已生效")
            else:
                logger.warning(f"重启 radar-beat 失败: HTTP {response.status}")
                
            conn.close()
        except Exception as e:
            logger.warning(f"重启 radar-beat 异常: {e}")
    
    return {
        "status": "success", 
        "updated": list(updates.keys()),
        "beat_restarted": beat_restarted
    }


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
    
    return {"status": "success", "version": new_version, "name": prompt_data.name}


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


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """删除指定的 Prompt 版本（不能删除当前激活版本）"""
    user = get_current_user(request, db)
    
    prompt = db.query(PromptVersion).filter(PromptVersion.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    
    if prompt.is_active:
        raise HTTPException(status_code=400, detail="不能删除当前激活的版本")
    
    version = prompt.version
    name = prompt.name
    
    db.delete(prompt)
    db.commit()
    
    logger.info(f"用户 {user.username} 删除了 Prompt: {name} v{version}")
    
    return {"status": "success", "message": f"已删除 {name} v{version}"}


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




# ===== 辅助函数 =====
def check_and_fix_stale_slots(db: Session):
    """检查并修复陈旧的 slot_run (超过30分钟仍为进行中)"""
    from ...domain.models import SlotRun
    from datetime import timedelta
    
    # 定义超时阈值 (30分钟)
    # 注意：started_at 存储的是 UTC 时间（如果 default=datetime.utcnow）
    # 但根据 debug 经验，数据库中可能是 naive time (且实际上是 UTC)
    timeout_threshold = datetime.utcnow() - timedelta(minutes=30)
    
    # 查找陈旧任务
    stale_tasks = db.query(SlotRun).filter(
        SlotRun.status == 0,  # 进行中
        SlotRun.started_at < timeout_threshold
    ).all()
    
    if stale_tasks:
        for task in stale_tasks:
            task.status = 2  # 失败
            task.error = "Task timed out (stale check)"
            task.finished_at = datetime.utcnow()
            logger.warning(f"发现陈旧任务，已标记为失败: ID={task.id}, Date={task.run_date}, Slot={task.slot}")
        
        db.commit()


@router.post("/run-now")
async def run_analysis_now(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """手动触发立即分析"""
    user = get_current_user(request, db)
    
    # 先清理陈旧任务
    check_and_fix_stale_slots(db)
    
    # 检查是否有正在运行的任务
    from ...domain.models import SlotRun
    running_task = db.query(SlotRun).filter(SlotRun.status == 0).first()
    if running_task:
        return {
            "status": "error",
            "message": "有任务正在执行，请稍后再试"
        }
    
    # 获取当前时间 HH:MM
    now_str = datetime.now().strftime("%H:%M")
    
    logger.info(f"用户 {user.username} 手动触发立即分析: {now_str}")
    
    # 使用 BackgroundTasks 在 Web 容器直接运行，绕过 Celery
    background_tasks.add_task(execute_slot, slot=now_str, manual=True)
    
    return {"status": "success", "message": "分析任务已在后台启动"}


@router.get("/analysis-progress")
async def get_analysis_progress(
    request: Request,
    db: Session = Depends(get_db)
):
    """获取当前分析进度"""
    user = get_current_user(request, db)
    
    # 先清理陈旧任务
    check_and_fix_stale_slots(db)
    
    from ...domain.models import ContentItem, SlotRun
    from sqlalchemy import desc, func
    
    # 获取待分析文章总数
    total_pending = db.query(ContentItem).filter(
        ContentItem.analyzed_status == 0
    ).count()
    
    # 获取正在进行中的 slot_run（status=0 表示进行中）
    recent_slot = db.query(SlotRun).filter(
        SlotRun.status == 0  # 进行中
    ).order_by(desc(SlotRun.started_at)).first()
    
    is_running = recent_slot is not None
    analyzed_count = 0
    current_article = None
    started_at = None
    total_initial = 0  # 初始待分析总数
    
    if is_running and recent_slot:
        # 从 stats 获取初始总数
        if recent_slot.stats and isinstance(recent_slot.stats, dict):
            total_initial = recent_slot.stats.get("articles_total", 0)
        
        # 统计本次已分析的数量
        from ...domain.models import AnalysisResult
        analyzed_count = db.query(AnalysisResult).filter(
            AnalysisResult.run_id == recent_slot.id
        ).count()
        
        # 获取最近一条已分析的文章（ID最大的）
        latest_analyzed = db.query(ContentItem).filter(
            ContentItem.analyzed_status.in_([1, 2])  # 1=成功, 2=失败
        ).order_by(desc(ContentItem.id)).first()
        
        if latest_analyzed:
            title = latest_analyzed.title
            if len(title) > 30:
                title = title[:30] + "..."
            current_article = {
                "title": title,
                "truncated": len(latest_analyzed.title) > 30
            }
        
        started_at = recent_slot.started_at.strftime("%Y-%m-%d %H:%M:%S")
    
    # 计算剩余数量和预计时间（每篇约1分钟）
    remaining = max(0, total_initial - analyzed_count)
    estimated_remaining_minutes = remaining
    
    return {
        "is_running": is_running,
        "total_initial": total_initial,  # 初始总数
        "total_pending": total_pending,  # 当前待分析数（保留兼容）
        "analyzed_count": analyzed_count,
        "remaining": remaining,  # 剩余数量
        "current_article": current_article,
        "started_at": started_at,
        "estimated_remaining_minutes": estimated_remaining_minutes
    }


# ===== 系统状态检测 API =====
@router.get("/system-status")
async def get_system_status(request: Request, db: Session = Depends(get_db)):
    """获取外部服务连接状态"""
    user = get_current_user(request, db)
    
    status = {
        "werss": {"status": "unknown", "message": "未检测"},
        "deepseek": {"status": "unknown", "message": "未检测"}
    }
    
    # 检查 WeRSS 连接
    try:
        from ...clients.werss import get_werss_client
        client = get_werss_client()
        
        # 检查现有 Token 是否有效
        if client._is_token_valid():
            status["werss"] = {"status": "ok", "message": "Token 有效"}
        else:
            # 尝试获取新 Token（会自动登录或刷新）
            client._get_token()
            status["werss"] = {"status": "ok", "message": "连接正常"}
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 50:
            error_msg = error_msg[:50] + "..."
        status["werss"] = {"status": "error", "message": f"连接失败: {error_msg}"}
        logger.warning(f"WeRSS 状态检测失败: {e}")
    
    # 检查 DeepSeek API 配置
    try:
        from ...config import get_settings
        settings = get_settings()
        if settings.deepseek_api_key:
            # 仅检查 API Key 是否配置，不实际调用（避免消耗额度）
            key_preview = settings.deepseek_api_key[:8] + "..." if len(settings.deepseek_api_key) > 8 else "***"
            status["deepseek"] = {"status": "ok", "message": f"已配置 ({key_preview})"}
        else:
            status["deepseek"] = {"status": "error", "message": "未配置 API Key"}
    except Exception as e:
        status["deepseek"] = {"status": "error", "message": f"配置异常: {str(e)}"}
    
    return status

@router.get("/health-detail")
async def get_health_detail(request: Request, db: Session = Depends(get_db)):
    """获取详细系统状态（包含 Celery 等）"""
    user = get_current_user(request, db)
    
    status = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "services": []
    }
    
    # 1. Web 服务
    status["services"].append({
        "name": "Web 服务",
        "status": "ok",
        "message": "运行正常",
        "icon": "globe"
    })
    
    # 2. Database
    try:
        db.execute(text("SELECT 1"))
        status["services"].append({
            "name": "PostgreSQL",
            "status": "ok",
            "message": "连接正常",
            "icon": "database"
        })
    except Exception as e:
        status["services"].append({
            "name": "PostgreSQL",
            "status": "error",
            "message": "连接失败",
            "detail": str(e),
            "icon": "database"
        })
        
    # 3. Redis
    try:
        from ...config import get_settings
        settings = get_settings()
        r = redis.from_url(settings.redis_url, socket_timeout=1)
        if r.ping():
             status["services"].append({
                "name": "Redis",
                "status": "ok",
                "message": "连接正常",
                "icon": "server"
            })
        else:
             status["services"].append({
                "name": "Redis",
                "status": "error",
                "message": "无响应",
                "icon": "server"
            })
    except Exception as e:
        status["services"].append({
            "name": "Redis",
            "status": "error",
            "message": "连接异常",
            "detail": str(e),
            "icon": "server"
        })

    # 4. Celery Worker (使用 inspect)
    try:
        i = celery_app.control.inspect(timeout=1.0)
        active = i.ping()
        if active:
            # 获取活跃节点的名称
            worker_names = list(active.keys())
            count = len(worker_names)
            status["services"].append({
                "name": "Celery Worker",
                "status": "ok",
                "message": f"{count} 个活跃节点",
                "detail": ", ".join(worker_names),
                "icon": "cpu"
            })
        else:
            status["services"].append({
                "name": "Celery Worker",
                "status": "error",
                "message": "未检测到活跃节点",
                "icon": "cpu"
            })
    except Exception as e:
        status["services"].append({
            "name": "Celery Worker",
            "status": "warning",
            "message": "检测超时或失败",
            "detail": str(e),
            "icon": "cpu"
        })

    # 5. Celery Beat (通过 Docker API 检查容器)
    beat_status = {"name": "Celery Beat", "icon": "clock"}
    if os.path.exists("/var/run/docker.sock"):
        try:
            class UnixHTTPConnection(http.client.HTTPConnection):
                def __init__(self, socket_path):
                    super().__init__("localhost")
                    self.socket_path = socket_path
                def connect(self):
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.sock.connect(self.socket_path)
            
            conn = UnixHTTPConnection("/var/run/docker.sock")
            conn.request("GET", "/containers/radar-beat/json")
            response = conn.getresponse()
            
            if response.status == 200:
                data = json.loads(response.read().decode())
                state = data.get("State", {})
                if state.get("Running"):
                    beat_status.update({
                        "status": "ok", 
                        "message": "运行正常 (Docker)"
                    })
                else:
                    beat_status.update({
                        "status": "error", 
                        "message": f"容器已停止 ({state.get('Status')})"
                    })
            else:
                 beat_status.update({
                    "status": "warning", 
                    "message": "容器未找到"
                })
            conn.close()
        except Exception as e:
            beat_status.update({
                "status": "warning", 
                "message": "Docker API 异常",
                "detail": str(e)
            })
    else:
        beat_status.update({
            "status": "info", 
            "message": "无法检测 (无 Docker 权限)"
        })
    status["services"].append(beat_status)



    # 6. WeRSS
    try:
        from ...clients.werss import get_werss_client
        client = get_werss_client()
        if client._is_token_valid():
             status["services"].append({
                "name": "WeRSS 连接",
                "status": "ok",
                "message": "Token 有效",
                "icon": "rss"
            })
        else:
             # 尝试刷新
             try:
                 client._get_token()
                 status["services"].append({
                    "name": "WeRSS 连接",
                    "status": "ok",
                    "message": "连接正常 (已刷新)",
                    "icon": "rss"
                })
             except Exception:
                 status["services"].append({
                    "name": "WeRSS 连接",
                    "status": "error",
                    "message": "Token 无效且刷新失败",
                    "icon": "rss"
                })
    except Exception as e:
        status["services"].append({
            "name": "WeRSS 连接",
            "status": "error",
            "message": "连接失败",
            "detail": str(e),
            "icon": "rss"
        })

    # 7. DeepSeek API
    try:
        from ...config import get_settings
        settings = get_settings()
        if settings.deepseek_api_key:
            key_preview = "***" + settings.deepseek_api_key[-4:] if len(settings.deepseek_api_key) > 4 else "***"
            status["services"].append({
                "name": "DeepSeek API",
                "status": "ok",
                "message": f"已配置 (结尾: {key_preview})",
                "icon": "zap"
            })
        else:
             status["services"].append({
                "name": "DeepSeek API",
                "status": "error",
                "message": "未配置 API Key",
                "icon": "zap"
            })
    except Exception as e:
        status["services"].append({
            "name": "DeepSeek API",
            "status": "error",
            "message": "配置检查异常",
            "detail": str(e),
            "icon": "zap"
        })
        
    # 计算总体状态
    has_error = any(s.get("status") == "error" for s in status["services"])
    status["overall"] = "error" if has_error else "ok"
    
    return status
