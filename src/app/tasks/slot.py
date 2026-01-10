"""
投资机会雷达 - Slot 任务

每个 Slot 的总编排逻辑：
1. 创建/获取 slot_run（幂等）
2. 从 WeRSS 拉取并入库文章
3. 逐篇分析
4. 推送机会/日报
"""
import json
import hashlib
from datetime import datetime, timedelta, date
from typing import Optional, List

from celery import shared_task
from sqlalchemy import and_

from ..database import SessionLocal
from ..domain.models import (
    SlotRun,
    ContentItem,
    AnalysisResult,
    DailyReport,
    PromptVersion,
    NotificationLog,
)
from ..services.analyzer import (
    fetch_and_save_articles,
    analyze_article,
    get_active_prompt,
    get_setting_value,
    should_push_opportunity,
    push_opportunity_alert,
    generate_msg_uuid,
    has_content,
    try_refresh_content,
)
from ..clients.dingtalk import get_dingtalk_client
from ..clients.deepseek import get_deepseek_client
from ..core.prompts import DAILY_DIGEST_SYSTEM_PROMPT, DAILY_DIGEST_USER_TEMPLATE
from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


def get_or_create_slot_run(session, run_date: date, slot: str) -> tuple[SlotRun, bool]:
    """
    获取或创建 slot_run（幂等）
    
    Returns:
        (slot_run, is_new)
    """
    existing = session.query(SlotRun).filter(
        SlotRun.run_date == run_date,
        SlotRun.slot == slot,
    ).first()
    
    if existing:
        return existing, False
    
    # 计算时间窗口
    now = datetime.now()
    window_days = get_setting_value(session, "window_days", 3)
    window_end = now
    window_start = now - timedelta(days=window_days)
    
    slot_run = SlotRun(
        run_date=run_date,
        slot=slot,
        window_start_at=window_start,
        window_end_at=window_end,
        status=0,  # 进行中
        stats={},
    )
    session.add(slot_run)
    session.commit()
    
    return slot_run, True


def is_last_slot_of_day(session, current_slot: str) -> bool:
    """
    判断当前 slot 是否为当天最后一个时间点
    
    从数据库读取 schedule_slots 配置，按时间排序后判断
    """
    from ..domain.models import Settings
    
    # 默认值
    default_slots = ["07:00", "12:00", "14:00", "18:00", "22:00"]
    
    # 从数据库读取
    setting = session.query(Settings).filter(Settings.key == "schedule_slots").first()
    if setting and setting.value_json:
        slots = setting.value_json
    else:
        slots = default_slots
    
    # 按时间排序
    sorted_slots = sorted(slots)
    
    # 判断是否为最后一个
    if sorted_slots:
        return current_slot == sorted_slots[-1]
    return False


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def run_slot(self, slot: str, manual: bool = False):
    """
    执行一个 slot 的完整流程 (Celery Task Wrapper)
    """
    execute_slot(slot, manual)


def execute_slot(slot: str, manual: bool = False):
    """
    执行一个 slot 的完整流程 (Core Logic)
    
    Args:
        slot: 时段标识，如 "07:00", "12:00", "22:00"
        manual: 是否为手动触发
    """
    settings = get_settings()
    session = SessionLocal()
    
    try:
        # 获取当前日期（北京时间）
        now = datetime.now()
        run_date = now.date()
        
        logger.info(f"===== 开始执行 slot: {run_date} {slot} =====")
        
        # 1. 获取或创建 slot_run（幂等）
        slot_run, is_new = get_or_create_slot_run(session, run_date, slot)
        
        if not is_new and slot_run.status == 1:
            logger.info(f"slot_run 已成功完成，跳过: {run_date} {slot}")
            return {"status": "skipped", "reason": "already_completed"}
        
        if not is_new and slot_run.status == 0:
            logger.warning(f"slot_run 正在运行中（可能重复触发）: {run_date} {slot}")
            # 允许继续（可能是重启后恢复）
        
        slot_run.status = 0  # 进行中
        slot_run.started_at = datetime.utcnow()
        session.commit()
        
        stats = {
            "articles_fetched": 0,
            "articles_new": 0,
            "articles_analyzed": 0,
            "articles_failed": 0,
            "opportunities_found": 0,
            "pushed": False,
        }
        
        try:
            # 2. 从 WeRSS 拉取并入库文章
            logger.info("开始获取文章...")
            new_items = fetch_and_save_articles(
                session=session,
                start_time=slot_run.window_start_at,
                end_time=slot_run.window_end_at,
            )
            stats["articles_new"] = len(new_items)
            logger.info(f"新增文章: {len(new_items)} 篇")
            
            # 3. 获取待分析文章
            pending_items = session.query(ContentItem).filter(
                ContentItem.analyzed_status == 0,
                ContentItem.published_at >= slot_run.window_start_at,
            ).all()
            
            stats["articles_fetched"] = len(pending_items)
            logger.info(f"待分析文章: {len(pending_items)} 篇")
            
            # 获取活跃的 Prompt
            prompt_version = get_active_prompt(session)
            if not prompt_version:
                logger.warning("未找到活跃的 Prompt，使用默认模板")
            
            # 判断是否为当天最后一个时间点（动态获取）
            is_last_slot = is_last_slot_of_day(session, slot)
            base_url = f"http://154.8.205.159:8080"  # TODO: 从配置读取
            
            # 4. 逐篇分析 + 立即推送
            pushed_count = 0
            skipped_count = 0  # 跳过的无正文文章数
            for item in pending_items:
                try:
                    # 检查正文，无正文则尝试重新拉取
                    if not has_content(item):
                        item = try_refresh_content(session, item)
                        if not has_content(item):
                            logger.info(f"跳过无正文文章: {item.title[:30]}")
                            skipped_count += 1
                            continue  # 跳过，不标记已分析
                    
                    analysis = analyze_article(
                        session=session,
                        content_item=item,
                        prompt_version=prompt_version,
                        run_id=slot_run.id,
                    )
                    if analysis:
                        stats["articles_analyzed"] += 1
                        if analysis.has_opportunity:
                            stats["opportunities_found"] += 1
                            # 立即推送有机会的文章
                            if should_push_opportunity(session, analysis, str(run_date), slot):
                                pushed = push_opportunity_alert(
                                    session=session,
                                    analysis=analysis,
                                    run_date=str(run_date),
                                    slot=slot,
                                    base_url=base_url,
                                )
                                if pushed:
                                    pushed_count += 1
                                    logger.info(f"已推送机会: {item.title[:30]}, score={analysis.score}")
                    else:
                        stats["articles_failed"] += 1
                except Exception as e:
                    logger.error(f"分析文章失败: {item.title[:30]}, {e}")
                    stats["articles_failed"] += 1
            
            stats["articles_skipped"] = skipped_count
            if skipped_count > 0:
                logger.info(f"跳过无正文文章: {skipped_count} 篇")
            
            # 5. 无机会时的通知 + 日报
            if is_last_slot:
                # 最后一个时间点：无机会时发送"当天没有机会"通知
                if pushed_count == 0:
                    from ..services.analyzer import push_no_opportunity_today
                    push_no_opportunity_today(
                        session=session,
                        analyzed_count=stats["articles_analyzed"],
                        run_date=str(run_date),
                        slot=slot,
                    )
                # 必发日报（无论有无机会）
                success = generate_and_push_daily_report(
                    session=session,
                    run_date=run_date,
                    slot=slot,
                    base_url=base_url,
                )
                stats["pushed"] = success
            elif manual:
                # 手动模式：无机会时发送汇总通知
                if pushed_count == 0:
                    from ..services.analyzer import push_manual_summary
                    push_manual_summary(
                        session=session,
                        analyzed_count=stats["articles_analyzed"],
                        run_date=str(run_date),
                        slot=slot,
                    )
                stats["pushed"] = pushed_count > 0 or True  # 手动模式总是标记为已推送
            else:
                # 非最后一次定时：无机会不发任何通知
                stats["pushed"] = pushed_count > 0
            
            stats["pushed_count"] = pushed_count
            
            # 6. 更新 slot_run 状态
            slot_run.status = 1  # 成功
            slot_run.stats = stats
            slot_run.finished_at = datetime.utcnow()
            session.commit()
            
            logger.info(f"===== slot 完成: {run_date} {slot}, stats={stats} =====")
            return {"status": "success", "stats": stats}
            
        except Exception as e:
            logger.error(f"slot 执行失败: {e}")
            slot_run.status = 2  # 失败
            slot_run.error = str(e)
            slot_run.finished_at = datetime.utcnow()
            session.commit()
            raise
            
    finally:
        session.close()


def generate_and_push_daily_report(
    session,
    run_date: date,
    slot: str,
    base_url: str,
) -> bool:
    """
    生成并推送日报（22:00 必推）
    """
    logger.info(f"开始生成日报: {run_date}")
    
    # 获取当天所有分析结果
    today_analyses = session.query(AnalysisResult).join(ContentItem).filter(
        and_(
            ContentItem.published_at >= datetime.combine(run_date, datetime.min.time()),
            ContentItem.published_at < datetime.combine(run_date + timedelta(days=1), datetime.min.time()),
        )
    ).all()
    
    # 构建 compact 结构
    analyses_compact = []
    for a in today_analyses:
        item = a.content_item
        opp_types = a.result_json.get("opportunity_types", [])
        analyses_compact.append({
            "title": item.title,
            "mp_name": item.mp_name,
            "published_at": item.published_at.isoformat(),
            "score": a.score,
            "has_opportunity": a.has_opportunity,
            "top_type": opp_types[0] if opp_types else "",
            "summary": a.summary_md[:200],
            "analysis_url": f"{base_url}/analysis/{a.id}",
        })
    
    # 获取阈值
    threshold = get_setting_value(session, "push_score_threshold", 60)
    
    # 统计
    total_articles = len(analyses_compact)
    opportunities = [a for a in analyses_compact if a["has_opportunity"] and a["score"] >= threshold]
    total_opportunities = len(opportunities)
    
    # 生成日报内容（调用 DeepSeek 或使用简单模板）
    if total_articles > 0:
        try:
            digest_result = generate_daily_digest(
                date=str(run_date),
                threshold=threshold,
                analyses=analyses_compact,
            )
            digest_md = digest_result.get("digest_md", "")
            has_opportunity = digest_result.get("has_opportunity", False)
        except Exception as e:
            logger.error(f"日报生成失败: {e}")
            digest_md = f"## {run_date} 日报\n\n日报生成失败，请稍后刷新。\n\n错误: {e}"
            has_opportunity = total_opportunities > 0
    else:
        digest_md = f"## {run_date} 日报\n\n**今日无新文章分析。**"
        has_opportunity = False
    
    # 保存日报
    report = session.query(DailyReport).filter(DailyReport.report_date == run_date).first()
    if report:
        report.digest_md = digest_md
        report.digest_json = {"analyses": analyses_compact}
        report.stats = {
            "articles_analyzed": total_articles,
            "opportunities_found": total_opportunities,
        }
        report.updated_at = datetime.utcnow()
    else:
        report = DailyReport(
            report_date=run_date,
            digest_md=digest_md,
            digest_json={"analyses": analyses_compact},
            slots_done=[slot],
            stats={
                "articles_analyzed": total_articles,
                "opportunities_found": total_opportunities,
            },
        )
        session.add(report)
    session.commit()
    
    # 推送日报
    dingtalk = get_dingtalk_client()
    msg_uuid = generate_msg_uuid(str(run_date), slot, "daily")
    
    try:
        result = dingtalk.send_daily_report(
            date=str(run_date),
            has_opportunity=has_opportunity,
            total_articles=total_articles,
            total_opportunities=total_opportunities,
            digest=digest_md[:500],  # 摘要
            base_url=base_url,
            msg_uuid=msg_uuid,
        )
        
        success = result.get("errcode") == 0
        
        # 记录推送日志
        log = NotificationLog(
            report_date=str(run_date),
            slot=slot,
            push_type="daily",
            msg_uuid=msg_uuid,
            target_url=f"{base_url}/daily/{run_date}",
            title=f"日报 {run_date}",
            payload={"report_date": str(run_date)},
            response=result,
            status=1 if success else 2,
            error=result.get("errmsg") if not success else None,
        )
        session.add(log)
        session.commit()
        
        logger.info(f"日报推送{'成功' if success else '失败'}: {run_date}")
        return success
        
    except Exception as e:
        logger.error(f"日报推送异常: {e}")
        return False


def generate_daily_digest(date: str, threshold: int, analyses: list) -> dict:
    """
    使用 DeepSeek 生成日报内容
    """
    deepseek = get_deepseek_client()
    
    user_prompt = DAILY_DIGEST_USER_TEMPLATE.format(
        date=date,
        threshold=threshold,
        today_analyses_json=json.dumps(analyses, ensure_ascii=False, indent=2),
    )
    
    result = deepseek.analyze_article(
        system_prompt=DAILY_DIGEST_SYSTEM_PROMPT,
        article_content=user_prompt,
    )
    
    return result
