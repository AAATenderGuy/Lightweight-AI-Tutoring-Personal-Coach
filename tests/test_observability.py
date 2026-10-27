"""可观测性：请求 ID、健康检查扩展字段、日志落盘。"""
from __future__ import annotations

import logging

from server.config import LOG_DIR
from server.observability import current_request_id


def test_health_reports_runtime_metadata(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["uptime_s"] >= 0
    assert data["pid"] > 0
    assert data["log_file"].endswith("app.log")


def test_request_id_header_is_returned(client):
    response = client.get("/api/health")
    rid = response.headers.get("x-request-id")
    assert rid and len(rid) == 12


def test_request_id_is_echoed_when_client_supplies_one(client):
    response = client.get("/api/health", headers={"X-Request-Id": "abc123def456"})
    assert response.headers.get("x-request-id") == "abc123def456"


def test_access_log_written_with_request_id(client):
    client.get("/api/health", headers={"X-Request-Id": "rid-in-file"})
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_file = LOG_DIR / "app.log"
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8", errors="replace")
    assert "rid=rid-in-file" in content
    assert "path=/api/health" in content


def test_request_id_defaults_outside_request():
    assert current_request_id() == "-"
