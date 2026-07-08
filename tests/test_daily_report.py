"""
generate_and_push_daily_report 的当前行为（拼装模式，不调用 AI）。

只断言外部可观察的行为契约（是否推送成功、汇总统计、DailyReport 落库），
不断言具体的 digest_md 文案格式——那部分会在钉钉简报化重构（issue 03）中改写。
"""
from datetime import date, datetime
from unittest.mock import patch

from src.app.domain.models import DailyReport
from src.app.tasks.slot import generate_and_push_daily_report


def test_daily_report_with_no_articles_reports_empty_day(db_session):
    today = date.today()

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
        return_value={"errcode": 0},
    ) as mock_send:
        success = generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00", base_url="http://localhost",
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
            session=db_session, run_date=today, slot="22:00", base_url="http://localhost",
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
            session=db_session, run_date=today, slot="22:00", base_url="http://localhost",
        )

    assert success is False
