"""
投资机会雷达 - Celery 任务模块
"""
from .celery_app import app as celery_app
from .slot import run_slot

__all__ = ["celery_app", "run_slot"]
