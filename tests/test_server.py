import pytest
from starlette.testclient import TestClient

from vision_mcp.server import build_app
from vision_mcp.config import Config


@pytest.fixture
def cfg():
    return Config(
        ark_base_url="https://ark.example.com",
        ark_api_key="k",
        ark_model="m",
        vision_bearer_token="the-secret-token",
        host="127.0.0.1",
        port=8100,
    )


def test_healthz_ok(cfg):
    app = build_app(cfg)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_no_auth_required(cfg):
    """Health check must not require Bearer (used by monitors without secrets)."""
    app = build_app(cfg)
    client = TestClient(app)
    r = client.get("/healthz", headers={})
    assert r.status_code == 200


def test_mcp_path_requires_bearer(cfg):
    app = build_app(cfg)
    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_mcp_path_with_wrong_bearer_is_401(cfg):
    app = build_app(cfg)
    client = TestClient(app)
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_mcp_path_with_correct_bearer_reaches_app(cfg):
    app = build_app(cfg)
    # FastMCP 1.28's stateless session manager needs the sub-app's lifespan
    # (which spawns its task group) to be running. Use TestClient as a context
    # manager so the lifespan startup/shutdown events fire. Also send a Host
    # header that matches FastMCP's transport-security allowed_hosts pattern
    # (the default `testserver` Host used by TestClient is rejected with 421).
    with TestClient(app) as client:
        r = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Authorization": "Bearer the-secret-token",
                "Accept": "application/json, text/event-stream",
                "Host": "localhost:80",
            },
        )
    assert r.status_code in (200, 202)