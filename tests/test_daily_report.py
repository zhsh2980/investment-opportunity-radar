"""
generate_and_push_daily_report 的当前行为（拼装模式，不调用 AI）。

前三个测试只断言外部可观察的行为契约（是否推送成功、汇总统计、DailyReport
落库），不涉及具体文案。后面几个测试针对钉钉简报化重构（issue 03）新增的
分组/排序/已提醒标记，需要断言 digest 正文内容——这是验收标准明确要求的。
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch

from src.app.domain.models import DailyReport, NotificationLog
from src.app.tasks.slot import generate_and_push_daily_report


def test_daily_report_with_no_articles_reports_empty_day(db_session):
    today = date.today()

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        success = generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    assert success is True
    _, kwargs = mock_send.call_args
    assert kwargs["total_articles"] == 0
    assert kwargs["total_opportunities"] == 0
    assert kwargs["has_opportunity"] is False

    report = db_session.query(DailyReport).filter(DailyReport.report_date == today).first()
    assert report is not None


def test_daily_report_counts_opportunities_above_threshold(
    db_session, make_content_item, make_analysis_result
):
    today = date.today()
    published = datetime.combine(today, datetime.min.time()).replace(hour=10)

    hit = make_content_item(published_at=published, title="机会文章")
    make_analysis_result(hit, score=75, has_opportunity=True)

    miss = make_content_item(published_at=published, title="无机会文章")
    make_analysis_result(miss, score=30, has_opportunity=False)

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        success = generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    assert success is True
    _, kwargs = mock_send.call_args
    assert kwargs["total_articles"] == 2
    assert kwargs["total_opportunities"] == 1  # 只有 score=75 的那篇过阈值(默认60)
    assert kwargs["has_opportunity"] is True


def test_daily_report_returns_false_when_dingtalk_push_fails(db_session):
    today = date.today()

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 1, "errmsg": "simulated failure"},
    ):
        success = generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    assert success is False


def test_daily_report_groups_by_source_and_sorts_by_score_desc(
    db_session, make_content_item, make_analysis_result
):
    today = date.today()
    published = datetime.combine(today, datetime.min.time()).replace(hour=10)

    a_low = make_content_item(published_at=published, mp_name="饕餮海投资", title="低分文章")
    make_analysis_result(a_low, score=40, has_opportunity=False)

    a_high = make_content_item(published_at=published, mp_name="饕餮海投资", title="高分文章")
    make_analysis_result(
        a_high,
        score=90,
        has_opportunity=True,
        result_json={
            "score": 90, "has_opportunity": True,
            "key_points": ["转债明日申购"], "opportunity_types": ["convertible_bond_ipo"],
            "no_opportunity_reason": "",
        },
    )

    b_item = make_content_item(published_at=published, mp_name="猫笔刀", title="大盘复盘")
    make_analysis_result(b_item, score=50, has_opportunity=False)

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    digest = mock_send.call_args.kwargs["digest"]

    # 两个信源都出现，且饕餮海投资分组内高分排在低分前面
    assert "饕餮海投资" in digest
    assert "猫笔刀" in digest
    assert digest.index("高分文章") < digest.index("低分文章")
    assert "转债明日申购" in digest


def test_daily_report_marks_already_alerted_and_skips_key_points(
    db_session, make_content_item, make_analysis_result
):
    today = date.today()
    published = datetime.combine(today, datetime.min.time()).replace(hour=10)

    item = make_content_item(published_at=published, title="已单独推送过的机会")
    analysis = make_analysis_result(
        item,
        score=85,
        has_opportunity=True,
        result_json={
            "score": 85, "has_opportunity": True,
            "key_points": ["不应该出现在日报里的要点"],
            "opportunity_types": ["convertible_bond_ipo"], "no_opportunity_reason": "",
        },
    )
    # 模拟这篇文章今天已经被 push_opportunity_alert 成功推送过
    db_session.add(NotificationLog(
        report_date=today,
        slot="12:00",
        push_type="opportunity",
        msg_uuid="test-uuid-already-alerted",
        target_url="",
        title="投资机会 [85分]",
        payload={"analysis_id": analysis.id},
        response={"errcode": 0},
        status=1,
    ))
    db_session.commit()

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    digest = mock_send.call_args.kwargs["digest"]
    assert "（已提醒）" in digest
    assert "不应该出现在日报里的要点" not in digest


def test_daily_report_contains_no_internal_links(
    db_session, make_content_item, make_analysis_result
):
    today = date.today()
    published = datetime.combine(today, datetime.min.time()).replace(hour=10)
    item = make_content_item(
        published_at=published,
        url="https://mp.weixin.qq.com/s/original-article",
    )
    make_analysis_result(item, score=70, has_opportunity=True)

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    digest = mock_send.call_args.kwargs["digest"]
    assert "/daily/" not in digest
    assert "/analysis/" not in digest
    assert "https://mp.weixin.qq.com/s/original-article" in digest


def test_daily_report_appends_source_status_with_stale_warning(
    db_session, make_content_item, make_analysis_result
):
    # 一个源今天有更新，另一个源 3 天没更新——日报尾部应展示两者状态，
    # 久未更新的带 ⚠️（这是"无新文章"独立告警删除后的替代形态）
    today = date.today()
    fresh = make_content_item(
        mp_name="饕餮海投资",
        published_at=datetime.combine(today, datetime.min.time()).replace(hour=10),
    )
    make_analysis_result(fresh, score=70, has_opportunity=True)
    make_content_item(
        mp_name="越女事务所",
        published_at=datetime.now() - timedelta(days=3),
    )

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        generate_and_push_daily_report(session=db_session, run_date=today, slot="22:00")

    digest = mock_send.call_args.kwargs["digest"]
    assert "信源状态" in digest
    assert "饕餮海投资" in digest
    assert "越女事务所：已 3 天无更新 ⚠️" in digest


def test_stale_source_no_longer_triggers_standalone_alert(db_session, make_content_item):
    # 回归：源 3 天无更新曾触发独立的"数据源健康告警"推送；降级后
    # check_source_health 在无拉取失败时不应发送任何告警消息
    from src.app.services.analyzer import check_source_health

    make_content_item(
        mp_name="越女事务所",
        published_at=datetime.now() - timedelta(days=3),
    )

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_markdown",
        return_value={"errcode": 0},
    ) as mock_send:
        check_source_health(db_session, failures={})

    mock_send.assert_not_called()
