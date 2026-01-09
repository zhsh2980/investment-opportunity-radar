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


def get_schedule_slots_from_db():
    """
    从数据库读取 schedule_slots 配置
    如果不存在则返回默认值
    """
    from ..database import SessionLocal
    from ..domain.models import Settings
    
    default_slots = ["07:00", "12:00", "14:00", "18:00", "22:00"]
    
    try:
        session = SessionLocal()
        setting = session.query(Settings).filter(Settings.key == "schedule_slots").first()
        session.close()
        
        if setting and setting.value_json:
            return setting.value_json
        return default_slots
    except Exception:
        return default_slots


def build_beat_schedule(slots: list) -> dict:
    """
    根据 slots 列表动态生成 beat_schedule
    """
    schedule = {}
    for slot in slots:
        try:
            hour, minute = map(int, slot.split(":"))
            schedule[f"slot-{slot}"] = {
                "task": "src.app.tasks.slot.run_slot",
                "schedule": crontab(hour=hour, minute=minute),
                "args": (slot,),
            }
        except ValueError:
            continue  # 跳过格式不正确的 slot
    return schedule


# 从数据库获取 slots 并生成调度
schedule_slots = get_schedule_slots_from_db()
beat_schedule = build_beat_schedule(schedule_slots)


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
    
    # 定时任务（Celery Beat）- 动态生成
    beat_schedule=beat_schedule,
)

# 自动发现任务
app.autodiscover_tasks(["src.app.tasks"])

