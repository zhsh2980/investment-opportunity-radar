"""
投资机会雷达 - FastAPI 主应用入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from .config import get_settings
from .logging_config import setup_logging, get_logger

# 初始化日志
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 投资机会雷达启动中...")
    settings = get_settings()
    logger.info(f"时区: {settings.tz}")
    yield
    logger.info("👋 投资机会雷达关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="投资机会雷达",
    description="从公众号文章中分析投资机会",
    version="0.1.0",
    lifespan=lifespan,
)

# 静态文件
app.mount("/static", StaticFiles(directory="src/app/web/static"), name="static")

# 模板
templates = Jinja2Templates(directory="src/app/web/templates")

# ===== 注册路由 =====
from .web.routers import auth
app.include_router(auth.router)


# ===== 健康检查 =====
@app.get("/healthz")
async def healthz():
    """健康检查端点"""
    return {"status": "ok", "service": "radar"}


# ===== 登录页面 =====
@app.get("/login")
async def login_page(request: Request):
    """登录页面"""
    # 如果已登录，跳转到首页
    token = request.cookies.get("session_token")
    if token:
        from .core.security import verify_session_token
        user_id = verify_session_token(token)
        if user_id:
            return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/")
async def root(request: Request):
    """根路由"""
    token = request.cookies.get("session_token")
    if token:
        from .core.security import verify_session_token
        user_id = verify_session_token(token)
        if user_id:
            return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard")
async def dashboard_page(request: Request):
    """仪表板页面（需要登录）"""
    from .core.security import verify_session_token
    from .database import SessionLocal
    from .domain.models import AppUser
    
    token = request.cookies.get("session_token")
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = verify_session_token(token)
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    
    # 获取用户名
    session = SessionLocal()
    try:
        user = session.query(AppUser).filter(AppUser.id == user_id).first()
        username = user.username if user else "未知用户"
    finally:
        session.close()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=True)

