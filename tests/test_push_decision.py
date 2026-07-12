"""
信息源分类驱动的推送决策：should_push_opportunity / push_opportunity_alert。

机会类信源命中 push_score_threshold 即推；宽泛类信源需达更高的
broad_category_override_score 才推；不设每日推送条数上限；当天最后一个
批次（按 schedule_slots 动态判断，默认 22:30）从不推送单独机会（留给日报）。
"""
from datetime import datetime, timezone
from unittest.mock import patch

from src.app.core.prompts import opportunity_type_label
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


def test_last_slot_never_pushes_individual_opportunity(
    db_session, make_content_item, make_analysis_result
):
    # 最后一个批次按 schedule_slots 动态判断（默认列表末位是 22:30），
    # 不硬编码具体时刻——曾硬编码 "22:00"，调整批次时间后会失效
    analysis = _make_analysis(
        make_content_item, make_analysis_result, category="opportunity", score=99
    )
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "22:30") is False
    # 同一篇文章在非最后批次照常推送
    assert should_push_opportunity(db_session, analysis, "2026-07-08", "18:00") is True


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


def test_opportunity_type_label_known_and_unknown():
    assert opportunity_type_label("a_share_ipo") == "A股打新"
    assert opportunity_type_label("convertible_bond_listing") == "可转债上市"
    # 模型自造的枚举外 slug 兜底为"其他机会"，不能漏英文
    assert opportunity_type_label("ipo_a_share") == "其他机会"
    assert opportunity_type_label("new_stock_listing") == "其他机会"


def test_card_title_never_leaks_english_slug(
    db_session, make_content_item, make_analysis_result
):
    # 生产事故回归：v4-pro 输出枚举外类型 'ipo_a_share'，推送卡片标题
    # 曾直接显示英文 slug（🎯 ipo_a_share · 78分 · ...）
    item = make_content_item()
    analysis = make_analysis_result(
        item,
        score=78,
        has_opportunity=True,
        result_json={
            "score": 78,
            "has_opportunity": True,
            "key_points": ["要点"],
            "opportunity_types": ["ipo_a_share"],  # 枚举外自造 slug
            "no_opportunity_reason": "",
        },
    )

    with patch(
        "src.app.clients.dingtalk.DingTalkClient.send_markdown",
        return_value={"errcode": 0},
    ) as mock_send:
        push_opportunity_alert(
            session=db_session, analysis=analysis, run_date="2026-07-10",
            slot="07:00", base_url="https://radar.codexcc.cc",
        )

    title = mock_send.call_args.kwargs["title"]
    assert "ipo_a_share" not in title
    assert "其他机会" in title
