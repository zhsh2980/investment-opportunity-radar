"""
analyze_article 的扁平化输出行为：AI 返回新的 5 字段结构，
系统应正确落库 score/has_opportunity/result_json/summary_md，
且不再向 Opportunity 子表写入任何记录。
"""
from unittest.mock import patch

from src.app.domain.models import Opportunity
from src.app.services.analyzer import analyze_article, build_summary_md

FLATTENED_RESPONSE = {
    "score": 72,
    "has_opportunity": True,
    "key_points": [
        "XX转债将于2026年7月10日开放申购，代码123456",
        "评级AA，预计上市首日有10%-15%收益空间",
    ],
    "opportunity_types": ["convertible_bond_ipo"],
    "no_opportunity_reason": "",
}


def test_analyze_article_stores_flattened_fields(db_session, make_content_item):
    item = make_content_item(title="XX转债打新公告")

    with patch(
        "src.app.clients.deepseek.DeepSeekClient.analyze_article",
        return_value=FLATTENED_RESPONSE,
    ):
        analysis = analyze_article(session=db_session, content_item=item, prompt_version=None)

    assert analysis is not None
    assert analysis.score == 72
    assert analysis.has_opportunity is True
    assert analysis.result_json["key_points"] == FLATTENED_RESPONSE["key_points"]
    assert analysis.result_json["opportunity_types"] == ["convertible_bond_ipo"]
    # 旧字段不应该出现在新结构里
    assert "opportunities" not in analysis.result_json
    assert "content_abstract" not in analysis.result_json


def test_analyze_article_populates_summary_md_from_key_points(db_session, make_content_item):
    item = make_content_item()

    with patch(
        "src.app.clients.deepseek.DeepSeekClient.analyze_article",
        return_value=FLATTENED_RESPONSE,
    ):
        analysis = analyze_article(session=db_session, content_item=item, prompt_version=None)

    assert "2026年7月10日" in analysis.summary_md
    assert "10%-15%" in analysis.summary_md


def test_analyze_article_does_not_write_opportunity_subtable(db_session, make_content_item):
    item = make_content_item()

    with patch(
        "src.app.clients.deepseek.DeepSeekClient.analyze_article",
        return_value=FLATTENED_RESPONSE,
    ):
        analyze_article(session=db_session, content_item=item, prompt_version=None)

    assert db_session.query(Opportunity).count() == 0


def test_analyze_article_marks_failed_when_ai_raises(db_session, make_content_item):
    item = make_content_item()

    with patch(
        "src.app.clients.deepseek.DeepSeekClient.analyze_article",
        side_effect=Exception("simulated DeepSeek failure"),
    ):
        analysis = analyze_article(session=db_session, content_item=item, prompt_version=None, max_retries=1)

    assert analysis is None
    assert item.analyzed_status == 3  # 失败


def test_analyze_article_marks_failed_when_key_points_missing(db_session, make_content_item):
    item = make_content_item()
    incomplete = {"score": 50, "has_opportunity": False}  # 缺 key_points

    with patch(
        "src.app.clients.deepseek.DeepSeekClient.analyze_article",
        return_value=incomplete,
    ):
        analysis = analyze_article(session=db_session, content_item=item, prompt_version=None, max_retries=1)

    assert analysis is None


def test_build_summary_md_joins_and_numbers_points():
    assert build_summary_md(["第一条", "第二条"]) == "1. 第一条 ｜ 2. 第二条"


def test_build_summary_md_empty_list_returns_empty_string():
    assert build_summary_md([]) == ""
