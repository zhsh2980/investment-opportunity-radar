"""
钉钉 + 飞书并行推送：两个渠道各自独立发送、各自记录 NotificationLog，
一个渠道失败不影响另一个渠道，也不影响函数的整体返回值判定。

飞书是否启用取决于 is_feishu_configured()（app_id + chat_id 是否配置），
未配置时应该完全跳过飞书调用，不产生错误、不落多余的 NotificationLog。
"""
from unittest.mock import patch

from src.app.domain.models import NotificationLog
from src.app.services.analyzer import push_opportunity_alert
from src.app.tasks.slot import generate_and_push_daily_report


def test_opportunity_alert_pushes_to_both_channels_when_feishu_configured(
    db_session, make_content_item, make_analysis_result
):
    item = make_content_item(url="https://mp.weixin.qq.com/s/article")
    analysis = make_analysis_result(item, score=75, has_opportunity=True)

    with patch("src.app.services.analyzer.is_feishu_configured", return_value=True), \
         patch(
             "src.app.clients.dingtalk.DingTalkClient.send_opportunity_alert",
             return_value={"errcode": 0},
         ) as mock_dingtalk, \
         patch(
             "src.app.clients.feishu.FeishuClient.send_opportunity_alert",
             return_value={"code": 0},
         ) as mock_feishu:
        success = push_opportunity_alert(
            session=db_session, analysis=analysis, run_date="2026-07-08",
            slot="12:00", base_url="https://radar.codexcc.cc",
        )

    assert success is True
    mock_dingtalk.assert_called_once()
    mock_feishu.assert_called_once()

    logs = db_session.query(NotificationLog).filter(
        NotificationLog.push_type == "opportunity"
    ).all()
    assert len(logs) == 2
    assert {log.status for log in logs} == {1}


def test_opportunity_alert_skips_feishu_when_not_configured(
    db_session, make_content_item, make_analysis_result
):
    item = make_content_item()
    analysis = make_analysis_result(item, score=75, has_opportunity=True)

    with patch("src.app.services.analyzer.is_feishu_configured", return_value=False), \
         patch(
             "src.app.clients.dingtalk.DingTalkClient.send_opportunity_alert",
             return_value={"errcode": 0},
         ), \
         patch("src.app.clients.feishu.FeishuClient.send_opportunity_alert") as mock_feishu:
        success = push_opportunity_alert(
            session=db_session, analysis=analysis, run_date="2026-07-08",
            slot="12:00", base_url="https://radar.codexcc.cc",
        )

    assert success is True
    mock_feishu.assert_not_called()

    logs = db_session.query(NotificationLog).filter(
        NotificationLog.push_type == "opportunity"
    ).all()
    assert len(logs) == 1


def test_opportunity_alert_succeeds_if_only_feishu_works(
    db_session, make_content_item, make_analysis_result
):
    item = make_content_item()
    analysis = make_analysis_result(item, score=75, has_opportunity=True)

    with patch("src.app.services.analyzer.is_feishu_configured", return_value=True), \
         patch(
             "src.app.clients.dingtalk.DingTalkClient.send_opportunity_alert",
             side_effect=Exception("dingtalk down"),
         ), \
         patch(
             "src.app.clients.feishu.FeishuClient.send_opportunity_alert",
             return_value={"code": 0},
         ):
        success = push_opportunity_alert(
            session=db_session, analysis=analysis, run_date="2026-07-08",
            slot="12:00", base_url="https://radar.codexcc.cc",
        )

    assert success is True

    logs = db_session.query(NotificationLog).filter(
        NotificationLog.push_type == "opportunity"
    ).all()
    # 两条都落库：钉钉那条记为失败（异常信息进 error 字段），飞书那条成功
    assert len(logs) == 2
    statuses = {log.msg_uuid.endswith("-feishu"): log.status for log in logs}
    assert statuses == {False: 2, True: 1}


def test_daily_report_pushes_to_both_channels_when_feishu_configured(db_session):
    from datetime import date as date_cls

    today = date_cls.today()

    with patch("src.app.tasks.slot.is_feishu_configured", return_value=True), \
         patch(
             "src.app.clients.dingtalk.DingTalkClient.send_daily_report",
             return_value={"errcode": 0},
         ) as mock_dingtalk, \
         patch(
             "src.app.clients.feishu.FeishuClient.send_daily_report",
             return_value={"code": 0},
         ) as mock_feishu:
        success = generate_and_push_daily_report(
            session=db_session, run_date=today, slot="22:00",
        )

    assert success is True
    mock_dingtalk.assert_called_once()
    mock_feishu.assert_called_once()

    logs = db_session.query(NotificationLog).filter(
        NotificationLog.push_type == "daily"
    ).all()
    assert len(logs) == 2
