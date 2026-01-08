# 投资机会雷达 (Investment Opportunity Radar)

从公众号文章中智能分析投资机会的系统。

## 功能特点

- 📡 **自动抓取**：从 WeRSS 定时拉取公众号文章
- 🧠 **AI 分析**：使用 DeepSeek 思考模型分析投资机会
- 📊 **智能评分**：对每篇文章进行机会评分（0-100）
- 🔔 **钉钉推送**：每天 5 次定时推送（07:00/12:00/14:00/18:00/22:00）
- 📱 **Web 界面**：响应式设计，支持 PC 和手机

## 快速开始

### 1. 安装依赖

```bash
# 使用 pip
pip install -e .

# 或使用 uv（更快）
uv pip install -e .
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际配置
```

### 3. 启动服务

```bash
# 开发模式
uvicorn src.app.main:app --reload --port 8000

# 生产模式
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

### 4. 访问

- 健康检查：http://localhost:8000/healthz
- 登录页面：http://localhost:8000/login

## 项目结构

```
src/
└── app/
    ├── main.py           # FastAPI 应用入口
    ├── config.py         # 配置管理
    ├── logging_config.py # 日志配置
    ├── clients/          # 外部服务客户端
    ├── core/             # 核心工具
    ├── domain/           # 数据模型
    ├── services/         # 业务逻辑
    ├── tasks/            # Celery 任务
    └── web/              # Web 界面
        ├── routers/      # API 路由
        ├── templates/    # Jinja2 模板
        └── static/       # 静态资源
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check .
```

## 许可证

MIT
