"""
路由层回归测试：只断言状态码/重定向目标，不断言页面内 HTML 细节。

覆盖 issue「页面精简与路由调整」的验收标准：
- 已删除的工作台/跟踪台/日报路由返回 404
- / 现在服务原历史页内容，未登录重定向到 /login
- /history 301 重定向到 /
- /analysis/{id} 恢复登录保护
- /system 不受影响
"""
import os
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import create_session_token
from src.app.domain.models import AppUser
from src.app.main import app
from src.app.web.routers import pages


@pytest.fixture()
def beijing_tz(monkeypatch):
    """把进程时区固定为 Asia/Shanghai，让 as_naive() 的转换结果可预测，
    不依赖跑测试的机器本身时区设置。"""
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        yield
    finally:
        if original_tz is not None:
            os.environ["TZ"] = original_tz
        else:
            os.environ.pop("TZ", None)
        time.tzset()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[pages.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def logged_in_client(client, db_session, next_id):
    user = AppUser(id=next_id(), username="tester", password_hash="x")
    db_session.add(user)
    db_session.flush()
    client.cookies.set("session_token", create_session_token(user.id))
    return client


def test_removed_workbench_and_tracking_routes_return_404(client):
    assert client.get("/tracking", follow_redirects=False).status_code == 404
    assert client.get("/daily", follow_redirects=False).status_code == 404
    assert client.get("/daily/2026-07-08", follow_redirects=False).status_code == 404
    assert client.post("/api/workbench/1/action", json={"action": "executed"}).status_code == 404
    assert client.post("/api/workbench/track/1/review", json={}).status_code == 404


def test_home_redirects_anonymous_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_home_serves_history_content_when_logged_in(logged_in_client):
    resp = logged_in_client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "历史与搜索" in resp.text
    assert "今日工作台" not in resp.text


def test_legacy_history_path_redirects_to_home(client):
    resp = client.get("/history", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/"


def test_analysis_detail_requires_login(client, make_content_item, make_analysis_result):
    item = make_content_item()
    analysis = make_analysis_result(item)

    resp = client.get(f"/analysis/{analysis.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_analysis_detail_accessible_when_logged_in(
    logged_in_client, make_content_item, make_analysis_result
):
    item = make_content_item()
    analysis = make_analysis_result(item)

    resp = logged_in_client.get(f"/analysis/{analysis.id}", follow_redirects=False)
    assert resp.status_code == 200


def test_as_naive_converts_utc_to_local_not_just_strips_tzinfo(beijing_tz):
    # 回归：as_naive() 曾经只是 dt.replace(tzinfo=None) 直接砍掉时区信息，
    # 没有先转换成本地时间，导致数据库里的 UTC 数字被当成本地时间直接显示，
    # 页面上的发布时间/更新时间比实际早 8 小时
    utc_dt = datetime(2026, 7, 13, 14, 46, 0, tzinfo=timezone.utc)  # 北京时间 22:46
    assert pages.as_naive(utc_dt) == datetime(2026, 7, 13, 22, 46, 0)


def test_analysis_detail_shows_beijing_time_not_raw_utc(
    beijing_tz, logged_in_client, make_content_item, make_analysis_result
):
    item = make_content_item(
        published_at=datetime(2026, 7, 13, 14, 46, 0, tzinfo=timezone.utc)  # 北京 22:46
    )
    analysis = make_analysis_result(item)

    resp = logged_in_client.get(f"/analysis/{analysis.id}", follow_redirects=False)
    assert resp.status_code == 200
    assert "2026-07-13 22:46" in resp.text
    assert "14:46" not in resp.text


def test_system_page_still_requires_login_and_renders(logged_in_client):
    resp = logged_in_client.get("/system", follow_redirects=False)
    assert resp.status_code == 200
    assert "系统设置" in resp.text


def test_system_page_shows_latest_category_not_max_string(
    logged_in_client, make_content_item
):
    # 同一来源先有一条旧数据被标为 opportunity（如迁移回填的默认值，id 较小），
    # 后有一条新入库的文章正确标为 broad（id 较大）。
    # 用字符串 MAX 聚合会错误地永久显示为 opportunity（'o' > 'b'）；
    # 正确做法是以"最近一次入库"（id 最大）的分类为准。
    make_content_item(mp_name="猫笔刀", source_category="opportunity")
    make_content_item(mp_name="猫笔刀", source_category="broad")

    resp = logged_in_client.get("/system", follow_redirects=False)
    assert resp.status_code == 200
    assert "宽泛类" in resp.text


def test_legacy_settings_redirects_still_work(client):
    for path in ("/prompts", "/settings", "/health"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/system"
