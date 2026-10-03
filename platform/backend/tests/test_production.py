"""Production safeguards: configuration checks, sign-up control, sign-in throttling, housekeeping,
security headers, request ids, structured logs and the readiness probe."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import middleware
from app.core import config, database, migrate
from app.core.logs import JsonFormatter, RequestIdFilter, request_id_var
from app.main import app
from app.models import LoginAttempt, User, utcnow
from app.models import Session as LoginSession
from app.services import login_throttle
from app.services.maintenance import prune_expired
from tests.conftest import ORIGIN

PASSWORD = "correct-horse-battery"


def settings(**changes):
    config.settings = replace(config.settings, **changes)


def signup(client, email, password=PASSWORD):
    return client.post("/api/auth/signup", headers=ORIGIN, json={"name": email, "email": email, "password": password})


def login(client, email, password=PASSWORD, **headers):
    return client.post("/api/auth/login", headers={**ORIGIN, **headers}, json={"email": email, "password": password})


# Configuration


SAFE_PRODUCTION = {
    "environment": "production",
    "secure_cookies": True,
    "database_url": "postgresql+psycopg://review:s3cret@db.internal:5432/review",
    "celery_broker_url": "amqp://review:s3cret@mq.internal:5672/review",
    "object_store_backend": "s3",
    "seed_poc": False,
    "trusted_origins": ("https://review.example.com",),
    "log_format": "json",
}
SAFE_ENV = {"AWS_ACCESS_KEY_ID": "AKIA-REAL", "AWS_SECRET_ACCESS_KEY": "real-secret"}


def test_production_accepts_a_safe_configuration():
    assert config.production_problems(replace(config.settings, **SAFE_PRODUCTION), SAFE_ENV) == []


def test_production_lists_every_unsafe_default_at_once():
    unsafe = replace(
        config.settings,
        environment="production",
        database_url="postgresql+psycopg://cuauto:local_database@postgres:5432/cuautoreview",
        celery_broker_url="amqp://cuauto:local_broker@rabbitmq:5672/cuautoreview",
        object_store_backend="s3",
        secure_cookies=False,
        seed_poc=True,
        trusted_origins=("http://review.example.com",),
    )
    problems = config.production_problems(unsafe, {"AWS_ACCESS_KEY_ID": "local_access", "AWS_SECRET_ACCESS_KEY": "x"})
    joined = "\n".join(problems)
    for expected in (
        "SECURE_COOKIES",
        "local database password",
        "CELERY_BROKER_URL",
        "AWS_ACCESS_KEY_ID",
        "SEED_POC",
        "https://host",
    ):
        assert expected in joined
    with pytest.raises(RuntimeError, match="Refusing to start: unsafe production configuration"):
        config.check_settings(replace(config.settings, environment="production"))


def test_development_skips_production_checks_but_rejects_unknown_environments():
    config.check_settings(replace(config.settings, environment="development"))
    with pytest.raises(RuntimeError, match="ENVIRONMENT must be"):
        config.check_settings(replace(config.settings, environment="staging"))


def test_trusted_origins_replace_the_host_comparison_behind_a_proxy(isolated):
    settings(trusted_origins=("https://review.example.com",))
    client = TestClient(app)
    allowed = login(client, "nobody@example.test", Origin="https://review.example.com")
    assert allowed.status_code == 401  # past the origin check
    denied = login(client, "nobody@example.test")  # Origin http://testserver is not listed
    assert denied.status_code == 403 and denied.json()["detail"] == "Cross-origin mutation denied"


# Sign-up and account creation


def test_disabled_signup_still_allows_the_bootstrap_admin_and_admin_created_accounts(isolated):
    settings(allow_signup=False)
    anonymous = TestClient(app)
    assert anonymous.get("/api/auth/config").json() == {"signup_enabled": True}
    admin = TestClient(app)
    assert signup(admin, "admin@example.test").json()["role"] == "admin"
    assert anonymous.get("/api/auth/config").json() == {"signup_enabled": False}
    refused = signup(TestClient(app), "admin@example.test")
    assert refused.status_code == 403 and "disabled" in refused.json()["detail"]  # no hint the email exists

    created = admin.post(
        "/api/users",
        headers=ORIGIN,
        json={"name": "Rev", "email": "Rev@Example.test", "password": PASSWORD, "role": "reviewer"},
    )
    assert created.status_code == 200 and created.json()["role"] == "reviewer"
    assert created.json()["email"] == "rev@example.test" and "password_hash" not in created.json()
    reviewer = TestClient(app)
    assert login(reviewer, "rev@example.test").status_code == 200
    assert (
        reviewer.post(
            "/api/users", headers=ORIGIN, json={"name": "X", "email": "x@example.test", "password": PASSWORD}
        ).status_code
        == 403
    )
    duplicate = admin.post(
        "/api/users", headers=ORIGIN, json={"name": "Rev", "email": "rev@example.test", "password": PASSWORD}
    )
    assert duplicate.status_code == 409


# Sign-in throttling


def test_repeated_failures_are_throttled_per_email_and_client(isolated):
    settings(login_max_failures=3, login_window_seconds=900)
    signup(TestClient(app), "admin@example.test")
    client = TestClient(app)
    for _ in range(3):
        assert login(client, "admin@example.test", "wrong-password").status_code == 401
    throttled = login(client, "admin@example.test")  # even the right password waits
    assert throttled.status_code == 429
    assert 1 <= int(throttled.headers["retry-after"]) <= 900
    # Another account from the same client is not locked by this pair counter.
    assert login(client, "other@example.test", "wrong-password").status_code == 401


def test_success_clears_the_pair_counter(isolated):
    settings(login_max_failures=3)
    signup(TestClient(app), "admin@example.test")
    client = TestClient(app)
    for _ in range(2):
        login(client, "admin@example.test", "wrong-password")
    assert login(client, "admin@example.test").status_code == 200
    for _ in range(2):
        assert login(client, "admin@example.test", "wrong-password").status_code == 401
    assert login(client, "admin@example.test").status_code == 200


def test_many_accounts_from_one_client_hit_the_address_limit(isolated):
    settings(login_max_failures=10, login_ip_max_failures=4)
    client = TestClient(app)
    for index in range(4):
        assert login(client, f"user{index}@example.test", "wrong-password").status_code == 401
    assert login(client, "fresh@example.test", "wrong-password").status_code == 429


def test_attempts_store_only_hashes(isolated):
    client = TestClient(app)
    login(client, "secret.person@example.test", "wrong-password")
    with database.SessionLocal() as db:
        attempt = db.scalars(select(LoginAttempt)).one()
    assert "secret" not in attempt.pair_hash and len(attempt.pair_hash) == 64
    assert (attempt.pair_hash, attempt.ip_hash) == login_throttle.keys("Secret.Person@example.test", "testclient")


# Housekeeping


def test_expired_sessions_and_stale_attempts_are_pruned_in_batches(isolated):
    admin = TestClient(app)
    signup(admin, "admin@example.test")
    with database.SessionLocal() as db:
        user_id = db.scalar(select(User.id))
        now = utcnow()
        for index in range(3):
            db.add(LoginSession(token_hash=f"{index:064d}", user_id=user_id, expires_at=now - timedelta(minutes=1)))
        db.add(LoginAttempt(pair_hash="a" * 64, ip_hash="b" * 64, created_at=now - timedelta(days=1)))
        db.add(LoginAttempt(pair_hash="c" * 64, ip_hash="d" * 64, created_at=now))
        db.commit()
        assert prune_expired(db, batch_size=2) == {"sessions": 2, "login_attempts": 1}
        assert prune_expired(db) == {"sessions": 1, "login_attempts": 0}
        db.commit()
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 1  # the live admin session
        assert db.scalar(select(func.count()).select_from(LoginAttempt)) == 1
    assert admin.get("/api/auth/me").status_code == 200


def test_logout_removes_the_users_expired_sessions(isolated):
    client = TestClient(app)
    signup(client, "admin@example.test")
    with database.SessionLocal() as db:
        user_id = db.scalar(select(User.id))
        db.add(LoginSession(token_hash="e" * 64, user_id=user_id, expires_at=utcnow() - timedelta(hours=1)))
        db.commit()
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 0


# Headers, request ids and logs


def test_security_headers_and_cache_policy(isolated):
    dist = isolated["tmp_path"] / "platform" / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>x</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    client = TestClient(app)
    api = client.get("/api/health")
    assert api.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in api.headers["content-security-policy"]
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in api.headers
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/assets/index-abc123.js").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/assets/missing.js").headers["cache-control"] == "no-cache"
    assert "content-security-policy" not in client.get("/docs").headers  # the docs page loads CDN assets
    settings(secure_cookies=True)
    assert client.get("/api/health").headers["strict-transport-security"].startswith("max-age=")


def test_request_ids_are_propagated_or_generated(isolated):
    client = TestClient(app)
    assert client.get("/api/health", headers={"X-Request-ID": "trace-123"}).headers["x-request-id"] == "trace-123"
    generated = client.get("/api/health", headers={"X-Request-ID": "bad id with spaces"}).headers["x-request-id"]
    assert len(generated) == 32 and " " not in generated


def test_access_log_records_the_signed_in_user_without_secrets(isolated, caplog):
    client = TestClient(app)
    user = signup(client, "admin@example.test").json()
    with caplog.at_level(logging.INFO, logger="cuautoreview.access"):
        client.get("/api/auth/me", headers={"X-Request-ID": "req-42"})
        login(client, "admin@example.test")
    records = [record for record in caplog.records if record.name == "cuautoreview.access"]
    me = next(record for record in records if record.http["path"] == "/api/auth/me")
    assert me.http["user_id"] == user["id"] and me.http["status"] == 200
    assert all(PASSWORD not in record.getMessage() and PASSWORD not in json.dumps(record.http) for record in records)


def test_json_log_lines_carry_the_request_id():
    token = request_id_var.set("req-7")
    try:
        record = logging.LogRecord("cuautoreview.access", logging.INFO, __file__, 1, "GET %s", ("/api/x",), None)
        record.http = {"status": 200}
        RequestIdFilter().filter(record)  # normally applied by the root handler
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req-7" and line["message"] == "GET /api/x" and line["http"] == {"status": 200}


# Readiness


def test_readiness_requires_the_migrated_schema(isolated):
    client = TestClient(app)
    stale = client.get("/api/ready")  # the test database is built without migration history
    assert stale.status_code == 503
    assert stale.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "schema": "outdated", "object_store": "ok"},
    }


def test_readiness_passes_once_migrated(tmp_path, monkeypatch, isolated):
    engine = database.make_engine(f"sqlite:///{tmp_path / 'ready.sqlite'}")
    migrate.upgrade(engine)
    monkeypatch.setattr(database, "engine", engine)
    response = TestClient(app).get("/api/ready")
    assert response.status_code == 200 and response.json()["status"] == "ready"
    engine.dispose()


def test_readiness_reports_an_unreachable_database_without_details(isolated, monkeypatch):
    monkeypatch.setattr(database, "engine", database.make_engine("sqlite:////nonexistent-dir/x.sqlite"))
    body = TestClient(app).get("/api/ready").json()
    assert body["checks"]["database"] == "unavailable" and body["checks"]["schema"] == "unavailable"


def test_middleware_order_is_request_context_outermost():
    names = [layer.cls.__name__ for layer in app.user_middleware]
    assert names[:2] == ["RequestContext", "SecurityHeaders"] and middleware.MAX_REQUEST_BYTES > 0
