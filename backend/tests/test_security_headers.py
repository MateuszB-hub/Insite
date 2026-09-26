"""Response headers, per Mozilla's Web Security guidelines."""

import importlib
import os

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_baseline_headers_present(client):
    h = client.get("/api/health").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert h["X-Frame-Options"] == "DENY"
    assert "camera=()" in h["Permissions-Policy"]
    assert h["Cross-Origin-Opener-Policy"] == "same-origin"


def test_csp_blocks_framing_and_object_embedding(client):
    csp = client.get("/api/health").headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp


def test_hsts_absent_in_dev(client):
    """Mozilla: ramp HSTS up deliberately. Never from a plain-HTTP dev box."""
    assert "Strict-Transport-Security" not in client.get("/api/health").headers


def test_hsts_shape_when_enabled(monkeypatch):
    """max-age must meet Mozilla's six-month floor."""
    from app.middleware import security_headers as sh
    monkeypatch.setattr(sh, "HSTS_ENABLED", True)
    monkeypatch.setattr(sh, "DEV_MODE", False)
    monkeypatch.setattr(sh, "HSTS_MAX_AGE", 15768000)
    monkeypatch.setattr(sh, "HSTS_INCLUDE_SUBDOMAINS", True)
    monkeypatch.setattr(sh, "HSTS_PRELOAD", False)
    with TestClient(main.app) as c:
        value = c.get("/api/health").headers["Strict-Transport-Security"]
    assert "max-age=15768000" in value
    assert int(value.split("max-age=")[1].split(";")[0]) >= 15768000
    assert "includeSubDomains" in value
    assert "preload" not in value  # opt-in only; removal takes months
