"""
投资机会雷达 - 文章分析服务

核心分析逻辑：
1. 从「今天看啥」VIP RSS 获取文章
2. 使用 DeepSeek 分析
3. 保存结果到数据库
4. 根据阈值触发钉钉推送
"""
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from ..clients.jtks import get_jtks_client
from ..clients.deepseek import get_deepseek_client
from ..clients.dingtalk import get_dingtalk_client
from ..core.prompts import (
    OPPORTUNITY_ANALYZER_SYSTEM_PROMPT,
    OPPORTUNITY_ANALYZER_USER_TEMPLATE,
    OPPORTUNITY_TYPES,
)
from ..domain.models import (
    ContentItem,
    AnalysisResult,
    Opportunity,
    SlotRun,
    PromptVersion,
    NotificationLog,
    Settings,
)
from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


def html_to_text(html: str) -> str:
    """将 HTML 转换为纯文本"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # 移除脚本和样式
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # 限制长度
    max_len = 15000
    if len(text) > max_len:
        text = text[:max_len] + "\n\n[内容过长，已截断]"
    return text


def compute_content_hash(content: str) -> str:
    """计算内容哈希（用于去重）"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


def has_content(item: ContentItem) -> bool:
    """
    检查文章是否有正文内容
    
    Args:
        item: 文章对象
        
    Returns:
        True 如果有正文内容，否则 False
    """
    # 优先检查 raw_text（已转换的纯文本）
    if item.raw_text and len(item.raw_text.strip()) > 50:  # 至少 50 字符
        return True
    
    # 如果 raw_text 为空或不足，尝试从 raw_html 重新转换后检查
    # 这样可以避免空模板 HTML（只有 CSS 样式，无实际内容）被误判为有内容
    if item.raw_html:
        converted_text = html_to_text(item.raw_html)
        if len(converted_text.strip()) > 50:
            return True
    
    return False


def try_refresh_content(session: Session, item: ContentItem) -> ContentItem:
    """
    尝试从「今天看啥」feed 重新获取文章正文

    当本地文章无正文时，重新扫描各专栏 feed 找到该文章并更新。
    feed 只保留最近若干篇，过旧的文章可能已不在 feed 中。

    Args:
        session: 数据库会话
        item: 文章对象

    Returns:
        更新后的文章对象（如果获取到正文）或原对象
    """
    client = get_jtks_client()

    try:
        logger.info(f"重新拉取文章正文: {item.title[:30]}...")
        articles, _ = client.fetch_all()
        match = next((a for a in articles if a["external_id"] == item.external_id), None)

        raw_html = match["html"] if match else ""
        if raw_html and len(raw_html.strip()) > 100:
            # 成功获取到正文，更新数据库
            raw_text = html_to_text(raw_html)
            item.raw_html = raw_html
            item.raw_text = raw_text
            item.content_hash = compute_content_hash(raw_text)
            session.commit()
            logger.info(f"成功更新文章正文: {item.title[:30]}")
        else:
            logger.info(f"feed 中未找到正文: {item.title[:30]}")

    except Exception as e:
        logger.error(f"重新拉取正文失败: {item.external_id}, {e}")

    return item


def get_active_prompt(session: Session, name: str = "opportunity_analyzer") -> Optional[PromptVersion]:
    """获取当前生效的 Prompt 版本"""
    return session.query(PromptVersion).filter(
        PromptVersion.name == name,
        PromptVersion.is_active == True
    ).first()


def get_setting_value(session: Session, key: str, default: Any = None) -> Any:
    """获取配置值"""
    setting = session.query(Settings).filter(Settings.key == key).first()
    if setting:
        return setting.value_json
    return default


def fetch_and_save_articles(
    session: Session,
    start_time: datetime,
    end_time: datetime,
) -> List[ContentItem]:
    """
    从「今天看啥」各专栏 feed 获取文章并保存到数据库

    Returns:
        新增的文章列表
    """
    client = get_jtks_client()
    articles, failures = client.fetch_all()

    new_items = []

    for article in articles:
        published_at = article["published_at"]
        # feed 只有最近若干篇，按窗口过滤（无发布时间的保留，交给后续流程判断）
        if published_at and not (start_time <= published_at <= end_time):
            continue

        external_id = article["external_id"]

        # 检查是否已存在
        existing = session.query(ContentItem).filter(
            ContentItem.external_id == external_id
        ).first()

        if existing:
            logger.debug(f"文章已存在: {external_id}")
            continue

        raw_html = article["html"]
        raw_text = html_to_text(raw_html)
        content_hash = compute_content_hash(raw_text)

        published_at = published_at or datetime.now()

        # 创建记录
        item = ContentItem(
            source_type="jtks",
            source_id=article["column_id"],
            external_id=external_id,
            mp_id=article["column_id"],
            mp_name=article["column_name"],
            title=article["title"],
            url=article["url"],
            description=raw_text[:200] if raw_text else None,
            pic_url=None,
            published_at=published_at,
            werss_publish_time=int(published_at.timestamp()),
            status=1,
            raw_html=raw_html,
            raw_text=raw_text,
            content_hash=content_hash,
            analyzed_status=0,  # 待分析
        )

        session.add(item)
        new_items.append(item)
        logger.info(f"新增文章: {item.title[:30]}...")

    session.commit()
    logger.info(f"获取文章完成: 新增 {len(new_items)} 篇")

    # 数据源健康检查（连续失败 / 长时间无新文章 → 钉钉告警）
    try:
        check_source_health(session, failures)
    except Exception as e:
        logger.error(f"数据源健康检查失败: {e}")

    return new_items


# 数据源健康告警阈值
FEED_FAIL_ALERT_THRESHOLD = 3      # feed 连续失败次数
COLUMN_STALE_HOURS = 48            # 专栏无新文章告警阈值（小时）
STALE_ALERT_INTERVAL_HOURS = 24    # 同一告警的最小间隔（小时）


def check_source_health(session: Session, failures: Dict[str, str]) -> None:
    """
    数据源健康检查，异常时钉钉告警：
    1. 某个 feed 连续失败 >= FEED_FAIL_ALERT_THRESHOLD 次
    2. 某专栏超过 COLUMN_STALE_HOURS 小时无新文章
    告警状态记录在 settings 表 key=jtks_feed_health。
    """
    now = datetime.now()
    health_setting = session.query(Settings).filter(Settings.key == "jtks_feed_health").first()
    health: Dict[str, Any] = dict(health_setting.value_json) if health_setting else {}
    feed_state: Dict[str, Any] = dict(health.get("feeds", {}))
    stale_state: Dict[str, Any] = dict(health.get("stale_alerts", {}))
    alerts: List[str] = []

    # 1. feed 连续失败计数
    settings = get_settings()
    for feed_url in settings.jtks_feeds:
        key = feed_url[-24:]  # 用尾部 token 片段做 key，避免整条 URL 入库
        state = dict(feed_state.get(key, {"fail_count": 0, "alerted": False}))
        if feed_url in failures:
            state["fail_count"] = state.get("fail_count", 0) + 1
            if state["fail_count"] >= FEED_FAIL_ALERT_THRESHOLD and not state.get("alerted"):
                alerts.append(
                    f"- feed 连续 {state['fail_count']} 次拉取失败（…{key}）：{failures[feed_url][:80]}"
                )
                state["alerted"] = True
        else:
            state = {"fail_count": 0, "alerted": False}
        feed_state[key] = state

    # 2. 专栏超时无新文章
    from sqlalchemy import func as sa_func
    rows = (
        session.query(ContentItem.mp_name, sa_func.max(ContentItem.published_at))
        .filter(ContentItem.source_type == "jtks")
        .group_by(ContentItem.mp_name)
        .all()
    )
    for mp_name, latest in rows:
        if latest is None:
            continue
        hours = (now - latest).total_seconds() / 3600
        if hours >= COLUMN_STALE_HOURS:
            last_alert = stale_state.get(mp_name)
            last_alert_dt = datetime.fromisoformat(last_alert) if last_alert else None
            if not last_alert_dt or (now - last_alert_dt).total_seconds() >= STALE_ALERT_INTERVAL_HOURS * 3600:
                alerts.append(f"- 专栏「{mp_name}」已 {int(hours)} 小时无新文章")
                stale_state[mp_name] = now.isoformat()
        else:
            stale_state.pop(mp_name, None)

    # 保存健康状态
    new_value = {"feeds": feed_state, "stale_alerts": stale_state, "checked_at": now.isoformat()}
    if health_setting:
        health_setting.value_json = new_value
    else:
        session.add(Settings(key="jtks_feed_health", value_json=new_value))
    session.commit()

    # 发送告警
    if alerts:
        try:
            dingtalk = get_dingtalk_client()
            dingtalk.send_markdown(
                title="数据源健康告警",
                text="## ⚠️ 数据源健康告警\n\n" + "\n".join(alerts),
            )
            logger.warning(f"已发送数据源健康告警: {len(alerts)} 条")
        except Exception as e:
            logger.error(f"发送数据源健康告警失败: {e}")


def analyze_article(
    session: Session,
    content_item: ContentItem,
    prompt_version: PromptVersion,
    run_id: Optional[int] = None,
    max_retries: int = 3,
) -> Optional[AnalysisResult]:
    """
    使用 DeepSeek 分析单篇文章
    
    Args:
        session: 数据库会话
        content_item: 待分析的文章
        prompt_version: Prompt 版本
        run_id: 批次运行 ID
        max_retries: 最大重试次数
    
    Returns:
        分析结果，失败返回 None
    """
    deepseek = get_deepseek_client()
    settings = get_settings()
    
    # 准备输入
    user_prompt = OPPORTUNITY_ANALYZER_USER_TEMPLATE.format(
        title=content_item.title,
        mp_name=content_item.mp_name or "未知公众号",
        published_at=content_item.published_at.isoformat(),
        url=content_item.url or "",
        content_text=content_item.raw_text or "",
    )
    
    # 使用数据库中的 system_prompt（如有），否则用默认模板
    system_prompt = prompt_version.system_prompt if prompt_version else OPPORTUNITY_ANALYZER_SYSTEM_PROMPT
    
    result_json = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 调用 DeepSeek
            current_user_prompt = user_prompt
            if attempt == 1:
                current_user_prompt += "\n\n务必只输出 JSON，不要输出任何其它字符。"
            elif attempt >= 2:
                current_user_prompt += "\n\n请严格按 EXAMPLE JSON OUTPUT 的字段顺序输出，缺字段用空值补齐。"
            
            result_json = deepseek.analyze_article(
                system_prompt=system_prompt,
                article_content=current_user_prompt,
            )
            
            # 校验必填字段
            required_fields = ["score", "has_opportunity", "summary"]
            missing = [f for f in required_fields if f not in result_json]
            if missing:
                raise ValueError(f"缺少必填字段: {missing}")
            
            break  # 成功
            
        except Exception as e:
            last_error = str(e)
            logger.warning(f"分析失败 (attempt {attempt + 1}): {e}")
    
    if not result_json:
        logger.error(f"文章分析最终失败: {content_item.title[:30]}, 错误: {last_error}")
        content_item.analyzed_status = 3  # 失败
        session.commit()
        return None
    
    # 创建分析结果
    score = result_json.get("score", 0)
    has_opportunity = result_json.get("has_opportunity", False)
    summary = result_json.get("summary", "")
    
    analysis = AnalysisResult(
        content_item_id=content_item.id,
        run_id=run_id,
        prompt_version_id=prompt_version.id if prompt_version else None,
        model=settings.deepseek_model,
        score=score,
        has_opportunity=has_opportunity,
        result_json=result_json,
        summary_md=summary,
    )
    session.add(analysis)
    session.flush()  # 获取 ID
    
    # 创建机会点记录
    opportunities = result_json.get("opportunities", [])
    for idx, opp in enumerate(opportunities):
        opp_record = Opportunity(
            analysis_id=analysis.id,
            idx=idx,
            type=opp.get("type", "other"),
            title=opp.get("title", ""),
            score_hint=opp.get("confidence", 0) * 100 if opp.get("confidence") else None,
            confidence=opp.get("confidence"),
            how_to=opp.get("action_steps", []),
            constraints=opp.get("constraints", []),
            need_search_queries=opp.get("search_suggestions", []),
            numbers=opp.get("key_numbers", {}),
        )
        
        # 解析时间窗口
        time_window = opp.get("time_window", {})
        if time_window.get("start"):
            try:
                opp_record.time_window_start = datetime.fromisoformat(
                    time_window["start"].replace("Z", "+00:00")
                )
            except Exception:
                pass
        if time_window.get("end"):
            try:
                opp_record.time_window_end = datetime.fromisoformat(
                    time_window["end"].replace("Z", "+00:00")
                )
            except Exception:
                pass
        
        session.add(opp_record)
    
    # 更新文章状态
    content_item.analyzed_status = 2  # 已分析
    content_item.analyzed_at = datetime.utcnow()
    
    session.commit()
    logger.info(f"分析完成: {content_item.title[:30]}, score={score}, has_opp={has_opportunity}")
    
    return analysis


def should_push_opportunity(
    session: Session,
    analysis: AnalysisResult,
    run_date: str,
    slot: str,
) -> bool:
    """
    判断是否应该推送机会提醒
    
    规则（按文档）：
    - 每天前 4 次 slot（不含 22:00）命中阈值才推
    - 22:00 只推日报，不推单独机会
    """
    if slot == "22:00":
        return False
    
    threshold = get_setting_value(session, "push_score_threshold", 60)
    
    if analysis.score < threshold:
        return False
    
    if not analysis.has_opportunity:
        return False
    
    # 检查当天已推送次数（排除 22:00 slot）
    today_pushes = session.query(NotificationLog).filter(
        NotificationLog.report_date == run_date,
        NotificationLog.push_type == "opportunity",
        NotificationLog.status == 1,  # 成功
    ).count()
    
    return today_pushes < 4


def push_opportunity_alert(
    session: Session,
    analysis: AnalysisResult,
    run_date: str,
    slot: str,
    base_url: str,
) -> bool:
    """推送机会提醒到钉钉"""
    dingtalk = get_dingtalk_client()
    
    content_item = analysis.content_item
    
    # 获取主要机会类型
    opp_types = analysis.result_json.get("opportunity_types", [])
    top_type = opp_types[0] if opp_types else "other"
    top_type_name = OPPORTUNITY_TYPES.get(top_type, top_type)
    
    # 生成幂等 key
    msg_uuid = hashlib.sha1(
        f"{run_date}:{slot}:opportunity:{analysis.id}".encode()
    ).hexdigest()
    
    try:
        result = dingtalk.send_opportunity_alert(
            analysis_id=analysis.id,
            title=content_item.title,
            mp_name=content_item.mp_name or "未知公众号",
            score=analysis.score,
            summary=analysis.summary_md[:200],
            opportunity_type=top_type_name,
            base_url=base_url,
            msg_uuid=msg_uuid,
        )
        
        success = result.get("errcode") == 0
        
        # 记录推送日志
        log = NotificationLog(
            report_date=run_date,
            slot=slot,
            push_type="opportunity",
            msg_uuid=msg_uuid,
            target_url=f"{base_url}/analysis/{analysis.id}",
            title=f"投资机会 [{analysis.score}分]",
            payload={"analysis_id": analysis.id},
            response=result,
            status=1 if success else 2,
            error=result.get("errmsg") if not success else None,
        )
        session.add(log)
        session.commit()
        
        return success
        
    except Exception as e:
        logger.error(f"推送机会提醒失败: {e}")
        return False


def generate_msg_uuid(date: str, slot: str, push_type: str) -> str:
    """生成推送幂等 key"""
    return hashlib.sha1(f"{date}:{slot}:{push_type}".encode()).hexdigest()


def push_manual_summary(
    session: Session,
    analyzed_count: int,
    run_date: str,
    slot: str,
) -> bool:
    """
    手动分析完成后发送汇总通知（当无机会时调用）
    
    Args:
        session: 数据库会话
        analyzed_count: 分析文章数量
        run_date: 运行日期
        slot: 运行时间段
    """
    dingtalk = get_dingtalk_client()
    
    # 生成幂等 key
    msg_uuid = generate_msg_uuid(run_date, slot, "manual_summary")
    
    text = f"""### 📊 手动分析完成
    
**执行时间**: {run_date} {slot}

**分析统计**: 共分析 {analyzed_count} 篇文章

**分析结果**: 暂未发现投资机会
"""
    
    try:
        result = dingtalk.send_markdown(
            title="📊 手动分析完成",
            text=text,
            msg_uuid=msg_uuid,
        )
        
        success = result.get("errcode") == 0
        
        # 记录推送日志
        log = NotificationLog(
            report_date=run_date,
            slot=slot,
            push_type="manual_summary",
            msg_uuid=msg_uuid,
            target_url="",
            title="手动分析汇总",
            payload={"analyzed_count": analyzed_count},
            response=result,
            status=1 if success else 2,
            error=result.get("errmsg") if not success else None,
        )
        session.add(log)
        session.commit()
        
        return success
    except Exception as e:
        logger.error(f"推送手动汇总失败: {e}")
        return False



