"""
信息源分类驱动的推送决策：should_push_opportunity / push_opportunity_alert。

机会类信源命中 push_score_threshold 即推；宽泛类信源需达更高的
broad_category_override_score 才推；不设每日推送条数上限；22:00 从不
推送单独机会（留给日报）。
"""
from datetime import datetime, timezone
from unittest.mock import patch

from src.app.services.analyzer import (
    format_publish_time,
    push_opportunity_alert,
    should_push_opportunity,
)


def _make_analysis(make_content_item, make_analysis_result, *, category, score):
    item = make_content_item(source_category=category)
    return make_analysis_result(item, score=score, has_opportunity=True)


def test_opportunity_category_pushes_at_default_threshold(
    db_session, make_content_item, make_analysis_result
):
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="opportunity", score=60
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "12:00") is True


def test_opportunity_category_does_not_push_below_threshold(
    db_session, make_content_item, make_analysis_result
):
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="opportunity", score=59
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "12:00") is False


def test_broad_category_does_not_push_at_opportunity_threshold(
    db_session, make_content_item, make_analysis_result
):
    # 60 分对机会类会推，但宽泛类的默认破例线是 80，不应该推
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="broad", score=60
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "12:00") is False


def test_broad_category_pushes_at_override_score(
    db_session, make_content_item, make_analysis_result
):
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="broad", score=80
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "12:00") is True


def test_no_daily_push_cap(db_session, make_content_item, make_analysis_result):
    # 连续 5 篇机会类高分文章都应判定为可推送，不受历史推送次数限制
    for _ in range(5):
        analysis = _make_analysis(
            make_content_item, make_analysis_result, category="opportunity", score=90
        )
        assert should_push_opportunity(db_session, analysis, "2026-07-08", "12:00") is True


def test_2200_slot_never_pushes_individual_opportunity(
    db_session, make_content_item, make_analysis_result
):
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="opportunity", score=99
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "22:00") is False


def test_push_opportunity_alert_includes_key_points_and_single_link(
    db_session, make_content_item, make_analysis_result
):
    item = make_content_item(url="https://mp.weixin.qq.com/s/real-article")
    analysis = make_analysis_result(
        item,
        score=75,
        has_opportunity=True,
        result_json={
            "score": 75,
            "has_opportunity": True,
            "key_points": ["要点一", "要点二"],
            "opportunity_types": ["convertible_bond_ipo"],
            "no_opportunity_reason": "",
        },
    )

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_markdown",
        return_value={"errcode": 0},
    ) as mock_send:
        success = push_opportunity_alert(
            session=db_session,
            analysis=analysis,
            run_date="2026-07-08",
            slot="12:00",
            base_url="https://radar.codexcc.cc",
        )

    assert success is True
    _, kwargs = mock_send.call_args
    text = kwargs["text"]
    assert "要点一" in text
    assert "要点二" in text
    assert text.count("[查看原文]") == 1
    assert "https://mp.weixin.qq.com/s/real-article" in text
    assert "radar.codexcc.cc/analysis" not in text


def test_push_opportunity_alert_handles_empty_article_url(
    db_session, make_content_item, make_analysis_result
):
    item = make_content_item(url=None)
    analysis = make_analysis_result(item, score=75, has_opportunity=True)

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_markdown",
        return_value={"errcode": 0},
    ) as mock_send:
        success = push_opportunity_alert(
            session=db_session,
            analysis=analysis,
            run_date="2026-07-08",
            slot="12:00",
            base_url="https://radar.codexcc.cc",
        )

    assert success is True
    _, kwargs = mock_send.call_args
    assert "[查看原文]" not in kwargs["text"]


def test_format_publish_time_converts_utc_to_beijing():
    # 数据库存的是 UTC，13:50 UTC = 北京时间 21:50
    dt = datetime(2026, 7, 8, 13, 50, tzinfo=timezone.utc)
    assert format_publish_time(dt) == "07-08 21:50"


def test_format_publish_time_handles_none():
    assert format_publish_time(None) == ""


def test_push_opportunity_alert_shows_publish_time_in_beijing(
    db_session, make_content_item, make_analysis_result
):
    # 文章发布于 07-08 13:50 UTC（存库形态），卡片里应显示北京时间 07-08 21:50
    item = make_content_item(
        published_at=datetime(2026, 7, 8, 13, 50, tzinfo=timezone.utc),
        url="https://mp.weixin.qq.com/s/x",
    )
    analysis = make_analysis_result(item, score=85, has_opportunity=True)

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_markdown",
        return_value={"errcode": 0},
    ) as mock_send:
        push_opportunity_alert(
            session=db_session, analysis=analysis, run_date="2026-07-09",
            slot="12:00", base_url="https://radar.codexcc.cc",
        )

    text = mock_send.call_args.kwargs["text"]
    assert "🕐 发布于 07-08 21:50" in text
    # 发布时间行在标题之后、第一条要点之前
    assert text.index("发布于") < text.index("- ")
