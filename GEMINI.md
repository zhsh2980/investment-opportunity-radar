docs/设计文档  这个文件夹是我开发计划的文档
docs/使用文档  这个是我目前实际开发出来的文档。
docs/UI设计文档  就是 UI 设计文档 ，已经按照这种方式设计了
docs/WeRSS相关  这个是项目部署文档
docs/开发工作流.md  这是工作开发的工作流程
docs/key    用部署相关的一些 `key`，这个不可以提交到 GitHub.

## SSH 连接
服务器 SSH 连接命令参见 `docs/key/ssh_commands.md`（该文件不会提交到 GitHub）

## 常用脚本
scripts/deploy.sh  一键部署脚本：服务器拉取代码并重启服务（web/worker/beat）

## 部署注意事项
- Docker 容器修改代码后必须用 `--build` 重建镜像，仅 `restart` 不会加载新代码
- 修改模板/静态文件后需 rebuild web 容器：`docker compose up -d --build web`

> **⚠️ 重要**: 每次修改代码后，**必须使用 `scripts/deploy.sh`** 或以下命令部署：
> ```bash
> cd /srv/opportunity-insight && docker compose up -d --build web worker beat
> ```
> **绝对不要**用 `docker compose restart`，这样无法加载新代码！

## 数据库安全操作规范

> **🚨 危险操作警告**: 涉及以下操作前，**必须先备份数据库**：
> - 执行 `docker compose down`
> - 重建 postgres 容器
> - 修改 docker-compose.yml 影响 volumes 的配置

### 备份命令
```bash
# 在服务器执行
docker exec radar-postgres pg_dump -U radar radar > /srv/opportunity-insight/data/backup_$(date +%Y%m%d_%H%M%S).sql
```

### 恢复命令
```bash
# 如果数据丢失，先重建表结构
docker exec radar-web alembic upgrade head

# 然后恢复数据
cat /srv/opportunity-insight/data/backup_YYYYMMDD_HHMMSS.sql | docker exec -i radar-postgres psql -U radar radar
```

## 常见错误经验

### 1. WeRSS API 响应格式
WeRSS 所有 API 返回格式都是 `{"code":0, "data":{...}}`，**不是**直接返回数据。
```python
# ❌ 错误写法
return self._request("GET", "/mps")

# ✅ 正确写法
result = self._request("GET", "/mps")
return result.get("data", {}).get("list", [])
```
**涉及文件**: `src/app/clients/werss.py` 中的所有 API 方法

### 2. 时区比较问题
数据库 `DateTime(timezone=True)` 字段存储的是带时区信息的时间，不能与 `datetime.now()` 或 `datetime.utcnow()` 直接比较。
```python
# ❌ 可能有问题（时区不匹配）
recent_time = datetime.utcnow() - timedelta(hours=1)
db.query(Model).filter(Model.started_at >= recent_time)

# ✅ 更简单的方案：避免时间比较，直接用状态字段
db.query(Model).filter(Model.status == 0)  # 0=进行中
```

### 3. Celery Task 与普通函数
`@shared_task(bind=True)` 装饰的函数期望 `self` 参数，不能被 FastAPI `BackgroundTasks` 直接调用。
```python
# ✅ 解决方案：提取核心逻辑到独立函数
def execute_slot(slot: str, manual: bool = False):
    """核心业务逻辑"""
    ...

@shared_task(bind=True)
def run_slot(self, slot: str, manual: bool = False):
    """Celery wrapper"""
    execute_slot(slot, manual)

# API 中直接调用 execute_slot
background_tasks.add_task(execute_slot, slot=now_str, manual=True)
```

### 4. PromptVersion 字段名
`PromptVersion` 模型使用 `system_prompt` 而不是 `prompt_text`。
```python
# ❌ 错误
system_prompt = prompt_version.prompt_text

# ✅ 正确
system_prompt = prompt_version.system_prompt
```

### 5. Celery Worker 队列配置
`celery_app.py` 中配置了 `task_routes`，将任务路由到不同队列。**Worker 必须监听这些队列**，否则任务无法消费！
```yaml
# docker-compose.yml 中 worker 的 command 必须包含 -Q 参数
command: celery -A src.app.tasks.celery_app worker -l info -Q celery,slot,analysis

# ❌ 错误：没有 -Q 参数，只监听默认 celery 队列
command: celery -A src.app.tasks.celery_app worker -l info
```
**涉及文件**: 
- `docker-compose.yml` 中 worker 的 command
- `src/app/tasks/celery_app.py` 中的 `task_routes` 配置

### 6. Web 容器端口映射（502 错误）
Nginx 配置转发到 `127.0.0.1:9000`，docker-compose.yml 中 web 端口映射必须是 `127.0.0.1:9000:8000`。
```yaml
# ❌ 错误（Nginx 无法转发，导致 502）
ports:
  - "8000:8000"

# ✅ 正确
ports:
  - "127.0.0.1:9000:8000"
```
**症状**: 访问任何页面都返回 502 Bad Gateway