"""
execute_slot 对单篇文章失败的隔离能力。

生产事故回归（2026-07-09）：一篇文章的分析结果 INSERT 违反数据库约束后，
session 进入 PendingRollback 状态被"毒化"，逐篇分析的 except 只记日志不
rollback，导致后续所有文章分析、日报推送、以及最外层"把批次标为失败"的
commit 全部连环失败——批次永远卡在"运行中"，系统静默停摆两天。

这里断言两条防线：
1. 一篇文章毒化 session 后，同批次的下一篇文章仍能正常分析入库
2. 即使整个批次失败，slot_run 也必须被标记为失败（status=2），不能停留在运行中
"""
from unittest.mock import patch

import pytest

from src.app.domain.models import AnalysisResult, SlotRun
from src.app.tasks.slot import execute_slot


@pytest.fixture()
def slot_env(db_session, make_content_item):
    """execute_slot 跑在内存库上所需的最小环境：两篇待分析文章 + 各处打桩"""
    from datetime import datetime

    body = "有效正文" * 20  # has_content 要求正文超过 50 字符
    items = [
        make_content_item(title="第一篇（将毒化 session）", published_at=datetime.now(), raw_text=body),
        make_content_item(title="第二篇（应正常分析）", published_at=datetime.now(), raw_text=body),
    ]

    patches = [
        patch("src.app.tasks.slot.SessionLocal", return_value=db_session),
        patch("src.app.tasks.slot.fetch_and_save_articles", return_value=[]),
        patch("src.app.tasks.slot.is_last_slot_of_day", return_value=False),
        patch(
            "src.app.clients.dingtalk.DingTalkClient.send_markdown",
            return_value={"errcode": 0},
        ),
    ]
    for p in patches:
        p.start()
    yield items
    for p in patches:
        p.stop()


def _poison_then_succeed(session, items, next_id):
    """构造 analyze_article 替身：第一篇触发真实的完整性错误毒化 session，第二篇正常"""
    calls = {"n": 0}

    def fake_analyze(session, content_item, prompt_version, run_id=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # 模拟生产事故：入库违反 NOT NULL 约束（score 是必填列），
            # flush 失败后 session 进入 PendingRollback 状态
            session.add(AnalysisResult(
                id=next_id(),
                content_item_id=content_item.id,
                score=None,  # NOT NULL 违约
                has_opportunity=True,
                result_json={},
                summary_md="",
            ))
            session.flush()  # 抛 IntegrityError，且毒化 session
            raise AssertionError("unreachable")
        # 第二篇正常分析
        analysis = AnalysisResult(
            id=next_id(),
            content_item_id=content_item.id,
            score=50,
            has_opportunity=False,
            result_json={"score": 50, "has_opportunity": False, "key_points": ["ok"]},
            summary_md="ok",
        )
        session.add(analysis)
        session.commit()
        return analysis

    return fake_analyze


def test_one_poisoned_article_does_not_block_the_rest(db_session, slot_env, next_id):
    fake = _poison_then_succeed(db_session, slot_env, next_id)

    with patch("src.app.tasks.slot.analyze_article", side_effect=fake):
        result = execute_slot("12:00", manual=False)

    assert result["status"] == "success"
    assert result["stats"]["articles_failed"] == 1
    assert result["stats"]["articles_analyzed"] == 1

    run = db_session.query(SlotRun).one()
    assert run.status == 1  # 批次整体成功（部分文章失败不拖垮批次）


def test_slot_run_marked_failed_even_when_session_poisoned(db_session, slot_env, next_id):
    def poison_and_raise(session, content_item, prompt_version, run_id=None, **kwargs):
        session.add(AnalysisResult(
            id=next_id(),
            content_item_id=content_item.id,
            score=None,  # NOT NULL 违约，毒化 session
            has_opportunity=True,
            result_json={},
            summary_md="",
        ))
        session.flush()

    # 日报也让它炸，把异常一路顶到最外层 except——断言批次仍能被标记为失败
    with patch("src.app.tasks.slot.analyze_article", side_effect=poison_and_raise), \
         patch(
             "src.app.tasks.slot.is_last_slot_of_day",
             side_effect=Exception("simulated failure after poisoning"),
         ):
        with pytest.raises(Exception):
            execute_slot("22:00", manual=False)

    run = db_session.query(SlotRun).one()
    assert run.status == 2  # 必须是"失败"，绝不能停留在 0（运行中）
    assert run.error
