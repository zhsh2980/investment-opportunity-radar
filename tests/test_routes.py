"""
路由层回归测试：只断言状态码/重定向目标，不断言页面内 HTML 细节。

覆盖 issue「页面精简与路由调整」的验收标准：
- 已删除的工作台/跟踪台/日报路由返回 404
- / 现在服务原历史页内容，未登录重定向到 /login
- /history 301 重定向到 /
- /analysis/{id} 恢复登录保护
- /system 不受影响
"""
import pytest
from fastapi.testclient import TestClient

from src.app.core.security import create_session_token
from src.app.domain.models import AppUser
from src.app.main import app
from src.app.web.routers import pages


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


def test_system_page_still_requires_login_and_renders(logged_in_client):
    resp = logged_in_client.get("/system", follow_redirects=False)
    assert resp.status_code == 200
    assert "系统设置" in resp.text


def test_legacy_settings_redirects_still_work(client):
    for path in ("/prompts", "/settings", "/health"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/system"
