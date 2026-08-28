"""3.2 /api/health 与 /api/metrics 端点测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes.health_routes import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health_endpoint():
    r = _client().get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "healthy"
    assert data["service"] == "agnes-video-generator"


def test_metrics_endpoint_structure():
    r = _client().get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "rate_limiter" in data
    assert "video_limiter" in data
    assert data["concurrency"]["max_weight"] > 0
    assert "usage_pct" in data["concurrency"]
    assert data["tasks"]["active"] == 0
