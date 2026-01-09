"""
投资机会雷达 - Celery 配置与应用

按照文档 9 定义的任务编排规范。
"""
from celery import Celery
from celery.schedules import crontab

from ..config import get_settings

settings = get_settings()

# 创建 Celery 应用
app = Celery(
    "radar",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# 配置
app.conf.update(
    # 时区设置（北京时间）
    timezone="Asia/Shanghai",
    enable_utc=False,
    
    # 任务序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    
    # 任务执行
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # 并发设置（文档建议 2）
    worker_concurrency=2,
    
    # 结果过期时间（1天）
    result_expires=86400,
    
    # 任务路由（可选）
    task_routes={
        "src.app.tasks.slot.*": {"queue": "slot"},
        "src.app.tasks.analysis.*": {"queue": "analysis"},
    },
    
    # 定时任务（Celery Beat）
    beat_schedule={
        # 每天 07:00 触发
        "slot-07:00": {
            "task": "src.app.tasks.slot.run_slot",
            "schedule": crontab(hour=7, minute=0),
            "args": ("07:00",),
        },
        # 每天 12:00 触发
        "slot-12:00": {
            "task": "src.app.tasks.slot.run_slot",
            "schedule": crontab(hour=12, minute=0),
            "args": ("12:00",),
        },
        # 每天 14:00 触发
        "slot-14:00": {
            "task": "src.app.tasks.slot.run_slot",
            "schedule": crontab(hour=14, minute=0),
            "args": ("14:00",),
        },
        # 每天 18:00 触发
        "slot-18:00": {
            "task": "src.app.tasks.slot.run_slot",
            "schedule": crontab(hour=18, minute=0),
            "args": ("18:00",),
        },
        # 每天 22:00 触发（必推日报）
        "slot-22:00": {
            "task": "src.app.tasks.slot.run_slot",
            "schedule": crontab(hour=22, minute=0),
            "args": ("22:00",),
        },
    },
)

# 自动发现任务
app.autodiscover_tasks(["src.app.tasks"])
