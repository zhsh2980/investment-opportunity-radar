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
    channel_msg_uuid,
    push_via_channel,
    has_content,
    try_refresh_content,
)
from ..clients.dingtalk import get_dingtalk_client
from ..clients.feishu import get_feishu_client, is_feishu_configured
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
            stats["articles_total"] = len(pending_items)  # 初始总数，用于进度显示
            # 立即更新 stats 到数据库，让进度 API 能读取
            slot_run.stats = stats.copy()
            session.commit()
            logger.info(f"待分析文章: {len(pending_items)} 篇")
            
            # 获取活跃的 Prompt
            prompt_version = get_active_prompt(session)
            if not prompt_version:
                logger.warning("未找到活跃的 Prompt，使用默认模板")
            
            # 判断是否为当天最后一个时间点（动态获取）
            is_last_slot = is_last_slot_of_day(session, slot)
            base_url = get_settings().public_base_url.rstrip("/")
            
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
                    # 必须先回滚再做任何事：失败可能发生在 flush/commit 中途，
                    # session 已进入 PendingRollback 状态且对象已被 expire——
                    # 此时连 item.title 这样的属性访问都会触发懒加载再次抛错。
                    # 不回滚的话后续所有 DB 操作（其余文章的分析、日报、
                    # 标记批次失败）都会连环失败，批次永远卡在"运行中"
                    session.rollback()
                    logger.error(f"分析文章失败: {item.title[:30]}, {e}")
                    stats["articles_failed"] += 1
            
            stats["articles_skipped"] = skipped_count
            if skipped_count > 0:
                logger.info(f"跳过无正文文章: {skipped_count} 篇")
            
            # 5. 无机会时的通知 + 日报
            if is_last_slot:
                # 最后一个时间点：无机会时发送"当天没有机会"通知
                # 最后一个时间点：无论有无机会，都必发日报
                # (移除 push_no_opportunity_today，避免重复通知)
                # 必发日报（无论有无机会）
                success = generate_and_push_daily_report(
                    session=session,
                    run_date=run_date,
                    slot=slot,
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
            # session 可能已被之前的异常毒化，先回滚才能写入失败状态；
            # 否则这里的 commit 也会抛 PendingRollbackError，批次永远停在"运行中"
            session.rollback()
            slot_run.status = 2  # 失败
            slot_run.error = str(e)
            slot_run.finished_at = datetime.utcnow()
            session.commit()
            raise
            
    finally:
        session.close()


def _get_alerted_analysis_ids(session, run_date: date) -> set:
    """今天已经通过独立简报成功推送过的 analysis id 集合（日报里不再重复展开要点）"""
    logs = session.query(NotificationLog).filter(
        NotificationLog.push_type == "opportunity",
        NotificationLog.report_date == run_date,
        NotificationLog.status == 1,
    ).all()
    return {
        log.payload.get("analysis_id")
        for log in logs
        if log.payload and log.payload.get("analysis_id") is not None
    }


def _format_digest_line(a) -> str:
    """未单独推送过的文章：分数 + 标题（超链原文）+ 要点首条"""
    item = a.content_item
    key_points = a.result_json.get("key_points", [])
    first_point = key_points[0] if key_points else ""
    title_md = f"[{item.title}]({item.url})" if item.url else item.title
    line = f"· {a.score}分 {title_md}"
    if first_point:
        line += f" — {first_point}"
    return line


def _build_grouped_digest_body(analyses, alerted_ids: set) -> str:
    """按信源分组、组内按分数降序拼装日报正文"""
    groups: dict = {}
    for a in analyses:
        name = a.content_item.mp_name or "未知来源"
        groups.setdefault(name, []).append(a)
    for items in groups.values():
        items.sort(key=lambda a: a.score, reverse=True)

    sections = []
    for name in sorted(groups.keys()):
        lines = [f"**{name}**"]
        for a in groups[name]:
            if a.id in alerted_ids:
                lines.append(f"· {a.score}分 {a.content_item.title}（已提醒）")
            else:
                lines.append(_format_digest_line(a))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def generate_and_push_daily_report(
    session,
    run_date: date,
    slot: str,
) -> bool:
    """
    生成并推送日报（拼装模式，不调用 AI）：按信源分组，已单独推送过简报的
    条目只标「（已提醒）」不重复展开要点。纯钉钉消息，不链接系统内任何页面。
    """
    logger.info(f"开始生成日报: {run_date}")

    # 获取当天所有分析结果
    today_analyses = session.query(AnalysisResult).join(ContentItem).filter(
        and_(
            ContentItem.published_at >= datetime.combine(run_date, datetime.min.time()),
            ContentItem.published_at < datetime.combine(run_date + timedelta(days=1), datetime.min.time()),
        )
    ).order_by(AnalysisResult.score.desc()).all()

    # 获取阈值
    threshold = get_setting_value(session, "push_score_threshold", 60)

    # 统计
    total_articles = len(today_analyses)
    opportunities = [a for a in today_analyses if a.has_opportunity and a.score >= threshold]
    total_opportunities = len(opportunities)
    has_opportunity = total_opportunities > 0

    # 构建日报正文（拼装模式，按信源分组）
    if total_articles > 0:
        alerted_ids = _get_alerted_analysis_ids(session, run_date)
        digest_md = _build_grouped_digest_body(today_analyses, alerted_ids)
    else:
        digest_md = "今日无新文章分析。"

    # 构建 compact 结构用于存储
    analyses_compact = []
    for a in today_analyses:
        item = a.content_item
        opp_types = a.result_json.get("opportunity_types", [])
        key_points = a.result_json.get("key_points", [])
        analyses_compact.append({
            "title": item.title,
            "mp_name": item.mp_name,
            "published_at": item.published_at.isoformat(),
            "score": a.score,
            "has_opportunity": a.has_opportunity,
            "top_type": opp_types[0] if opp_types else "",
            "key_points": key_points,
            "url": item.url,
        })

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

    # 推送日报（钉钉 + 飞书并行，各自独立记录一条 NotificationLog）
    msg_uuid = generate_msg_uuid(str(run_date), slot, "daily")

    # report_date 是 Date 列，需要真正的 date 对象；Postgres 曾容忍字符串，SQLite 不容忍
    dingtalk_success, dt_result, dt_error = push_via_channel(
        lambda: get_dingtalk_client().send_daily_report(
            date=str(run_date),
            has_opportunity=has_opportunity,
            total_articles=total_articles,
            total_opportunities=total_opportunities,
            digest=digest_md,
            msg_uuid=msg_uuid,
        ),
        success_field="errcode",
        channel_label="钉钉",
    )
    # target_url 留空：/daily 落地页已下线，日报只作为消息存在
    session.add(NotificationLog(
        report_date=run_date,
        slot=slot,
        push_type="daily",
        msg_uuid=msg_uuid,
        target_url="",
        title=f"日报 {run_date}",
        payload={"report_date": str(run_date)},
        response=dt_result,
        status=1 if dingtalk_success else 2,
        error=dt_error,
    ))
    session.commit()

    feishu_success = False
    if is_feishu_configured():
        feishu_msg_uuid = channel_msg_uuid(msg_uuid, "feishu")
        feishu_success, fs_result, fs_error = push_via_channel(
            lambda: get_feishu_client().send_daily_report(
                date=str(run_date),
                has_opportunity=has_opportunity,
                total_articles=total_articles,
                total_opportunities=total_opportunities,
                digest=digest_md,
                msg_uuid=feishu_msg_uuid,
            ),
            success_field="code",
            channel_label="飞书",
        )
        session.add(NotificationLog(
            report_date=run_date,
            slot=slot,
            push_type="daily",
            msg_uuid=feishu_msg_uuid,
            target_url="",
            title=f"日报 {run_date}",
            payload={"report_date": str(run_date)},
            response=fs_result,
            status=1 if feishu_success else 2,
            error=fs_error,
        ))
        session.commit()

    success = dingtalk_success or feishu_success
    logger.info(f"日报推送{'成功' if success else '失败'}: {run_date}")
    return success
