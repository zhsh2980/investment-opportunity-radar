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

# 强制浏览器不缓存 HTML (解决用户开发期间看不到更新的问题)
# 同时为 JS/CSS 文件添加正确的 UTF-8 编码声明
@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    
    # HTML 不缓存
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    
    # JS/CSS 文件添加 UTF-8 编码
    if "javascript" in content_type and "charset" not in content_type:
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    elif "text/css" in content_type and "charset" not in content_type:
        response.headers["Content-Type"] = "text/css; charset=utf-8"
    
    return response

# 静态文件
app.mount("/static", StaticFiles(directory="src/app/web/static"), name="static")

# 模板
templates = Jinja2Templates(directory="src/app/web/templates")

# ===== 注册路由 =====
from .web.routers import auth, pages, admin
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(admin.router)


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
            return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=True)
